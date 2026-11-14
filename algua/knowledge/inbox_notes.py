"""Owner Inbox item -> one `source_kind: human` inspiration note (spec 2026-11-14 §7.3).

Pure: builds frontmatter + body, no I/O. The note enters the funnel at the same point as a foraged
note, so leap's critic and dedup apply to it. Everything the owner pasted (link, note, extracted
text) is untrusted content, carried in the body exactly like a foraged note's.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import PurePath
from typing import Any

from algua.knowledge.frontmatter import render_doc
from algua.knowledge.inspirations import MAX_NOTE_BYTES, RESERVED_HUMAN_CATEGORY

_MECHANISM_CHARS = 500
_SLUG_CHARS = 48  # "<date>-inbox-<slug>-<6 hex>" must stay inside NOTE_ID_RE's 60-char tail


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


def _s(item: dict[str, Any], key: str) -> str:
    return str(item.get(key) or "").strip()


def note_suffix(item: dict[str, Any]) -> str:
    """The date-free tail of the item's deterministic note id: `-inbox-<slug>-<sha1(id)[:6]>`."""
    slug_src = (_s(item, "title") or _s(item, "note") or _s(item, "url") or _s(item, "text"))
    return f"-inbox-{_slug(slug_src)}-{hashlib.sha1(str(item['id']).encode()).hexdigest()[:6]}"


def build_note(item: dict[str, Any], *, today: date,
               categories: set[str]) -> tuple[dict[str, Any], str]:
    title, note, url, text = _s(item, "title"), _s(item, "note"), _s(item, "url"), _s(item, "text")
    file_name = PurePath(_s(item, "file_path")).name if _s(item, "file_path") else ""
    idea = title or note or url or text[:_MECHANISM_CHARS] or file_name or "owner inbox item"
    category = _s(item, "category")
    note_id = f"{today.isoformat()}{note_suffix(item)}"
    fm: dict[str, Any] = {
        "id": note_id, "found_at": today.isoformat(),
        "source_url": url or f"inbox:{item['id']}", "venue": "inbox", "source_kind": "human",
        "category": category if category in categories else RESERVED_HUMAN_CATEGORY,
        "market": "us_equities", "horizon": "daily", "mechanism": idea[:_MECHANISM_CHARS],
        "obscurity": "human", "status": "fresh", "inbox_item_id": item["id"],
    }
    parts = [f"## Idea\n\n{title or note or idea}"]
    if note:
        parts.append(f"## Why / notes\n\n{note}")
    if url:
        parts.append(f"## Link\n\n{url}")
    if file_name:
        parts.append(f"## File\n\n{file_name}")
    if text:
        parts.append(f"## Extracted text\n\n{text}")
    return fm, _fit(fm, "\n\n".join(parts) + "\n")
