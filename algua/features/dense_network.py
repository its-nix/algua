"""Pure frozen dense inference: two ReLU hidden layers and one linear scalar output.

The closed JSON contains parameters only. It supplies no fitting, model resolution or I/O.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, NoReturn

import numpy as np
import pandas as pd

MAX_MODEL_BYTES = 64 * 1024
MAX_WIDTH, MAX_ROWS = 32, 4096
_SCHEMA = "frozen-dense/v1"
_Matrix = tuple[tuple[float, ...], ...]
_Layer = tuple[_Matrix, tuple[float, ...]]


class DenseNetworkError(ValueError):
    """An invalid frozen model, feature matrix or nonfinite numerical result."""


def _require(condition: Any) -> None:
    if not condition:
        raise DenseNetworkError("invalid frozen-dense model or features")


def _number(value: Any) -> float:
    _require(not isinstance(value, (bool, np.bool_))
             and isinstance(value, (int, float, np.integer, np.floating)))
    try:
        result = float(value)
    except OverflowError as exc:
        raise DenseNetworkError("frozen-dense number exceeds float64 range") from exc
    _require(np.isfinite(result))
    return result


def _sequence(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def _layer(value: Any, inputs: int, *, output: bool) -> _Layer:
    _require(isinstance(value, dict) and set(value) == {"weights", "bias"})
    weights, bias = value["weights"], value["bias"]
    _require(_sequence(weights) and 0 < len(weights) <= MAX_WIDTH)
    _require(not output or len(weights) == 1)
    _require(_sequence(bias) and len(bias) == len(weights))
    _require(all(_sequence(row) and len(row) == inputs for row in weights))
    return (tuple(tuple(_number(v) for v in row) for row in weights),
            tuple(_number(v) for v in bias))


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        _require(key not in result)
        result[key] = value
    return result


def _constant(value: str) -> NoReturn:
    raise DenseNetworkError("frozen-dense JSON numbers must be finite")


@dataclass(frozen=True, slots=True, init=False)
class FrozenDenseNetwork:
    """An immutable bounded network with output-by-input weight matrices.

    Feature order is exact. Both hidden layers apply ReLU; the last layer is linear.
    Predictions are per-row scores, never portfolio weights or execution instructions.
    """

    features: tuple[str, ...]
    _layers: tuple[_Layer, ...] = field(repr=False)

    def __init__(self, features: Any, layers: Any) -> None:
        _require(_sequence(features) and 0 < len(features) <= MAX_WIDTH)
        _require(all(isinstance(name, str) and name and name == name.strip()
                     and len(name) <= 128 for name in features))
        _require(len(set(features)) == len(features))
        _require(_sequence(layers) and len(layers) == 3)
        parsed = []
        width = len(features)
        for index, value in enumerate(layers):
            layer = _layer(value, width, output=index == 2)
            parsed.append(layer)
            width = len(layer[0])
        object.__setattr__(self, "features", tuple(features))
        object.__setattr__(self, "_layers", tuple(parsed))
        try:
            _require(len(self.to_json()) <= MAX_MODEL_BYTES)
        except UnicodeEncodeError as exc:
            raise DenseNetworkError("frozen-dense feature names must be UTF-8") from exc

    @classmethod
    def from_json(cls, payload: bytes) -> FrozenDenseNetwork:
        """Decode up to 64 KiB, refusing duplicate keys, unknown fields and invalid dimensions."""
        _require(isinstance(payload, bytes) and 0 < len(payload) <= MAX_MODEL_BYTES)
        try:
            value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs,
                               parse_constant=_constant)
            _require(isinstance(value, dict) and set(value) == {"schema", "features", "layers"})
            _require(value["schema"] == _SCHEMA)
            return cls(value["features"], value["layers"])
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise DenseNetworkError("invalid frozen-dense JSON") from exc

    def to_json(self) -> bytes:
        """Deterministic detached encoding; no mutable parameter arrays escape."""
        value = {"schema": _SCHEMA, "features": self.features,
                 "layers": [{"weights": w, "bias": b} for w, b in self._layers]}
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Apply only fixed finite float64 parameters, preserving the caller's row order."""
        _require(isinstance(features, pd.DataFrame) and 0 < len(features) <= MAX_ROWS
                 and tuple(features.columns) == self.features and features.index.is_unique)
        raw = features.to_numpy()
        values = np.array([_number(v) for v in raw.ravel()], dtype="float64").reshape(raw.shape)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                for index, (weights, bias) in enumerate(self._layers):
                    values = values @ np.asarray(weights).T + np.asarray(bias)
                    _require(np.isfinite(values).all())
                    if index < 2:
                        values = np.maximum(values, 0.0)
        except FloatingPointError as exc:
            raise DenseNetworkError("frozen-dense inference exceeds float64 range") from exc
        return pd.Series(values[:, 0], index=features.index.copy(),
                         name="prediction", dtype="float64")
