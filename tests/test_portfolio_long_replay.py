"""Bounded research replay: two years through the unchanged canonical fill engine."""

import math
from datetime import timedelta
from time import perf_counter

import pandas as pd
import pytest

from algua.backtest.errors import BacktestError
from algua.backtest.portfolio import simulate_portfolio
from algua.calendar.market_calendar import MarketCalendar
from algua.live.planner import PlannerInput, plan, plan_portfolio
from algua.portfolio.allocator import PortfolioConstraints, RiskEstimate
from algua.strategies.base import LoadedStrategy, StrategyConfig
from tests.test_book_portfolio_parity import EXECUTION

DATES = pd.DatetimeIndex(MarketCalendar().sessions_in_range(
    pd.Timestamp("2024-01-05").date(), pd.Timestamp("2026-03-01").date(),
), tz="UTC")
LIMITS = PortfolioConstraints(0.95, 0.9, 0.55)
BUDGETS = {"a": 0.4, "b": 0.4}
RISK = {
    "a": [RiskEstimate(DATES[0], 0.2, "fixture:past-a")],
    "b": [RiskEstimate(DATES[0], 0.4, "fixture:past-b"),
          RiskEstimate(DATES[65], 0.1, "fixture:future-b")],
}


class DailyProvider:
    snapshot_id = "long-replay-synthetic-v1"
    seed = 17

    def __init__(self):
        self.calls = 0
        self.frame = pd.DataFrame([
            [t, symbol, price * 1.001, price * 1.01, price * 0.99, price, price, 1_000_000.0]
            for i, t in enumerate(DATES[:501]) for j, symbol in enumerate(("AAA", "BBB"))
            for price in [10 * (1 + 0.0002 * i + 0.02 * math.sin(i / 13 + j))]
        ], columns=["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
        ).set_index("timestamp")

    def get_bars(self, symbols, start, end, timeframe):
        self.calls += 1
        return self.frame.loc[(self.frame.index >= start) & (self.frame.index < end)
                              & self.frame.symbol.isin(symbols)].copy(deep=True)


def sleeves(*, mutate_future=False):
    def candidate(name, rotating):
        def signal(view, params):
            assert view.index.max() <= DATES[500]
            if mutate_future and rotating and view.index.max() >= DATES[64]:
                return pd.Series(dtype="float64")
            i = DATES.get_loc(view.index.max())
            return pd.Series({"BBB" if rotating and (i // 17) % 2 else "AAA": 1.0})

        return LoadedStrategy(
            StrategyConfig(name=name, universe=["AAA", "BBB"], execution=EXECUTION,
                           construction="equal_weight_positive"),
            construct_fn=lambda scores, view, params: scores, signal_fn=signal,
        )

    return {"a": candidate("a", False), "b": candidate("b", True)}


def replay(provider, *, n=501, strategies=None, budgets=None, risk=None, symbols=None):
    return simulate_portfolio(
        sleeves() if strategies is None else strategies,
        BUDGETS if budgets is None else budgets, LIMITS, provider,
        DATES[0], DATES[n - 1] + timedelta(days=1), execution=EXECUTION,
        initial_cash=7.5, symbols=["AAA", "BBB"] if symbols is None else symbols,
        risk_estimates=RISK if risk is None else risk, seed=17,
    )


@pytest.fixture(scope="module")
def long_result():
    provider = DailyProvider()
    started = perf_counter()
    result = replay(provider)
    print(f"501-session canonical prefix replay: {perf_counter() - started:.3f}s")
    assert provider.calls == 1
    return result


def test_501_sessions_keep_actual_cost_bearing_fills_and_marked_cash(long_result):
    result = long_result
    assert len(result.decision_weights) == 501
    pf = result.portfolio
    orders = pf.orders.records_readable
    assert len(orders) > 500
    assert orders.Timestamp.min() == DATES[1]  # Friday decision -> Monday fill
    assert result.executed_weights.iloc[0].sum() == 0
    pd.testing.assert_frame_equal(result.executed_weights,
                                  result.decision_weights.shift(1).fillna(0),
                                  check_names=False)
    assert pf.cash().min() >= 0
    assert (pf.assets() >= 0).all().all()
    assert orders.Fees.sum() > 0
    first = orders.iloc[0]
    price = DailyProvider().frame.loc[DATES[1]].set_index("symbol").loc[first.Column, "open"]
    assert first.Price == pytest.approx(price * (1 + EXECUTION.slippage))
    assert first.Fees == pytest.approx(first.Size * first.Price * EXECUTION.fees)
    assert pf.cash().iloc[1] == pytest.approx(7.5 - first.Size * first.Price - first.Fees)
    marks = DailyProvider().frame.reset_index().pivot(
        index="timestamp", columns="symbol", values="adj_close",
    )
    values = pf.assets() * marks
    marked = values.div(values.sum(axis=1) + pf.cash(), axis=0)
    pd.testing.assert_frame_equal(result.current_weights, marked, check_names=False)
    assert result.current_weights.iloc[1].AAA != result.decision_weights.iloc[0].AAA
    assert ((result.decision_weights - result.current_weights).abs().sum(axis=1)
            <= LIMITS.max_turnover + 1e-12).all()
    # After the risk update, exiting a 40% rotating sleeve binds turnover. Sell all BBB first;
    # only the remaining turnover may increase AAA. The next session really fills that exit.
    current, target = result.current_weights.loc[DATES[68]], result.decision_weights.loc[DATES[68]]
    assert current.BBB > 0.39
    assert target.BBB == 0
    assert target.AAA == pytest.approx(current.AAA + 0.55 - current.BBB)
    assert pf.assets().loc[DATES[69], "BBB"] == 0


def test_full_window_keeps_original_short_prefix_and_pure_plan_parity(long_result):
    short = replay(DailyProvider(), n=64)
    for attr in ("current_weights", "decision_weights", "executed_weights"):
        pd.testing.assert_frame_equal(getattr(long_result, attr).iloc[:64], getattr(short, attr),
                                      check_exact=True)
    pd.testing.assert_frame_equal(
        long_result.portfolio.assets().iloc[:64], short.portfolio.assets(), check_exact=True,
    )
    pd.testing.assert_series_equal(long_result.portfolio.cash().iloc[:64], short.portfolio.cash(),
                                   check_exact=True)
    frame = DailyProvider().frame
    strategies = sleeves()
    for t in DATES[:64]:
        view = frame.loc[frame.index <= t]
        targets = {name: plan(s, PlannerInput(view, {}, t)).weights
                   for name, s in strategies.items()}
        current = short.current_weights.loc[t]
        paper = plan_portfolio(
            targets, BUDGETS, LIMITS, PlannerInput(view, current.to_dict(), t),
            execution=EXECUTION, allowed_symbols=["AAA", "BBB"], risk_estimates=RISK,
        )
        pd.testing.assert_series_equal(paper.weights.reindex(["AAA", "BBB"], fill_value=0),
                                       short.decision_weights.loc[t], check_names=False,
                                       check_exact=True)
        assert (short.decision_weights.loc[t] - current).abs().sum() <= 0.55 + 1e-12
    # The rotating sleeve exits BBB: reductions get their full share before additions.
    t = DATES[34]
    assert short.current_weights.loc[t, "BBB"] > 0
    assert short.decision_weights.loc[t, "BBB"] == 0


def test_future_prices_decisions_and_risk_cannot_change_history(long_result):
    provider = DailyProvider()
    provider.frame.loc[provider.frame.index >= DATES[64],
                       ["open", "high", "low", "close", "adj_close"]] *= 1.2
    future_risk = {**RISK, "b": [RISK["b"][0], RiskEstimate(DATES[65], 0.9, "future:changed")]}
    mutated = replay(provider, n=70, strategies=sleeves(mutate_future=True), risk=future_risk)
    for attr in ("current_weights", "decision_weights", "executed_weights"):
        pd.testing.assert_frame_equal(getattr(long_result, attr).iloc[:64],
                                      getattr(mutated, attr).iloc[:64], check_exact=True)
    pd.testing.assert_frame_equal(
        long_result.portfolio.assets().iloc[:64], mutated.portfolio.assets().iloc[:64],
        check_exact=True,
    )
    pd.testing.assert_series_equal(
        long_result.portfolio.cash().iloc[:64], mutated.portfolio.cash().iloc[:64],
        check_exact=True,
    )
    # Future risk is invisible even in a full replay that already has the estimate in memory.
    assert long_result.decision_weights.loc[DATES[64], "BBB"] == pytest.approx(0.2)
    assert long_result.decision_weights.loc[DATES[65], "BBB"] == pytest.approx(0.4)


def test_reversed_mappings_reproduce_identical_economics_and_config():
    normal = replay(DailyProvider(), n=8)
    reverse = replay(
        DailyProvider(), n=8, strategies=dict(reversed(list(sleeves().items()))),
        budgets=dict(reversed(list(BUDGETS.items()))), symbols=["BBB", "AAA"],
        risk={n: list(reversed(rs)) for n, rs in reversed(list(RISK.items()))},
    )
    for attr in ("current_weights", "decision_weights", "executed_weights"):
        pd.testing.assert_frame_equal(getattr(normal, attr), getattr(reverse, attr),
                                      check_exact=True)
    pd.testing.assert_frame_equal(normal.portfolio.orders.records, reverse.portfolio.orders.records,
                                  check_exact=True)
    assert normal.provenance == reverse.provenance


def test_replay_method_and_finite_limits_are_explicit_in_provenance(long_result):
    replay_info = long_result.provenance["replay"]
    assert replay_info["method"] == "canonical_engine_prefix"
    assert replay_info["scope"] == "research_only"
    assert replay_info["sessions"] == 501
    assert replay_info["symbols"] == 2
    assert replay_info["sleeves"] == 2
    # Engine prefix grids + final grid + expanding sleeve history rows, not elapsed seconds.
    assert replay_info["work_units"] == (2 + 2 * 2) * (501 * 502 // 2) + 2 * 501
    assert replay_info["limits"] == {
        "sessions": 512, "symbols": 8, "sleeves": 8, "work_units": 2_000_000,
    }


@pytest.mark.parametrize("mode,match", [
    ("sessions", "sessions"), ("symbols", "symbols"), ("sleeves", "sleeves"),
    ("work", "work"), ("naive", "tz-aware"), ("nat", "valid"),
    ("reversed", "requires start before end"), ("cash", "initial_cash"),
    ("bool_cash", "initial_cash"),
    ("no_midnight", "sessions"), ("calendar", "calendar"),
])
def test_invalid_or_oversized_workload_refuses_before_fetch(mode, match, monkeypatch):
    provider = DailyProvider()

    def forbidden_fetch(*args):
        provider.calls += 1
        raise AssertionError("unexpected provider fetch")

    monkeypatch.setattr(provider, "get_bars", forbidden_fetch)
    strategies, symbols = {}, ["AAA", "BBB"]
    start, end = DATES[0], DATES[1]
    initial_cash = 7.5
    if mode == "sessions":
        end = DATES[512] + timedelta(days=1)
    elif mode == "symbols":
        symbols = [f"S{i}" for i in range(9)]
    elif mode in ("sleeves", "work"):
        symbols = [f"S{i}" for i in range(8)]
        for i in range(9 if mode == "sleeves" else 8):
            strategy = sleeves()["a"]
            strategy.config = strategy.config.model_copy(update={"universe": symbols})
            strategies[str(i)] = strategy
        if mode == "work":
            end = DATES[500] + timedelta(days=1)
    elif mode == "naive":
        start = start.tz_localize(None)
    elif mode == "nat":
        end = pd.NaT
    elif mode == "reversed":
        end = start - timedelta(days=1)
    elif mode == "bool_cash":
        initial_cash = True
    elif mode == "no_midnight":
        start += timedelta(hours=1)
        end = start + timedelta(hours=1)
    elif mode == "calendar":
        start, end = pd.Timestamp("2099-01-05", tz="UTC"), pd.Timestamp("2099-01-06", tz="UTC")
    else:
        initial_cash = float("nan")
    with pytest.raises(BacktestError, match=match):
        simulate_portfolio(
            strategies, {n: 1 / len(strategies) for n in strategies}, LIMITS, provider, start, end,
            execution=EXECUTION, initial_cash=initial_cash, symbols=symbols,
        )
    assert provider.calls == 0


def test_provider_cannot_exceed_preflight_row_bound(monkeypatch):
    provider = DailyProvider()
    provider.frame = pd.concat([provider.frame.iloc[:2]] * 3)

    def forbidden_engine(*args, **kwargs):
        raise AssertionError("unbounded input reached expensive engine replay")

    monkeypatch.setattr("algua.backtest.portfolio.engine.simulate", forbidden_engine)
    with pytest.raises(BacktestError, match="more bars than.*bounded"):
        replay(provider, n=1)
    assert provider.calls == 1


def test_preflight_counts_half_open_utc_sessions_with_non_utc_intraday_bounds():
    result = simulate_portfolio(
        {}, {}, LIMITS, DailyProvider(), pd.Timestamp("2024-01-05T03:00:00+02:00"),
        pd.Timestamp("2024-01-09T03:00:00+02:00"), execution=EXECUTION,
        initial_cash=7.5, symbols=["AAA", "BBB"],
    )
    assert list(result.decision_weights.index) == list(DATES[1:3])
    assert result.provenance["replay"]["requested_sessions"] == 2
    assert result.provenance["replay"]["requested_work_units"] == 10
    assert result.portfolio.cash().iloc[-1] == 7.5
