"""One row per registered identity, joined to its latest gate; read-only display, lifecycle order.
Never feeds promotion or selection. Contract: docs/development/specs/spec-strategy-board/.
"""
from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from algua.contracts.lifecycle import Stage
from algua.registry.board_comparison import comparison_evidence
from algua.registry.run_provenance import recorded_run_evidence
from algua.registry.store import SqliteStrategyRepository

__all__ = [
    "BOARD_METRICS",
    "EVIDENCE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SnapshotEvidenceResolver",
    "strategy_board_payload",
]

SCHEMA_VERSION = "strategy-board/v1"
EVIDENCE_SCHEMA_VERSION = "strategy-board-evidence/v2"
type SnapshotEvidenceResolver = Callable[[str], dict[str, Any]]

#: The gate-run scalars the board exposes — a subset of the fixed run vocabulary, selected from
#: the run row as stored. Nothing is derived, imputed or normalized.
BOARD_METRICS: tuple[str, ...] = (
    "sharpe_oos", "total_return_oos", "max_drawdown_oos", "n_obs_oos",
    "mean_window_sharpe", "min_window_sharpe", "pct_positive_windows",
)

_INT_METRICS = frozenset({"n_obs_oos"})
_LIFECYCLE_ORDER = {stage.value: i for i, stage in enumerate(Stage)}

# The latest gate run is chosen per strategy IDENTITY (`runs.strategy_id = strategies.id`), never
# by reusable name, and by recency (`created_at DESC, id DESC`), never by metric.
_BOARD_SQL = f"""
SELECT s.id AS strategy_id, s.name, s.family, s.stage,
       r.id AS run_id, r.created_at, r.passed, {", ".join(f"r.{m}" for m in BOARD_METRICS)}
FROM strategies s
LEFT JOIN runs r ON r.id = (
    SELECT g.id FROM runs g
    WHERE g.kind = 'gate' AND g.strategy_id = s.id
    ORDER BY g.created_at DESC, g.id DESC
    LIMIT 1)
"""

_EVIDENCE_BOARD_SQL = f"""
SELECT s.id AS strategy_id, s.name, s.family, s.stage,
       r.id AS run_id, r.created_at, r.passed, {", ".join(f"r.{m}" for m in BOARD_METRICS)},
       r.metric_schema_version, r.timeframe, r.period_start, r.period_end, r.snapshot_id,
       r.series_holdout_id, r.derived_from, r.data_source, r.seed, r.universe_name,
       r.fundamentals_snapshot, r.news_snapshot, r.delisting_snapshot,
       r.config_hash, r.dependency_hash,
       h.id AS holdout_id, h.strategy_id AS holdout_strategy_id,
       h.holdout_start, h.holdout_end, h.n_bars AS holdout_n_bars,
       he.id AS evaluation_id, he.strategy_id AS evaluation_strategy_id,
       he.snapshot_id AS evaluation_snapshot_id, he.committed_at AS evaluation_committed_at,
       he.period_start AS evaluation_period_start, he.period_end AS evaluation_period_end,
       he.holdout_start AS evaluation_holdout_start, he.holdout_end AS evaluation_holdout_end
FROM strategies s
LEFT JOIN runs r ON r.id = (
    SELECT g.id FROM runs g
    WHERE g.kind = 'gate' AND g.strategy_id = s.id
    ORDER BY g.created_at DESC, g.id DESC
    LIMIT 1)
LEFT JOIN holdout_returns h ON h.id = r.series_holdout_id
LEFT JOIN holdout_evaluations he ON he.id = h.holdout_evaluation_id
"""


def _scalar(value: Any, *, integer: bool) -> float | int | None:
    """A stored metric as a finite number, or None. SQLite is dynamically typed, so a REAL column
    can hold text or infinity; malformed evidence stays unavailable rather than becoming zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if integer:
        return int(value) if float(value).is_integer() else None
    return float(value)


def _passed(value: Any) -> bool | None:
    if isinstance(value, bool) or value not in (0, 1):
        return None
    return bool(value)


def _valid_created_at(value: Any) -> str | None:
    """Return an offset-aware ISO timestamp, or ``None`` for unusable recency evidence."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _gate_entry(row: sqlite3.Row) -> dict[str, Any] | None:
    if row["run_id"] is None:
        return None
    created_at = _valid_created_at(row["created_at"])
    if created_at is None:
        return None
    entry: dict[str, Any] = {
        "run_id": row["run_id"],
        "created_at": created_at,
        "passed": _passed(row["passed"]),
    }
    for metric in BOARD_METRICS:
        value = _scalar(row[metric], integer=metric in _INT_METRICS)
        entry[metric] = None if metric == "n_obs_oos" and value is not None and value < 0 else value
    return entry


def _wrapper(status: str, reason: str | None, value: dict[str, Any] | None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


def _canonical_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return value if parsed.isoformat() == value else None


def _contained_interval(start: Any, end: Any, lower: str, upper: str) -> tuple[str, str] | None:
    first, last = _canonical_date(start), _canonical_date(end)
    if first is None or last is None or not lower <= first <= last <= upper:
        return None
    return first, last


def _evaluation(row: sqlite3.Row) -> dict[str, Any]:
    values = row["period_start"], row["period_end"], row["timeframe"], row["metric_schema_version"]
    if any(value is None or value == "" for value in values):
        return _wrapper("UNAVAILABLE", "missing_fields", None)
    start = _canonical_date(row["period_start"])
    end = _canonical_date(row["period_end"])
    timeframe = row["timeframe"]
    version = row["metric_schema_version"]
    if (
        start is None
        or end is None
        or start > end
        or not isinstance(timeframe, str)
        or not timeframe
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version <= 0
    ):
        return _wrapper("INVALID", "malformed_fields", None)
    return _wrapper(
        "VALID",
        None,
        {
            "period_start": start,
            "period_end": end,
            "timeframe": timeframe,
            "metric_schema_version": version,
        },
    )


def _oos_interval(row: sqlite3.Row) -> dict[str, Any]:
    if row["series_holdout_id"] is None:
        return _wrapper("UNAVAILABLE", "no_holdout_pointer", None)
    if row["holdout_id"] is None:
        return _wrapper("INVALID", "dangling_holdout_pointer", None)
    if row["holdout_strategy_id"] != row["strategy_id"]:
        return _wrapper("INVALID", "strategy_mismatch", None)
    if row["evaluation_id"] is None:
        return _wrapper("INVALID", "dangling_evaluation_pointer", None)
    if row["evaluation_strategy_id"] != row["strategy_id"]:
        return _wrapper("INVALID", "strategy_mismatch", None)
    evaluation_snapshot = row["evaluation_snapshot_id"]
    run_snapshot = row["snapshot_id"]
    if (
        _valid_created_at(row["evaluation_committed_at"]) is None
        or not isinstance(evaluation_snapshot, str)
        or not evaluation_snapshot
        or not isinstance(run_snapshot, str)
        or not run_snapshot
    ):
        return _wrapper("INVALID", "malformed_fields", None)
    if evaluation_snapshot != run_snapshot:
        return _wrapper("INVALID", "snapshot_binding_mismatch", None)
    evaluation_start = _canonical_date(row["evaluation_period_start"])
    evaluation_end = _canonical_date(row["evaluation_period_end"])
    run_start = _canonical_date(row["period_start"])
    run_end = _canonical_date(row["period_end"])
    if (
        evaluation_start is None or evaluation_end is None
        or evaluation_start > evaluation_end
        or run_start is None or run_end is None
        or run_start > run_end
    ):
        return _wrapper("INVALID", "malformed_fields", None)
    if (evaluation_start, evaluation_end) != (run_start, run_end):
        return _wrapper("INVALID", "evaluation_binding_mismatch", None)
    run_count = row["n_obs_oos"]
    if run_count is None:
        return _wrapper("UNAVAILABLE", "missing_run_oos_count", None)
    interval = _contained_interval(
        row["holdout_start"], row["holdout_end"], evaluation_start, evaluation_end)
    evaluation_interval = _contained_interval(
        row["evaluation_holdout_start"], row["evaluation_holdout_end"],
        evaluation_start, evaluation_end)
    holdout_count = row["holdout_n_bars"]
    if (
        interval is None or evaluation_interval is None
        or isinstance(run_count, bool)
        or not isinstance(run_count, int)
        or run_count <= 0
        or isinstance(holdout_count, bool)
        or not isinstance(holdout_count, int)
        or holdout_count <= 0
    ):
        return _wrapper("INVALID", "malformed_fields", None)
    if interval != evaluation_interval:
        return _wrapper("INVALID", "interval_binding_mismatch", None)
    if holdout_count != run_count:
        return _wrapper("INVALID", "count_mismatch", None)
    return _wrapper("VALID", None, {
        "holdout_start": interval[0], "holdout_end": interval[1], "n_bars": holdout_count})


def _evidence(row: sqlite3.Row, recorded: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
    snapshot_id = row["snapshot_id"]
    snapshot = (
        _wrapper("UNAVAILABLE", "no_snapshot_pointer", None)
        if snapshot_id is None
        else recorded[1]
    )
    return {
        "run_id": row["run_id"],
        "evaluation": _evaluation(row),
        "oos_interval": _oos_interval(row),
        "snapshot_provenance": snapshot,
    }


def strategy_board_payload(
    repo: SqliteStrategyRepository,
    *,
    snapshot_evidence: SnapshotEvidenceResolver | None = None,
) -> dict[str, Any]:
    """`runs board` — every registered strategy once, in lifecycle order, with its latest gate run
    (or ``None``). An empty registry is a successful empty payload."""
    sql = _BOARD_SQL if snapshot_evidence is None else _EVIDENCE_BOARD_SQL
    rows = repo.connection.execute(sql).fetchall()
    rows.sort(key=lambda r: (
        _LIFECYCLE_ORDER.get(r["stage"], len(_LIFECYCLE_ORDER)),
        str(r["name"]).lower(),
        r["strategy_id"],
    ))
    board: list[dict[str, Any]] = []
    for row in rows:
        gate = _gate_entry(row)
        entry = {
            "strategy_id": row["strategy_id"],
            "name": row["name"],
            "family": row["family"],
            "stage": row["stage"],
            "latest_gate": gate,
        }
        if snapshot_evidence is not None:
            if gate is None:
                entry["evidence"] = entry["recorded_provenance"] = None
            else:
                recorded = recorded_run_evidence(repo, row)
                entry["recorded_provenance"] = recorded[0]
                entry["evidence"] = _evidence(row, recorded)
                entry["evidence"]["comparison"] = comparison_evidence(
                    repo, row, entry["evidence"], recorded[0])
        board.append(entry)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "count": len(board),
        "rows": board,
    }
    if snapshot_evidence is not None:
        payload["evidence_schema_version"] = EVIDENCE_SCHEMA_VERSION
    return payload
