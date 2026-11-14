import pandas as pd

from algua.strategies.momentum.midcap_weekly_momentum_smoke import (
    CONFIG,
    signal,
    signal_panel,
)


def fixture_bars():
    dates = pd.bdate_range("2025-01-01", periods=90, tz="UTC", name="timestamp")
    # A missing Friday represents a holiday; anchor selection still uses only existing bars.
    dates = dates.delete(17)
    return pd.concat(
        [
            pd.DataFrame(
                {"symbol": s, "adj_close": [100 + i * direction for i in range(len(dates))]},
                index=dates,
            )
            for s, direction in [("AAA", 0.4), ("BBB", -0.2)]
        ]
    ).sort_index()


def test_vectorized_weekly_signal_matches_every_closed_prefix():
    frame = fixture_bars()
    panel = signal_panel(frame, CONFIG.params)
    for stamp in frame.index.unique():
        expected = signal(frame.loc[:stamp], CONFIG.params)
        pd.testing.assert_series_equal(
            panel.loc[stamp].dropna(), expected, check_names=False, check_index_type=False
        )


def test_future_prices_cannot_change_earlier_scores():
    frame = fixture_bars()
    cutoff = frame.index.unique()[55]
    expected = signal_panel(frame, CONFIG.params).loc[:cutoff]
    changed = frame.copy()
    changed.loc[changed.index > cutoff, "adj_close"] *= 9
    pd.testing.assert_frame_equal(signal_panel(changed, CONFIG.params).loc[:cutoff], expected)


def test_demo_keeps_normal_risk_cost_and_lag_contracts():
    assert len(CONFIG.universe) == 300
    assert CONFIG.execution.decision_lag_bars == 1
    assert CONFIG.execution.fees + CONFIG.execution.slippage >= 0.001
    assert CONFIG.execution.allow_short is False
