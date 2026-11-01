"""Unsupported account execution controls must fail closed at the bounded book seam."""
from dataclasses import replace
from datetime import timedelta

import pandas as pd
import pytest

from algua.backtest.portfolio import simulate_portfolio
from algua.contracts.types import CapacityLimit
from algua.live.planner import PlannerInput, plan_portfolio
from algua.portfolio.allocator import PortfolioConstraints
from tests.test_book_portfolio_parity import DATES, EXECUTION, FixtureProvider


def test_paper_plan_refuses_unsupported_account_capacity_before_intents():
    execution = replace(EXECUTION, capacity=CapacityLimit(
        reference_aum=1_000_000_000.0, max_participation_rate=0.1, adv_window_bars=1,
    ))
    with pytest.raises(ValueError, match="capacity"):
        plan_portfolio(
            {"a": pd.Series({"AAA": 1.0})}, {"a": 1.0}, PortfolioConstraints(1, 1, None),
            PlannerInput(FixtureProvider().frame, {}, DATES[0]),
            execution=execution, allowed_symbols=["AAA", "BBB"],
        )


def test_reference_replay_refuses_whole_share_contract_instead_of_fractional_fills():
    with pytest.raises(RuntimeError, match="fractional"):
        simulate_portfolio(
            {}, {}, PortfolioConstraints(1, 1, None), FixtureProvider(),
            DATES[0], DATES[-1] + timedelta(days=1),
            execution=replace(EXECUTION, allow_fractional=False), initial_cash=7.5,
            symbols=["AAA", "BBB"],
        )
