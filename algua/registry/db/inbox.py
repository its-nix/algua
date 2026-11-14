"""Inbox context: ``inbox_items`` (v54), the owner's dashboard Inbox, operated by
``algua/registry/inbox.py``.
"""
from __future__ import annotations

SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox_items (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('link','file','text')),
    url TEXT,
    canonical_url TEXT,
    title TEXT,
    note TEXT,
    file_path TEXT,
    text TEXT,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','taken')),
    taken_at TEXT,
    inspiration_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_inbox_items_status ON inbox_items(status);
"""
