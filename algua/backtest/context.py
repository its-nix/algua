"""Build the immutable multimodal context consumed by the canonical backtest loop."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

import pandas as pd

from algua.contracts.strategy_context import AsOfContext, AsOfView
from algua.contracts.strategy_interface import uses_context_interface
from algua.strategies.base import LoadedStrategy


@dataclass(frozen=True)
class ContextInputs:
    """Run-level identities needed to build every immutable decision context."""
    first_decision_ts: pd.Timestamp
    bars_snapshot_id: str | None
    fundamentals_snapshot_id: str | None
    news_snapshot_id: str | None


def _snapshot_id(value: str | None, modality: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"context strategy requires a pinned {modality} snapshot_id (fail closed)"
        )
    return value


def build_context(
    strategy: LoadedStrategy,
    *,
    decision_ts: pd.Timestamp,
    first_decision_ts: pd.Timestamp,
    universe: Collection[str],
    bars: pd.DataFrame,
    bars_snapshot_id: str | None,
    fundamentals: pd.DataFrame | None,
    fundamentals_snapshot_id: str | None,
    news: pd.DataFrame | None,
    news_snapshot_id: str | None,
) -> AsOfContext:
    """Assemble one already-masked decision context with exact input identities."""
    decision = decision_ts.to_pydatetime()
    features = {
        "bars": AsOfView(
            kind="bars",
            as_of=decision,
            snapshot_id=_snapshot_id(bars_snapshot_id, "bars"),
            frame=bars,
        )
    }
    if strategy.config.needs_fundamentals:
        if fundamentals is None:
            raise ValueError("missing required feature modalities: ['fundamentals']")
        features["fundamentals"] = AsOfView(
            kind="fundamentals",
            as_of=decision,
            snapshot_id=_snapshot_id(fundamentals_snapshot_id, "fundamentals"),
            frame=fundamentals,
        )
    if strategy.config.needs_news:
        if news is None:
            raise ValueError("missing required feature modalities: ['news']")
        features["news"] = AsOfView(
            kind="news",
            as_of=decision,
            snapshot_id=_snapshot_id(news_snapshot_id, "news"),
            frame=news,
        )
    models = {}
    if strategy.config.needs_model:
        ref = strategy.config.model_ref
        handle = strategy.model_handle
        if ref is None or handle is None:
            raise ValueError("missing required pinned model")
        models[ref.name] = handle
    return AsOfContext(
        decision_ts=decision,
        first_decision_ts=first_decision_ts.to_pydatetime(),
        universe=tuple(sorted(universe)),
        features=features,
        models=models,
    )


def target_weights(
    strategy: LoadedStrategy,
    *,
    decision_ts: pd.Timestamp,
    universe: Collection[str],
    bars: pd.DataFrame,
    fundamentals: pd.DataFrame | None,
    news: pd.DataFrame | None,
    inputs: ContextInputs | None,
) -> pd.Series:
    """Mask sidecars as of one decision and dispatch the legacy or context interface."""
    from algua.backtest.pit_view import _fundamentals_as_of, _news_as_of

    f_asof = _fundamentals_as_of(fundamentals, decision_ts) if fundamentals is not None else None
    n_asof = _news_as_of(news, decision_ts) if news is not None else None
    if f_asof is not None:
        f_asof = f_asof[f_asof["symbol"].isin(universe)]
    if n_asof is not None:
        n_asof = n_asof[n_asof["symbol"].isin(universe)]
    if not uses_context_interface(strategy.strategy_interface):
        if f_asof is not None:
            return strategy.target_weights(bars, fundamentals=f_asof)
        if n_asof is not None:
            return strategy.target_weights(bars, news=n_asof)
        return strategy.target_weights(bars)
    if inputs is None:
        raise ValueError("context strategy is missing run-level snapshot identities")
    try:
        context = build_context(
            strategy,
            decision_ts=decision_ts,
            first_decision_ts=inputs.first_decision_ts,
            universe=universe,
            bars=bars,
            bars_snapshot_id=inputs.bars_snapshot_id,
            fundamentals=f_asof,
            fundamentals_snapshot_id=inputs.fundamentals_snapshot_id,
            news=n_asof,
            news_snapshot_id=inputs.news_snapshot_id,
        )
        return strategy.target_weights_context(context)
    except (TypeError, ValueError) as exc:
        from algua.backtest.errors import BacktestError

        raise BacktestError(
            f"strategy {strategy.name!r} context decision failed at {decision_ts}: {exc}"
        ) from exc
