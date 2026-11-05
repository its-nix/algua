"""Pooled float64 ridge on observed-price returns; no source/availability/registry policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from algua.features.price_linear import (
    FEATURE_ORDER,
    FrozenPriceLinear,
    PriceLinearError,
    _event,
    _geometry,
    _number,
    _price_matrix,
    _require,
    return_features,
)
from algua.features.scaling import ScalerError
from algua.features.scaling_fit import fit_standard_scaler


@dataclass(frozen=True)
class PriceLinearReport:
    train_start: str
    train_end: str
    symbols: tuple[str, ...]
    l2: float
    consumed_events: int
    window_events: int
    candidate_observations: int
    warmup_observations: int
    unlabelled_observations: int
    fitted_observations: int
    max_x_event: str
    max_y_event: str


@dataclass(frozen=True)
class PriceLinearFit:
    model: FrozenPriceLinear
    report: PriceLinearReport


def fit_price_linear(prices: pd.DataFrame, *, train_start: str | datetime,
                     train_end: str | datetime, l2: float = 1e-3) -> PriceLinearFit:
    """Fit ||y - intercept - scaled_X @ coefficients||² + l2*||coefficients||².

    Intercept is unpenalized. Shared coefficients/scaler pool event-major, explicit-symbol order.
    At least three eligible observations and nonzero variance in both features are required.
    Positive ridge accepts correlated nonconstant features; numerical solve failures refuse.
    """
    start, end, penalty = _event(train_start), _event(train_end), _number(l2)
    _require(start < end and penalty > 0)
    _geometry(prices)
    # Clip before ANY price-value validation or return/next-observation label construction.
    clipped = prices.loc[prices.index < end]
    first = int(clipped.index.searchsorted(start))
    consumed = clipped.iloc[max(0, first - 5):]
    _require(not consumed.empty and (consumed.index >= start).any())
    values = _price_matrix(consumed)
    features = return_features(consumed)
    symbols = len(consumed.columns)
    positions = np.repeat(np.arange(len(consumed)), symbols)
    in_window = np.repeat(consumed.index >= start, symbols)
    warmup = in_window & (positions < 5)
    unlabelled = in_window & ~warmup & (positions == len(consumed) - 1)
    eligible = in_window & ~warmup & ~unlabelled
    counts = tuple(int(mask.sum()) for mask in (in_window, warmup, unlabelled, eligible))
    if counts[-1] < 3:
        raise PriceLinearError(f"insufficient observations: warmup={counts[1]}, "
                               f"unlabelled={counts[2]}, fitted={counts[3]}")
    x = features.loc[eligible].copy()
    x.index = pd.DatetimeIndex(x.index.get_level_values("event_label"))
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            targets = (values[1:] / values[:-1] - 1.0).ravel()
            y = targets[eligible[:len(targets)]]
            _require(np.isfinite(y).all())
            scaler = fit_standard_scaler(x, columns=FEATURE_ORDER)
            z = scaler.transform(x).to_numpy(dtype="float64")
            design = np.column_stack([np.ones(len(x)), z])
            gram = design.T @ design + np.diag([0.0, penalty, penalty])
            solution = np.linalg.solve(gram, design.T @ y)
            _require(np.isfinite(solution).all())
    except (ScalerError, FloatingPointError, np.linalg.LinAlgError) as exc:
        raise PriceLinearError("price-linear fit is degenerate or numerically invalid") from exc
    target_positions = positions[eligible] + 1
    max_y = consumed.index[int(target_positions.max())].isoformat()
    model = FrozenPriceLinear(scaler, tuple(solution[1:]), float(solution[0]), max_y_event=max_y)
    report = PriceLinearReport(
        train_start=start.isoformat(), train_end=end.isoformat(), symbols=tuple(consumed.columns),
        l2=penalty, consumed_events=len(consumed),
        window_events=int((consumed.index >= start).sum()), candidate_observations=counts[0],
        warmup_observations=counts[1], unlabelled_observations=counts[2],
        fitted_observations=counts[3], max_x_event=model.max_x_event, max_y_event=model.max_y_event)
    return PriceLinearFit(model, report)
