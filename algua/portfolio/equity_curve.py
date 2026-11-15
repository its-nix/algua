"""P&L-indexed portfolio curve: capital moving in or out is never shown as profit."""
from __future__ import annotations

from datetime import UTC, datetime


def _utc(tick_ts: str) -> datetime:
    dt = datetime.fromisoformat(tick_ts)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def pnl_curve(
    series_by_strategy: dict[str, list[dict]],
    active_lanes: dict[str, set[str]] | None = None,
) -> list[dict]:
    """Aggregate per-strategy tick rows (``tick_ts``, ``equity``, ``lane``) into
    ``[{session, pnl, equity}]`` ascending (session = UTC date of ``tick_ts``).

    Per (strategy, lane) book a session keeps its last tick; P&L is the change in equity less
    ``allocated_capital``, and the book's first tick is entry (0). Rows without that field retain
    legacy raw-equity accounting. ``pnl`` is cumulative.
    ``equity`` sums each book's latest equity: counted through the book's own last tick session,
    then carried forward only if the book's lane is in ``active_lanes[strategy]`` (the lanes the
    strategy's CURRENT stage belongs to). ``active_lanes=None`` carries every book forward."""
    books: list[tuple[dict[str, tuple[float, float]], bool]] = []
    for name, rows in series_by_strategy.items():
        by_lane: dict[object, list[tuple[datetime, float, float]]] = {}
        for r in rows:
            equity = float(r["equity"])
            basis = equity - float(r.get("allocated_capital", 0.0))
            by_lane.setdefault(r.get("lane"), []).append((_utc(r["tick_ts"]), equity, basis))
        for lane, lane_rows in by_lane.items():
            active = active_lanes is None or lane in active_lanes.get(name, set())
            books.append(({dt.date().isoformat(): (eq, basis)
                           for dt, eq, basis in sorted(lane_rows, key=lambda row: row[0])}, active))
    latest: list[tuple[float, float] | None] = [None] * len(books)
    cumulative = 0.0
    points: list[dict] = []
    for session in sorted({s for b, _ in books for s in b}):
        total = 0.0
        for i, (book, active) in enumerate(books):
            if session in book:
                prev = latest[i]
                if prev is not None:
                    cumulative += book[session][1] - prev[1]
                latest[i] = book[session]
            cur = latest[i]
            if cur is not None and (active or session <= max(book)):
                total += cur[0]
        points.append({"session": session, "pnl": cumulative, "equity": total})
    return points


def change_today(points: list[dict], today: str) -> float:
    """P&L change over the last session, but only if that session is ``today`` (UTC date)."""
    if len(points) < 2 or points[-1]["session"] != today:
        return 0.0
    return points[-1]["pnl"] - points[-2]["pnl"]
