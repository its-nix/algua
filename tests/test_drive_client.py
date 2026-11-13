"""The stdlib Drive/Sheets client (spec 2026-11-12 §6.1): header mapping, retries, auth errors,
call logging that never leaks ids, and find-or-create of a spreadsheet inside the folder."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import unquote

import pytest

from algua.config.settings import Settings
from algua.knowledge.drive import DriveClient, DriveError

FOLDER = "FOLDERID123"
SHEET = "SHEETID456"


class FakeTransport:
    """Scripted Google: the token endpoint always answers; everything else goes to `handler`."""

    def __init__(self, handler, *, token_status: int = 200, token_body: dict | None = None):
        self.handler = handler
        self.calls: list[tuple[str, str]] = []
        self.token_status = token_status
        self.token_body = token_body or {"access_token": "tok", "expires_in": 3600}

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if url.startswith("https://oauth2.googleapis.com/token"):
            return self.token_status, json.dumps(self.token_body).encode()
        status, payload = self.handler(method, unquote(url), body)
        return status, json.dumps(payload).encode()


def _creds(tmp_path: Path) -> Path:
    p = tmp_path / "drive.json"
    p.write_text(json.dumps({"client_id": "c", "client_secret": "s", "refresh_token": "r"}))
    return p


def _sheet_router(values: list[list[str]]):
    """Folder has one spreadsheet with one tab `t` holding `values`."""
    def handler(method, url, body):
        if "drive/v3/files" in url and method == "GET":
            return 200, {"files": [{"id": SHEET, "name": "S"}]}
        if url.endswith("fields=sheets.properties.title"):
            return 200, {"sheets": [{"properties": {"title": "t"}}]}
        if "/values/" in url and method == "GET":
            return 200, {"values": values}
        return 200, {}
    return handler


def _client(tmp_path, transport, **kw) -> DriveClient:
    return DriveClient(FOLDER, _creds(tmp_path), transport=transport, sleep=lambda _s: None, **kw)


def test_read_tab_maps_rows_by_header_not_order(tmp_path):
    t = FakeTransport(_sheet_router([["status", "id", "idea"], ["", "r1", "buy dips"], []]))
    rows = _client(tmp_path, t).read_tab("S", "t", required=["idea"])
    assert rows == [{"status": "", "id": "r1", "idea": "buy dips", "_row": "2"}]


def test_read_tab_pads_short_rows(tmp_path):
    t = FakeTransport(_sheet_router([["id", "idea", "status"], ["r1", "x"]]))
    rows = _client(tmp_path, t).read_tab("S", "t", required=[])
    assert rows == [{"id": "r1", "idea": "x", "status": "", "_row": "2"}]


def test_read_tab_missing_required_header_raises_schema(tmp_path):
    t = FakeTransport(_sheet_router([["id", "why"]]))
    with pytest.raises(DriveError) as exc:
        _client(tmp_path, t).read_tab("S", "t", required=["idea"])
    assert exc.value.code == "drive_schema"
    assert "missing header idea" in str(exc.value)


def test_retries_429_then_succeeds(tmp_path):
    sleeps: list[float] = []
    state = {"n": 0}
    base = _sheet_router([["id"], ["a"]])

    def handler(method, url, body):
        if "/values/" in url:
            state["n"] += 1
            if state["n"] <= 2:
                return 429, {"error": "rate"}
        return base(method, url, body)

    client = DriveClient(FOLDER, _creds(tmp_path), transport=FakeTransport(handler),
                         sleep=sleeps.append)
    assert client.read_tab("S", "t", required=["id"]) == [{"id": "a", "_row": "2"}]
    assert len(sleeps) == 2


def test_exhausted_5xx_raises_unavailable(tmp_path):
    def handler(method, url, body):
        return 503, {"error": "down"}
    with pytest.raises(DriveError) as exc:
        _client(tmp_path, FakeTransport(handler)).read_tab("S", "t", required=[])
    assert exc.value.code == "drive_unavailable"


def test_other_4xx_raises_http(tmp_path):
    def handler(method, url, body):
        return 404, {"error": "nope"}
    with pytest.raises(DriveError) as exc:
        _client(tmp_path, FakeTransport(handler)).read_tab("S", "t", required=[])
    assert exc.value.code == "drive_http"


def test_missing_credentials_raises_auth(tmp_path):
    s = Settings(_env_file=None, drive_folder_id=FOLDER)
    with pytest.raises(DriveError) as exc:
        DriveClient.from_settings(s)
    assert exc.value.code == "drive_auth"


def test_unreadable_credentials_raises_auth(tmp_path):
    s = Settings(_env_file=None, drive_folder_id=FOLDER, drive_credentials=tmp_path / "nope.json")
    with pytest.raises(DriveError) as exc:
        DriveClient.from_settings(s)
    assert exc.value.code == "drive_auth"


def test_revoked_refresh_token_raises_auth(tmp_path):
    t = FakeTransport(_sheet_router([["id"]]), token_status=400,
                      token_body={"error": "invalid_grant"})
    with pytest.raises(DriveError) as exc:
        _client(tmp_path, t).read_tab("S", "t", required=[])
    assert exc.value.code == "drive_auth"


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_every_call_logs_drive_call_without_ids(tmp_path):
    # A handler on the logger itself, not caplog: once anything configures the `algua` root
    # logger (propagate=False), records never reach pytest's capture handler.
    t = FakeTransport(_sheet_router([["id"], ["a"]]))
    logger = logging.getLogger("algua.drive")
    handler, old_level = _Collect(), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        _client(tmp_path, t).read_tab("S", "t", required=[])
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
    records = handler.records
    api_calls = [c for c in t.calls if "oauth2" not in c[1]]
    assert len(records) == len(api_calls) > 0
    for r in records:
        fields = r.fields
        assert fields["event"] == "drive_call" and "op" in fields and "ms" in fields
        blob = r.getMessage() + json.dumps(fields, default=str)
        assert FOLDER not in blob and SHEET not in blob


def test_sheet_id_creates_missing_sheet_in_folder_and_caches(tmp_path):
    created: list[dict] = []

    def handler(method, url, body):
        if "drive/v3/files" in url and method == "GET":
            return 200, {"files": []}
        if "drive/v3/files" in url and method == "POST":
            created.append(json.loads(body))
            return 200, {"id": SHEET}
        if url.endswith("fields=sheets.properties.title"):
            return 200, {"sheets": [{"properties": {"title": "Sheet1"}}]}
        return 200, {}

    t = FakeTransport(handler)
    client = _client(tmp_path, t)
    assert client.sheet_id("Inbox", ["ideas"]) == SHEET
    assert created == [{"name": "Inbox", "mimeType": "application/vnd.google-apps.spreadsheet",
                        "parents": [FOLDER]}]
    assert any(":batchUpdate" in u and m == "POST" for m, u in t.calls)  # tab `ideas` added
    n = len(t.calls)
    assert client.sheet_id("Inbox", ["ideas"]) == SHEET
    assert len(t.calls) == n


def test_settings_drive_fields_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DRIVE_FOLDER_ID", "F")
    monkeypatch.setenv("ALGUA_DRIVE_CREDENTIALS", str(tmp_path / "d.json"))
    monkeypatch.setenv("ALGUA_STEERING_DIR", str(tmp_path / "steer"))
    s = Settings(_env_file=None)
    assert s.drive_folder_id == "F"
    assert s.drive_credentials == tmp_path / "d.json"
    assert s.steering_dir == tmp_path / "steer"


def test_settings_drive_fields_default_off():
    s = Settings(_env_file=None)
    assert (s.drive_folder_id, s.drive_credentials, s.steering_dir) == (None, None, None)


# --- review I4: error envelopes ------------------------------------------------------------------

def test_cli_error_code_uses_the_drive_error_code():
    from algua.cli.errors import error_envelope
    env = error_envelope(DriveError("drive_unavailable", "Inspirations/notes: HTTP 503"))
    assert env == {"ok": False, "error": "Inspirations/notes: HTTP 503",
                   "code": "drive_unavailable", "retryable": True}
    assert error_envelope(DriveError("drive_schema", "x"))["retryable"] is False


def test_token_endpoint_5xx_is_retried_then_succeeds(tmp_path):
    state = {"n": 0}

    class Flaky(FakeTransport):
        def __call__(self, method, url, headers, body):
            if url.startswith("https://oauth2.googleapis.com/token"):
                state["n"] += 1
                if state["n"] <= 2:
                    return 503, b"{}"
            return super().__call__(method, url, headers, body)

    rows = _client(tmp_path, Flaky(_sheet_router([["id"], ["a"]]))).read_tab("S", "t", [])
    assert rows == [{"id": "a", "_row": "2"}] and state["n"] == 3


def test_token_response_without_access_token_is_auth_error(tmp_path):
    t = FakeTransport(_sheet_router([["id"]]), token_body={"expires_in": 3600})
    with pytest.raises(DriveError) as exc:
        _client(tmp_path, t).read_tab("S", "t", required=[])
    assert exc.value.code == "drive_auth"
