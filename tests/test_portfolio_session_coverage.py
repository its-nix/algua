"""The requested daily replay window cannot silently lose whole boundary sessions."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from algua.backtest.errors import BacktestError
from algua.backtest.portfolio import simulate_portfolio
from algua.calendar.market_calendar import MarketCalendar
from algua.cli.main import app
from algua.contracts.types import ExecutionContract
from algua.portfolio.allocator import PortfolioConstraints
from algua.strategies.base import LoadedStrategy, StrategyConfig
from tests.test_cli_portfolio_replay import replay as replay

DATES = pd.DatetimeIndex(["2024-01-05", "2024-01-08", "2024-01-09"], tz="UTC")
EXECUTION = ExecutionContract("1d", fees=0.0, slippage=0.0)


class BoundaryProvider:
    snapshot_id = "synthetic-boundary-coverage"

    def __init__(self, missing: str):
        omitted = DATES[0] if missing == "first" else DATES[-1]
        self.calls = 0
        self.frame = pd.DataFrame([
            [timestamp, symbol, 10.0, 10.0, 10.0, 10.0, 10.0, 1000.0]
            for timestamp in DATES if timestamp != omitted for symbol in ("AAA", "BBB")
        ], columns=["timestamp", "symbol", "open", "high", "low", "close", "adj_close", "volume"]
        ).set_index("timestamp")

    def get_bars(self, symbols, start, end, timeframe):
        self.calls += 1
        return self.frame.copy(deep=True)


@pytest.mark.parametrize("missing", ["first", "last"])
@pytest.mark.parametrize("with_sleeve", [False, True], ids=["all-cash", "sleeve"])
def test_whole_boundary_session_missing_refuses_before_any_replay(
        missing, with_sleeve, monkeypatch):
    calls = {"engine": 0, "score": 0}

    def forbidden_engine(*args, **kwargs):
        calls["engine"] += 1
        pytest.fail("incomplete requested coverage reached the replay engine")

    def forbidden_score(view, params):
        calls["score"] += 1
        pytest.fail("incomplete requested coverage reached a sleeve scorer")

    strategy = LoadedStrategy(
        StrategyConfig(name="coverage", universe=["AAA", "BBB"], execution=EXECUTION,
                       construction="equal_weight_positive"),
        construct_fn=lambda scores, view, params: scores, signal_fn=forbidden_score,
    )
    monkeypatch.setattr("algua.backtest.portfolio.engine.simulate", forbidden_engine)
    provider = BoundaryProvider(missing)
    strategies = {"coverage": strategy} if with_sleeve else {}
    budgets = {"coverage": 0.5} if with_sleeve else {}
    with pytest.raises(BacktestError, match="complete requested.*session"):
        simulate_portfolio(
            strategies, budgets, PortfolioConstraints(1.0, 1.0, None), provider,
            DATES[0], DATES[-1] + pd.Timedelta(days=1), execution=EXECUTION,
            initial_cash=10.0, symbols=["AAA", "BBB"], seed=0,
        )
    assert provider.calls == 1
    assert calls == {"engine": 0, "score": 0}


@pytest.mark.parametrize("missing", ["first", "last"])
def test_cli_boundary_coverage_refusal_creates_no_registry(replay, missing):
    manifest, path, db = replay
    calendar = MarketCalendar()
    if missing == "first":
        first = pd.Timestamp(manifest["start"])
        previous = calendar.previous_session(first.date())
        manifest["start"] = pd.Timestamp(previous, tz="UTC").isoformat()
    else:
        # end is exclusive: adding one day asks for the first bar absent from this snapshot.
        manifest["end"] = (pd.Timestamp(manifest["end"]) + pd.Timedelta(days=1)).isoformat()
    manifest["sleeves"] = []
    path.write_text(json.dumps(manifest))
    assert not db.exists()
    result = CliRunner().invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    value = json.loads(result.stdout)
    assert value["ok"] is False and value["code"] == "backtest_error"
    assert "complete requested" in value["error"]
    assert not db.exists()
