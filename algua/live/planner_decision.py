"""Pure target-weight validation and intent construction."""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from numbers import Real
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


def finite_number(value: object, label: str, *, allow_real_scalars: bool = False) -> float:
    """Finite float; captured state defaults to exact built-in int/float types.

    Current holdings opt into real numeric scalars (including NumPy), excluding bool.
    """
    scalar = allow_real_scalars and isinstance(value, Real) and not isinstance(value, bool)
    if not scalar and type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    assert isinstance(value, (int, float, Real))
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def numeric_mapping(
    value: object, label: str, *, normalize: bool = True, allow_real_scalars: bool = False
) -> dict[str, float]:
    """Non-empty string keys and finite values. Public because ``planner_late`` imports it.

    ``normalize=True`` (captured late-planner state) NFC-normalizes keys and rejects a
    collision after that. ``build_intents`` passes ``normalize=False`` so a valid holding
    label is checked and kept byte-for-byte. Renaming it would disagree with the strategy
    label, which this contract does not NFC-normalize.
    ``allow_real_scalars`` is only enabled for current holdings; late state keeps exact types.
    """
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    result: dict[str, float] = {}
    for symbol, number in value.items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError(f"{label} keys must be non-empty strings")
        key = unicodedata.normalize("NFC", symbol) if normalize else symbol
        if normalize and key in result:
            raise ValueError(f"{label} keys collide after Unicode normalization")
        result[key] = finite_number(
            number, f"{label}[{symbol!r}]", allow_real_scalars=allow_real_scalars
        )
    return result


def build_intents(
    weights: pd.Series, current_weights: dict[str, float], decision_ts: datetime
) -> list[OrderIntent]:
    """Emit sorted target-weight deltas, including zero targets for dropped holdings.

    ``current_weights`` must have non-empty string keys and finite values. Keys are validated
    and not renamed: strategy labels are outside NFC normalization. A violation raises before
    any intent is built.
    """
    holdings = numeric_mapping(
        current_weights, "current_weights", normalize=False, allow_real_scalars=True
    )
    intents: list[OrderIntent] = []
    for symbol in sorted(set(weights.index) | set(holdings)):
        target = float(weights.get(symbol, 0.0))
        current = float(holdings.get(symbol, 0.0))
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
