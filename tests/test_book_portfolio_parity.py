"""Explicit disposable daily book: real vectorbt fills versus the pure paper PLAN seam."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from algua.backtest.portfolio import simulate_portfolio
from algua.contracts.types import ExecutionContract
from algua.execution.sizing import size_order
from algua.live.planner import PlannerInput, plan, plan_portfolio
from algua.portfolio.allocator import PortfolioConstraints
from algua.registry.allocations import portfolio_risk_estimates
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository
from algua.risk.limits import RiskBreach
from algua.strategies.base import LoadedStrategy, StrategyConfig, config_hash

DATES = pd.to_datetime(["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"], utc=True)
EXECUTION = ExecutionContract(rebalance_frequency="1d", fees=0.001, slippage=0.001,
                              target_gross_utilization=1.0)


class FixtureProvider:
    snapshot_id = "explicit-task3-fixture-v1"
    seed = 17

    def __init__(self, shock=10.0):
        self.calls = 0
        self.frame = pd.DataFrame([
            [t, s, 10.0, p, 10.0, p, p, 1_000_000.0]
            for i, t in enumerate(DATES) for s in ("AAA", "BBB")
            for p in [shock if s == "AAA" and i >= 2 else 10.0]
        ], columns=["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
        ).set_index("timestamp")

    def get_bars(self, symbols, start, end, timeframe):
        self.calls += 1
        return self.frame.loc[(self.frame.index >= start) & (self.frame.index < end)
                              & self.frame.symbol.isin(symbols)].copy()


def candidate(name, reverse=False):
    def signal(view, params):
        # Both want AAA on Friday. Monday b changes its mind, while a continues to hold.
        later = view.index.max() >= DATES[1]
        return pd.Series({"BBB" if reverse and later else "AAA": 1.0})

    return LoadedStrategy(
        StrategyConfig(name=name, universe=["AAA", "BBB"], execution=EXECUTION,
                       construction="equal_weight_positive"),
        construct_fn=lambda scores, view, params: scores,
        signal_fn=signal,
    )


@pytest.mark.parametrize("empty", [False, True])
def test_actual_simulation_and_paper_plan_share_targets_and_next_session_fills(empty):
    strategies = {} if empty else {"b": candidate("b", True), "a": candidate("a")}
    budgets = {} if empty else {"a": 0.5, "b": 0.5}
    limits = PortfolioConstraints(0.8, 0.6, 0.2)
    provider = FixtureProvider()
    result = simulate_portfolio(
        strategies, budgets, limits, provider, DATES[0].to_pydatetime(),
        (DATES[-1] + timedelta(days=1)).to_pydatetime(),
        execution=EXECUTION, initial_cash=7.5, symbols=["AAA", "BBB"], seed=17,
    )
    assert provider.calls == 1  # pinned once, all prefix replays use the captured fixture
    for t in DATES:
        view = provider.frame.loc[provider.frame.index <= t]
        sleeves = {n: plan(s, PlannerInput(view, {}, t.to_pydatetime())).weights
                   for n, s in strategies.items()}
        holdings = result.current_weights.loc[t].to_dict()
        paper = plan_portfolio(
            sleeves, budgets, limits, PlannerInput(view, holdings, t.to_pydatetime()),
            execution=EXECUTION, allowed_symbols=["AAA", "BBB"],
        )
        pd.testing.assert_series_equal(
            paper.weights.reindex(["AAA", "BBB"], fill_value=0),
            result.decision_weights.loc[t], check_names=False,
        )
        assert sum(abs(i.target_weight - holdings.get(i.symbol, 0))
                   for i in paper.intents) <= 0.2 + 1e-12
    pf = result.portfolio
    assert pf.cash().min() >= -1e-10
    assert result.executed_weights.iloc[0].sum() == 0  # no same-Friday fill
    if empty:
        assert pf.orders.count() == 0
        assert pf.cash().iloc[-1] == 7.5
    else:
        orders = pf.orders.records_readable
        assert orders.Timestamp.min() == DATES[1]  # Friday -> Monday
        assert orders.iloc[0].Size == pytest.approx(0.15)
        assert orders.iloc[0].Price == pytest.approx(10.01)
        assert orders.iloc[0].Fees == pytest.approx(0.0015015)
        assert 0 < pf.cash().iloc[-1] < 7.5
        assert result.decision_weights.iloc[0].AAA == pytest.approx(0.2)
    assert result.provenance["snapshot_id"] == provider.snapshot_id
    assert result.provenance["seed"] == 17
    assert result.provenance["initial_cash"] == 7.5
    assert result.provenance["execution"]["fees"] == 0.001
    assert result.provenance["dependency_hash"]
    assert result.provenance["config_hash"]


def test_future_bars_do_not_rewrite_prior_decisions_and_turnover_uses_marked_positions():
    args = ({"a": candidate("a"), "b": candidate("b", True)}, {"a": 0.5, "b": 0.5},
            PortfolioConstraints(0.9, 0.9, 0.2))
    kwargs = dict(execution=EXECUTION, initial_cash=100.0, symbols=["AAA", "BBB"])
    normal = simulate_portfolio(*args, FixtureProvider(), DATES[0], DATES[-1] + timedelta(days=1),
                                **kwargs)
    shocked = simulate_portfolio(*args, FixtureProvider(12.0), DATES[0],
                                 DATES[-1] + timedelta(days=1), **kwargs)
    pd.testing.assert_frame_equal(normal.decision_weights.iloc[:2],
                                  shocked.decision_weights.iloc[:2])
    # Monday's filled weight differs from its target after explicit execution costs. The next target
    # therefore uses the filled book rather than a synthetic previous-target state.
    assert normal.current_weights.loc[DATES[1], "AAA"] != 0.2
    assert (shocked.current_weights.loc[DATES[2], "AAA"]
            > normal.current_weights.loc[DATES[2], "AAA"])


def test_paper_plan_timestamps_and_existing_sizing_keeps_dust_as_cash():
    view = FixtureProvider().frame
    request = PlannerInput(view, {}, DATES[0].to_pydatetime())
    paper = plan_portfolio({"a": pd.Series({"AAA": 1.0})}, {"a": 1.0},
                           PortfolioConstraints(1, 1, None), request,
                           execution=EXECUTION, allowed_symbols=["AAA", "BBB"])
    intent = paper.intents[0]
    assert intent.decision_ts == DATES[0]
    small = size_order(symbol="AAA", target_weight=intent.target_weight,
                       equity=1.5, current_market_value=0)
    assert small.is_noop  # existing $1 hysteresis, no invented transaction costs
    fractional = size_order(symbol="AAA", target_weight=intent.target_weight,
                            equity=7.5, current_market_value=0)
    assert fractional.delta_notional == 3.75
    assert not fractional.is_noop


def test_account_contract_remains_authoritative_after_allocation():
    with pytest.raises(RiskBreach, match="max_weight_per_symbol"):
        plan_portfolio(
            {"a": pd.Series({"AAA": 1.0})}, {"a": 1.0}, PortfolioConstraints(1, 1, None),
            PlannerInput(pd.DataFrame(), {}, datetime(2024, 1, 5, tzinfo=UTC)),
            execution=ExecutionContract(rebalance_frequency="1d", max_weight_per_symbol=0.1),
            allowed_symbols=["AAA"],
        )


def test_persisted_risk_drives_real_simulation_and_paper_plan(tmp_path, monkeypatch):
    strategies = {"a": candidate("a"), "b": candidate("b", True)}
    with connect(tmp_path / "explicit-disposable.db") as conn:
        migrate(conn)
        repo = SqliteStrategyRepository(conn)
        monkeypatch.setattr("algua.registry.store.runs._now",
                            lambda: "2024-01-04T00:00:00+00:00")
        identities = {n: ("fixture-code", config_hash(s)) for n, s in strategies.items()}
        for n, vol in [("a", 0.2), ("b", 0.4)]:
            repo.record_run(
                "walk_forward", n, provenance={"code_hash": "fixture-code",
                "config_hash": identities[n][1], "period_end": "2024-01-03"},
                metrics={"ann_vol_oos": vol, "n_obs_oos": 63},
            )
        risk = portfolio_risk_estimates(repo, identities, as_of=DATES[0])
    provider = FixtureProvider()
    limits = PortfolioConstraints(0.9, 0.9, None)
    budgets = {"a": 0.5, "b": 0.5}
    result = simulate_portfolio(
        strategies, budgets, limits, provider, DATES[0], DATES[-1] + timedelta(days=1),
        execution=EXECUTION, initial_cash=7.5, symbols=["AAA", "BBB"], risk_estimates=risk,
    )
    assert result.decision_weights.loc[DATES[0], "AAA"] == 0.75
    assert result.decision_weights.loc[DATES[1], "AAA"] == 0.5
    assert result.decision_weights.loc[DATES[1], "BBB"] == 0.25
    assert result.portfolio.cash().min() > 0
    for t in DATES:
        view = provider.frame.loc[provider.frame.index <= t]
        sleeve = {n: plan(s, PlannerInput(view, {}, t)).weights for n, s in strategies.items()}
        paper = plan_portfolio(
            sleeve, budgets, limits,
            PlannerInput(view, result.current_weights.loc[t].to_dict(), t), execution=EXECUTION,
            allowed_symbols=["AAA", "BBB"], risk_estimates=risk,
        )
        pd.testing.assert_series_equal(paper.weights.reindex(["AAA", "BBB"], fill_value=0),
                                       result.decision_weights.loc[t], check_names=False)


def test_conflicting_signed_sleeves_net_to_cash_in_simulation_and_paper():
    from dataclasses import replace

    short = candidate("short")
    short.config = short.config.model_copy(
        update={"execution": replace(EXECUTION, allow_short=True)}
    )
    short.signal_fn = lambda view, params: pd.Series({"AAA": -1.0})
    strategies = {"long": candidate("long"), "short": short}
    provider = FixtureProvider()
    budgets = {"long": 0.5, "short": 0.5}
    limits = PortfolioConstraints(1, 1, 0.2)
    result = simulate_portfolio(
        strategies, budgets, limits, provider, DATES[0], DATES[-1] + timedelta(days=1),
        execution=EXECUTION, initial_cash=1.5, symbols=["AAA", "BBB"],
    )
    assert result.portfolio.orders.count() == 0
    assert result.portfolio.cash().iloc[-1] == 1.5
    for t in DATES:
        view = provider.frame.loc[provider.frame.index <= t]
        sleeve = {n: plan(s, PlannerInput(view, {}, t)).weights for n, s in strategies.items()}
        paper = plan_portfolio(sleeve, budgets, limits, PlannerInput(view, {}, t),
                               execution=EXECUTION, allowed_symbols=["AAA", "BBB"])
        assert paper.weights.empty
        assert paper.intents == []


def test_snapshot_identity_cannot_change_during_capture():
    class DriftingProvider(FixtureProvider):
        def get_bars(self, *args):
            self.snapshot_id = "changed-during-fetch"
            return super().get_bars(*args)

    with pytest.raises(RuntimeError, match="snapshot.*changed"):
        simulate_portfolio({}, {}, PortfolioConstraints(1, 1, None), DriftingProvider(),
                           DATES[0], DATES[-1] + timedelta(days=1), execution=EXECUTION,
                           initial_cash=7.5, symbols=["AAA", "BBB"])


@pytest.mark.parametrize("mode", ["missing", "sparse", "unbounded", "future", "intraday"])
def test_reference_replay_refuses_unsupported_or_unpinned_inputs(mode):
    provider = FixtureProvider()
    start, end = DATES[0], DATES[-1] + timedelta(days=1)
    if mode == "missing":
        provider.snapshot_id = None
    elif mode == "sparse":
        provider.frame = provider.frame.iloc[1:]
    elif mode == "unbounded":
        from algua.calendar.market_calendar import MarketCalendar

        days = MarketCalendar().sessions_in_range(start.date(), datetime(2024, 5, 1).date())
        provider.frame = pd.concat([provider.frame.iloc[:2].set_axis(
            pd.DatetimeIndex([d, d], tz="UTC", name="timestamp")) for d in days])
        end = pd.Timestamp("2024-05-02", tz="UTC")
    elif mode == "future":
        # A provider violating its half-open window cannot make a replay evaluate future signals.
        end = DATES[2]
        provider.get_bars = lambda *args: provider.frame.copy()
    else:
        provider.frame.index += timedelta(hours=12)
    with pytest.raises(RuntimeError):
        simulate_portfolio({}, {}, PortfolioConstraints(1, 1, None), provider, start, end,
                           execution=EXECUTION, initial_cash=7.5, symbols=["AAA", "BBB"])


def test_stopped_overlay_remains_flat_in_actual_replay_and_plan():
    from algua.portfolio.overlays import OverlaySpec, trailing_stop

    params = {"lookback": 3, "stop_pct": 0.1, "cooldown_bars": 1}
    stop = OverlaySpec(policy="trailing_stop", params=params)
    strategy = candidate("stopped")
    strategy.config = strategy.config.model_copy(update={"overlays": [stop]})
    strategy.overlay_fns = (trailing_stop,)
    provider = FixtureProvider()
    falling = (provider.frame.index >= DATES[2]) & (provider.frame.symbol == "AAA")
    provider.frame.loc[falling, ["close", "adj_close", "low"]] = 8.0
    limits = PortfolioConstraints(0.9, 0.9, 0.6)
    result = simulate_portfolio(
        {"a": strategy}, {"a": 1.0}, limits, provider, DATES[0],
        DATES[-1] + timedelta(days=1), execution=EXECUTION, initial_cash=100,
        symbols=["AAA", "BBB"],
    )
    assert result.decision_weights.loc[DATES[2], "AAA"] == 0
    assert result.portfolio.assets().loc[DATES[3], "AAA"] == 0
    view = provider.frame.loc[provider.frame.index <= DATES[2]]
    sleeve = plan(strategy, PlannerInput(view, {}, DATES[2]))
    paper = plan_portfolio(
        {"a": sleeve.weights}, {"a": 1.0}, limits,
        PlannerInput(view, result.current_weights.loc[DATES[2]].to_dict(), DATES[2]),
        execution=EXECUTION, allowed_symbols=["AAA", "BBB"],
    )
    assert paper.weights.empty
    assert paper.intents[0].target_weight == 0


@pytest.mark.parametrize("holding", [True, "0.25", float("inf")])
def test_paper_plan_refuses_coerced_or_nonfinite_holdings(holding):
    with pytest.raises(ValueError):
        plan_portfolio(
            {"a": pd.Series({"AAA": 1.0})}, {"a": 1.0}, PortfolioConstraints(1, 1, None),
            PlannerInput(pd.DataFrame(), {"AAA": holding}, DATES[0]), execution=EXECUTION,
            allowed_symbols=["AAA"],
        )
