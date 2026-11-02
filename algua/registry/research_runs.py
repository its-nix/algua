"""Public in-sample/selection windows, independently validated before display-only grouping."""
from __future__ import annotations

from typing import Any

from algua.data.board_provenance import project_snapshot_record
from algua.provenance.research_disclosure import public_run_provenance
from algua.registry.board_comparison import _unknown
from algua.registry.research_record import record_digest
from algua.registry.run_provenance import decode_json
from algua.registry.store import SqliteStrategyRepository
from algua.registry.store.public_windows import METRICS, PROVENANCE, number, public_record

RESEARCH_SCHEMA_VERSION = "strategy-board-research/v2"


def _wrapper(status: str, reason: str | None, value: Any = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


def _comparison(run: Any, config: Any, identity: int) -> tuple[dict[str, Any], dict[str, Any]]:
    observation = config.get("public_window_record")
    if observation is None:
        return _unknown("research_record_absent"), {}
    record = public_record(observation)
    if record.get("invalid_fields"):
        return _unknown("invalid_recorded_context"), {}
    if (set(config) - {"params", "run_provenance", "public_window_record",
                       "windows", "holdout_frac", "embargo"}
        or type(record["strategy_id"]) is not int or record["strategy_id"] != identity
        or record["provenance"] != {k: run[k] for k in PROVENANCE if run[k] is not None}
        or any(not number(run[k]) or run[k] != record["statistics"][k] for k in METRICS)
        or config.get("run_provenance") != record["inputs"]
        or record_digest(config.get("params", {})) != record_digest(record["params"])
        or public_run_provenance(config.get("run_provenance")) != record["inputs"]):
        return _unknown("invalid_recorded_context"), {}
    context, inputs = record["context"], record["inputs"]
    for key in ("windows", "holdout_frac", "embargo"):
        expected = len(context["windows"]) if key == "windows" else context[key]
        if type(config.get(key)) is not type(expected) or config.get(key) != expected:
            return _unknown("invalid_recorded_context"), {}
    if (run["passed"] is not None or run["gate_id"] is not None
        or run["series_holdout_id"] is not None or run["series_backtest_id"] is not None
        or decode_json(run["derived_from"]) != []
        or any(run[k] is not None for k in run.keys() if k.endswith(("_is", "_oos", "_realized")))):
        return _unknown("invalid_canonical_lineage"), {}
    if any(run[k] is not None for k in (
        "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
    )) or decode_json(run["components"]) != [] or record["research_inputs"] != {
        "delisting_snapshot": None, "assume_terminal_last_close": False,
    }:
        return _unknown("unsupported_modal_inputs"), {}
    if type(run["metric_schema_version"]) is not int or run["metric_schema_version"] != 1:
        return _unknown("unsupported_metric_schema"), {}
    bars, costs = inputs["bars"], inputs["execution_costs"]
    source = project_snapshot_record(run["snapshot_id"], bars)
    if source["status"] != "VALID":
        return _unknown("invalid_source_metadata"), {}
    snapshot = source["value"]
    if snapshot["data_tier"] != "pilot_real_proxy":
        return _unknown("unsupported_data_tier"), {}
    if (run["data_source"] != "StoreBackedProvider"
        or not set(context["execution"]["symbol_order"]) <= set(bars["symbols"])
        or context["public_interval"]["start"] < snapshot["coverage_start"]
        or context["public_interval"]["end"] > snapshot["coverage_end"]):
        return _unknown("invalid_source_metadata"), {}
    cohort = {**context, "execution_costs": {**costs, "fees": float(costs["fees"]),
              "slippage": float(costs["slippage"])}, "snapshot_id": bars["snapshot_id"],
              "content_hash": bars["content_hash"], "data_tier": snapshot["data_tier"],
              "source": snapshot, "dependency_hash": run["dependency_hash"], "seed": run["seed"]}
    digest = record_digest({"kind": "public_windows", "context": cohort})
    return {"status": "COMPARABLE", "observed_metric_sort_enabled": True, "reasons": [],
            "cohort_id": digest, "context": cohort}, source


def research_run_payload(
    repo: SqliteStrategyRepository, strategy_id: int, run_id: int | None = None,
) -> dict[str, Any]:
    from algua.registry.strategy_board import _valid_created_at

    strategy = repo.connection.execute("SELECT id FROM strategies WHERE id=?", (strategy_id,))
    if strategy.fetchone() is None:
        raise ValueError("strategy identity not found")
    if run_id is None:
        run = repo.connection.execute(
            "SELECT * FROM runs WHERE kind='walk_forward' AND strategy_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT 1", (strategy_id,),
        ).fetchone()
    else:
        run = repo.connection.execute(
            "SELECT * FROM runs WHERE kind='walk_forward' AND strategy_id=? AND id=?",
            (strategy_id, run_id),
        ).fetchone()
        if run is None:
            raise ValueError("research run does not belong to this strategy identity")
    payload: dict[str, Any] = {"strategy_id": strategy_id, "latest_research": None,
                               "evidence": None, "recorded_provenance": None}
    if run is None or _valid_created_at(run["created_at"]) is None:
        return payload
    comparison = _unknown("invalid_recorded_context")
    source: dict[str, Any] = {}
    try:
        config = decode_json(run["config_json"])
        if isinstance(config, dict):
            comparison, source = _comparison(run, config, strategy_id)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        pass
    valid, context = comparison["status"] == "COMPARABLE", comparison["context"]
    payload["latest_research"] = {
        "kind": "public_windows", "run_id": run["id"], "created_at": run["created_at"],
        **{k: float(run[k]) if valid else None for k in METRICS},
    }
    unavailable = _wrapper("UNAVAILABLE", "missing_fields")
    payload["evidence"] = {
        "kind": "public_windows", "run_id": run["id"],
        "evaluation": _wrapper("VALID", None, {k: run[k] for k in (
            "period_start", "period_end", "timeframe", "metric_schema_version")}) if valid
            else unavailable,
        "public_interval": (_wrapper("VALID", None, context["public_interval"])
                            if valid else unavailable),
        "statistics": (_wrapper("VALID", None, {k: float(run[k]) for k in METRICS})
                       if valid else unavailable),
        "snapshot_provenance": source if valid else unavailable,
        "comparison": comparison,
    }
    payload["recorded_provenance"] = _wrapper("VALID", None, {
        "bars_snapshot_id": context["snapshot_id"], "bars_content_hash": context["content_hash"],
        "execution_costs": context["execution_costs"],
    }) if valid else unavailable
    return payload
