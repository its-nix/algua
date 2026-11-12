"""The ideation Sheets as typed tables (spec 2026-11-12 §4, §6.3–6.6).

Headers are the contract, column order is not: the owner may reorder or add columns freely.
Sheet and tab names are fixed here; the folder holding them comes from settings.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from algua.config.settings import Settings
from algua.knowledge.drive.client import DriveClient, DriveError
from algua.knowledge.inspirations import REQUIRED, url_hash

INSPIRATIONS = ("Inspirations", "notes")
INSPIRATION_HEADER = [*REQUIRED, "leaps", "body", "url_hash", "inbox_row_id"]
CATEGORIES = ("Steering", "Categories")
CATEGORY_HEADER = ["slug", "market", "horizon", "enabled", "notes"]
SOURCES = ("Steering", "Sources")
SOURCES_HEADER = ["key", "kind", "url", "categories", "added_by", "added_at", "yield", "extra"]
INBOX = ("Inbox", "ideas")
INBOX_HEADER = ["id", "idea", "why / notes", "links", "category", "status", "updated"]
IDEAS = ("Ideas", "pool")

_OFF = frozenset({"false", "no", "0", "n", "off"})
_SOURCE_TEXT = ("key", "kind", "url", "added_by", "added_at")


class Client(Protocol):
    def read_tab(self, sheet: str, tab: str, required: Any) -> list[dict[str, str]]: ...
    def ensure_header(self, sheet: str, tab: str, header: Any) -> None: ...
    def append_rows(self, sheet: str, tab: str, rows: Any) -> None: ...
    def update_cells(self, sheet: str, tab: str, row: int, values: Any) -> None: ...
    def replace_tab(self, sheet: str, tab: str, header: Any, rows: Any) -> None: ...


def client_for(settings: Settings) -> Client:
    """The one place a live client is built (tests swap it for an in-memory fake)."""
    return DriveClient.from_settings(settings)


def note_from_row(row: dict[str, str]) -> tuple[dict[str, Any], str]:
    """A Sheet row back into (frontmatter, body), the shape the vault notes have."""
    fm: dict[str, Any] = {k: row[k] for k in REQUIRED if row.get(k, "").strip()}
    leaps = json.loads(row["leaps"]) if row.get("leaps", "").strip() else []
    if leaps:
        fm["leaps"] = leaps
    return fm, row.get("body", "")


class InspirationsTable:
    def __init__(self, client: Client) -> None:
        self._c = client
        self._c.ensure_header(*INSPIRATIONS, INSPIRATION_HEADER)

    def rows(self) -> list[dict[str, str]]:
        return self._c.read_tab(*INSPIRATIONS, required=["id"])

    def ids(self) -> set[str]:
        return {r["id"] for r in self.rows()}

    def append(self, fm: dict[str, Any], body: str, *, inbox_row_id: str = "") -> None:
        row = {k: str(fm.get(k, "")) for k in REQUIRED}
        row.update(leaps=json.dumps(list(fm.get("leaps") or [])), body=body,
                   url_hash=url_hash(str(fm.get("source_url", ""))), inbox_row_id=inbox_row_id)
        self._c.append_rows(*INSPIRATIONS, [row])

    def update(self, note_id: str, mutate: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        for row in self.rows():
            if row["id"] == note_id:
                fm, _ = note_from_row(row)
                mutate(fm)
                new = {k: str(fm.get(k, "")) for k in REQUIRED}
                new["leaps"] = json.dumps(list(fm.get("leaps") or []))
                changed = {k: v for k, v in new.items() if row.get(k, "") != v}
                if changed:
                    self._c.update_cells(*INSPIRATIONS, int(row["_row"]), changed)
                return fm
        raise KeyError(note_id)


class SourcesTable:
    """`_sources.yaml` venues as rows. Fields that don't fit a column cleanly ride in `extra`
    (JSON) so a save → load round-trip is lossless."""

    def __init__(self, client: Client) -> None:
        self._c = client
        self._c.ensure_header(*SOURCES, SOURCES_HEADER)

    def load(self) -> list[dict[str, Any]]:
        venues = []
        for row in self._c.read_tab(*SOURCES, required=["key"]):
            v: dict[str, Any] = {k: row[k] for k in _SOURCE_TEXT if row.get(k, "")}
            if row.get("categories", ""):
                v["categories"] = [c.strip() for c in row["categories"].split(",") if c.strip()]
            if row.get("yield", ""):
                v["yield"] = json.loads(row["yield"])
            if row.get("extra", ""):
                v.update(json.loads(row["extra"]))
            venues.append(v)
        return venues

    def save(self, venues: list[dict[str, Any]]) -> None:
        rows = []
        for v in venues:
            row: dict[str, str] = {}
            extra: dict[str, Any] = {}
            for k, val in v.items():
                if k in _SOURCE_TEXT and isinstance(val, str) and val:
                    row[k] = val
                elif (k == "categories" and isinstance(val, list) and val
                      and all(isinstance(c, str) and "," not in c for c in val)):
                    row[k] = ",".join(val)
                elif k == "yield" and val is not None:
                    row[k] = json.dumps(val)
                else:
                    extra[k] = val
            if extra:
                row["extra"] = json.dumps(extra, default=str)
            rows.append(row)
        self._c.replace_tab(*SOURCES, SOURCES_HEADER, rows)


class CategoriesTable:
    def __init__(self, client: Client) -> None:
        self._c = client
        self._c.ensure_header(*CATEGORIES, CATEGORY_HEADER)

    def lines(self) -> list[str]:
        """Rows rendered as `categories.txt` lines; disabled rows as comments."""
        out: list[str] = []
        enabled = 0
        for row in self._c.read_tab(*CATEGORIES, required=["slug"]):
            slug = row.get("slug", "").strip()
            if not slug:
                continue
            line = slug
            for hint in ("market", "horizon"):
                if row.get(hint, "").strip():
                    line += f" {hint}={row[hint].strip()}"
            if row.get("enabled", "").strip().lower() in _OFF:
                out.append(f"# {line}")
            else:
                out.append(line)
                enabled += 1
        if not enabled:
            raise DriveError("drive_schema", "Steering/Categories: no enabled category")
        return out
