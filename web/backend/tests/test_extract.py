"""Article fetch (SSRF guard, redirects, caps) and PDF text extraction — no real network."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpcore
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


@pytest.mark.parametrize("addr", [
    # NAT64 (well-known /96 and local-use /48) wrapping loopback, RFC 1918, metadata and public v4
    "64:ff9b::7f00:1", "64:ff9b::a00:1", "64:ff9b::a9fe:a9fe", "64:ff9b::c0a8:105",
    "64:ff9b::5db8:d822", "64:ff9b:1::a00:1", "64:ff9b:1:ffff::7f00:1",
    # IPv4-compatible, IPv4-translated, mapped, 6to4 and Teredo forms of private addresses
    "::7f00:1", "::a00:1", "::ffff:0:a00:1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
    "2002:a00:1::1", "2002:7f00:1::1", "2001:0:a00:1::1",
    # unique-local, site-local, documentation, discard, unspecified
    "fc00::1", "fd12:3456::1", "fec0::1", "2001:db8::1", "100::1", "::",
])
async def test_translated_and_mapped_private_forms_are_refused(
    monkeypatch: pytest.MonkeyPatch, addr: str,
) -> None:
    assert extract._is_public(addr) is False
    _dns(monkeypatch, {"example.com": [addr]})
    seen = _serve(monkeypatch, _html)
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert seen == []


def test_public_v6_is_still_allowed() -> None:
    assert extract._is_public("2606:4700:4700::1111") is True
    assert extract._is_public(PUBLIC) is True


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


async def test_peer_check_fails_closed_on_real_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real (non-mock) transport that hides the peer address is refused, not skipped."""
    _dns(monkeypatch, {"example.com": [PUBLIC]})

    class HiddenPeer(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return _html(request)

    monkeypatch.setattr(extract, "_transport", lambda: None)
    monkeypatch.setattr(extract, "_real_transport", lambda: HiddenPeer())
    assert await extract.fetch_article("https://example.com/a") == (None, None)


# --- connect-time pinning: the real transport over a fake socket layer -------------------------

PUBLIC_2 = "93.184.216.35"


class _FakeStream(httpcore.AsyncNetworkStream):
    def __init__(self, addr: str, log: dict[str, Any], response: bytes) -> None:
        self.addr, self.log, self._response = addr, log, [response]

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._response.pop() if self._response else b""

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self.log["sent"].append(bytes(buffer))

    async def aclose(self) -> None:
        pass

    async def start_tls(self, ssl_context: Any, server_hostname: str | None = None,
                        timeout: float | None = None) -> httpcore.AsyncNetworkStream:
        self.log["sni"].append(server_hostname)
        raise httpcore.ConnectError("test stops after recording the TLS server name")

    def get_extra_info(self, info: str) -> Any:
        return (self.addr, 80) if info == "server_addr" else None


class _FakeSockets(httpcore.AsyncNetworkBackend):
    """Records what the pinned backend asks it to connect to; serves canned HTTP/1.1."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.log: dict[str, Any] = {"connects": [], "sent": [], "sni": []}

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None,
                          socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        self.log["connects"].append(host)
        return _FakeStream(host, self.log, self.responses[host])

    async def sleep(self, seconds: float) -> None:
        pass


def _http(body: bytes, status: str = "200 OK", extra: str = "") -> bytes:
    return (f"HTTP/1.1 {status}\r\ncontent-type: text/html\r\n{extra}"
            f"content-length: {len(body)}\r\n\r\n").encode() + body


def _pinned(monkeypatch: pytest.MonkeyPatch, responses: dict[str, bytes]) -> _FakeSockets:
    sockets = _FakeSockets(responses)
    monkeypatch.setattr(extract, "_transport", lambda: None)
    monkeypatch.setattr(extract, "_real_transport", lambda: extract._PinnedTransport(
        backend=extract._PinnedBackend(inner=sockets)))
    return sockets


async def test_connection_goes_to_the_vetted_ip_with_the_hostname_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    sockets = _pinned(monkeypatch, {PUBLIC: _http(b"<title>Pinned</title><p>ok</p>")})
    title, text = await extract.fetch_article("http://example.com/a")
    assert (title, text) == ("Pinned", "ok")
    assert sockets.log["connects"] == [PUBLIC]  # the IP, never the name
    assert b"Host: example.com\r\n" in b"".join(sockets.log["sent"])


async def test_tls_server_name_is_the_hostname_not_the_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    sockets = _pinned(monkeypatch, {PUBLIC: b""})
    assert await extract.fetch_article("https://example.com/a") == (None, None)
    assert sockets.log["connects"] == [PUBLIC]
    assert sockets.log["sni"] == ["example.com"]


@pytest.mark.parametrize("second", [["10.0.0.1"], [PUBLIC, "127.0.0.1"], ["64:ff9b::7f00:1"], []])
async def test_rebinding_between_check_and_connect_is_refused(
    monkeypatch: pytest.MonkeyPatch, second: list[str],
) -> None:
    """The pre-check sees a public answer, the connect-time lookup a private one: no connect."""
    answers = [[PUBLIC], second]

    async def rebinding(host: str, port: int) -> list[str]:
        return answers.pop(0) if answers else second

    monkeypatch.setattr(extract, "_resolve", rebinding)
    sockets = _pinned(monkeypatch, {PUBLIC: _http(b"<title>x</title>")})
    assert await extract.fetch_article("http://example.com/a") == (None, None)
    assert sockets.log["connects"] == [] and sockets.log["sent"] == []


async def test_each_redirect_hop_is_vetted_and_pinned_at_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked_up = _dns(monkeypatch, {"example.com": [PUBLIC], "other.example": [PUBLIC_2]})
    sockets = _pinned(monkeypatch, {
        PUBLIC: _http(b"", "302 Found", "location: http://other.example/b\r\n"),
        PUBLIC_2: _http(b"<title>Hop</title>"),
    })
    title, _ = await extract.fetch_article("http://example.com/a")
    assert title == "Hop"
    assert sockets.log["connects"] == [PUBLIC, PUBLIC_2]
    # pre-check + connect-time vetting for each hop
    assert looked_up == ["example.com", "example.com", "other.example", "other.example"]
    sent = b"".join(sockets.log["sent"])
    assert b"Host: example.com\r\n" in sent and b"Host: other.example\r\n" in sent


async def test_redirect_hop_rebinding_to_private_is_never_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {"example.com": [[PUBLIC], [PUBLIC]], "other.example": [[PUBLIC_2], ["10.9.9.9"]]}

    async def resolve(host: str, port: int) -> list[str]:
        return answers[host].pop(0)

    monkeypatch.setattr(extract, "_resolve", resolve)
    sockets = _pinned(monkeypatch, {
        PUBLIC: _http(b"", "302 Found", "location: http://other.example/b\r\n"),
    })
    assert await extract.fetch_article("http://example.com/a") == (None, None)
    assert sockets.log["connects"] == [PUBLIC]


async def test_pinned_backend_refuses_unix_sockets() -> None:
    with pytest.raises(extract._Refused):
        await extract._PinnedBackend(inner=_FakeSockets({})).connect_unix_socket("/run/x.sock")


async def test_real_sockets_connect_to_the_vetted_ip_not_a_second_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real transport (anyio sockets) over a loopback listener the test vets as public.

    `.invalid` never resolves through system DNS, so a fetch only succeeds if the socket went to
    the address vetted here; the real stream's peer address must also pass the post-connect
    check."""
    import asyncio

    received: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        received.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(_http(b"<title>Real</title><p>sockets</p>"))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    real_is_public = extract._is_public
    monkeypatch.setattr(extract, "_is_public", lambda a: a == "127.0.0.1" or real_is_public(a))
    _dns(monkeypatch, {"pinned.invalid": ["127.0.0.1"]})
    monkeypatch.setattr(extract, "_transport", lambda: None)
    try:
        title, text = await extract.fetch_article(f"http://pinned.invalid:{port}/a")
    finally:
        server.close()
        await server.wait_closed()
    assert (title, text) == ("Real", "sockets")
    assert f"Host: pinned.invalid:{port}\r\n".encode() in received[0]


async def test_real_transport_is_pinned() -> None:
    transport = extract._real_transport()
    assert isinstance(transport, extract._PinnedTransport)
    assert isinstance(transport._pool._network_backend, extract._PinnedBackend)
    await transport.aclose()


async def test_control_chars_stripped_from_fetched_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _dns(monkeypatch, {"example.com": [PUBLIC]})
    _serve(monkeypatch, lambda r: httpx.Response(
        200, headers={"content-type": "text/html"},
        text="<title>A\x00B</title><body>x\x00y\x07z</body>"))
    title, text = await extract.fetch_article("https://example.com/a")
    assert title == "AB" and text == "xyz"


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


def _pdf_with_pages(path: Path, n: int) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(n):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as fh:
        writer.write(fh)


def test_pdf_page_cap_stops_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "many.pdf"
    _pdf_with_pages(path, 5)
    monkeypatch.setattr(extract, "MAX_PDF_PAGES", 2)
    seen: list[int] = []
    from pypdf._page import PageObject

    real = PageObject.extract_text

    def counting(self, *a, **kw):  # type: ignore[no-untyped-def]
        seen.append(1)
        return real(self, *a, **kw)

    monkeypatch.setattr(PageObject, "extract_text", counting)
    extract.extract_pdf_text(path)
    assert len(seen) == 2


async def test_bounded_extraction_reads_the_worker_text(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "t.pdf"
    path.write_bytes(b"x")
    monkeypatch.setattr(
        extract, "_worker_argv",
        lambda p: [sys.executable, "-c", "print('hello pdf')"])
    assert await extract.extract_pdf_text_bounded(path) == "hello pdf"


async def test_bounded_extraction_real_worker_on_blank_and_broken(tmp_path: Path) -> None:
    blank = tmp_path / "blank.pdf"
    _pdf_with_pages(blank, 1)
    assert await extract.extract_pdf_text_bounded(blank) is None
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 not really")
    assert await extract.extract_pdf_text_bounded(broken) is None


async def test_bounded_extraction_times_out_and_kills_the_worker(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.params import InvalidParam

    path = tmp_path / "slow.pdf"
    path.write_bytes(b"x")
    monkeypatch.setattr(extract, "PDF_TIMEOUT_S", 0.3)
    monkeypatch.setattr(
        extract, "_worker_argv",
        lambda p: [sys.executable, "-c", "import time; time.sleep(60)"])
    with pytest.raises(InvalidParam, match="timed out"):
        await extract.extract_pdf_text_bounded(path)
