"""Article fetch (SSRF guard, redirects, caps) and PDF text extraction — no real network."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from backend import extract

PUBLIC = "93.184.216.34"


def _dns(monkeypatch: pytest.MonkeyPatch, table: dict[str, list[str]]) -> list[str]:
    looked_up: list[str] = []

    async def fake_resolve(host: str, port: int) -> list[str]:
        looked_up.append(host)
        return table[host]

    monkeypatch.setattr(extract, "_resolve", fake_resolve)
    return looked_up


def _serve(monkeypatch: pytest.MonkeyPatch, handler: object) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[operator]

    monkeypatch.setattr(extract, "_transport", lambda: httpx.MockTransport(recording))
    return seen


def _html(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/html; charset=utf-8"},
        text="<html><head><title>Hello</title><style>p{}</style></head>"
             "<body><script>evil()</script><p>Readable  text</p></body></html>")


async def test_public_page_title_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    seen = _serve(monkeypatch, _html)
    title, text = await extract.fetch_article("https://example.com/a")
    assert len(seen) == 1
    assert title == "Hello"
    assert text is not None and "Readable text" in text
    assert "evil" not in text and "p{}" not in text


@pytest.mark.parametrize("addr", [
    "127.0.0.1", "10.0.0.1", "192.168.1.5", "169.254.169.254", "100.100.1.1",
    "::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1", "0.0.0.0",
])
async def test_private_address_is_not_fetched(monkeypatch: pytest.MonkeyPatch, addr: str) -> None:
    _dns(monkeypatch, {"example.com": [addr]})
    seen = _serve(monkeypatch, _html)
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert seen == []


async def test_any_private_answer_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC, "10.0.0.1"]})
    seen = _serve(monkeypatch, _html)
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert seen == []


async def test_redirect_to_private_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC], "internal.example": ["10.1.2.3"]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return _html(request)

    seen = _serve(monkeypatch, handler)
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert [r.url.host for r in seen] == ["example.com"]


async def test_redirect_followed_to_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC], "other.example": [PUBLIC]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(301, headers={"location": "https://other.example/b"})
        return _html(request)

    seen = _serve(monkeypatch, handler)
    title, _ = await extract.fetch_article("https://example.com/a")
    assert title == "Hello" and len(seen) == 2


async def test_too_many_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    seen = _serve(monkeypatch, lambda r: httpx.Response(302, headers={"location": "/again"}))
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert len(seen) == 1 + extract.MAX_REDIRECTS


async def test_redirect_to_non_http_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    seen = _serve(monkeypatch, lambda r: httpx.Response(302, headers={"location": "file:///etc"}))
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert len(seen) == 1


async def test_peer_address_rechecked_after_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS rebinding: the address actually connected to is checked before the body is read."""
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    _serve(monkeypatch, _html)
    monkeypatch.setattr(extract, "_peer_ip", lambda response: "10.0.0.7")
    assert await extract.fetch_article("https://example.com/a") == (None, None)


@pytest.mark.parametrize("url", [
    "https://x.com/a/status/1", "https://twitter.com/a", "https://www.youtube.com/watch?v=1",
    "https://m.youtube.com/watch?v=1", "https://youtu.be/abc", "https://mobile.twitter.com/a",
    "https://YouTube.com./watch",
])
async def test_x_and_youtube_are_not_fetched(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    looked_up = _dns(monkeypatch, {})
    seen = _serve(monkeypatch, _html)
    assert await extract.fetch_article(url) == (None, None)
    assert seen == [] and looked_up == []


@pytest.mark.parametrize("url", ["ftp://example.com/a", "file:///etc/passwd", "notaurl"])
async def test_non_http_is_not_fetched(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    seen = _serve(monkeypatch, _html)
    assert await extract.fetch_article(url) == (None, None)
    assert seen == []


async def test_body_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    sent = {"bytes": 0}
    chunk = b"a" * 65536

    async def body() -> AsyncIterator[bytes]:
        yield b"<html><head><title>Big</title></head><body>"
        for _ in range(64):  # 4 MiB, twice the cap
            sent["bytes"] += len(chunk)
            yield chunk

    _serve(monkeypatch, lambda r: httpx.Response(
        200, headers={"content-type": "text/html"}, content=body()))
    title, text = await extract.fetch_article("https://example.com/a")
    assert sent["bytes"] <= extract.MAX_BODY_BYTES + len(chunk)
    assert title == "Big"
    assert text is not None


async def test_non_text_content_type_has_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    _serve(monkeypatch, lambda r: httpx.Response(
        200, headers={"content-type": "application/octet-stream"}, content=b"\x00\x01"))
    assert await extract.fetch_article("https://example.com/a") == (None, None)


async def test_network_error_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    _serve(monkeypatch, boom)
    assert await extract.fetch_article("https://example.com/a") == (None, None)


def test_pdf_without_text_returns_none(tmp_path: Path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / "blank.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    assert extract.extract_pdf_text(path) is None


def test_broken_pdf_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4 not really")
    assert extract.extract_pdf_text(path) is None
