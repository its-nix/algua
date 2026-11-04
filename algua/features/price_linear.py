"""Apply-only observed-price returns and a closed frozen two-feature linear codec.

Event labels describe observations, never source availability or a model information cutoff.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from algua.features.scaling import STANDARD, FrozenScaler, ScalerError

FEATURE_ORDER = ("return_1", "return_5")
MAX_EVENTS, MAX_SYMBOLS, MAX_OBSERVATIONS = 100_000, 512, 2_000_000
_SCHEMA, _RECIPE = "price-linear/v1", "pooled-return-ridge/v1"


class PriceLinearError(ValueError):
    """Malformed data, numerical failure or invalid frozen numerical declaration."""


def _require(condition: Any) -> None:
    if not condition:
        raise PriceLinearError("invalid price-linear data")


def _number(value: Any) -> float:
    _require(not isinstance(value, (bool, np.bool_))
             and isinstance(value, (int, float, np.integer, np.floating)))
    try:
        result = float(value)
    except OverflowError as exc:
        raise PriceLinearError("number exceeds float64 range") from exc
    _require(np.isfinite(result))
    return result


def _event(value: Any) -> pd.Timestamp:
    _require(isinstance(value, (str, datetime)))
    try:
        stamp = pd.Timestamp(value)
        _require(not pd.isna(stamp) and stamp.tzinfo is not None)
        return stamp.tz_convert("UTC")
    except (ValueError, TypeError, OverflowError) as exc:
        raise PriceLinearError("finite aware event timestamp required") from exc


def _geometry(prices: pd.DataFrame) -> None:
    _require(isinstance(prices, pd.DataFrame) and not prices.empty)
    index = prices.index
    _require(isinstance(index, pd.DatetimeIndex) and str(index.tz) == "UTC"
             and not index.hasnans and index.is_unique and index.is_monotonic_increasing)
    _require(0 < len(prices.columns) <= MAX_SYMBOLS and prices.columns.is_unique
             and all(isinstance(s, str) and s and s.strip() == s for s in prices.columns))


def _price_matrix(prices: pd.DataFrame) -> np.ndarray:
    _geometry(prices)
    _require(len(prices) <= MAX_EVENTS and prices.size <= MAX_OBSERVATIONS)
    raw = prices.to_numpy()
    values = np.empty(raw.shape, dtype="float64")
    for position, value in np.ndenumerate(raw):
        if isinstance(value, (complex, np.complexfloating)):
            _require(value.imag == 0)
            # Explicit real-valued container promotion; never discard an imaginary part.
            value = value.real
        number = _number(value)
        _require(number > 0)
        values[position] = number
    return values


def return_features(prices: pd.DataFrame) -> pd.DataFrame:
    """One/five observed-row returns, retaining undefined warmup as NaN; no implicit fill."""
    values = _price_matrix(prices)
    columns = []
    try:
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for lag in (1, 5):
                feature = np.full(values.shape, np.nan, dtype="float64")
                feature[lag:] = values[lag:] / values[:-lag] - 1.0
                _require(np.isfinite(feature[lag:]).all())
                columns.append(feature.ravel())
    except FloatingPointError as exc:
        raise PriceLinearError("return calculation exceeds float64 range") from exc
    index = pd.MultiIndex.from_product([prices.index, prices.columns],
                                       names=["event_label", "symbol"])
    return pd.DataFrame(np.column_stack(columns), index=index, columns=FEATURE_ORDER)


def _exact(value: Any, keys: set[str]) -> None:
    _require(isinstance(value, dict) and set(value) == keys)


def _scaler_parts(blob: dict) -> tuple[tuple[float, float], tuple[float, float], str]:
    _exact(blob, {"kind", "columns", "params", "fit_max_timestamp"})
    _require(blob["kind"] == STANDARD and blob["columns"] == list(FEATURE_ORDER))
    _exact(blob["params"], set(FEATURE_ORDER))
    means, stds = [], []
    for column in FEATURE_ORDER:
        part = blob["params"][column]
        _exact(part, {"mean", "std"})
        means.append(_number(part["mean"]))
        stds.append(_number(part["std"]))
        _require(stds[-1] > 0)
    return (means[0], means[1]), (stds[0], stds[1]), _event(blob["fit_max_timestamp"]).isoformat()


@dataclass(frozen=True, init=False)
class FrozenPriceLinear:
    """Immutable primitive parameters; each scaler accessor returns a detached existing scaler."""

    _means: tuple[float, float]
    _stds: tuple[float, float]
    coefficients: tuple[float, float]
    intercept: float
    max_x_event: str
    max_y_event: str

    def __init__(self, scaler: FrozenScaler, coefficients: Sequence[float], intercept: float,
                 *, max_y_event: str) -> None:
        _require(isinstance(scaler, FrozenScaler) and set(scaler.params) == set(FEATURE_ORDER))
        means, stds, maximum = _scaler_parts(scaler.to_dict())
        _require(isinstance(coefficients, (tuple, list, np.ndarray)) and len(coefficients) == 2)
        weights = (_number(coefficients[0]), _number(coefficients[1]))
        target = _event(max_y_event).isoformat()
        _require(_event(maximum) < _event(target))
        for key, value in (("_means", means), ("_stds", stds), ("coefficients", weights),
                           ("intercept", _number(intercept)), ("max_x_event", maximum),
                           ("max_y_event", target)):
            object.__setattr__(self, key, value)

    @property
    def scaler(self) -> FrozenScaler:
        return FrozenScaler(kind=STANDARD, columns=FEATURE_ORDER,
            params={c: {"mean": self._means[i], "std": self._stds[i]}
                    for i, c in enumerate(FEATURE_ORDER)}, fit_max_timestamp=self.max_x_event)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Apply fixed parameters to finite real features, preserving the caller's row order."""
        _require(isinstance(features, pd.DataFrame) and 0 < len(features) <= MAX_OBSERVATIONS
                 and tuple(features.columns) == FEATURE_ORDER)
        raw = features.to_numpy()
        values = np.array([_number(v) for v in raw.ravel()], dtype="float64").reshape(raw.shape)
        frame = pd.DataFrame(values, index=features.index, columns=FEATURE_ORDER)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                scaled = self.scaler.transform(frame).to_numpy(dtype="float64")
                predicted = scaled @ np.asarray(self.coefficients) + self.intercept
            _require(np.isfinite(predicted).all())
        except FloatingPointError as exc:
            raise PriceLinearError("prediction exceeds float64 range") from exc
        return pd.Series(predicted, index=features.index.copy(), name="prediction", dtype="float64")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": _SCHEMA, "recipe": _RECIPE, "features": list(FEATURE_ORDER),
                "scaler": self.scaler.to_dict(), "coefficients": list(self.coefficients),
                "intercept": self.intercept, "observed_events": {
                    "max_x_event": self.max_x_event, "max_y_event": self.max_y_event}}

    def to_json(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> FrozenPriceLinear:
        _require(type(raw) is bytes and len(raw) <= 64 * 1024)

        def pairs(items: list[tuple[str, Any]]) -> dict:
            result: dict = {}
            for key, value in items:
                _require(key not in result)
                result[key] = value
            return result

        def constant(value: str) -> None:
            raise PriceLinearError("nonfinite JSON number")

        try:
            blob = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
            _exact(blob, {"schema", "recipe", "features", "scaler", "coefficients",
                          "intercept", "observed_events"})
            _require(blob["schema"] == _SCHEMA and blob["recipe"] == _RECIPE
                     and blob["features"] == list(FEATURE_ORDER))
            _scaler_parts(blob["scaler"])
            _exact(blob["observed_events"], {"max_x_event", "max_y_event"})
            result = cls(FrozenScaler.from_dict(blob["scaler"]), blob["coefficients"],
                         blob["intercept"], max_y_event=blob["observed_events"]["max_y_event"])
            _require(_event(blob["observed_events"]["max_x_event"])
                     == _event(result.max_x_event))
            return result
        except (ValueError, TypeError, KeyError, RecursionError, OverflowError, ScalerError) as exc:
            raise PriceLinearError("invalid frozen price-linear JSON") from exc
