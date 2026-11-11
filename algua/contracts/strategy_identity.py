"""Stable pure strategy config identity for backtest, approvals, and frozen decoding."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from algua.contracts.strategy_interface import (
    CONTEXT_INTERFACE_V1,
    LEGACY_INTERFACE,
    StrategyInterface,
    is_supported_strategy_interface,
    uses_context_interface,
)


def loaded_config_hash(strategy: Any) -> str:
    return strategy_config_hash(strategy.config, strategy_interface=strategy.strategy_interface)


def strategy_config_hash(
    config: Any, *, strategy_interface: StrategyInterface = LEGACY_INTERFACE,
) -> str:
    if not is_supported_strategy_interface(strategy_interface):
        raise ValueError("unsupported strategy interface for config identity")
    identity = _identity(config)
    if uses_context_interface(strategy_interface):
        identity["strategy_interface"] = CONTEXT_INTERFACE_V1
    return _hash(identity)


def _identity(config: Any) -> dict[str, Any]:
    identity: dict[str, Any] = {
        "name": config.name,
        "universe": config.universe,
        "params": config.params,
        "execution": asdict(config.execution),
        "construction": config.construction,
        "construction_params": config.construction_params,
        "needs_fundamentals": config.needs_fundamentals,
        "needs_news": config.needs_news,
        "feature_lookback": config.feature_lookback,
    }
    if config.needs_model:
        assert config.model_ref is not None
        identity["needs_model"] = True
        identity["model_ref"] = config.model_ref.as_dict()
    if config.overlays:
        identity["overlays"] = [spec.model_dump() for spec in config.overlays]
    return identity


def _hash(identity: dict[str, Any]) -> str:
    payload = json.dumps(identity, sort_keys=True, allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
