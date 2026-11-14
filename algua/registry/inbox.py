"""Operations on the owner's dashboard Inbox (``inbox_items``)."""
from __future__ import annotations

import sqlite3

from algua.knowledge.inspirations import canonical_url


def _row(conn: sqlite3.Connection, item_id: int) -> dict:
    cur = conn.execute("SELECT * FROM inbox_items WHERE id = ?", (item_id,))
    return dict(zip([d[0] for d in cur.description], cur.fetchone(), strict=True))


def _rows(cur: sqlite3.Cursor) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def add_item(
    conn: sqlite3.Connection, *, kind: str, url: str | None = None, title: str | None = None,
    note: str | None = None, file_path: str | None = None, text: str | None = None, now: str,
) -> tuple[dict, bool]:
    """Insert an item; a link duplicating a still-queued one returns it with ``True``."""
    canon = canonical_url(url) if kind == "link" and url else None
    if canon is not None:
        row = conn.execute(
            "SELECT id FROM inbox_items WHERE canonical_url = ? AND status = 'queued' "
            "ORDER BY id LIMIT 1", (canon,)).fetchone()
        if row is not None:
            return _row(conn, row[0]), True
    cur = conn.execute(
        "INSERT INTO inbox_items (created_at, kind, url, canonical_url, title, note, file_path, "
        "text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now, kind, url, canon, title, note, file_path, text))
    conn.commit()
    assert cur.lastrowid is not None
    return _row(conn, cur.lastrowid), False


def list_items(conn: sqlite3.Connection, *, limit: int = 50) -> list[dict]:
    return _rows(conn.execute("SELECT * FROM inbox_items ORDER BY id DESC LIMIT ?", (limit,)))


def queued_items(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn.execute("SELECT * FROM inbox_items WHERE status = 'queued' ORDER BY id"))


def mark_taken(conn: sqlite3.Connection, item_id: int, *, inspiration_id: str, now: str) -> bool:
    cur = conn.execute(
        "UPDATE inbox_items SET status = 'taken', taken_at = ?, inspiration_id = ? "
        "WHERE id = ? AND status = 'queued'", (now, inspiration_id, item_id))
    conn.commit()
    return cur.rowcount == 1
