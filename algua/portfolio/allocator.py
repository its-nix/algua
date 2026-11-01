"""Pure, long-only account targets from explicitly supplied qualified strategy targets.

Budgets are fractions of account equity and ceilings, never allocation permissions. Signed
opinions may cancel, but the account never shorts or borrows. Freed capacity stays in cash.
Unknown risk gets half the smallest known risk multiplier (half-budget if none are known).
No equity series is consulted. Execution and account risk walls still own order acceptance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

import pandas as pd


def _number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return float(value)


@dataclass(frozen=True)
class PortfolioConstraints:
    max_gross: float
    max_weight_per_symbol: float
    max_turnover: float | None

    def __post_init__(self) -> None:
        for name in ("max_gross", "max_weight_per_symbol"):
            if _number(getattr(self, name), name) > 1:
                raise ValueError(f"{name} must be <= 1 (no borrowing)")
        if self.max_turnover is not None:
            _number(self.max_turnover, "max_turnover")


def _instant(value: datetime) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if pd.isna(ts) or ts.tzinfo is None:
        raise ValueError("as_of must be a valid tz-aware timestamp")
    return ts.tz_convert("UTC")


@dataclass(frozen=True)
class RiskEstimate:
    """An already-persisted volatility estimate and when it became available, with provenance.

    The producer must bind the estimate to the supplied strategy identity and ensure its whole
    estimation interval predates as_of. This object does not qualify a strategy for trading.
    """

    as_of: datetime
    volatility: float
    source: str

    def __post_init__(self) -> None:
        _instant(self.as_of)
        if _number(self.volatility, "volatility") <= 0:
            raise ValueError("volatility must be positive")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("risk estimate requires a source")


def _vector(weights: pd.Series) -> pd.Series:
    if not isinstance(weights, pd.Series):
        raise ValueError("weights must be a Series")
    if weights.index.has_duplicates or any(
        not isinstance(s, str) or not s.strip() for s in weights.index
    ):
        raise ValueError("weights require unique nonempty string symbols")
    if weights.empty:
        return pd.Series(dtype="float64")
    if (pd.api.types.is_bool_dtype(weights) or pd.api.types.is_complex_dtype(weights)
            or not pd.api.types.is_numeric_dtype(weights)):
        raise ValueError("weights must be real numeric, not bool")
    out = weights.astype("float64").sort_index()
    if not all(math.isfinite(v) for v in out):
        raise ValueError("weights must be finite")
    return out


def _risk_scales(
    names: Sequence[str],
    estimates: Mapping[str, Sequence[RiskEstimate]],
    as_of: datetime | None,
) -> dict[str, float]:
    if estimates and as_of is None:
        raise ValueError("risk_estimates require as_of")
    cutoff = _instant(as_of) if as_of is not None else None
    vols: dict[str, float] = {}
    for name in names:
        known = [r for r in estimates.get(name, ())
                 if cutoff is not None and _instant(r.as_of) <= cutoff]
        if known:
            # Equal-time estimates resolve conservatively, independently of input ordering.
            latest = max(known, key=lambda r: (_instant(r.as_of), r.volatility, r.source))
            vols[name] = latest.volatility
    reference = min(vols.values(), default=1.0)
    scales = {name: reference / vol for name, vol in vols.items()}
    fallback = 0.5 * min(scales.values(), default=1.0)
    return {name: scales.get(name, fallback) for name in names}


def allocate_targets(
    strategies: Mapping[str, pd.Series],
    budgets: Mapping[str, float],
    constraints: PortfolioConstraints,
    *,
    current_weights: pd.Series | None = None,
    risk_estimates: Mapping[str, Sequence[RiskEstimate]] | None = None,
    as_of: datetime | None = None,
) -> pd.Series:
    """Net, cap, honor reductions, then bound increases by an L1 turnover ceiling.

    current_weights is REQUIRED for bounded turnover: absence never means flat. It must be
    actual marked holdings in account-equity units. An illegal starting book is refused; its
    liquidation belongs to the authoritative risk machinery, not this optimizer. Turnover is
    sum(abs(target-current)), not half that sum; it excludes cash. Caps apply to net overlap,
    and neither caps nor volatility haircuts redistribute freed budget to other strategies.
    A reduction is never deferred (it may come from a hard stop/capacity overlay). If reductions
    alone exceed turnover, constraints are infeasible and planning refuses. Only increases scale.
    """
    if any(not isinstance(n, str) or not n.strip() for n in strategies):
        raise ValueError("strategy names must be nonempty strings")
    if set(budgets) != set(strategies):
        raise ValueError("budgets must match explicitly supplied strategies")
    names = sorted(strategies)
    amounts = {n: _number(budgets[n], f"budget {n}") for n in names}
    if math.fsum(amounts.values()) > 1:
        raise ValueError("sum of budgets exceeds account equity (no borrowing)")
    scales = _risk_scales(names, risk_estimates or {}, as_of)
    vectors = {n: _vector(strategies[n]) for n in names}
    symbols = sorted({s for w in vectors.values() for s in w.index})
    # Bound each sleeve's gross at one BEFORE combining signed opinions. No strategy may
    # contribute more than its approved equity fraction, even if its own contract allows leverage.
    divisors = {n: max(1.0, math.fsum(abs(v) for v in vectors[n])) for n in names}
    desired = pd.Series({s: math.fsum(
        float(vectors[n].get(s, 0.0)) / divisors[n] * amounts[n] * scales[n] for n in names
    ) for s in symbols}, dtype="float64")
    desired = desired.clip(lower=0.0, upper=constraints.max_weight_per_symbol)
    gross = math.fsum(desired)
    if gross > constraints.max_gross:
        desired *= constraints.max_gross / gross

    if constraints.max_turnover is not None and current_weights is None:
        raise ValueError("bounded turnover requires actual current_weights")
    if current_weights is not None:
        current = _vector(current_weights)
        if (bool((current < 0).any())
                or bool((current > constraints.max_weight_per_symbol).any())
                or math.fsum(current) > constraints.max_gross):
            raise ValueError("current weights violate constraints; risk handling required")
        if constraints.max_turnover is not None:
            union = sorted(set(desired.index) | set(current.index))
            desired = desired.reindex(union, fill_value=0.0)
            current = current.reindex(union, fill_value=0.0)
            delta = desired - current
            reductions = -math.fsum(delta[delta < 0])
            if reductions > constraints.max_turnover:
                raise ValueError("turnover limit cannot accommodate required reductions")
            increases = delta.clip(lower=0.0)
            buying = math.fsum(increases)
            remaining = constraints.max_turnover - reductions
            if buying > remaining:
                desired = current + delta.clip(upper=0.0) + increases * (remaining / buying)
    # Cancellation at binary floating-point precision is cash, not a tradeable opinion.
    return desired[desired > 1e-15].sort_index()
