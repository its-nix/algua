"""Inbox writes, the share target, the owner check and /api/equity (run_cli stubbed)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import backend.main as main_mod
import httpx
import pytest
from backend import inbox
from backend.algua_cli import CliError

OWNER = "owner@example.com"
ITEM = {"id": 7, "kind": "link", "url": "https://x.com/a/status/1", "status": "queued"}


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=main_mod.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", OWNER)
    return {"Tailscale-User-Login": OWNER}


@pytest.fixture(autouse=True)
def inbox_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "inbox"
    monkeypatch.setenv("ALGUA_WEB_INBOX_DIR", str(d))
    return d


@pytest.fixture(autouse=True)
def no_fetch(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Never touch the network: article fetches are recorded and return nothing."""
    fetched: list[str] = []

    async def fake_fetch(url: str) -> tuple[str | None, str | None]:
        fetched.append(url)
        return None, None

    monkeypatch.setattr(main_mod, "fetch_article", fake_fetch)
    return fetched


class Calls(list[list[str]]):
    """argv lists in call order; ``extracted`` holds each --extracted-text-file's text."""

    extracted: list[str]


@pytest.fixture
def cli_calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Stub run_cli; record argv and, for --extracted-text-file, the file's text at call time."""
    calls = Calls()
    calls.extracted = []

    async def fake_run_cli(*args: str, ttl_s: float, timeout_s: float = 60.0) -> dict[str, Any]:
        calls.append(list(args))
        for a in args:
            if a.startswith("--extracted-text-file="):
                calls.extracted.append(Path(a.split("=", 1)[1]).read_text(encoding="utf-8"))
        if args[:3] == ("research", "inbox", "add"):
            return {"ok": True, "data": {"ok": True, "item": ITEM, "duplicate": False},
                    "fetched_at": "t", "stale": False}
        return {"ok": True, "data": {"ok": True, "items": []}, "fetched_at": "t", "stale": False}

    monkeypatch.setattr(main_mod, "run_cli", fake_run_cli)
    return calls


# --- owner check ---


async def test_write_without_owner_header_is_403(
    monkeypatch: pytest.MonkeyPatch, cli_calls: Calls
) -> None:
    monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", OWNER)
    async with _client() as client:
        r = await client.post("/api/inbox", json={"url": "https://example.com/a"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert r.json()["ok"] is False
    assert cli_calls == []


async def test_write_with_wrong_owner_is_403(
    monkeypatch: pytest.MonkeyPatch, cli_calls: Calls
) -> None:
    monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", OWNER)
    async with _client() as client:
        r = await client.post("/api/inbox", json={"url": "https://example.com/a"},
                              headers={"Tailscale-User-Login": "mallory@example.com"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert cli_calls == []


@pytest.mark.parametrize("env", [None, ""])
async def test_write_refused_when_owner_env_unset(
    monkeypatch: pytest.MonkeyPatch, cli_calls: Calls, env: str | None
) -> None:
    if env is None:
        monkeypatch.delenv("ALGUA_WEB_OWNER_LOGIN", raising=False)
    else:
        monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", env)
    async with _client() as client:
        r = await client.post("/api/inbox", json={"url": "https://example.com/a"},
                              headers={"Tailscale-User-Login": ""})
        s = await client.post("/share", data={"url": "https://example.com/a"},
                              headers={"Tailscale-User-Login": ""})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert s.status_code == 403 and s.json()["code"] == "forbidden"
    assert cli_calls == []


async def test_unauthenticated_upload_is_refused_before_saving(
    monkeypatch: pytest.MonkeyPatch, inbox_dir: Path, cli_calls: Calls
) -> None:
    monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", OWNER)
    async with _client() as client:
        r = await client.post("/api/inbox", files={"file": ("a.txt", b"hello")})
    assert r.status_code == 403
    assert not inbox_dir.exists()


async def test_cross_site_inbox_post_is_403(
    owner: dict[str, str], cli_calls: Calls
) -> None:
    async with _client() as client:
        r = await client.post("/api/inbox", json={"url": "https://example.com/a"},
                              headers={**owner, "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert cli_calls == []


# --- POST /api/inbox (JSON) ---


async def test_owner_link_calls_cli_add(
    owner: dict[str, str], cli_calls: Calls
) -> None:
    async with _client() as client:
        r = await client.post("/api/inbox",
                              json={"url": "https://x.com/a/status/1", "note": "why"},
                              headers=owner)
    assert r.status_code == 201
    assert r.json() == {"ok": True, "item": ITEM, "duplicate": False}
    argv = cli_calls[-1]
    assert argv[:3] == ["research", "inbox", "add"]
    assert argv[3] == "--url=https://x.com/a/status/1"
    assert "--note=why" in argv


async def test_link_with_extracted_text_passes_temp_file_then_deletes_it(
    owner: dict[str, str], cli_calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(url: str) -> tuple[str | None, str | None]:
        return "Page title", "Readable body"

    monkeypatch.setattr(main_mod, "fetch_article", fake_fetch)
    async with _client() as client:
        r = await client.post("/api/inbox", json={"url": "https://example.com/a"}, headers=owner)
    assert r.status_code == 201
    argv = cli_calls[-1]
    assert "--title=Page title" in argv
    (tf,) = [a.split("=", 1)[1] for a in argv if a.startswith("--extracted-text-file=")]
    assert cli_calls.extracted == ["Readable body"]
    assert not Path(tf).exists()


async def test_owner_title_wins_over_fetched_title(
    owner: dict[str, str], cli_calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(url: str) -> tuple[str | None, str | None]:
        return "Page title", None

    monkeypatch.setattr(main_mod, "fetch_article", fake_fetch)
    async with _client() as client:
        await client.post("/api/inbox", json={"url": "https://example.com/a", "title": "Mine"},
                          headers=owner)
    assert "--title=Mine" in cli_calls[-1]


async def test_text_item(owner: dict[str, str], cli_calls: Calls) -> None:
    async with _client() as client:
        r = await client.post("/api/inbox", json={"text": "buy low"}, headers=owner)
    assert r.status_code == 201
    assert cli_calls[-1][:4] == ["research", "inbox", "add", "--text=buy low"]


@pytest.mark.parametrize("body", [
    {"url": "ftp://example.com/a"},
    {"url": "javascript:alert(1)"},
    {"url": "https://example.com/a", "text": "both"},
    {},
    {"note": "only a note"},
    [1, 2],
])
async def test_invalid_json_is_422(
    owner: dict[str, str], cli_calls: Calls, body: Any
) -> None:
    async with _client() as client:
        r = await client.post("/api/inbox", json=body, headers=owner)
    assert r.status_code == 422 and r.json()["code"] == "invalid_param"
    assert cli_calls == []


async def test_stale_add_is_a_failure(
    owner: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_cli serves an old cached value (stale) when the CLI fails — never a fake success."""
    async def fake_run_cli(*args: str, ttl_s: float, timeout_s: float = 60.0) -> dict[str, Any]:
        return {"ok": True, "data": {"ok": True, "item": ITEM, "duplicate": False},
                "fetched_at": "t", "stale": True, "last_error_code": "db_locked"}

    monkeypatch.setattr(main_mod, "run_cli", fake_run_cli)
    async with _client() as client:
        r = await client.post("/api/inbox", json={"text": "x"}, headers=owner)
    assert r.status_code == 502 and r.json()["code"] == "db_locked"


async def test_cli_error_on_add_is_502(
    owner: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_cli(*args: str, ttl_s: float, timeout_s: float = 60.0) -> dict[str, Any]:
        raise CliError("validation_error", "bad")

    monkeypatch.setattr(main_mod, "run_cli", fake_run_cli)
    async with _client() as client:
        r = await client.post("/api/inbox", json={"text": "x"}, headers=owner)
    assert r.status_code == 502 and r.json()["code"] == "validation_error"


# --- POST /api/inbox (multipart) ---


async def test_upload_saves_file_and_passes_path(
    owner: dict[str, str], cli_calls: Calls, inbox_dir: Path
) -> None:
    async with _client() as client:
        r = await client.post("/api/inbox", files={"file": ("../../evil name.txt", b"hello")},
                              data={"note": "read this"}, headers=owner)
    assert r.status_code == 201
    argv = cli_calls[-1]
    (path,) = [a.split("=", 1)[1] for a in argv if a.startswith("--file=")]
    saved = Path(path)
    assert saved.is_absolute() and saved.read_bytes() == b"hello"
    assert saved.parent.parent == inbox_dir
    assert saved.name == "evil_name.txt"
    assert "--note=read this" in argv
    assert cli_calls.extracted == ["hello"]


async def test_upload_over_20mb_is_413(
    owner: dict[str, str], cli_calls: Calls, inbox_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert inbox.MAX_UPLOAD_BYTES == 20 * 1024 * 1024
    monkeypatch.setattr(inbox, "MAX_UPLOAD_BYTES", 1000)
    async with _client() as client:
        r = await client.post("/api/inbox", files={"file": ("big.pdf", b"x" * 1001)},
                              headers=owner)
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert cli_calls == []
    assert not any(p.is_file() for p in inbox_dir.rglob("*")) if inbox_dir.exists() else True


async def test_upload_dir_removed_when_cli_fails(
    owner: dict[str, str], inbox_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_cli(*args: str, ttl_s: float, timeout_s: float = 60.0) -> dict[str, Any]:
        raise CliError("validation_error", "bad")

    monkeypatch.setattr(main_mod, "run_cli", fake_run_cli)
    async with _client() as client:
        r = await client.post("/api/inbox", files={"file": ("a.txt", b"hi")}, headers=owner)
    assert r.status_code == 502
    assert list(inbox_dir.iterdir()) == [] if inbox_dir.exists() else True


@pytest.mark.parametrize("chunked", [False, True])
async def test_oversized_form_body_is_cut_off(
    owner: dict[str, str], cli_calls: Calls, inbox_dir: Path,
    monkeypatch: pytest.MonkeyPatch, chunked: bool,
) -> None:
    """The whole-body cap holds even when Content-Length is absent (chunked upload)."""
    monkeypatch.setattr(inbox, "MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(inbox, "FORM_OVERHEAD_BYTES", 100)
    boundary = "xyzzy"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"a.txt\"\r\nContent-Type: text/plain\r\n\r\n").encode()
    body = head + b"x" * 5000 + f"\r\n--{boundary}--\r\n".encode()

    async def gen() -> Any:
        for i in range(0, len(body), 512):
            yield body[i:i + 512]

    headers = {**owner, "content-type": f"multipart/form-data; boundary={boundary}"}
    async with _client() as client:
        r = await client.post("/api/inbox", content=gen() if chunked else body, headers=headers)
    assert r.status_code == 413 and r.json()["code"] == "too_large"
    assert cli_calls == []


def test_inbox_dir_defaults_under_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ALGUA_WEB_INBOX_DIR", raising=False)
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "d"))
    assert inbox.inbox_dir() == tmp_path / "d" / "inbox"
    monkeypatch.delenv("ALGUA_DATA_DIR")
    assert inbox.inbox_dir() == inbox.REPO / "data" / "inbox"


# --- POST /share ---


async def test_share_target_redirects_to_inbox(
    owner: dict[str, str], cli_calls: Calls
) -> None:
    async with _client() as client:
        r = await client.post("/share", data={"url": "https://youtu.be/x", "title": "t"},
                              headers=owner, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/inbox?shared=1"
    argv = cli_calls[-1]
    assert argv[3] == "--url=https://youtu.be/x" and "--title=t" in argv


async def test_share_link_inside_text_becomes_a_link(
    owner: dict[str, str], cli_calls: Calls
) -> None:
    async with _client() as client:
        r = await client.post("/share", data={"text": "look at this https://example.com/p"},
                              headers=owner, follow_redirects=False)
    assert r.status_code == 303
    argv = cli_calls[-1]
    assert argv[3] == "--url=https://example.com/p"
    assert "--note=look at this https://example.com/p" in argv


async def test_share_plain_text(owner: dict[str, str], cli_calls: Calls) -> None:
    async with _client() as client:
        r = await client.post("/share", data={"text": "an idea"}, headers=owner,
                              follow_redirects=False)
    assert r.status_code == 303
    assert cli_calls[-1][3] == "--text=an idea"


async def test_share_files_each_become_an_item(
    owner: dict[str, str], cli_calls: Calls
) -> None:
    async with _client() as client:
        r = await client.post(
            "/share",
            files=[("files", ("a.txt", b"one")), ("files", ("b.txt", b"two"))],
            data={"title": "shared"}, headers=owner, follow_redirects=False)
    assert r.status_code == 303
    adds = [c for c in cli_calls if c[:3] == ["research", "inbox", "add"]]
    assert len(adds) == 2
    assert all(any(a.startswith("--file=") for a in c) for c in adds)


async def test_empty_share_is_422(owner: dict[str, str], cli_calls: Calls) -> None:
    async with _client() as client:
        r = await client.post("/share", data={"title": "nothing"}, headers=owner,
                              follow_redirects=False)
    assert r.status_code == 422
    assert cli_calls == []


# --- reads ---


async def test_inbox_list_reads_uncached(cli_calls: Calls) -> None:
    async with _client() as client:
        r = await client.get("/api/inbox")
    assert r.status_code == 200
    assert cli_calls[-1] == ["research", "inbox", "list"]


async def test_equity_wraps_fleet_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[tuple[str, ...], float]] = []

    async def fake_run_cli(*args: str, ttl_s: float, timeout_s: float = 60.0) -> dict[str, Any]:
        seen.append((args, ttl_s))
        return {"ok": True, "data": {"ok": True, "points": []}, "fetched_at": "t", "stale": False}

    monkeypatch.setattr(main_mod, "run_cli", fake_run_cli)
    async with _client() as client:
        a = await client.get("/api/equity")
        b = await client.get("/api/equity?lane=paper")
        c = await client.get("/api/equity?lane=bogus")
    assert a.status_code == 200 and b.status_code == 200
    assert seen == [(("fleet", "equity"), 30.0), (("fleet", "equity", "--lane=paper"), 30.0)]
    assert c.status_code == 422 and c.json()["code"] == "invalid_param"
