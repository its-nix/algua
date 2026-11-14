import pandas as pd
import pytest

from algua.calendar.market_calendar import MarketCalendar
from scripts.midcap_screen import PROFILE, screen


def bars(symbols=("AAA", "BBB"), periods=252):
    from datetime import date

    sessions = MarketCalendar("XNYS").sessions_in_range(date(2024, 1, 2), date(2025, 3, 1))
    dates = pd.DatetimeIndex(sessions[:periods], tz="UTC", name="timestamp")
    return pd.concat(
        [
            pd.DataFrame({"symbol": s, "close": 10.0, "volume": 2_000_000.0}, index=dates)
            for s in symbols
        ]
    )


def test_inclusive_price_liquidity_and_history_boundaries():
    result = screen(bars(), {"AAA": "A", "BBB": "B"})
    assert result["selected_symbols"] == ["AAA", "BBB"]
    assert result["selected_by_sector"] == {"A": 1, "B": 1}
    assert result["point_in_time_membership"] is False
    assert result["broker_tradability_verified"] is False


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("price", "price_below_floor"),
        ("liquidity", "liquidity_below_floor"),
        ("history", "insufficient_history"),
        ("stale", "stale_or_missing_latest_bar"),
        ("gap", "incomplete_liquidity_window"),
    ],
)
def test_each_universe_filter_is_enforced(fault, reason):
    frame = bars()
    if fault == "price":
        frame.loc[frame.symbol == "AAA", "close"] = 9.99
    elif fault == "liquidity":
        frame.loc[frame.symbol == "AAA", "volume"] = 1_999_999
    else:
        i = {"history": 0, "stale": 251, "gap": 245}[fault]
        frame = (
            frame.drop(frame[(frame.symbol == "AAA")].index[i]).copy()
            if fault == "history"
            else frame
        )
        if fault != "history":
            frame = frame[~((frame.symbol == "AAA") & (frame.index == frame.index.unique()[i]))]
    result = screen(frame, {"AAA": "A", "BBB": "B"})
    row = next(r for r in result["records"] if r["symbol"] == "AAA")
    assert not row["eligible"] and reason in row["reasons"]


def test_liquidity_uses_median_not_one_volume_spike():
    frame = bars()
    frame.loc[frame.symbol == "AAA", "volume"] = 1
    frame.iloc[251, frame.columns.get_loc("volume")] = 1e12
    assert screen(frame, {"AAA": "A", "BBB": "B"})["selected_symbols"] == ["BBB"]


def test_sector_round_robin_and_deterministic_cap(monkeypatch):
    monkeypatch.setitem(PROFILE, "max_symbols", 2)
    frame = bars(("AAA", "BBB", "CCC"))
    result = screen(frame, {"AAA": "A", "BBB": "A", "CCC": "B"})
    assert result["selected_symbols"] == ["AAA", "CCC"]
    assert result == screen(
        frame.sample(frac=1, random_state=3), {"CCC": "B", "BBB": "A", "AAA": "A"}
    )


def test_duplicate_observations_refuse():
    frame = bars()
    with pytest.raises(ValueError, match="duplicate"):
        screen(pd.concat([frame, frame.iloc[:1]]), {"AAA": "A"})
