"""Lossless public memory inputs and portfolio bindings, separate from WF disclosure."""
from __future__ import annotations

from typing import Any

from algua.operator.portfolio_memory_inputs import public_portfolio_inputs
from algua.operator.research_memory_checkpoint import canonical
from algua.registry.store.run_public import public_config


def public_memory_inputs(kind: str, config: Any) -> dict:
    """The new namespace is public only for a complete supported in-sample backtest."""
    if isinstance(config, dict) and "portfolio_replay" in config:
        if kind != "backtest":
            raise ValueError("portfolio_memory:invalid_input")
        return public_portfolio_inputs(config)
    return public_config(config)


def context_input_limit(kind: str, inputs: dict) -> int:
    """Call only after lossless input admission; keep the complete context at24KiB."""
    return (16 * 1024 if kind == "backtest" and set(inputs) == {"portfolio_replay"}
            else 4 * 1024)


def validate_portfolio_bindings(
    kind: str, inputs: dict, *, strategy_name: str, strategy_local_id: Any,
    provenance: dict, metrics: dict, model_refs: list, parent_refs: list,
    extra_metrics: dict,
) -> None:
    """Bind the record's public scalars to its complete replay; never grant authority."""
    if "portfolio_replay" not in inputs:
        return
    payload = inputs["portfolio_replay"]
    captured, manifest = payload["provenance"], payload["manifest"]
    expected_provenance = {key: captured[key] for key in (
        "code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id", "seed")}
    expected_provenance.update(universe_name=None, fundamentals_snapshot=None, news_snapshot=None,
        delisting_snapshot=None, timeframe="1d", period_start=manifest["start"],
        period_end=manifest["end"])
    expected_metrics = {key: payload["metrics"][source] for key, source in (
        ("sharpe_is", "sharpe"), ("sortino_is", "sortino"), ("total_return_is", "total_return"),
        ("max_drawdown_is", "max_drawdown"), ("ann_vol_is", "ann_volatility"),
        ("cagr_is", "cagr"), ("calmar_is", "calmar"))}
    expected_metrics["n_obs_is"] = captured["replay"]["sessions"]
    if (kind != "backtest" or strategy_name != payload["portfolio_name"]
            or strategy_local_id is not None or model_refs or parent_refs or extra_metrics
            or canonical(provenance) != canonical(expected_provenance)
            or canonical(metrics) != canonical(expected_metrics)):
        raise ValueError("portfolio_memory:invalid_binding")
