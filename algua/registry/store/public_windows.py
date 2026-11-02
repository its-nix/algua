"""Closed public-window record, under the existing protected registry/store boundary."""
from __future__ import annotations

import copy
import math
import re
from datetime import date
from typing import Any

from algua.provenance.research_disclosure import public_run_provenance

METRICS = ("mean_window_sharpe", "std_window_sharpe", "min_window_sharpe", "pct_positive_windows")
DEFINITION = "window_sharpe_mean_min_population_std_positive_return_fraction/v1"
PROVENANCE = ("code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id",
              "universe_name", "fundamentals_snapshot", "news_snapshot", "delisting_snapshot",
              "seed", "timeframe", "period_start", "period_end")
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


def number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def integer(value: Any, minimum: int = 1) -> bool:
    return type(value) is int and minimum <= value <= 2**53 - 1


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


def execution_valid(value: Any) -> bool:
    if not exact(value, "schema_version decision_lag_bars fill_basis valuation_basis sizing "
                 "cash_sharing initial_cash symbol_order rebalance price_units simulation"):
        return False
    simulation, symbols = value["simulation"], value["symbol_order"]
    return (
        value["schema_version"] == "replay-execution/v1"
        and integer(value["decision_lag_bars"])
        and value["fill_basis"] in ("adjusted_close", "adjusted_open")
        and value["valuation_basis"] == value["fill_basis"]
        and value["sizing"] == "targetpercent" and value["cash_sharing"] is True
        and number(value["initial_cash"]) and value["initial_cash"] > 0
        and value["rebalance"] == "every_daily_bar" and value["price_units"] == "vendor_adjusted"
        and isinstance(symbols, list) and bool(symbols)
        and all(isinstance(s, str) and s.strip() for s in symbols)
        and len(set(symbols)) == len(symbols)
        and exact(simulation, " ".join(_SIMULATION))
        and all((number(simulation[k]) if type(expected) in (int, float)
                 else type(simulation[k]) is type(expected)) and simulation[k] == expected
                for k, expected in _SIMULATION.items())
    )


def context_valid(value: Any) -> bool:
    if not exact(value, "schema_version protocol metrics timeframe period_start period_end "
                 "holdout_frac embargo windows public_interval execution"):
        return False
    if (value["schema_version"] != "public-window-comparison/v1"
        or value["protocol"] != "continuous_portfolio_public_windows"
        or value["metrics"] != DEFINITION or value["timeframe"] != "1d"
        or not day(value["period_start"]) or not day(value["period_end"])
        or not value["period_start"] < value["period_end"]
        or not number(value["holdout_frac"]) or not 0 < value["holdout_frac"] < 1
        or not integer(value["embargo"], 0) or not execution_valid(value["execution"])):
        return False
    windows, interval = value["windows"], value["public_interval"]
    if (not isinstance(windows, list) or not 2 <= len(windows) <= 10000
        or not all(segment(w) and w["n_bars"] >= 5 for w in windows)
        or not exact(interval, "start end n_bars n_windows")
        or interval != {"start": windows[0]["start"], "end": windows[-1]["end"],
                        "n_bars": sum(w["n_bars"] for w in windows), "n_windows": len(windows)}
        or not integer(interval["n_bars"]) or not integer(interval["n_windows"])
        or windows[0]["start"] < value["period_start"]
        or windows[-1]["end"] >= value["period_end"]
        or any(a["end"] >= b["start"] for a, b in zip(windows, windows[1:], strict=False))
        or any(w["n_bars"] != windows[0]["n_bars"] for w in windows[:-1])
        or not windows[0]["n_bars"] <= windows[-1]["n_bars"]
               < windows[0]["n_bars"] + len(windows)):
        return False
    return True


def valid_record(value: Any) -> bool:
    if (not exact(value, "schema_version strategy_id provenance context windows statistics "
                  "inputs research_inputs execution params")
        or value["schema_version"] != "public-wf-windows/v1"
        or not (value["strategy_id"] is None or integer(value["strategy_id"]))
        or not context_valid(value["context"])
        or value["execution"] != value["context"]["execution"]
        or not execution_valid(value["execution"]) or not isinstance(value["params"], dict)):
        return False
    provenance, context = value["provenance"], value["context"]
    if (not isinstance(provenance, dict) or set(provenance) - set(PROVENANCE)
        or any(not isinstance(v, str) or not v.strip()
               for k, v in provenance.items() if k != "seed")
        or "seed" in provenance and not integer(provenance["seed"], 0)
        or any(provenance.get(k) != context[k] for k in ("period_start", "period_end", "timeframe"))
        or any(not provenance.get(k) for k in ("code_hash", "config_hash", "dependency_hash",
                                               "data_source", "snapshot_id"))):
        return False
    inputs = value["inputs"]
    if (not exact(inputs, "bars execution_costs") or public_run_provenance(inputs) != inputs
        or not isinstance(inputs["bars"], dict) or inputs["bars"].get("invalid_fields")
        or not isinstance(inputs["execution_costs"], dict)
        or inputs["execution_costs"].get("invalid_fields")
        or inputs["bars"]["snapshot_id"] != provenance["snapshot_id"]
        or inputs["bars"]["timeframe"] != context["timeframe"]
        or re.fullmatch(r"[a-f0-9]{64}", inputs["bars"]["content_hash"]) is None
        or not integer(inputs["bars"]["row_count"])
        or len(set(inputs["bars"]["symbols"])) != len(inputs["bars"]["symbols"])):
        return False
    research = value["research_inputs"]
    if (not exact(research, "delisting_snapshot assume_terminal_last_close")
        or research["delisting_snapshot"] is not None
        and not isinstance(research["delisting_snapshot"], str)
        or type(research["assume_terminal_last_close"]) is not bool):
        return False
    windows, statistics = value["windows"], value["statistics"]
    if (not isinstance(windows, list) or len(windows) != len(context["windows"])
        or not exact(statistics, " ".join(METRICS))
        or not all(number(v) for v in statistics.values())
        or not all(exact(w, "start end n_bars sharpe total_return") and number(w["sharpe"])
                   and number(w["total_return"]) and w["total_return"] >= -1 for w in windows)
        or [{k: w[k] for k in ("start", "end", "n_bars")} for w in windows] != context["windows"]):
        return False
    sharpes = [w["sharpe"] for w in windows]
    try:
        mean = math.fsum(s / len(sharpes) for s in sharpes)
        std = math.hypot(*(s - mean for s in sharpes)) / math.sqrt(len(sharpes))
        expected = (mean, std, min(sharpes),
                    sum(w["total_return"] > 0 for w in windows) / len(windows))
        return all(math.isclose(statistics[k], v, rel_tol=1e-12, abs_tol=1e-12)
                   for k, v in zip(METRICS, expected, strict=True))
    except (OverflowError, ValueError):
        return False


def public_record(value: Any) -> dict[str, Any]:
    """All-or-nothing, detached projection. Hashes/flags cannot admit arbitrary result fields."""
    try:
        return copy.deepcopy(value) if valid_record(value) else {"invalid_fields": True}
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return {"invalid_fields": True}
