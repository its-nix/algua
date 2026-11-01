"""Pure target-weight validation and intent construction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import pandas as pd

from algua.contracts.planner import PLANNER_PROTOCOL_VERSION
from algua.contracts.types import OrderIntent, Side
from algua.portfolio.allocator import PortfolioConstraints, RiskEstimate, allocate_targets
from algua.risk.limits import WEIGHT_TOL, check_finite_weights, validate_decision_weights

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from algua.contracts.types import ExecutionContract
    from algua.strategies.base import LoadedStrategy


@dataclass(frozen=True)
class PlannerInput:
    view: pd.DataFrame
    current_weights: dict[str, float]
    decision_ts: datetime
    protocol_version: int = PLANNER_PROTOCOL_VERSION


@dataclass(frozen=True)
class PlannerResult:
    weights: pd.Series
    intents: list[OrderIntent]
    protocol_version: int = PLANNER_PROTOCOL_VERSION


def build_intents(
    weights: pd.Series, current_weights: dict[str, float], decision_ts: datetime
) -> list[OrderIntent]:
    """Emit sorted target-weight deltas, including zero targets for dropped holdings."""
    intents: list[OrderIntent] = []
    for symbol in sorted(set(weights.index) | set(current_weights)):
        target = float(weights.get(symbol, 0.0))
        current = float(current_weights.get(symbol, 0.0))
        if abs(target - current) > WEIGHT_TOL:
            side = Side.BUY if target > current else Side.SELL
            intents.append(OrderIntent(symbol, side, target, decision_ts))
    return intents


def canonical_weights(weights: pd.Series, strategy_name: str) -> pd.Series:
    """The strategy's weights as float64 in symbol order: the form a frozen tick's supervisor
    re-validates them in (Story 1.3c §7), so a float32 weight at a cap, or a gross summed in
    another order, cannot pass one side and breach the other. The dtype guards run on the
    strategy's own Series first, so a bool or string weight still breaches instead of coercing."""
    check_finite_weights(weights, strategy_name)
    return weights.astype("float64").sort_index(key=lambda index: index.map(str))


def plan(strategy: LoadedStrategy, inputs: PlannerInput) -> PlannerResult:
    if (
        type(inputs.protocol_version) is not int
        or inputs.protocol_version != PLANNER_PROTOCOL_VERSION
    ):
        raise ValueError(f"unsupported planner protocol: {inputs.protocol_version!r}")
    weights = canonical_weights(strategy.target_weights(inputs.view), strategy.name)
    validate_decision_weights(
        weights, strategy.execution, strategy.name, allowed_symbols=strategy.universe
    )
    return PlannerResult(
        weights, build_intents(weights, inputs.current_weights, inputs.decision_ts)
    )


def decide(
    strategy: LoadedStrategy,
    view: pd.DataFrame,
    current_weights: dict[str, float],
    decision_ts: datetime,
) -> tuple[pd.Series, list[OrderIntent]]:
    result = plan(strategy, PlannerInput(view, current_weights, decision_ts))
    return result.weights, result.intents


def plan_portfolio(
    strategies: Mapping[str, pd.Series],
    budgets: Mapping[str, float],
    constraints: PortfolioConstraints,
    inputs: PlannerInput,
    *,
    execution: ExecutionContract,
    allowed_symbols: Collection[str],
    risk_estimates: Mapping[str, Sequence[RiskEstimate]] | None = None,
) -> PlannerResult:
    """Pure PLAN for explicit qualified sleeve targets, with no broker or registry authority.

    Callers first produce sleeve targets through their existing as-of strategy planners. This
    function does not evaluate signals, qualify candidates, or schedule/order a runtime tick.
    """
    if (
        type(inputs.protocol_version) is not int
        or inputs.protocol_version != PLANNER_PROTOCOL_VERSION
    ):
        raise ValueError(f"unsupported planner protocol: {inputs.protocol_version!r}")
    if execution.capacity is not None:
        raise ValueError("portfolio PLAN does not support account capacity contracts")
    weights = allocate_targets(
        strategies, budgets, constraints,
        current_weights=(pd.Series(inputs.current_weights) if inputs.current_weights
                         else pd.Series(dtype="float64")),
        as_of=inputs.decision_ts, risk_estimates=risk_estimates,
    )
    weights = canonical_weights(weights, "portfolio")
    validate_decision_weights(weights, execution, "portfolio", allowed_symbols=allowed_symbols)
    return PlannerResult(
        weights, build_intents(weights, inputs.current_weights, inputs.decision_ts)
    )
