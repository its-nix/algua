"""Identity-bound ordinary WF research disclosure, separate from gate/series authority."""
from __future__ import annotations

from typing import Any

from algua.data.board_provenance import project_snapshot_record
from algua.registry.board_comparison import (
    _strict_bars,
    _unknown,
    decode_context,
    number,
)
from algua.registry.research_record import record_digest
from algua.registry.run_provenance import _costs_valid, decode_json
from algua.registry.store import SqliteStrategyRepository

RESEARCH_SCHEMA_VERSION = "strategy-board-research/v1"
_METRICS = ("sharpe_oos", "sortino_oos", "total_return_oos", "max_drawdown_oos", "ann_vol_oos",
            "n_obs_oos", "mean_window_sharpe", "std_window_sharpe", "min_window_sharpe",
            "pct_positive_windows")
_PROVENANCE = ("code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id",
               "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
               "seed", "timeframe", "period_start", "period_end")


def _wrapper(status: str, reason: str | None, value: Any = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


def _comparison(run: Any, config: Any, identity: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate each producer record before grouping. Never reconstruct metrics or inputs."""
    context = decode_context(config.get("comparison_context"))
    observation = config.get("research_record")
    if observation is None:
        return _unknown("research_record_absent"), {}
    if not isinstance(observation, dict) or set(observation) != {
        "schema_version", "strategy_id", "provenance", "metrics", "context_sha256", "inputs_sha256",
    } or observation["schema_version"] != "recorded-wf-scalars/v1":
        return _unknown("invalid_recorded_context"), {}
    if (type(observation["strategy_id"]) is not int or observation["strategy_id"] != identity
        or observation["provenance"] != {k: run[k] for k in _PROVENANCE if run[k] is not None}
        or not isinstance(observation["metrics"], dict)
        or any(v is not None and not number(v) for v in observation["metrics"].values())
        or observation["metrics"] != {k: run[k] for k in _METRICS}
        or observation["context_sha256"] != record_digest(config.get("comparison_context"))
        or observation["inputs_sha256"] != record_digest({
            "run_provenance": config.get("run_provenance"),
            "research_inputs": config.get("research_inputs")})):
        return _unknown("invalid_recorded_context"), {}
    if context is None:
        return _unknown("invalid_recorded_context"), {}
    inputs = config.get("run_provenance")
    if not isinstance(inputs, dict) or set(inputs) != {"bars", "execution_costs"}:
        return _unknown("recorded_inputs_unavailable"), {}
    bars, costs = inputs["bars"], inputs["execution_costs"]
    if not _strict_bars(bars) or not _costs_valid(costs):
        return _unknown("invalid_source_metadata"), {}
    source = project_snapshot_record(run["snapshot_id"], bars)
    if source["status"] != "VALID":
        return _unknown("invalid_source_metadata"), {}
    snapshot = source["value"]
    if snapshot["data_tier"] != "pilot_real_proxy":
        return _unknown("unsupported_data_tier"), {}
    if (bars["timeframe"] != context["timeframe"] or run["data_source"] != "StoreBackedProvider"
        or not set(context["execution"]["symbol_order"]) <= set(bars["symbols"])
        or context["windows"][0]["start"] < snapshot["coverage_start"]
        or context["oos"]["end"] > snapshot["coverage_end"]):
        return _unknown("invalid_source_metadata"), {}
    if config.get("research_inputs") != {
        "delisting_snapshot": None, "assume_terminal_last_close": False,
    } or type(config["research_inputs"]["assume_terminal_last_close"]) is not bool:
        return _unknown("unsupported_modal_inputs"), {}
    if any(run[k] is not None for k in (
        "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
    )) or decode_json(run["components"]) != []:
        return _unknown("unsupported_modal_inputs"), {}
    if any(not isinstance(run[k], str) or not run[k].strip()
           for k in ("code_hash", "config_hash", "dependency_hash")):
        return _unknown("missing_artifact_identity"), {}
    if type(run["metric_schema_version"]) is not int or run["metric_schema_version"] != 1:
        return _unknown("unsupported_metric_schema"), {}
    if any(context[k] != run[k] for k in ("period_start", "period_end", "timeframe")):
        return _unknown("invalid_recorded_context"), {}
    if (run["n_obs_oos"] != context["oos"]["n_bars"]
        or any(run[k] is not None and not number(run[k]) for k in _METRICS)
        or run["ann_vol_oos"] is not None and run["ann_vol_oos"] < 0
        or run["sharpe_oos"] is not None
        and (run["ann_vol_oos"] is None or run["ann_vol_oos"] <= 0)
        or run["total_return_oos"] is not None and run["total_return_oos"] < -1
        or run["max_drawdown_oos"] is not None and not -1 <= run["max_drawdown_oos"] <= 0):
        return _unknown("metric_binding_mismatch"), {}
    if (run["passed"] is not None or run["gate_id"] is not None
        or run["series_holdout_id"] is not None or run["series_backtest_id"] is not None
        or decode_json(run["derived_from"]) != []):
        return _unknown("invalid_canonical_lineage"), {}
    cohort = {**context, "execution_costs": {**costs, "fees": float(costs["fees"]),
               "slippage": float(costs["slippage"])}, "snapshot_id": bars["snapshot_id"],
              "content_hash": bars["content_hash"], "data_tier": snapshot["data_tier"],
              "source": snapshot, "dependency_hash": run["dependency_hash"]}
    # Different evidence modes never share a cohort, even if all numerical inputs match.
    digest = record_digest({"kind": "walk_forward", "context": cohort})
    return {"status": "COMPARABLE", "observed_metric_sort_enabled": True, "reasons": [],
            "cohort_id": digest, "context": cohort}, source


def research_run_payload(
    repo: SqliteStrategyRepository, strategy_id: int, run_id: int | None = None,
) -> dict[str, Any]:
    from algua.registry.strategy_board import _gate_entry

    strategy = repo.connection.execute("SELECT id FROM strategies WHERE id=?", (strategy_id,))
    if strategy.fetchone() is None:
        raise ValueError("strategy identity not found")
    if run_id is None:
        run = repo.connection.execute(
            "SELECT *, id AS run_id FROM runs WHERE kind='walk_forward' AND strategy_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT 1", (strategy_id,),
        ).fetchone()
    else:
        run = repo.connection.execute(
            "SELECT *, id AS run_id FROM runs WHERE kind='walk_forward' AND strategy_id=? AND id=?",
            (strategy_id, run_id),
        ).fetchone()
        if run is None:
            raise ValueError("research run does not belong to this strategy identity")
    payload: dict[str, Any] = {"strategy_id": strategy_id, "latest_research": None,
                               "evidence": None, "recorded_provenance": None}
    if run is None:
        return payload
    metrics = _gate_entry(run)
    if metrics is None:
        return payload
    metrics.pop("passed")
    payload["latest_research"] = {"kind": "walk_forward", **metrics}
    comparison = _unknown("invalid_recorded_context")
    source: dict[str, Any] = {}
    try:
        config = decode_json(run["config_json"])
        if isinstance(config, dict):
            comparison, source = _comparison(run, config, strategy_id)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        pass
    valid = comparison["status"] == "COMPARABLE"
    context = comparison["context"]
    unavailable = _wrapper("UNAVAILABLE", "missing_fields")
    payload["evidence"] = {
        "run_id": run["id"],
        "evaluation": _wrapper("VALID", None, {k: run[k] for k in (
            "period_start", "period_end", "timeframe", "metric_schema_version")}) if valid
            else unavailable,
        "oos_interval": _wrapper("VALID", None, {
            "holdout_start": context["oos"]["start"], "holdout_end": context["oos"]["end"],
            "n_bars": context["oos"]["n_bars"],
        }) if valid else unavailable,
        "snapshot_provenance": source if valid else unavailable,
        "comparison": comparison,
    }
    payload["recorded_provenance"] = _wrapper("VALID", None, {
        "bars_snapshot_id": context["snapshot_id"], "bars_content_hash": context["content_hash"],
        "execution_costs": context["execution_costs"],
    }) if valid else unavailable
    return payload
