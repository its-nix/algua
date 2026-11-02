"""Closed comparison syntax; pure metadata parsing shared by capture and display."""
from __future__ import annotations

import math
from datetime import date
from typing import Any

RECORD_SCHEMA = "gate-owned-comparison/v1"
GATE_METRICS = ("sharpe_oos", "total_return_oos", "max_drawdown_oos", "ann_vol_oos", "n_obs_oos")

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


