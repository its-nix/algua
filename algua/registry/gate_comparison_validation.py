"""Independent gate/burn/series/public-sibling checks. Metadata is never authorization."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from algua.provenance.json_record import decode_json
from algua.registry.gate_comparison_context import GATE_METRICS as METRICS
from algua.registry.gate_comparison_context import RECORD_SCHEMA as SCHEMA
from algua.registry.store.public_windows import METRICS as PUBLIC_METRICS
from algua.registry.store.public_windows import (
    PROVENANCE,
    exact,
    integer,
    number,
    public_record,
)

if TYPE_CHECKING:
    from algua.registry.store import SqliteStrategyRepository

def validate_gate_record(
    repo: SqliteStrategyRepository,
    record: Any,
    gate: Any,
    sibling: Any,
) -> bool:
    if (
        not exact(
            record,
            "schema_version strategy_id wf_run_id gate_run_id gate_evaluation_id "
            "holdout_evaluation_id series_holdout_id context public_record metrics",
        )
        or record["schema_version"] != SCHEMA
        or any(
            not integer(record[k])
            for k in (
                "strategy_id",
                "wf_run_id",
                "gate_evaluation_id",
                "holdout_evaluation_id",
                "series_holdout_id",
            )
        )
        or not integer(record["gate_run_id"])
        or record["gate_run_id"] != gate["id"]
        or record["strategy_id"] != gate["strategy_id"]
        or record["wf_run_id"] != sibling["id"]
        or record["gate_evaluation_id"] != gate["gate_id"]
        or record["series_holdout_id"] != gate["series_holdout_id"]
        or gate["kind"] != "gate"
        or sibling["kind"] != "walk_forward"
        or decode_json(gate["derived_from"]) != [sibling["id"]]
        or sibling["strategy_id"] != gate["strategy_id"]
    ):
        return False
    public = public_record(record["public_record"])
    config = decode_json(sibling["config_json"])
    if (
        public.get("invalid_fields")
        or config.get("public_window_record") != public
        or public["strategy_id"] != gate["strategy_id"]
        or public["provenance"] != {k: sibling[k] for k in PROVENANCE if sibling[k] is not None}
        or public["inputs"] != config.get("run_provenance")
        or public["params"] != config.get("params", {})
        or public["research_inputs"]
        != {"delisting_snapshot": None, "assume_terminal_last_close": False}
        or any(
            not number(sibling[k]) or sibling[k] != public["statistics"][k] for k in PUBLIC_METRICS
        )
        or any(
            config.get(k) != v
            for k, v in (
                ("windows", len(public["windows"])),
                ("holdout_frac", public["context"]["holdout_frac"]),
                ("embargo", public["context"]["embargo"]),
            )
        )
    ):
        return False
    context = record["context"]
    # Public bounds and effective execution are separately recorded by the WF recorder;
    # no withheld WF scalar or alias is consulted.
    if any(
        context.get(k) != public["context"][k]
        for k in (
            "timeframe",
            "period_start",
            "period_end",
            "holdout_frac",
            "embargo",
            "windows",
            "execution",
        )
    ):
        return False
    if (
        not exact(record["metrics"], " ".join(METRICS))
        or any(
            not number(gate[k])
            or not number(record["metrics"][k])
            or record["metrics"][k] != gate[k]
            for k in METRICS
        )
        or gate["ann_vol_oos"] <= 0
        or not integer(gate["n_obs_oos"], 2)
    ):
        return False
    evaluation = repo.connection.execute(
        "SELECT * FROM gate_evaluations WHERE id=?",
        (gate["gate_id"],),
    ).fetchone()
    burn = repo.connection.execute(
        "SELECT * FROM holdout_evaluations WHERE id=?",
        (record["holdout_evaluation_id"],),
    ).fetchone()
    series = repo.connection.execute(
        "SELECT id,holdout_evaluation_id,strategy_id,holdout_start,holdout_end,n_bars,created_at "
        "FROM holdout_returns WHERE id=?",
        (record["series_holdout_id"],),
    ).fetchone()
    if (
        evaluation is None
        or burn is None
        or series is None
        or series["holdout_evaluation_id"] != burn["id"]
        or evaluation["passed"] not in (0, 1)
        or evaluation["passed"] != gate["passed"]
        or evaluation["holdout_n_bars"] != gate["n_obs_oos"]
        or any(
            evaluation[k] != gate[k]
            for k in (
                "strategy_id",
                "code_hash",
                "config_hash",
                "dependency_hash",
                "data_source",
                "snapshot_id",
                "period_start",
                "period_end",
                "universe_name",
                "fundamentals_snapshot",
                "news_snapshot",
            )
        )
        or any(
            burn[k] != sibling[k]
            for k in (
                "strategy_id",
                "config_hash",
                "data_source",
                "snapshot_id",
                "period_start",
                "period_end",
            )
        )
        or burn["reused"] != 0
        or burn["holdout_frac"] != context["holdout_frac"]
        or evaluation["holdout_frac"] != context["holdout_frac"]
        or series["strategy_id"] != gate["strategy_id"]
        or context["oos"]
        != {
            "start": series["holdout_start"],
            "end": series["holdout_end"],
            "n_bars": series["n_bars"],
        }
        or (burn["holdout_start"], burn["holdout_end"])
        != (series["holdout_start"], series["holdout_end"])
    ):
        return False
    times = [
        burn["created_at"],
        burn["committed_at"],
        series["created_at"],
        sibling["created_at"],
        evaluation["created_at"],
        gate["created_at"],
    ]
    try:
        instants = [datetime.fromisoformat(t) for t in times]
    except (ValueError, TypeError):
        return False
    if any(t.tzinfo is None for t in instants):
        return False
    if instants != sorted(instants):
        return False
    decision = decode_json(evaluation["decision_json"])
    if not isinstance(decision, dict) or decision.get("passed") is not bool(gate["passed"]):
        return False
    checks = decision.get("checks")
    if not isinstance(checks, list):
        return False
    for name, key in (
        ("holdout_sharpe", "sharpe_oos"),
        ("holdout_return", "total_return_oos"),
        ("min_holdout_observations", "n_obs_oos"),
    ):
        values = [c.get("value") for c in checks if isinstance(c, dict) and c.get("name") == name]
        if len(values) != 1 or not number(values[0]) or values[0] != gate[key]:
            return False
    return True
