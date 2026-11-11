"""The narrow bars-plus-pinned-linear-model profile for immutable planner execution."""
from __future__ import annotations

from algua.contracts.model_types import ModelHandle
from algua.features.price_linear_context import validate_proxy_model
from algua.strategies.base import LoadedStrategy
from algua.strategies.loader import load_strategy


def load_frozen_model_strategy(name: str, *, model: ModelHandle) -> LoadedStrategy:
    """Resolve authored code with caller-verified bundle bytes, never the host model store."""
    validate_proxy_model(model)
    strategy = load_strategy(name, model_resolver=lambda _name, _config: model)
    config = strategy.config
    if (strategy.strategy_interface != 'context_v1' or not config.needs_model
            or config.model_ref != model.version.as_ref()
            or config.needs_news or config.needs_fundamentals
            or config.execution.rebalance_frequency != '1d'):
        raise ValueError(
            'unsupported frozen model profile: daily context bars and one pin required')
    return strategy
