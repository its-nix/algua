"""Disclosure of the exact detached order inputs; no alternative simulation or cost math."""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from typing import Any

import numpy as np
import vectorbt as vbt
from vectorbt._engine import is_rust_available

# These are the defaults consumed by the installed Portfolio.from_orders implementation.
# Detach them before the call and pass the same values to the numerical producer and recorder.
_DEFAULTS = (
    "fixed_fees", "min_size", "max_size", "size_granularity", "reject_prob", "lock_cash",
    "allow_partial", "raise_reject", "log", "val_price", "init_cash", "call_seq",
    "ffill_val_price", "update_value", "seed", "attach_call_seq", "fillna_close",
)
_SIMULATION = (
    "fixed_fees", "min_size", "max_size", "size_granularity", "reject_prob", "lock_cash",
    "allow_partial", "raise_reject", "log", "price", "val_price", "call_seq",
    "ffill_val_price", "update_value", "seed", "fillna_close", "direction", "freq", "group_by",
)


def _scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if type(value) is float and not math.isfinite(value):
        return "nan" if math.isnan(value) else "+inf" if value > 0 else "-inf"
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("array-valued simulation settings are outside comparison v1")


def from_orders_recorded(
    factory: Callable[..., Any], *, decision_lag_bars: int, fill_basis: str, **kwargs: Any,
) -> Any:
    """Call the existing numerical producer once, with its unchanged effective parameter values.

    Resolving defaults here makes the disclosure detached from later global/config mutations.
    The original fee/slippage/grid/weight objects are passed through, never recalculated.
    """
    defaults = vbt.settings["portfolio"]
    effective = dict(kwargs)
    for key in _DEFAULTS:
        if effective.get(key) is None:
            effective[key] = copy.deepcopy(defaults[key])
    if effective.get("direction") is None:
        effective["direction"] = copy.deepcopy(defaults["order_direction"])
    if effective.get("price") is None:
        effective["price"] = np.inf  # from_orders' own default, not a portfolio setting
    policy = kwargs.get("engine") or vbt.settings["engine"]
    engine = ("numba" if policy == "numba" or policy == "auto" and not is_rust_available()
              else None)  # auto/Rust dispatch is outside this bounded comparison class
    pf = factory(**effective)
    try:
        simulation = {key: _scalar(effective[key]) for key in _SIMULATION}
        simulation["engine"] = engine
        simulation["vectorbt_version"] = vbt.__version__
        cash_input = _scalar(effective["init_cash"])
        simulation["initial_cash_mode"] = (
            "automatic" if isinstance(cash_input, str) or type(cash_input) is int
            and cash_input in (0, 1) else "fixed"
        )
        evidence = {
            "schema_version": "replay-execution/v1", "decision_lag_bars": decision_lag_bars,
            "fill_basis": fill_basis, "valuation_basis": fill_basis,
            "sizing": effective["size_type"], "cash_sharing": bool(pf.cash_sharing),
            "initial_cash": float(np.asarray(pf.init_cash).item()),
            "symbol_order": list(pf.wrapper.columns), "rebalance": "every_daily_bar",
            "price_units": "vendor_adjusted", "simulation": simulation,
        }
        # Immutable JSON bytes cannot alias provider, config, settings, or returned dicts.
        pf._algua_execution_json = json.dumps(evidence, sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError, AttributeError, OverflowError):
        pf._algua_execution_json = None  # unsupported evidence never changes numerical outcomes
    return pf


def recorded_execution(pf: Any) -> dict[str, Any] | None:
    payload = getattr(pf, "_algua_execution_json", None)
    return json.loads(payload) if payload is not None else None
