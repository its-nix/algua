from datetime import UTC, datetime

import pandas as pd
import pytest

from algua.portfolio.allocator import PortfolioConstraints, RiskEstimate, allocate_targets


def test_overlapping_and_conflicting_targets_are_net_long_capped_and_order_independent():
    candidates = {
        "b": pd.Series({"ZZZ": 1.0, "AAA": -0.5}),
        "a": pd.Series({"ZZZ": 0.5, "AAA": 0.5}),
    }
    limits = PortfolioConstraints(0.4, 0.3, None)
    # Unknown risk halves, never inflates, each approved budget. AAA nets to cash.
    expected = pd.Series({"ZZZ": 0.3})
    result = allocate_targets(candidates, {"a": 0.4, "b": 0.6}, limits)
    pd.testing.assert_series_equal(result, expected)
    pd.testing.assert_series_equal(
        allocate_targets(dict(reversed(list(candidates.items()))), {"b": 0.6, "a": 0.4}, limits),
        expected,
    )


def test_gross_cap_leaves_cash_without_renormalizing_capped_symbols():
    result = allocate_targets(
        {"a": pd.Series({"AAA": 0.8, "BBB": 0.2}), "b": pd.Series({"CCC": 1.0})},
        {"a": 0.5, "b": 0.5}, PortfolioConstraints(0.25, 0.15, None),
    )
    assert list(result.index) == ["AAA", "BBB", "CCC"]
    assert result.sum() == pytest.approx(0.25)
    assert result.max() <= 0.15


def test_turnover_uses_holdings_including_dropped_symbols_and_refuses_infeasible_state():
    limits = PortfolioConstraints(1.0, 0.6, 0.2)
    current = pd.Series({"OLD": 0.1})
    result = allocate_targets(
        {"a": pd.Series({"NEW": 1.0})}, {"a": 1.0}, limits, current_weights=current,
    )
    assert result["NEW"] == pytest.approx(0.1)
    assert "OLD" not in result
    assert (result.subtract(current, fill_value=0).abs().sum()) == pytest.approx(0.2)
    with pytest.raises(ValueError, match="current_weights"):
        allocate_targets({}, {}, limits)
    with pytest.raises(ValueError, match="current.*constraints"):
        allocate_targets({}, {}, limits, current_weights=pd.Series({"OLD": 0.7}))


def test_empty_candidates_all_cash_and_turnover_limited_unwind():
    assert allocate_targets({}, {}, PortfolioConstraints(1, 1, None)).empty
    # Turnover must never retain a stopped/dropped sleeve and undo a tighten-only overlay.
    with pytest.raises(ValueError, match="turnover.*reductions"):
        allocate_targets({}, {}, PortfolioConstraints(1, 1, 0.1),
                         current_weights=pd.Series({"OLD": 0.4}))
    assert allocate_targets({}, {}, PortfolioConstraints(1, 1, 0.5),
                            current_weights=pd.Series({"OLD": 0.4})).empty


def test_risk_estimates_are_asof_only_and_missing_risk_is_conservative():
    now = datetime(2024, 1, 5, tzinfo=UTC)
    past = datetime(2024, 1, 4, tzinfo=UTC)
    future = datetime(2024, 1, 8, tzinfo=UTC)
    targets = {"a": pd.Series({"AAA": 1.0}), "b": pd.Series({"BBB": 1.0})}
    risk = {"a": [RiskEstimate(past, 0.2, "run:1")],
            "b": [RiskEstimate(past, 0.4, "run:2"), RiskEstimate(future, 0.01, "run:3")]}
    result = allocate_targets(
        targets, {"a": 0.5, "b": 0.5}, PortfolioConstraints(1, 1, None),
        as_of=now, risk_estimates=risk,
    )
    pd.testing.assert_series_equal(result, pd.Series({"AAA": 0.5, "BBB": 0.25}))
    risk["b"] = [RiskEstimate(future, 0.01, "run:3")]
    missing = allocate_targets(
        targets, {"a": 0.5, "b": 0.5}, PortfolioConstraints(1, 1, None),
        as_of=now, risk_estimates=risk,
    )
    assert missing["BBB"] == 0.25


@pytest.mark.parametrize("budgets", [{"a": -0.1}, {"a": float("nan")}, {"a": 1.01}, {}])
def test_invalid_or_missing_budgets_refuse(budgets):
    with pytest.raises(ValueError):
        allocate_targets({"a": pd.Series({"AAA": 1.0})}, budgets,
                         PortfolioConstraints(1, 1, None))


@pytest.mark.parametrize("weights", [pd.Series({"A": float("inf")}), pd.Series({"A": True}),
                                     pd.Series({"A": 0.5 + 0.2j}),
                                     pd.Series([0.2, 0.3], index=["A", "A"])])
def test_invalid_target_vectors_refuse(weights):
    with pytest.raises(ValueError):
        allocate_targets({"a": weights}, {"a": 1.0}, PortfolioConstraints(1, 1, None))


@pytest.mark.parametrize("gross,symbol,turnover", [
    (1.01, 1, None), (1, 1.01, None), (float("nan"), 1, None), (1, 1, -0.1),
    (True, 1, None), (1, 1, float("inf")),
])
def test_constraints_cannot_enable_borrowing_or_disable_finite_limits(gross, symbol, turnover):
    with pytest.raises(ValueError):
        PortfolioConstraints(gross, symbol, turnover)
