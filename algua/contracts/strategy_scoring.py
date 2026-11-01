"""Pure context-scoring behavior mixed into the loaded research strategy adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast

import pandas as pd

from algua.contracts.model_types import ModelHandle, ModelRef
from algua.contracts.strategy_context import AsOfContext, validate_score_output
from algua.contracts.strategy_interface import uses_context_interface

ScoreFn = Callable[[AsOfContext], pd.Series]


class _Config(Protocol):
    needs_fundamentals: bool
    needs_news: bool
    model_ref: ModelRef | None


class _Strategy(Protocol):
    name: str
    strategy_interface: object
    score_fn: ScoreFn | None
    model_handle: ModelHandle | None
    config: _Config

    def construct(self, scores: pd.Series, view: pd.DataFrame) -> pd.Series: ...


class ContextStrategyMixin:
    @property
    def required_features(self) -> frozenset[str]:
        return required_features(cast(Any, self))

    @property
    def required_models(self) -> Mapping[str, ModelRef]:
        return required_models(cast(Any, self))

    def score(self, context: AsOfContext) -> pd.Series:
        return score(cast(Any, self), context)

    def target_weights_context(self, context: AsOfContext) -> pd.Series:
        return target_weights(cast(Any, self), context)


def required_features(strategy: _Strategy) -> frozenset[str]:
    required = {"bars"}
    if strategy.config.needs_fundamentals:
        required.add("fundamentals")
    if strategy.config.needs_news:
        required.add("news")
    return frozenset(required)


def required_models(strategy: _Strategy) -> Mapping[str, ModelRef]:
    ref = strategy.config.model_ref
    return {} if ref is None else {ref.name: ref}


def score(strategy: _Strategy, context: AsOfContext) -> pd.Series:
    if not uses_context_interface(strategy.strategy_interface) or strategy.score_fn is None:
        raise ValueError(f"strategy {strategy.name!r} does not use score(context)")
    missing_features = set(required_features(strategy)) - context.features.keys()
    if missing_features:
        raise ValueError(f"missing required feature modalities: {sorted(missing_features)}")
    models = context.models
    pins = required_models(strategy)
    missing_models = set(pins) - models.keys()
    if missing_models:
        raise ValueError(f"missing required pinned models: {sorted(missing_models)}")
    for key, ref in pins.items():
        if models[key].version.as_ref() != ref:
            raise ValueError(f"context model reference {key!r} does not match strategy pin")
        if strategy.model_handle != models[key]:
            raise ValueError("bound model handle changed after context validation")
    return validate_score_output(strategy.score_fn(context), context.universe)


def target_weights(strategy: _Strategy, context: AsOfContext) -> pd.Series:
    if not uses_context_interface(strategy.strategy_interface):
        raise ValueError(f"strategy {strategy.name!r} does not use score(context)")
    return strategy.construct(score(strategy, context), context.features["bars"].frame)
