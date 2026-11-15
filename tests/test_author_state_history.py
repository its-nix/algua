"""Synthetic causal check of the author guide's finite-state history example.

No recorded idea, vendor input, numerical attempt or campaign is accessed here.
"""
from pathlib import Path

import pandas as pd
import pytest

from algua.backtest.decision_path import _decision_weights
from algua.contracts.types import ExecutionContract
from algua.operator.source_recipe import assess_recipe
from algua.portfolio.construction import equal_weight_positive
from algua.strategies.base import LoadedStrategy, StrategyConfig


@pytest.fixture
def example():
    guide = Path(".opencode/skills/author-a-strategy/SKILL.md").read_text()
    section = guide.split("### Declare the whole state history", 1)[1]
    code = section.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(compile(code, "author-history-example", "exec"), namespace)
    return namespace


def bars():
    index = pd.date_range("2026-01-01", periods=60, tz="UTC", name="timestamp")
    # A positive event followed by quiet decisions exercises carry, then expiry.
    return pd.DataFrame(
        {"symbol": "SYNTH", "adj_close": [100.0] * 25 + [110.0] * 35}, index=index
    )


def recipe(lookback):
    leg = dict(market="us_equities", horizon="daily", required_data=["ohlcv"],
               construction="top_k_equal_weight", feature_lookback=lookback)
    return {**leg, "controls": [dict(leg, construction="equal_weight_positive")]}


def test_underdeclared_state_can_pass_advisory_but_fail_first_decision(example):
    signal = example["bounded_state_scores"]
    required = example["REQUIRED_BARS"]
    profile = dict(coverage={"grid_sessions": 150}, windows=4, holdout_frac=0.2,
                   execution={"decision_lag_bars": 1})
    assert assess_recipe(recipe(21), profile)["status"] == "feasible"
    honest = assess_recipe(recipe(required), profile)
    assert honest["status"] == "blocked"
    assert "insufficient_post_warmup_history" in honest["reasons"]

    def demanding_signal(view, params):
        if view.index.nunique() < required:
            raise ValueError("persistent state requires 25 closes")
        return signal(view, params)

    def strategy(warmup, lookback):
        return LoadedStrategy(
            config=StrategyConfig(
                name="synthetic_state", universe=["SYNTH"],
                execution=ExecutionContract(rebalance_frequency="1d", warmup_bars=warmup),
                feature_lookback=lookback, construction="equal_weight_positive",
            ),
            signal_fn=demanding_signal, construct_fn=equal_weight_positive,
        )

    frame = bars()
    adj = frame.pivot(columns="symbol", values="adj_close")
    # Reproduce the mismatch in the unchanged canonical loop, not a mock of its slicing.
    with pytest.raises(ValueError, match="persistent state requires 25 closes"):
        _decision_weights(strategy(21, 21), frame, adj)
    weights = _decision_weights(strategy(required, required), frame, adj)
    assert weights.iloc[:required].eq(0).all().all()
    assert weights.iloc[25]["SYNTH"] > 0
    assert weights.iloc[-1]["SYNTH"] == 0


def test_documented_state_reconstructs_from_declared_bars_without_call_memory(example):
    signal = example["bounded_state_scores"]
    required = example["REQUIRED_BARS"]
    frame = bars()
    assert signal(frame.iloc[:21], {}).empty
    # Deliberately out of chronological order; no prior invocation supplies state.
    for stop, expected in [(49, 1.0), (25, 0.0), (60, 0.0), (26, 1.0), (50, 0.0)]:
        prefix = frame.iloc[:stop].copy()
        suffix = prefix.iloc[-required:]
        score = signal(prefix, {})
        assert score["SYNTH"] == expected
        pd.testing.assert_series_equal(score, signal(suffix, {}))
        prefix.iloc[:-required, prefix.columns.get_loc("adj_close")] = 9999.0
        pd.testing.assert_series_equal(score, signal(prefix, {}))
    sparse = frame.iloc[1:26].copy()
    sparse.iloc[0, sparse.columns.get_loc("adj_close")] = float("nan")
    assert signal(sparse, {}).empty
