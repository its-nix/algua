"""Owner inbox intake (spec 2026-11-12 §6.4).

Each Inbox row with an `idea` becomes ONE `source_kind: human` inspiration, entering the funnel at
the same point as a foraged note, so leap's critic and dedup apply to it. Exactly-once is keyed on
the row's `id` cell, recorded on the inspiration as `inbox_row_id`; editing a taken row changes
nothing, clearing its `id` resubmits it. Every write is idempotent, so a re-run after a Drive
failure converges instead of duplicating.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any

from algua.knowledge.drive.tables import INBOX, INBOX_HEADER, Client, InspirationsTable
from algua.knowledge.frontmatter import render_doc
from algua.knowledge.inspirations import MAX_NOTE_BYTES, RESERVED_HUMAN_CATEGORY

_MECHANISM_CHARS = 500
_SLUG_CHARS = 48  # "<date>-inbox-<slug>-<6 hex>" must stay inside NOTE_ID_RE's 60-char tail
_TAKEN = "taken → inspiration "


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:_SLUG_CHARS].strip("-")
    return slug if len(slug) >= 2 else "idea"


def _fit(fm: dict[str, Any], body: str) -> str:
    """Trim `body` (by bytes, on a character boundary) so the rendered note fits the note cap."""
    budget = MAX_NOTE_BYTES - len(render_doc(fm, "").encode()) - 64
    raw = body.encode()
    if len(raw) <= budget:
        return body
    return raw[:max(budget, 0)].decode("utf-8", errors="ignore").rstrip() + "\n\n…(truncated)\n"


def _note(row: dict[str, str], rid: str, *, today: date,
          categories: set[str]) -> tuple[dict[str, Any], str]:
    idea = row["idea"].strip()
    category = row.get("category", "").strip()
    note_id = (f"{today.isoformat()}-inbox-{_slug(idea)}-"
               f"{hashlib.sha1(rid.encode()).hexdigest()[:6]}")
    fm: dict[str, Any] = {
        "id": note_id, "found_at": today.isoformat(), "source_url": f"inbox:{rid}",
        "venue": "inbox", "source_kind": "human",
        "category": category if category in categories else RESERVED_HUMAN_CATEGORY,
        "market": "us_equities", "horizon": "daily", "mechanism": idea[:_MECHANISM_CHARS],
        "obscurity": "human", "status": "fresh",
    }
    parts = [f"## Idea\n\n{idea}"]
    if row.get("why / notes", "").strip():
        parts.append(f"## Why / notes\n\n{row['why / notes'].strip()}")
    if row.get("links", "").strip():
        parts.append(f"## Links\n\n{row['links'].strip()}")
    return fm, _fit(fm, "\n\n".join(parts) + "\n")


def intake(client: Client, *, today: date, categories: set[str]) -> dict[str, Any]:
    client.ensure_header(*INBOX, INBOX_HEADER)
    rows = client.read_tab(*INBOX, required=["id", "idea"])
    table = InspirationsTable(client)
    taken_by = {r["inbox_row_id"]: r["id"] for r in table.rows() if r.get("inbox_row_id")}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    assigned = 0
    taken: list[str] = []
    warnings: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("idea", "").strip():
            continue
        line = int(row["_row"])
        rid = row.get("id", "").strip()
        if not rid:
            rid = uuid.uuid4().hex[:12]
            client.update_cells(*INBOX, line, {"id": rid})
            assigned += 1
        if rid not in taken_by:
            category = row.get("category", "").strip()
            if category and category not in categories:
                warnings.append({"row": line, "warning": f"unknown category {category!r}"})
            fm, body = _note(row, rid, today=today, categories=categories)
            table.append(fm, body, inbox_row_id=rid)
            taken_by[rid] = fm["id"]
            taken.append(fm["id"])
            row["status"] = ""  # a resubmitted row's old status no longer describes it
        if not row.get("status", "").strip():
            client.update_cells(*INBOX, line, {"status": _TAKEN + taken_by[rid], "updated": now})
    return {"assigned_ids": assigned, "taken": taken, "warnings": warnings}
