"""PIT-correct market benchmark projection from captured bars."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import date, datetime

import pandas as pd

from algua.backtest.grid import adj_grid
from algua.backtest.pit_view import members_as_of
from algua.contracts.types import DataProvider
from algua.strategies.base import LoadedStrategy


def market_return_series_from_bars(
    bars: pd.DataFrame,
    universe_by_date: Mapping[date, Collection[str]] | None,
) -> tuple[list[float], list[str]] | None:
    """Equal-weighted full-period returns from one captured bars materialization."""
    try:
        adj = adj_grid(bars)
        daily = adj.pct_change()
        if universe_by_date is not None:
            masked = daily.copy()
            for ts in daily.index:
                members = members_as_of(universe_by_date, ts)
                non_members = [column for column in daily.columns if column not in members]
                if non_members:
                    masked.loc[ts, non_members] = float("nan")
            xs = masked.mean(axis=1).dropna()
        else:
            xs = daily.mean(axis=1).dropna()
        if xs.empty:
            return None
        return [float(value) for value in xs.to_numpy()], [str(idx.date()) for idx in xs.index]
    except Exception:
        return None


def market_return_series(
    strategy: LoadedStrategy,
    provider: DataProvider,
    start: datetime,
    end: datetime,
    universe_by_date: Mapping[date, Collection[str]] | None,
) -> tuple[list[float], list[str]] | None:
    """Historical direct-call seam; top-level walk-forward never uses this fetching adapter."""
    try:
        from algua.backtest.engine import fetch_symbols

        bars = provider.get_bars(fetch_symbols(strategy, universe_by_date), start, end, "1d")
    except Exception:
        return None
    return market_return_series_from_bars(bars, universe_by_date)
