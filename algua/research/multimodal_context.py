"""Research composition and validation for multimodal ``score(context)`` experiments.

The canonical backtest has its own small context assembler; paper/live remain unsupported. News
and fundamentals reuse the protected PIT masks, and models are accepted only after the filesystem
registry has verified metadata and bytes together.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from algua.backtest.errors import BacktestError
from algua.backtest.pit_view import (
    _assert_fundamentals_shape,
    _assert_news_shape,
    _fundamentals_as_of,
    _news_as_of,
)
from algua.contracts.model_types import ModelHandle, ModelRef, normalize_as_of
from algua.contracts.strategy_context import (
    AsOfContext,
    AsOfView,
    ResearchStrategy,
    validate_score_output,
)
from algua.data.schema import validate_bars
from algua.models import ModelRegistryError, get_version_with_bytes
from algua.strategies.base import LoadedStrategy

_FEATURES = frozenset({"bars", "fundamentals", "news"})


class ContextError(ValueError):
    """A research context or score failed closed at the compatibility boundary."""


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContextError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _resolve_models(
    refs: Mapping[str, ModelRef], *, root: Path | None, first_decision_ts: datetime
) -> dict[str, ModelHandle]:
    if refs and root is None:
        raise ContextError("model_registry_root is required when pinned models are requested")
    resolved: dict[str, ModelHandle] = {}
    cutoff = pd.Timestamp(first_decision_ts)
    for key, ref in refs.items():
        if not key or key != key.strip():
            raise ContextError("model keys must be non-empty trimmed strings")
        try:
            version, artifact = get_version_with_bytes(ref.name, ref.version, root=root)
        except ModelRegistryError as exc:
            raise ContextError(f"pinned model {key!r} failed verification: {exc}") from exc
        if (
            version.name != ref.name
            or version.version != ref.version
            or version.digest != ref.digest
            or version.training_as_of != ref.training_as_of
            or version.provenance_digest != ref.provenance_digest
        ):
            raise ContextError(
                f"pinned model {key!r} reference does not match the verified registry version"
            )
        try:
            training_as_of = normalize_as_of(version.training_as_of)
        except (TypeError, ValueError) as exc:
            raise ContextError(
                f"pinned model {key!r} has unparseable training_as_of"
            ) from exc
        if pd.isna(training_as_of):
            raise ContextError(f"pinned model {key!r} has unparseable training_as_of")
        if training_as_of > cutoff:
            raise ContextError(
                f"pinned model {key!r} training_as_of is after the first decision (look-ahead)"
            )
        resolved[key] = ModelHandle(version=version, artifact_bytes=artifact)
    return resolved


def build_as_of_context(
    *,
    decision_ts: datetime,
    first_decision_ts: datetime,
    universe: tuple[str, ...],
    bars: pd.DataFrame,
    bars_snapshot_id: str,
    required_features: Collection[str],
    model_refs: Mapping[str, ModelRef],
    model_registry_root: Path | None,
    news: pd.DataFrame | None = None,
    news_snapshot_id: str | None = None,
    fundamentals: pd.DataFrame | None = None,
    fundamentals_snapshot_id: str | None = None,
) -> AsOfContext:
    """Compose one decision context from already fetched histories.

    Bars are canonical session-labelled rows and are masked to ``timestamp <= decision_ts``;
    this does not claim their index is an observed availability time.  Bitemporal sidecars are
    delegated to the existing engine masks so revision/retraction behavior cannot drift here.
    """
    decision = _utc(decision_ts, "decision_ts")
    first_decision = _utc(first_decision_ts, "first_decision_ts")
    if first_decision > decision:
        raise ContextError("first_decision_ts must be <= decision_ts")
    required = frozenset(required_features)
    unknown = required - _FEATURES
    if unknown:
        raise ContextError(f"unsupported required feature modalities: {sorted(unknown)}")
    if "bars" not in required:
        raise ContextError("bars must be an explicit required feature in this research slice")

    try:
        validate_bars(bars, timeframe="1d")
    except ValueError as exc:
        raise ContextError(f"bars failed the frozen schema: {exc}") from exc
    decision_stamp = pd.Timestamp(decision)
    symbols = set(universe)
    visible_bars = bars[(bars.index <= decision_stamp) & bars["symbol"].isin(symbols)].copy()
    features: dict[str, AsOfView] = {
        "bars": AsOfView(
            kind="bars",
            as_of=decision,
            snapshot_id=bars_snapshot_id,
            frame=visible_bars,
            source_timestamp=None,
        )
    }

    if news is not None:
        if news_snapshot_id is None:
            raise ContextError("news_snapshot_id is required when news is supplied")
        try:
            _assert_news_shape(news)
            visible_news = _news_as_of(news, decision_stamp)
        except BacktestError as exc:
            raise ContextError(f"news failed the existing PIT seam: {exc}") from exc
        visible_news = visible_news[visible_news["symbol"].isin(symbols)].reset_index(drop=True)
        features["news"] = AsOfView(
            kind="news",
            as_of=decision,
            snapshot_id=news_snapshot_id,
            frame=visible_news,
        )
    if fundamentals is not None:
        if fundamentals_snapshot_id is None:
            raise ContextError(
                "fundamentals_snapshot_id is required when fundamentals are supplied"
            )
        try:
            _assert_fundamentals_shape(fundamentals)
            visible_fundamentals = _fundamentals_as_of(fundamentals, decision_stamp)
        except BacktestError as exc:
            raise ContextError(f"fundamentals failed the existing PIT seam: {exc}") from exc
        visible_fundamentals = visible_fundamentals[
            visible_fundamentals["symbol"].isin(symbols)
        ].reset_index(drop=True)
        features["fundamentals"] = AsOfView(
            kind="fundamentals",
            as_of=decision,
            snapshot_id=fundamentals_snapshot_id,
            frame=visible_fundamentals,
        )

    missing = required - features.keys()
    if missing:
        raise ContextError(f"missing required feature modalities: {sorted(missing)}")
    models = _resolve_models(
        model_refs, root=model_registry_root, first_decision_ts=first_decision
    )
    return AsOfContext(
        decision_ts=decision,
        first_decision_ts=first_decision,
        universe=universe,
        features=features,
        models=models,
    )


def _same_ref(handle: ModelHandle, ref: ModelRef) -> bool:
    version = handle.version
    return (
        version.name == ref.name
        and version.version == ref.version
        and version.digest == ref.digest
        and version.training_as_of == ref.training_as_of
        and version.provenance_digest == ref.provenance_digest
    )


def score_context(strategy: ResearchStrategy, context: AsOfContext) -> pd.Series:
    """Run and validate one pure research score vector."""
    required_features = frozenset(strategy.required_features)
    required_models = dict(strategy.required_models)
    if any(not isinstance(key, str) or not key or key != key.strip() for key in required_models):
        raise ContextError("required model keys must be non-empty trimmed strings")
    if any(not isinstance(ref, ModelRef) for ref in required_models.values()):
        raise ContextError("required model declarations must contain ModelRef values")
    missing_features = set(required_features) - context.features.keys()
    if missing_features:
        raise ContextError(f"missing required feature modalities: {sorted(missing_features)}")
    models = context.models
    missing_models = set(required_models) - models.keys()
    if missing_models:
        raise ContextError(f"missing required pinned models: {sorted(missing_models)}")
    mismatched = [
        key for key, ref in required_models.items() if not _same_ref(models[key], ref)
    ]
    if mismatched:
        raise ContextError(f"context model references do not match strategy pins: {mismatched}")

    try:
        return validate_score_output(strategy.score(context), context.universe)
    except (TypeError, ValueError) as exc:
        raise ContextError(str(exc)) from exc


@dataclass(frozen=True)
class LegacyStrategyAdapter:
    """Temporary score adapter for one existing ``LoadedStrategy``.

    It invokes the legacy authored signal exactly as before and delegates all weight production to
    ``LoadedStrategy.construct``.  Extra context lanes are never passed through a closure or hidden
    global.  Remove this adapter after every supported strategy has direct ``score(context)`` parity
    and the protected backtest/paper/live integration has one reviewed context-aware path.
    """

    strategy: LoadedStrategy

    @property
    def required_features(self) -> frozenset[str]:
        required = {"bars"}
        if self.strategy.config.needs_news:
            required.add("news")
        if self.strategy.config.needs_fundamentals:
            required.add("fundamentals")
        return frozenset(required)

    @property
    def required_models(self) -> Mapping[str, ModelRef]:
        ref = self.strategy.config.model_ref
        return {} if ref is None else {ref.name: ref}

    def score(self, context: AsOfContext) -> pd.Series:
        bars = context.features["bars"].frame
        if self.strategy.config.needs_news:
            return self.strategy.signal(bars, news=context.features["news"].frame)
        if self.strategy.config.needs_fundamentals:
            return self.strategy.signal(
                bars, fundamentals=context.features["fundamentals"].frame
            )
        # A legacy model strategy consumes the already loader-bound handle. score_context first
        # proves the context carries the same independently verified pin. Re-check the mutable
        # LoadedStrategy field too: a post-construction replacement must not drift from that pin.
        if self.strategy.config.needs_model:
            ref = self.strategy.config.model_ref
            bound = self.strategy.model_handle
            if ref is None or bound != context.models[ref.name]:
                raise ContextError("legacy strategy bound model handle changed after validation")
        return self.strategy.signal(bars)

    def target_weights(self, context: AsOfContext) -> pd.Series:
        bars = context.features["bars"].frame
        return self.strategy.construct(score_context(self, context), bars)

