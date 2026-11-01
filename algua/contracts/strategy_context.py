"""Pure research contracts for point-in-time multimodal scoring.

This is a research-only compatibility seam.  It deliberately does not change the frozen
``DataProvider`` or legacy strategy configuration contracts.  Frames and model metadata are
copied on ingress and again on read so a scoring function cannot mutate authoritative inputs.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Protocol

import pandas as pd

from algua.contracts.model_types import (
    ModelHandle,
    ModelRef,
    compute_provenance_digest,
    normalize_as_of,
)


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _copy_model(handle: ModelHandle) -> ModelHandle:
    version = replace(
        handle.version,
        hyperparameters=deepcopy(handle.version.hyperparameters),
        eval_report=deepcopy(handle.version.eval_report),
    )
    return ModelHandle(version=version, artifact_bytes=bytes(handle.artifact_bytes))


def _copy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy a frame without retaining aliases to mutable Python objects in object cells."""
    copied = frame.copy(deep=True)
    for column in copied.select_dtypes(include="object").columns:
        copied[column] = copied[column].map(deepcopy)
    return copied


def _verify_model(handle: ModelHandle, first_decision_ts: datetime) -> None:
    version = handle.version
    actual_digest = hashlib.sha256(handle.artifact_bytes).hexdigest()[:16]
    if actual_digest != version.digest:
        raise ValueError("model artifact bytes do not match the recorded digest")
    expected_provenance = compute_provenance_digest(
        digest=version.digest,
        training_snapshot_id=version.training_snapshot_id,
        training_as_of=version.training_as_of,
        code_hash=version.code_hash,
        hyperparameters=version.hyperparameters,
        seed=version.seed,
        eval_report=version.eval_report,
    )
    if expected_provenance != version.provenance_digest:
        raise ValueError("model provenance metadata does not match its recorded digest")
    try:
        training_as_of = normalize_as_of(version.training_as_of)
    except (TypeError, ValueError) as exc:
        raise ValueError("model training_as_of is not a valid timestamp") from exc
    if pd.isna(training_as_of):
        raise ValueError("model training_as_of is not a valid timestamp")
    if training_as_of > pd.Timestamp(first_decision_ts):
        raise ValueError("model training_as_of is after the first decision")


def _verify_view(view: AsOfView, decision_ts: datetime, universe: tuple[str, ...]) -> None:
    if view.as_of != decision_ts:
        raise ValueError("feature view as_of must equal the context decision_ts")
    frame = view.frame
    if "symbol" in frame.columns:
        outside = set(frame["symbol"]) - set(universe)
        if outside:
            raise ValueError(f"feature view contains symbols outside the universe: {outside}")
    decision = pd.Timestamp(decision_ts)
    if view.kind == "bars":
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError("bars view requires a timezone-aware DatetimeIndex")
        if frame.index.hasnans:
            raise ValueError("bars view index must not contain NaT")
        if (frame.index > decision).any():
            raise ValueError("bars view contains a future session label")
    if view.kind in {"news", "fundamentals"} and "knowable_at" not in frame.columns:
        raise ValueError(f"{view.kind} view requires knowable_at")
    if "knowable_at" in frame.columns:
        knowable_at = frame["knowable_at"]
        if not isinstance(knowable_at.dtype, pd.DatetimeTZDtype):
            raise ValueError("knowable_at must be timezone-aware")
        if knowable_at.isna().any():
            raise ValueError("knowable_at must not be null")
        if (knowable_at > decision).any():
            raise ValueError("feature view contains a future-known row")


@dataclass(frozen=True, slots=True, init=False)
class AsOfView:
    """One modality after its point-in-time mask has been applied.

    ``as_of`` is the decision cutoff used to make the view; it is not a claimed source-observation
    timestamp.  In particular, daily bar indexes remain exchange session labels at UTC midnight.
    ``source_timestamp`` is therefore optional and is ``None`` when no truthful single timestamp
    exists; news keeps its distinct ``published_at`` and ``knowable_at`` columns in ``frame``.
    """

    kind: str
    as_of: datetime
    snapshot_id: str
    source_timestamp: datetime | None
    _frame: pd.DataFrame = field(repr=False)

    def __init__(
        self,
        *,
        kind: str,
        as_of: datetime,
        snapshot_id: str,
        frame: pd.DataFrame,
        source_timestamp: datetime | None = None,
    ) -> None:
        if not kind or kind != kind.strip():
            raise ValueError("view kind must be a non-empty trimmed string")
        if not snapshot_id or snapshot_id != snapshot_id.strip():
            raise ValueError("view snapshot_id must be a non-empty trimmed string")
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("view frame must be a pandas DataFrame")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "as_of", _aware_utc(as_of, "view as_of"))
        object.__setattr__(self, "snapshot_id", snapshot_id)
        object.__setattr__(
            self,
            "source_timestamp",
            None if source_timestamp is None else _aware_utc(source_timestamp, "source_timestamp"),
        )
        object.__setattr__(self, "_frame", _copy_frame(frame))

    @property
    def frame(self) -> pd.DataFrame:
        return _copy_frame(self._frame)


@dataclass(frozen=True, slots=True, init=False)
class AsOfContext:
    """All immutable inputs visible to one research scoring decision."""

    decision_ts: datetime
    first_decision_ts: datetime
    universe: tuple[str, ...]
    _features: dict[str, AsOfView] = field(repr=False)
    _models: dict[str, ModelHandle] = field(repr=False)

    def __init__(
        self,
        *,
        decision_ts: datetime,
        first_decision_ts: datetime,
        universe: tuple[str, ...],
        features: Mapping[str, AsOfView],
        models: Mapping[str, ModelHandle],
    ) -> None:
        if any(not symbol or symbol != symbol.strip() for symbol in universe):
            raise ValueError("universe symbols must be non-empty trimmed strings")
        if len(set(universe)) != len(universe):
            raise ValueError("universe must not contain duplicate symbols")
        copied_features = dict(features)
        if any(name != view.kind for name, view in copied_features.items()):
            raise ValueError("feature mapping keys must match each AsOfView.kind")
        decision = _aware_utc(decision_ts, "decision_ts")
        first_decision = _aware_utc(first_decision_ts, "first_decision_ts")
        if first_decision > decision:
            raise ValueError("first_decision_ts must be <= decision_ts")
        for view in copied_features.values():
            _verify_view(view, decision, universe)
        for handle in models.values():
            _verify_model(handle, first_decision)
        object.__setattr__(self, "decision_ts", decision)
        object.__setattr__(self, "first_decision_ts", first_decision)
        object.__setattr__(self, "universe", tuple(universe))
        object.__setattr__(self, "_features", copied_features)
        object.__setattr__(self, "_models", {k: _copy_model(v) for k, v in models.items()})

    @property
    def features(self) -> Mapping[str, AsOfView]:
        return MappingProxyType(dict(self._features))

    @property
    def models(self) -> Mapping[str, ModelHandle]:
        return MappingProxyType({k: _copy_model(v) for k, v in self._models.items()})


class ResearchStrategy(Protocol):
    """Temporary research scoring interface; not a paper/live strategy contract."""

    @property
    def required_features(self) -> frozenset[str]: ...

    @property
    def required_models(self) -> Mapping[str, ModelRef]: ...

    def score(self, context: AsOfContext) -> pd.Series: ...

