"""Legacy round-robin selection, shared by the existing attempt repository."""
from __future__ import annotations

import sqlite3

from algua.contracts.idea import IdeaStatus


def select_ideas(conn: sqlite3.Connection, *, limit: int, week_cutoff: str,
                 category: str | None = None) -> list[int]:
    sql = (
        "SELECT i.id, i.category, i.created_at,"
        " (SELECT MIN(CASE ins.obscurity WHEN 'rare' THEN 0 WHEN 'niche' THEN 1"
        "   WHEN 'common' THEN 2 ELSE 3 END) FROM idea_inspirations ins"
        "   WHERE ins.idea_id = i.id) AS obs_rank"
        " FROM ideas i WHERE i.status=? AND i.claimed_by IS NULL"
    )
    params: list[object] = [IdeaStatus.OPEN.value]
    if category is not None:
        sql += " AND category = ?"
        params.append(category)
    rows = conn.execute(sql, params).fetchall()
    recent = {r["category"]: r["n"] for r in conn.execute(
        "SELECT i.category AS category, COUNT(*) AS n FROM idea_attempts a"
        " JOIN ideas i ON i.id = a.idea_id WHERE a.claimed_at >= ? GROUP BY i.category",
        (week_cutoff,))}
    by_cat: dict[str | None, list] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    for lst in by_cat.values():
        lst.sort(key=lambda r: (r["obs_rank"] if r["obs_rank"] is not None else 3,
                                r["created_at"], r["id"]))
    legacy = by_cat.pop(None, [])
    order = sorted(by_cat, key=lambda c: (recent.get(c, 0), c))
    picked: list[int] = []
    while len(picked) < limit and any(by_cat.values()):
        for cat in order:
            if by_cat[cat] and len(picked) < limit:
                picked.append(by_cat[cat].pop(0)["id"])
    while len(picked) < limit and legacy:
        picked.append(legacy.pop(0)["id"])
    return picked
