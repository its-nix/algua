"""Capture detached, public-only WF evidence at the existing recorder seam."""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from algua.registry.store.public_windows import DEFINITION, public_record


def record_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def capture_public_record(
    result: Any, strategy_id: int | None, provenance: dict[str, Any], metrics: dict[str, Any],
    inputs: dict[str, Any], research_inputs: dict[str, Any] | None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Only actual public records are consulted; never access private result attributes."""
    if research_inputs is None:
        return None
    try:
        windows = [{k: w.get(k) for k in ("start", "end", "n_bars", "sharpe", "total_return")}
                   for w in result.window_metrics]
        context = {
            "schema_version": "public-window-comparison/v1",
            "protocol": "continuous_portfolio_public_windows", "metrics": DEFINITION,
            "timeframe": result.timeframe, "period_start": result.period["start"],
            "period_end": result.period["end"], "holdout_frac": result.holdout_frac,
            "embargo": result.embargo,
            "windows": [{k: w[k] for k in ("start", "end", "n_bars")} for w in windows],
            "public_interval": {"start": windows[0]["start"], "end": windows[-1]["end"],
                                "n_bars": sum(w["n_bars"] for w in windows),
                                "n_windows": len(windows)},
            "execution": getattr(result, "execution_semantics", None),
        }
        record = public_record({
            "schema_version": "public-wf-windows/v1", "strategy_id": strategy_id,
            "provenance": provenance, "context": context, "windows": windows,
            "statistics": metrics, "inputs": inputs, "research_inputs": research_inputs,
            "execution": getattr(result, "execution_semantics", None), "params": dict(params or {}),
        })
        return None if record.get("invalid_fields") else copy.deepcopy(record)
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return None
