"""P&L-indexed portfolio curve: capital moving in or out is never shown as profit."""
from __future__ import annotations

from datetime import UTC, datetime


def _utc(tick_ts: str) -> datetime:
    dt = datetime.fromisoformat(tick_ts)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def pnl_curve(series_by_strategy: dict[str, list[dict]]) -> list[dict]:
    """Aggregate per-strategy tick rows (``tick_ts``, ``equity``, ``lane``) into
    ``[{session, pnl, equity}]`` ascending (session = UTC date of ``tick_ts``).

    Per (strategy, lane) book a session keeps its last tick; P&L is the change vs the book's
    previous session equity, and the book's first tick is entry (0). ``pnl`` is cumulative;
    ``equity`` sums each book's latest equity as of the session."""
    books: list[dict[str, float]] = []
    for rows in series_by_strategy.values():
        by_lane: dict[object, list[tuple[datetime, float]]] = {}
        for r in rows:
            by_lane.setdefault(r.get("lane"), []).append((_utc(r["tick_ts"]), float(r["equity"])))
        for lane_rows in by_lane.values():
            books.append({dt.date().isoformat(): eq for dt, eq in sorted(lane_rows)})
    latest: list[float | None] = [None] * len(books)
    cumulative = 0.0
    points: list[dict] = []
    for session in sorted({s for b in books for s in b}):
        for i, book in enumerate(books):
            if session in book:
                prev = latest[i]
                if prev is not None:
                    cumulative += book[session] - prev
                latest[i] = book[session]
        points.append({
            "session": session,
            "pnl": cumulative,
            "equity": sum(v for v in latest if v is not None),
        })
    return points
