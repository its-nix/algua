"""Test-local stand-ins for the removed bundled fundamentals/news strategies.

The bundled `fundamentals_earnings_tilt` / `news_coverage_tilt` strategies were deleted, but the
context-input plumbing they exercised (loader binding, PIT masks, promote/sweep/paper guards) stays.
`context_strategies` writes equivalent sources into a real family dir for the duration of a test
(same mechanics as tests/test_loader_news.py) and removes them in `finally`. Tests that use it must
be marked `serial` because they write into the real algua/ source tree.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

import algua.strategies.momentum as _fam

FUNDAMENTALS_SRC = '''"""Earnings-yield tilt: SIGNAL = latest KNOWN diluted EPS per symbol.
CONSTRUCTION = equal-weight the positive-score names."""
from __future__ import annotations

from typing import Any

import pandas as pd

from algua.contracts.types import ExecutionContract
from algua.strategies.base import StrategyConfig

# Provenance marker (additions-only discipline): these bundled seed examples are hand-authored.
# Informational only — read by `algua doctor`'s advisory generated_provenance probe, NOT a trust
# or authorization control.
GENERATED_BY = "human"

CONFIG = StrategyConfig(
    name="fundamentals_earnings_tilt",
    universe=["AAPL", "MSFT", "NVDA"],
    execution=ExecutionContract(rebalance_frequency="1d", decision_lag_bars=1),
    params={"metric": "eps_diluted"},
    construction="equal_weight_positive",
    needs_fundamentals=True,
    feature_lookback=0,  # latest-value tilt, no rolling window -> embargo = decision lag (#345)
)


def signal(view: pd.DataFrame, params: dict[str, Any], fundamentals: pd.DataFrame) -> pd.Series:
    """Most-recent-fiscal-period value of `metric` per symbol (the score). equal_weight_positive
    then holds the names with a positive score, equal weight.

    "Latest" means the latest fiscal period: the as-of engine already keeps each
    (symbol, fiscal_period_end) at its latest revision, so we sort EXPLICITLY by
    fiscal_period_end and take the last per symbol. Relying on `.last()` over the incoming frame
    order would silently depend on the engine's internal knowable_at ordering — an implementation
    detail, not the strategy-input contract — and a restatement of an old period landing with a
    later knowable_at could flip the selection (#274)."""
    metric = str(params["metric"])
    rows = fundamentals[fundamentals["metric"] == metric]
    if rows.empty:
        return pd.Series(dtype="float64")
    # Take the POSITIONAL last row per symbol after sorting — not groupby(...).last(), which
    # SKIPS nulls and would fall back to an older period when the newest period's value is NaN
    # ('reported-but-unavailable' is a valid contract value). The newest period's actual value
    # (incl. NaN -> a non-positive score, so the name isn't held) must win.
    ordered = rows.sort_values("fiscal_period_end", kind="stable")
    return ordered.drop_duplicates("symbol", keep="last").set_index("symbol")["value"]
'''

NEWS_SRC = '''"""Headline-coverage tilt: SIGNAL = count of an article-mention per symbol within a
trailing window of the as-of news; CONSTRUCTION = equal-weight the positively-covered
names. A minimal
demonstration of the as-of news lane — no sentiment/NLP, just coverage counts."""
from __future__ import annotations

from typing import Any

import pandas as pd

from algua.contracts.types import ExecutionContract
from algua.strategies.base import StrategyConfig

# Provenance marker (additions-only discipline): these bundled seed examples are hand-authored.
# Informational only — read by `algua doctor`'s advisory generated_provenance probe, NOT a trust
# or authorization control.
GENERATED_BY = "human"

CONFIG = StrategyConfig(
    name="news_coverage_tilt",
    universe=["AAPL", "MSFT", "NVDA"],
    execution=ExecutionContract(rebalance_frequency="1d", decision_lag_bars=1),
    params={"window_days": 5},
    construction="equal_weight_positive",
    needs_news=True,
    feature_lookback=5,  # 5-day news coverage window -> walk-forward embargo (#345)
)


def signal(view: pd.DataFrame, params: dict[str, Any], news: pd.DataFrame) -> pd.Series:
    """Score = number of distinct articles mentioning each symbol whose published_at is within the
    last `window_days` of the latest bar. The engine's as-of mask already removed retracted
    mentions and any news not knowable by the decision bar; we window on published_at here."""
    if news.empty or view.empty:
        return pd.Series(dtype="float64")
    window = int(params["window_days"])
    cutoff = view.index.max() - pd.Timedelta(days=window)
    recent = news[news["published_at"] >= cutoff]
    if recent.empty:
        return pd.Series(dtype="float64")
    return recent.groupby("symbol")["article_id"].nunique().astype("float64")
'''

_FILES = {
    "fundamentals_earnings_tilt": FUNDAMENTALS_SRC,
    "news_coverage_tilt": NEWS_SRC,
}


@pytest.fixture
def context_strategies() -> Iterator[None]:
    fam = Path(_fam.__path__[0])
    written: list[Path] = []
    try:
        for name, src in _FILES.items():
            path = fam / f"{name}.py"
            path.write_text(src)
            written.append(path)
        yield
    finally:
        for path in written:
            path.unlink(missing_ok=True)
            sys.modules.pop(f"algua.strategies.momentum.{path.stem}", None)
