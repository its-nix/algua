"""Compose an immutable decision context from already captured, as-of input values."""
from __future__ import annotations

from collections.abc import Collection

import pandas as pd

from algua.contracts.strategy_context import AsOfContext, AsOfView
from algua.strategies.base import LoadedStrategy


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
