"""Read-only rows for the Drive Ideas mirror and the owner's Inbox status (spec 2026-11-12 §6.5).

SQLite stays the idea-pool authority in step 1; this only projects it for humans. Pure reads.
"""
from __future__ import annotations

import sqlite3

IDEAS_HEADER = ["id", "title", "category", "status", "parked_reason", "source", "inspirations",
                "latest_outcome", "latest_reason", "strategy", "created_at", "updated_at"]
_REASON_CHARS = 300
_STATUS_REASON_CHARS = 120


def publish_rows(conn: sqlite3.Connection) -> list[dict[str, str]]:
    links: dict[int, list[tuple[str, str]]] = {}
    for r in conn.execute("SELECT idea_id, inspiration_id, venue FROM idea_inspirations "
                          "ORDER BY inspiration_id"):
        links.setdefault(int(r[0]), []).append((str(r[1]), str(r[2])))
    latest: dict[int, tuple[str, str, str]] = {}
    for r in conn.execute("SELECT idea_id, outcome, reason, strategy_name FROM idea_attempts "
                          "WHERE outcome IS NOT NULL ORDER BY outcome_at, id"):
        latest[int(r[0])] = (str(r[1] or ""), str(r[2] or ""), str(r[3] or ""))
    rows = []
    for r in conn.execute("SELECT id, title, category, status, parked_reason, source_type, "
                          "created_at, updated_at FROM ideas ORDER BY id"):
        idea_id = int(r[0])
        venues = list(dict.fromkeys(v for _, v in links.get(idea_id, [])))
        outcome, reason, strategy = latest.get(idea_id, ("", "", ""))
        rows.append({
            "id": str(idea_id), "title": str(r[1] or ""), "category": str(r[2] or ""),
            "status": str(r[3] or ""), "parked_reason": str(r[4] or ""),
            "source": ",".join(venues) or str(r[5] or ""),
            "inspirations": ",".join(i for i, _ in links.get(idea_id, [])),
            "latest_outcome": outcome, "latest_reason": reason[:_REASON_CHARS],
            "strategy": strategy, "created_at": str(r[6] or ""), "updated_at": str(r[7] or ""),
        })
    return rows


def ideas_by_inspiration(conn: sqlite3.Connection) -> dict[str, list[dict[str, str]]]:
    by_id = {row["id"]: row for row in publish_rows(conn)}
    out: dict[str, list[dict[str, str]]] = {}
    for r in conn.execute("SELECT inspiration_id, idea_id FROM idea_inspirations "
                          "ORDER BY idea_id"):
        row = by_id.get(str(r[1]))
        if row is not None:
            out.setdefault(str(r[0]), []).append(row)
    return out


def inbox_status(rows: list[dict[str, str]]) -> str:
    """What happened to an owner idea: `#12 refuted: walkforward_refuted — reason; #13 open`."""
    parts = []
    for row in rows:
        part = f"#{row['id']} {row['status']}"
        if row["latest_outcome"]:
            part += f": {row['latest_outcome']}"
            if row["latest_reason"]:
                part += f" — {row['latest_reason'][:_STATUS_REASON_CHARS]}"
        parts.append(part)
    return "; ".join(parts)
