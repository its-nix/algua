"""A small Google Drive v3 + Sheets v4 client over stdlib `urllib` (no new dependency: the root
lockfile is deployment identity).

Every API call logs one `drive_call` line naming the sheet/tab — never a file or folder id, so a
log can be pasted anywhere in this public repo's issues. Transient failures (429/5xx, network)
are retried with backoff; everything else raises a typed `DriveError` whose `code` the CLI emits.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from algua.config.settings import Settings
from algua.observability.log import get_logger
from algua.primitives.retry import RetriesExhausted, call_with_backoff

Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE = "https://www.googleapis.com/drive/v3/files"
_SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# 2+4+8+16+32 = 62s of backoff: long enough to outlast Sheets' per-minute quota window.
_ATTEMPTS = 6
_BACKOFF = 2.0
_TIMEOUT_S = 30

_log = get_logger("algua.drive")


class DriveError(RuntimeError):
    """`code` is one of drive_auth | drive_unavailable | drive_schema | drive_http."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


def urllib_transport(method: str, url: str, headers: dict[str, str],
                     body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310 - https only
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _col(index: int) -> str:
    """0-based column index -> A1 letters."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _range(tab: str, a1: str = "") -> str:
    name = "'" + tab.replace("'", "''") + "'"
    return quote(f"{name}!{a1}" if a1 else name, safe="")


class DriveClient:
    def __init__(self, folder_id: str, credentials_path: Path, *,
                 transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._folder = folder_id
        self._creds_path = credentials_path
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self._token: str | None = None
        self._token_expiry = 0.0
        self._sheet_ids: dict[str, str] = {}
        self._tabs: dict[str, set[str]] = {}
        self._headers: dict[tuple[str, str], list[str]] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> DriveClient:
        if not settings.drive_folder_id:
            raise DriveError("drive_auth", "ALGUA_DRIVE_FOLDER_ID is not set")
        path = settings.drive_credentials
        if path is None or not Path(path).is_file():
            raise DriveError("drive_auth", "ALGUA_DRIVE_CREDENTIALS is unset or unreadable")
        return cls(settings.drive_folder_id, Path(path))

    # --- auth -------------------------------------------------------------------------------
    def _access_token(self, *, force: bool = False) -> str:
        if self._token and not force and time.time() < self._token_expiry - 60:
            return self._token
        try:
            creds = json.loads(self._creds_path.read_text(encoding="utf-8"))
            form = urlencode({"client_id": creds["client_id"],
                              "client_secret": creds["client_secret"],
                              "refresh_token": creds["refresh_token"],
                              "grant_type": "refresh_token"}).encode()
        except (OSError, ValueError, KeyError) as exc:
            raise DriveError("drive_auth", f"credentials unreadable: {type(exc).__name__}") from exc
        def send() -> tuple[int, bytes]:
            return self._transport(
                "POST", _TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, form)

        try:
            status, raw = call_with_backoff(
                send, attempts=_ATTEMPTS, backoff_base=_BACKOFF,
                retryable_exceptions=(urllib.error.URLError, TimeoutError, ConnectionError),
                retry_result=lambda r: r[0] in _RETRY_STATUS, sleep=self._sleep)
        except RetriesExhausted as exc:
            raise DriveError("drive_unavailable", "token endpoint unreachable") from exc
        if status in _RETRY_STATUS:
            raise DriveError("drive_unavailable", f"token endpoint HTTP {status} after retries")
        if status != 200:
            raise DriveError("drive_auth", f"token refresh failed (HTTP {status})")
        try:
            payload = json.loads(raw or b"{}")
            self._token = str(payload["access_token"])
        except (ValueError, KeyError, TypeError) as exc:
            raise DriveError("drive_auth", "token response has no access_token") from exc
        self._token_expiry = time.time() + float(payload.get("expires_in", 3600))
        return self._token

    # --- transport --------------------------------------------------------------------------
    def _call(self, method: str, url: str, *, op: str, file: str = "", tab: str = "",
              rows: int = 0, body: Any = None, idempotent: bool = True) -> Any:
        """One API call. A non-idempotent call (append, create) is retried ONLY on 429: a 5xx or a
        timeout may mean the server already committed it, and a second send would duplicate rows
        or files. The id-keyed callers converge on a re-run instead."""
        data = None if body is None else json.dumps(body).encode()
        retry_status = _RETRY_STATUS if idempotent else frozenset({429})
        retry_exc: tuple[type[BaseException], ...] = (
            (urllib.error.URLError, TimeoutError, ConnectionError) if idempotent else ())

        def send_once() -> tuple[int, bytes]:
            headers = {"Authorization": f"Bearer {self._access_token()}",
                       "Content-Type": "application/json"}
            t0 = time.monotonic()
            status = 0
            try:
                status, raw = self._transport(method, url, headers, data)
                return status, raw
            finally:
                _log.info("drive_call", extra={"fields": {
                    "event": "drive_call", "op": op, "file": file, "tab": tab, "rows": rows,
                    "ms": round((time.monotonic() - t0) * 1000), "ok": 200 <= status < 300,
                    "status": status}})

        def send() -> tuple[int, bytes]:
            status, raw = send_once()
            if status == 401:
                self._access_token(force=True)
                status, raw = send_once()
                if status == 401:
                    raise DriveError("drive_auth", f"{op}: unauthorized")
            return status, raw

        try:
            status, raw = call_with_backoff(
                send, attempts=_ATTEMPTS, backoff_base=_BACKOFF,
                retryable_exceptions=retry_exc,
                retry_result=lambda r: r[0] in retry_status, sleep=self._sleep)
        except (RetriesExhausted, urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise DriveError("drive_unavailable", f"{op}: network failure") from exc
        if status in _RETRY_STATUS:
            raise DriveError("drive_unavailable", f"{op}: HTTP {status} after retries")
        if not 200 <= status < 300:
            raise DriveError("drive_http", f"{op} {file}/{tab}: HTTP {status}")
        return json.loads(raw) if raw else {}

    # --- files and tabs ---------------------------------------------------------------------
    def sheet_id(self, name: str, tabs: Sequence[str]) -> str:
        """Find the spreadsheet `name` in the folder (create it if absent) and ensure its tabs."""
        sid = self._sheet_ids.get(name)
        if sid is None:
            esc = name.replace("\\", "\\\\").replace("'", "\\'")
            q = (f"'{self._folder}' in parents and name='{esc}' and mimeType='{_SHEET_MIME}' "
                 "and trashed=false")
            found = self._call("GET", f"{_DRIVE}?{urlencode({'q': q, 'fields': 'files(id,name)'})}",
                               op="find_sheet", file=name).get("files") or []
            if len(found) > 1:
                raise DriveError("drive_schema", f"{len(found)} spreadsheets named {name!r} in "
                                 "the Algua folder; keep one (trash the others)")
            if found:
                sid = str(found[0]["id"])
            else:
                sid = str(self._call("POST", _DRIVE, op="create_sheet", file=name,
                                     idempotent=False, body={
                                         "name": name, "mimeType": _SHEET_MIME,
                                         "parents": [self._folder]})["id"])
            self._sheet_ids[name] = sid
        if name not in self._tabs:
            meta = self._call("GET", f"{_SHEETS}/{sid}?fields=sheets.properties.title",
                              op="list_tabs", file=name)
            self._tabs[name] = {str(s["properties"]["title"]) for s in meta.get("sheets") or []}
        missing = [t for t in tabs if t not in self._tabs[name]]
        if missing:
            self._call("POST", f"{_SHEETS}/{sid}:batchUpdate", op="add_tabs", file=name,
                       body={"requests": [{"addSheet": {"properties": {"title": t}}}
                                          for t in missing]})
            self._tabs[name].update(missing)
        return sid

    def _values(self, sheet: str, tab: str) -> list[list[str]]:
        sid = self.sheet_id(sheet, [tab])
        got = self._call("GET", f"{_SHEETS}/{sid}/values/{_range(tab)}", op="read",
                         file=sheet, tab=tab)
        values = [[str(c) for c in row] for row in got.get("values") or []]
        self._headers[(sheet, tab)] = [h.strip() for h in values[0]] if values else []
        return values

    def _header(self, sheet: str, tab: str) -> list[str]:
        """The tab's header, read once per client: re-reading the whole tab for every write
        burns the per-minute Sheets quota."""
        if (sheet, tab) not in self._headers:
            self._values(sheet, tab)
        return self._headers[(sheet, tab)]

    def _write_header(self, sheet: str, tab: str, header: list[str]) -> None:
        sid = self.sheet_id(sheet, [tab])
        self._call("PUT", f"{_SHEETS}/{sid}/values/{_range(tab, 'A1')}?valueInputOption=RAW",
                   op="write_header", file=sheet, tab=tab, body={"values": [header]})
        self._headers[(sheet, tab)] = list(header)

    def read_tab(self, sheet: str, tab: str, required: Sequence[str]) -> list[dict[str, str]]:
        values = self._values(sheet, tab)
        header = [h.strip() for h in values[0]] if values else []
        for h in required:
            if h not in header:
                raise DriveError("drive_schema", f"{sheet}/{tab}: missing header {h}")
        rows: list[dict[str, str]] = []
        for i, raw in enumerate(values[1:], start=2):
            if not any(c.strip() for c in raw):
                continue
            row = {h: (raw[j] if j < len(raw) else "") for j, h in enumerate(header) if h}
            row["_row"] = str(i)
            rows.append(row)
        return rows

    def ensure_header(self, sheet: str, tab: str, header: Sequence[str],
                      required: Sequence[str] = ()) -> None:
        """Write `header` into an empty tab. On an existing tab a missing REQUIRED column is a
        `drive_schema` error (the owner renamed or deleted it; adding a fresh empty column would
        silently ignore their data). Missing optional columns are appended on the right."""
        current = self._header(sheet, tab)
        if not current:
            self._write_header(sheet, tab, list(header))
            return
        for h in required:
            if h not in current:
                raise DriveError("drive_schema", f"{sheet}/{tab}: missing header {h}")
        merged = current + [h for h in header if h not in current]
        if merged != current:
            self._write_header(sheet, tab, merged)

    def append_rows(self, sheet: str, tab: str, rows: Sequence[Mapping[str, str]]) -> None:
        if not rows:
            return
        header = self._header(sheet, tab)
        sid = self.sheet_id(sheet, [tab])
        values = [[str(r.get(h, "")) for h in header] for r in rows]
        self._call("POST", f"{_SHEETS}/{sid}/values/{_range(tab, 'A1')}:append?"
                   "valueInputOption=RAW&insertDataOption=INSERT_ROWS",
                   op="append", file=sheet, tab=tab, rows=len(rows), body={"values": values},
                   idempotent=False)

    def update_cells(self, sheet: str, tab: str, row: int, values: Mapping[str, str]) -> None:
        header = self._header(sheet, tab)
        sid = self.sheet_id(sheet, [tab])
        data = []
        for key, value in values.items():
            if key not in header:
                raise DriveError("drive_schema", f"{sheet}/{tab}: missing header {key}")
            a1 = f"{_col(header.index(key))}{row}"
            data.append({"range": f"'{tab}'!{a1}", "values": [[str(value)]]})
        self._call("POST", f"{_SHEETS}/{sid}/values:batchUpdate", op="update", file=sheet,
                   tab=tab, rows=1, body={"valueInputOption": "RAW", "data": data})

    def replace_tab(self, sheet: str, tab: str, header: Sequence[str],
                    rows: Sequence[Mapping[str, str]]) -> None:
        """Rewrite a machine-owned tab in ONE write: the current header (with any columns the
        owner added) is kept, `header` columns are ensured, and leftover old rows are blanked.
        Never clear-then-write: a failure between the two would leave the tab empty."""
        sid = self.sheet_id(sheet, [tab])
        old = self._values(sheet, tab)
        current = [h.strip() for h in old[0]] if old else []
        merged = current + [h for h in header if h not in current]
        values = [merged] + [[str(r.get(h, "")) for h in merged] for r in rows]
        values += [[""] * len(merged) for _ in range(max(0, len(old) - len(values)))]
        self._call("PUT", f"{_SHEETS}/{sid}/values/{_range(tab, 'A1')}?valueInputOption=RAW",
                   op="replace", file=sheet, tab=tab, rows=len(rows), body={"values": values})
        self._headers[(sheet, tab)] = merged
