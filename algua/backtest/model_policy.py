"""Narrow fixed-model eligibility for chronological research; no model acquisition or fitting."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from algua.backtest.errors import BacktestError
from algua.contracts.model_types import normalize_as_of
from algua.features.price_linear_context import validate_proxy_model
from algua.strategies.base import LoadedStrategy


def require_fixed_model_period(strategy: LoadedStrategy, start: datetime) -> None:
    """A supported fixed pin must already exist before the whole evaluated period starts.

    This is not rolling retraining. All folds/parameter combinations consume the identical pin;
    simulate retains its independent guard against the first actual input bar.
    """
    if not strategy.config.needs_model:
        return
    try:
        handle, ref = strategy.model_handle, strategy.config.model_ref
        if (strategy.strategy_interface != 'context_v1' or handle is None or ref is None
                or strategy.config.needs_news or strategy.config.needs_fundamentals
                or handle.version.as_ref() != ref):
            raise ValueError('requires the supported bars + fixed price-linear context profile')
        validate_proxy_model(handle)
        cutoff = normalize_as_of(ref.training_as_of)
        beginning = pd.Timestamp(start)
        beginning = (beginning.tz_localize('UTC') if beginning.tzinfo is None
                     else beginning.tz_convert('UTC'))
        if pd.isna(cutoff) or pd.isna(beginning) or cutoff > beginning:
            raise ValueError('model training_as_of is after the evaluated period start')
    except (TypeError, ValueError) as exc:
        raise BacktestError(
            f'strategy {strategy.name!r} declares needs_model; sweep/walk-forward require a '
            f'validated fixed pre-period model; per-window fitting remains unsupported: {exc}'
        ) from exc
