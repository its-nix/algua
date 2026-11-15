"""Read historical allocation bases for the fleet's display-only P&L accounting."""
from __future__ import annotations

import math
import sqlite3
from bisect import bisect_right
from datetime import UTC, datetime


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def allocation_capitals_at(
    conn: sqlite3.Connection, strategy_id: int, tick_timestamps: list[str],
) -> list[float] | None:
    """Match ticks to allocation intervals [effective_ts, revoked_ts), in input order.

    No history (or a wholly pre-allocation legacy interval) returns None: those snapshots retain
    their historical raw-equity display. Mixed legacy/allocated or gapped history is unknowable
    and refused rather than assigning zero capital and inventing profit. Allocations have no
    lane/account column; callers must keep the tick lanes' P&L baselines separate.
    """
    rows = conn.execute(
        "SELECT id, capital, effective_ts, revoked_ts FROM strategy_allocations "
        "WHERE strategy_id = ?", (strategy_id,),
    ).fetchall()
    if not rows or not tick_timestamps:
        return None
    history = sorted(
        ((_utc(row["effective_ts"]), row["id"], float(row["capital"]),
          _utc(row["revoked_ts"]) if row["revoked_ts"] is not None else None)
         for row in rows), key=lambda row: (row[0], row[1]))
    ticks = [_utc(value) for value in tick_timestamps]
    if max(ticks) < history[0][0]:
        return None
    effective = [row[0] for row in history]
    capitals = []
    for tick in ticks:
        index = bisect_right(effective, tick) - 1
        if index < 0:
            raise ValueError("incomplete allocation history for fleet equity")
        _, _, capital, revoked = history[index]
        if (revoked is not None and tick >= revoked) or not math.isfinite(capital) or capital <= 0:
            raise ValueError("incomplete allocation history for fleet equity")
        capitals.append(capital)
    return capitals
