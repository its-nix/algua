"""Fetched-once immutable authority for one backtest-family run."""

from __future__ import annotations

import json
import pickle
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from algua.backtest.errors import BacktestError
from algua.contracts.strategy_interface import uses_context_interface
from algua.contracts.types import DataProvider, FundamentalsProvider, NewsProvider
from algua.provenance.snapshot_evidence import project_snapshot_record

if TYPE_CHECKING:
    from algua.strategies.base import LoadedStrategy


def _snapshot_id(source: object | None, modality: str, *, required: bool) -> str | None:
    try:
        value = getattr(source, "snapshot_id", None)
    except Exception as exc:
        raise BacktestError(f"could not read {modality} snapshot_id: {exc}") from exc
    if isinstance(value, str) and value.strip():
        return value
    if required:
        raise BacktestError(
            f"context strategy requires a pinned {modality} snapshot_id (fail closed)"
        )
    return None


def _verify_snapshot(source: object, modality: str, pinned: str) -> None:
    current = _snapshot_id(source, modality, required=True)
    if current != pinned:
        raise BacktestError(
            f"{modality} snapshot_id changed during fetch: pinned {pinned!r}, now {current!r}"
        )


def _freeze_frame(frame: pd.DataFrame, modality: str) -> bytes:
    """Serialize immediately so nested object cells cannot alias a provider-owned frame."""
    if not isinstance(frame, pd.DataFrame):
        raise BacktestError(f"{modality} provider returned a non-DataFrame value")
    try:
        return pickle.dumps(frame, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PickleError, TypeError, AttributeError) as exc:
        raise BacktestError(f"could not materialize immutable {modality} run input: {exc}") from exc


def _thaw_frame(payload: bytes, modality: str) -> pd.DataFrame:
    """Return an isolated consumer frame from the immutable serialized authority."""
    try:
        frame = pickle.loads(payload)  # noqa: S301 - bytes were created in-process above
    except (pickle.PickleError, EOFError, TypeError, AttributeError) as exc:
        raise BacktestError(f"could not read immutable {modality} run input: {exc}") from exc
    if not isinstance(frame, pd.DataFrame):
        raise BacktestError(f"immutable {modality} run input did not contain a DataFrame")
    return frame


@dataclass(frozen=True, slots=True)
class RunInputBundle:
    """Immutable bytes and source identities captured once at a top-level run boundary.

    Frozen fields are only the facade; the authority is the immutable serialized bytes. Every
    consumer deserializes a fresh frame, severing provider, sibling-consumer, pandas-block and
    nested object-cell aliases.
    """

    bars_payload: bytes
    fundamentals_payload: bytes | None
    news_payload: bytes | None
    data_source: str
    provider_seed: int | None
    bars_snapshot_id: str | None
    fundamentals_snapshot_id: str | None
    news_snapshot_id: str | None
    bars_provenance_payload: bytes | None
    execution_fees: float
    execution_slippage: float

    def bars(self) -> pd.DataFrame:
        return _thaw_frame(self.bars_payload, "bars")

    def fundamentals(self) -> pd.DataFrame | None:
        return (
            None
            if self.fundamentals_payload is None
            else _thaw_frame(self.fundamentals_payload, "fundamentals")
        )

    def news(self) -> pd.DataFrame | None:
        return None if self.news_payload is None else _thaw_frame(self.news_payload, "news")

    def provenance(self, seed: int | None) -> dict[str, Any]:
        return {
            "data_source": self.data_source,
            "seed": self.provider_seed if self.provider_seed is not None else seed,
            "snapshot_id": self.bars_snapshot_id,
            "bars_provenance": (
                json.loads(self.bars_provenance_payload)
                if self.bars_provenance_payload is not None else None
            ),
            "execution_costs": self.execution_costs(),
        }

    def execution_costs(self) -> dict[str, Any]:
        return {
            "schema_version": "execution-costs/v1", "model": "vectorbt.from_orders",
            "fees": self.execution_fees,
            "fees_unit": "fraction_of_trade_notional_per_side",
            "slippage": self.execution_slippage,
            "slippage_unit": "adverse_fill_price_fraction_per_side",
        }


def capture_run_inputs(
    strategy: LoadedStrategy,
    provider: DataProvider,
    symbols: Collection[str],
    start: datetime,
    end: datetime,
    *,
    fundamentals_provider: FundamentalsProvider | None = None,
    news_provider: NewsProvider | None = None,
    include_provenance: bool,
) -> RunInputBundle:
    """Fetch each required source once, verify context identities, and freeze the frames."""
    context = uses_context_interface(strategy.strategy_interface)
    if strategy.config.needs_fundamentals and fundamentals_provider is None:
        raise BacktestError(
            f"strategy {strategy.name!r} declares needs_fundamentals but no "
            "fundamentals_provider was supplied (fail closed)"
        )
    if strategy.config.needs_news and news_provider is None:
        raise BacktestError(
            f"strategy {strategy.name!r} declares needs_news but no news_provider was "
            "supplied (fail closed)"
        )

    requested = list(symbols)
    execution = strategy.execution
    bars_pin = (
        _snapshot_id(provider, "bars", required=context) if context or include_provenance else None
    )
    bars_metadata = getattr(provider, "bars_provenance", None) if include_provenance else None
    if bars_metadata is not None and (
        not isinstance(bars_metadata, dict) or bars_metadata.get("snapshot_id") != bars_pin
    ):
        raise BacktestError("bars provenance snapshot binding mismatch")
    bars_provenance_payload = (
        json.dumps(bars_metadata, sort_keys=True, allow_nan=False).encode()
        if bars_metadata is not None else None
    )
    if bars_provenance_payload is not None:
        if bars_pin is None:
            raise BacktestError("bars provenance requires a pinned snapshot_id")
        evidence = project_snapshot_record(bars_pin, json.loads(bars_provenance_payload))
        if evidence["status"] != "VALID":
            raise BacktestError(f"invalid bars provenance: {evidence['reason']}")
    try:
        bars = provider.get_bars(requested, start, end, "1d")
    except Exception as exc:
        raise BacktestError(f"provider error: {exc}") from exc
    bars_payload = _freeze_frame(bars, "bars")
    if bars_pin is not None:
        _verify_snapshot(provider, "bars", bars_pin)

    fundamentals_pin: str | None = None
    fundamentals_payload: bytes | None = None
    if strategy.config.needs_fundamentals and fundamentals_provider is not None:
        if context:
            fundamentals_pin = _snapshot_id(
                fundamentals_provider, "fundamentals", required=True
            )
        try:
            fundamentals = fundamentals_provider.get_fundamentals(requested, end)
        except Exception as exc:
            raise BacktestError(f"provider error: {exc}") from exc
        fundamentals_payload = _freeze_frame(fundamentals, "fundamentals")
        if fundamentals_pin is not None:
            _verify_snapshot(fundamentals_provider, "fundamentals", fundamentals_pin)

    news_pin: str | None = None
    news_payload: bytes | None = None
    if strategy.config.needs_news and news_provider is not None:
        if context:
            news_pin = _snapshot_id(news_provider, "news", required=True)
        try:
            news = news_provider.get_news(requested, end)
        except Exception as exc:
            raise BacktestError(f"provider error: {exc}") from exc
        news_payload = _freeze_frame(news, "news")
        if news_pin is not None:
            _verify_snapshot(news_provider, "news", news_pin)

    # A later source callback may revise an earlier source identity. Frames are already frozen,
    # but every required identity must still describe the same source state at capture completion.
    if (
        news_payload is not None
        and fundamentals_pin is not None
        and fundamentals_provider is not None
    ):
        _verify_snapshot(fundamentals_provider, "fundamentals", fundamentals_pin)
    if (fundamentals_payload is not None or news_payload is not None) and bars_pin is not None:
        _verify_snapshot(provider, "bars", bars_pin)

    bars_snapshot = bars_pin
    fundamentals_snapshot = fundamentals_pin
    news_snapshot = news_pin
    provider_seed: int | None = None
    if include_provenance:
        if bars_snapshot is None:
            bars_snapshot = _snapshot_id(provider, "bars", required=False)
        if fundamentals_snapshot is None and fundamentals_provider is not None:
            fundamentals_snapshot = _snapshot_id(
                fundamentals_provider, "fundamentals", required=False
            )
        if news_snapshot is None and strategy.config.needs_news:
            news_snapshot = _snapshot_id(news_provider, "news", required=False)
        provider_seed = getattr(provider, "seed", None)

    return RunInputBundle(
        bars_payload=bars_payload,
        fundamentals_payload=fundamentals_payload,
        news_payload=news_payload,
        data_source=type(provider).__name__,
        provider_seed=provider_seed,
        bars_snapshot_id=bars_snapshot,
        fundamentals_snapshot_id=fundamentals_snapshot,
        news_snapshot_id=news_snapshot,
        bars_provenance_payload=bars_provenance_payload,
        execution_fees=execution.fees,
        execution_slippage=execution.slippage,
    )
