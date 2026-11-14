"""Observed history geometry for exploratory planning; never qualification evidence."""
from __future__ import annotations

from typing import TYPE_CHECKING

from algua.backtest.walkforward import _segment_bounds

if TYPE_CHECKING:
    import pandas as pd


def observed_coverage(bars: pd.DataFrame, symbols: list[str]) -> dict:
    selected = bars[bars['symbol'].isin(symbols)]
    grid = selected.index.unique().sort_values()
    if grid.empty:
        raise ValueError('research_profile:observed_coverage_unavailable')
    counts = {symbol: int(count) for symbol, count in selected.groupby('symbol').size().items()}
    return {'schema_version': 'observed-research-coverage/v1', 'grid_sessions': len(grid),
            'observed_start': grid[0].date().isoformat(),
            'observed_end': grid[-1].date().isoformat(),
            'symbol_sessions': {symbol: counts.get(symbol, 0) for symbol in symbols},
            'complete_symbols': sum(counts.get(symbol, 0) == len(grid) for symbol in symbols),
            'note': 'Observed rows, not PIT provenance or a guarantee of valid feature inputs.'}


def window_capacity(sessions: int, *, lookback: int, lag: int,
                    windows: int, holdout_frac: float) -> list[int]:
    """Match existing continuous-portfolio partition; conservatively reserve warm-up plus lag."""
    if any(type(v) is not int or v < 0 for v in (sessions, lookback, lag)):
        raise ValueError('history capacity requires nonnegative integer counts')
    bounds, _ = _segment_bounds(sessions, windows, holdout_frac, max(lookback, lag))
    return [max(0, end - max(start, lookback + lag)) for start, end in bounds]
