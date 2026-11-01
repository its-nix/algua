"""Recorded, bounded research cohorts for display only; no promotion consumer."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date
from typing import Any

from algua.provenance.snapshot import SCHEMA_VERSION, SnapshotRecord
from algua.registry.run_provenance import decode_json
from algua.registry.store import SqliteStrategyRepository

METRICS = "net_daily_returns_252_rf0_ddof1_compounded_floored_drawdown/v1"
_SIMULATION = {
    "fixed_fees": 0.0, "min_size": 1e-8, "max_size": "+inf", "size_granularity": "nan",
    "reject_prob": 0.0, "lock_cash": False, "allow_partial": True, "raise_reject": False,
    "log": False, "price": "+inf", "val_price": "+inf", "call_seq": "default",
    "ffill_val_price": True, "update_value": False, "seed": None, "fillna_close": True,
    "direction": "both", "freq": "1D", "group_by": True, "engine": "numba",
    "initial_cash_mode": "fixed", "vectorbt_version": "1.0.0",
}


def exact(value: Any, keys: str) -> bool:
    return isinstance(value, dict) and set(value) == set(keys.split())


def integer(value: Any, minimum: int = 1) -> bool:
    return type(value) is int and minimum <= value <= 2**53 - 1


def number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def day(value: Any) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def segment(value: Any) -> bool:
    return (exact(value, "start end n_bars") and day(value["start"]) and day(value["end"])
            and value["start"] <= value["end"] and integer(value["n_bars"])
            and value["n_bars"] <= (date.fromisoformat(value["end"])
                                    - date.fromisoformat(value["start"])).days + 1)


def _simulation(value: Any) -> bool:
    return exact(value, " ".join(_SIMULATION)) and all(
        (number(value[k]) if type(expected) in (int, float)
         else type(value[k]) is type(expected)) and value[k] == expected
        for k, expected in _SIMULATION.items()
    )


def decode_context(value: Any) -> dict[str, Any] | None:
    """Closed schema: unknown versions/fields or requested rather than effective flags refuse."""
    if not exact(value, "schema_version protocol metrics timeframe period_start period_end "
                 "holdout_frac embargo windows oos execution"):
        return None
    if (value["schema_version"] != "research-comparison/v1"
        or value["protocol"] != "continuous_portfolio_tail_holdout"
        or value["metrics"] != METRICS or value["timeframe"] != "1d"
        or not day(value["period_start"]) or not day(value["period_end"])
        or not value["period_start"] < value["period_end"]
        or not number(value["holdout_frac"]) or not 0 < value["holdout_frac"] < 1
        or not integer(value["embargo"], 0) or not segment(value["oos"])):
        return None
    windows, oos, execution = value["windows"], value["oos"], value["execution"]
    if not isinstance(windows, list) or len(windows) < 2 or not all(map(segment, windows)):
        return None
    segments = [*windows, oos]
    if (any(a["end"] >= b["start"] for a, b in zip(segments, segments[1:], strict=False))
        or segments[0]["start"] < value["period_start"] or oos["end"] >= value["period_end"]):
        return None
    n = sum(w["n_bars"] for w in segments) + value["embargo"]
    if n > (date.fromisoformat(value["period_end"])
            - date.fromisoformat(value["period_start"])).days:
        return None
    if int(n * value["holdout_frac"]) != oos["n_bars"]:
        return None
    base = (n - oos["n_bars"] - value["embargo"]) // len(windows)
    if base < 5 or any(w["n_bars"] != base for w in windows[:-1]):
        return None
    if not exact(execution, "schema_version decision_lag_bars fill_basis valuation_basis sizing "
                 "cash_sharing initial_cash symbol_order rebalance price_units simulation"):
        return None
    symbols = execution["symbol_order"]
    if (execution["schema_version"] != "replay-execution/v1"
        or not integer(execution["decision_lag_bars"])
        or execution["fill_basis"] not in ("adjusted_close", "adjusted_open")
        or execution["valuation_basis"] != execution["fill_basis"]
        or execution["sizing"] != "targetpercent"
        or not _simulation(execution["simulation"])
        or execution["cash_sharing"] is not True
        or not number(execution["initial_cash"]) or execution["initial_cash"] <= 0
        or execution["rebalance"] != "every_daily_bar"
        or execution["price_units"] != "vendor_adjusted"
        or not isinstance(symbols, list) or not symbols
        or any(not isinstance(s, str) or not s.strip() for s in symbols)
        or len(set(symbols)) != len(symbols)):
        return None
    return value


def _strict_bars(bars: Any) -> bool:
    if not isinstance(bars, dict):
        return False
    try:
        decoded = SnapshotRecord.from_dict(bars)
        return (decoded.to_dict() == bars and type(bars["schema_version"]) is int
                and bars["schema_version"] == SCHEMA_VERSION
                and re.fullmatch(r"[a-f0-9]{64}", decoded.content_hash) is not None
                and integer(bars["row_count"]) and isinstance(bars["symbols"], list)
                and all(isinstance(s, str) and s for s in bars["symbols"])
                and len(set(bars["symbols"])) == len(bars["symbols"])
                and isinstance(bars["source_metadata"], dict)
                and all(isinstance(k, str) and isinstance(v, str)
                        for k, v in bars["source_metadata"].items())
                and all(k not in bars["source_metadata"]
                        or bars["source_metadata"][k] == bars[k]
                        for k in ("timeframe", "adjustment")))
    except (ValueError, KeyError, TypeError, OverflowError):
        return False


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "UNKNOWN", "observed_metric_sort_enabled": False,
            "reasons": [reason], "cohort_id": None, "context": None}


def comparison_evidence(
    repo: SqliteStrategyRepository, row: Any, evidence: dict[str, Any],
    recorded: dict[str, Any],
) -> dict[str, Any]:
    """Validate a row independently before computing a cohort; never use present-day inputs."""
    if recorded["status"] != "VALID":
        return _unknown("recorded_inputs_unavailable")
    if any(evidence[k]["status"] != "VALID" for k in (
        "evaluation", "oos_interval", "snapshot_provenance",
    )):
        return _unknown("lineage_or_source_unavailable")
    try:
        # recorded_run_evidence already checked the single sibling and canonical identities.
        sibling = repo.get_run(decode_json(row["derived_from"])[0])
        if sibling is None:
            return _unknown("invalid_recorded_context")
        config = decode_json(sibling["config_json"])
        if "comparison_context" not in config or config["comparison_context"] is None:
            return _unknown("comparison_context_absent")
        context = decode_context(config["comparison_context"])
        if context is None:
            raw = config["comparison_context"]
            return _unknown("execution_context_absent" if isinstance(raw, dict)
                            and raw.get("execution", "absent") is None
                            else "invalid_recorded_context")
        snapshot = evidence["snapshot_provenance"]["value"]
        if snapshot["data_tier"] != "pilot_real_proxy":
            return _unknown("unsupported_data_tier")
        bars = config["run_provenance"]["bars"]
        if (not _strict_bars(bars) or bars["timeframe"] != context["timeframe"]
            or sibling["data_source"] != "StoreBackedProvider"
            or not set(context["execution"]["symbol_order"]) <= set(bars["symbols"])
            or context["windows"][0]["start"] < snapshot["coverage_start"]
            or context["oos"]["end"] > snapshot["coverage_end"]):
            return _unknown("invalid_source_metadata")
        if any(sibling[k] is not None for k in (
            "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
        )) or decode_json(sibling["components"]) != []:
            return _unknown("unsupported_modal_inputs")
        if any(not isinstance(sibling[k], str) or not sibling[k].strip()
               for k in ("code_hash", "config_hash", "dependency_hash")):
            return _unknown("missing_artifact_identity")
        gate = repo.get_run(row["run_id"])
        if gate is None or not isinstance(gate["code_hash"], str) or not gate["code_hash"].strip():
            return _unknown("missing_artifact_identity")
        # These code hashes deliberately retain different schemes; config/dependencies were
        # matched upstream. Modal components must agree independently, including empty lists.
        if decode_json(gate["components"]) != decode_json(sibling["components"]):
            return _unknown("invalid_recorded_context")
        if sibling["metric_schema_version"] != 1 or row["metric_schema_version"] != 1:
            return _unknown("unsupported_metric_schema")
        for key in ("period_start", "period_end", "timeframe"):
            if context[key] != row[key]:
                return _unknown("invalid_recorded_context")
        oos = evidence["oos_interval"]["value"]
        if context["oos"] != {"start": oos["holdout_start"], "end": oos["holdout_end"],
                              "n_bars": oos["n_bars"]}:
            return _unknown("invalid_recorded_context")
        burn = repo.connection.execute(
            "SELECT config_hash,data_source,holdout_frac FROM holdout_evaluations WHERE id=?",
            (row["evaluation_id"],),
        ).fetchone()
        if (burn is None or burn["config_hash"] != sibling["config_hash"]
            or burn["data_source"] != sibling["data_source"]
            or not number(burn["holdout_frac"]) or burn["holdout_frac"] != context["holdout_frac"]):
            return _unknown("invalid_canonical_lineage")
        vol = sibling["ann_vol_oos"]
        if (vol != gate["ann_vol_oos"]
            or vol is not None and (not number(vol) or vol < 0)
            or row["sharpe_oos"] is not None and (vol is None or vol <= 0)):
            return _unknown("metric_binding_mismatch")
        for key in ("sharpe_oos", "total_return_oos", "max_drawdown_oos", "n_obs_oos"):
            if row[key] != sibling[key] or (row[key] is not None and not number(row[key])):
                return _unknown("metric_binding_mismatch")
        if (row["total_return_oos"] is not None and row["total_return_oos"] < -1
            or row["max_drawdown_oos"] is not None and not -1 <= row["max_drawdown_oos"] <= 0):
            return _unknown("metric_binding_mismatch")
        cohort = {**context, "execution_costs": recorded["value"]["execution_costs"],
                  "snapshot_id": bars["snapshot_id"], "content_hash": bars["content_hash"],
                  "data_tier": snapshot["data_tier"], "source": snapshot,
                  "dependency_hash": sibling["dependency_hash"]}
        # JSON gives stable equality for numbers written as int or float by different callers.
        costs = cohort["execution_costs"]
        cohort["execution_costs"] = {**costs, "fees": float(costs["fees"]),
                                     "slippage": float(costs["slippage"])}
        encoded = json.dumps(cohort, sort_keys=True, allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return {"status": "COMPARABLE", "observed_metric_sort_enabled": True, "reasons": [],
                "cohort_id": digest, "context": cohort}
    except (ValueError, KeyError, TypeError, IndexError, RecursionError):
        return _unknown("invalid_recorded_context")
