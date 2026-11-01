"""Public WF ledger shape, applied on write and legacy read without altering history."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from algua.provenance.research_disclosure import (
    public_number,
    public_numbers,
    public_run_provenance,
)

WINDOW_METRICS = frozenset({
    "mean_window_sharpe", "std_window_sharpe", "min_window_sharpe", "pct_positive_windows",
})
WINDOWED_KINDS = frozenset({"walk_forward", "sweep", "sweep_trial"})


def public_lineage(value: Any) -> list[int]:
    return value if isinstance(value, list) and all(type(i) is int for i in value) else []


def public_extra(kind: str, metrics: dict[str, Any] | None) -> dict[str, Any]:
    if kind not in WINDOWED_KINDS:
        return dict(metrics or {})
    return {k: public_number(v) for k, v in (metrics or {}).items()
            if kind == "sweep" and k == "mean_trial_sharpe"}


def public_config(config: Any) -> dict[str, Any]:
    """Only declared input namespaces may accompany ordinary WF measurements.

    User params are opaque input, preserved losslessly; never recursively strip their keys.
    Unknown result/diagnostic namespaces are not public input evidence.
    """
    if not isinstance(config, dict):
        return {}
    out = {key: config[key] for key in ("params", "grid") if key in config}
    out.update(public_numbers(
        config, ("windows", "holdout_frac", "embargo"), ("windows", "embargo")))
    if "rank_by" in config:
        rank = config["rank_by"]
        out["rank_by"] = rank if rank in ("mean_sharpe", "min_sharpe") else None
    if "run_provenance" in config:
        out["run_provenance"] = public_run_provenance(config["run_provenance"])
    return out


def public_rows(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    """Keep sqlite.Row compatibility for existing repository consumers and import seams."""
    rows = []
    for row in cursor.fetchall():
        if row["kind"] in WINDOWED_KINDS:
            values = dict(row)
            for key in values:
                if key.endswith(("_is", "_oos", "_realized")):
                    values[key] = None
            try:
                config = json.loads(values["config_json"])
            except (ValueError, TypeError):
                config = None
            for key in WINDOW_METRICS:
                values[key] = public_number(values[key])
            values["config_json"] = json.dumps(public_config(config), sort_keys=True)
            try:
                values["derived_from"] = json.dumps(
                    public_lineage(json.loads(values["derived_from"])))
            except (ValueError, TypeError):
                values["derived_from"] = "[]"
            values["components"] = "[]"  # model-backed WF is unsupported
            values["series_backtest_id"] = values["series_holdout_id"] = None
            row = sqlite3.Row(cursor, tuple(values[key] for key in row.keys()))
        rows.append(row)
    return rows


def public_sort_metric(sort: str | None) -> str | None:
    """Sort is already validated by the ledger; invalid ordinary measurements are unavailable."""
    if sort is None:
        return None
    visible = (f"CASE WHEN typeof({sort}) IN ('integer','real') "
               f"AND abs({sort}) <= 1.7976931348623157e308 THEN {sort} END"
               if sort in WINDOW_METRICS else "NULL")
    return ("CASE WHEN kind IN ('walk_forward','sweep','sweep_trial') "
            f"THEN ({visible}) ELSE {sort} END")
