"""Pure closed manifest parsing shared by portfolio replay and public evidence validation."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_MANIFEST_BYTES = 65536
_Number = Annotated[float, Field(ge=0)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class _Execution(_Closed):
    rebalance_frequency: Literal["1d"]
    decision_lag_bars: Annotated[int, Field(ge=1, le=1)]
    allow_fractional: bool
    max_gross_exposure: Annotated[float, Field(gt=0, le=1)]
    max_weight_per_symbol: Annotated[float, Field(gt=0, le=1)]
    allow_short: bool
    warmup_bars: Annotated[int, Field(ge=0, le=512)]
    fees: _Number
    slippage: _Number
    capacity: None
    fill_price: Literal["open", "close"]
    target_gross_utilization: Annotated[float, Field(gt=0, le=1)]


class _Constraints(_Closed):
    max_gross: Annotated[float, Field(ge=0, le=1)]
    max_weight_per_symbol: Annotated[float, Field(ge=0, le=1)]
    max_turnover: _Number | None


class _Sleeve(_Closed):
    strategy: Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,95}$")]
    budget: Annotated[float, Field(ge=0, le=1)]


class _Risk(_Closed):
    as_of: str
    volatility: Annotated[float, Field(gt=0)]
    source: Annotated[str, Field(min_length=1, max_length=256)]


def _aware(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("portfolio replay dates must be timezone-aware")
    return instant.astimezone(UTC)


class _Manifest(_Closed):
    schema_version: Literal["portfolio-replay/v1"]
    snapshot_id: Annotated[str, Field(pattern=r"^[a-f0-9]{16}$")]
    start: str
    end: str
    symbols: Annotated[list[str], Field(min_length=1, max_length=8)]
    sleeves: Annotated[list[_Sleeve], Field(max_length=8)]
    execution: _Execution
    constraints: _Constraints
    initial_cash: Annotated[float, Field(gt=0)]
    seed: Annotated[int, Field(ge=0, le=2**32 - 1)] | None
    risk_estimates: dict[str, Annotated[list[_Risk], Field(max_length=512)]]

    @model_validator(mode="after")
    def supported(self) -> Self:
        names = [s.strategy for s in self.sleeves]
        if len(set(names)) != len(names) or sum(s.budget for s in self.sleeves) > 1:
            raise ValueError("unique sleeves and total budget <= 1 are required")
        if len(set(self.symbols)) != len(self.symbols) or any(
            not symbol or symbol.strip() != symbol for symbol in self.symbols
        ):
            raise ValueError("symbols must be unique nonempty trimmed strings")
        if set(self.risk_estimates) - set(names):
            raise ValueError("risk estimates must reference declared sleeves")
        start, end = _aware(self.start), _aware(self.end)
        if start >= end:
            raise ValueError("portfolio replay requires start before end")
        self.start, self.end = start.isoformat(), end.isoformat()
        self.symbols.sort()
        self.sleeves.sort(key=lambda sleeve: sleeve.strategy)
        if self.execution.allow_short or not self.execution.allow_fractional:
            raise ValueError("portfolio replay requires long-only fractional account execution")
        if (self.constraints.max_gross > self.execution.max_gross_exposure
                or self.constraints.max_weight_per_symbol > self.execution.max_weight_per_symbol):
            raise ValueError("portfolio constraints must fit the account execution limits")
        for estimates in self.risk_estimates.values():
            for estimate in estimates:
                estimate.as_of = _aware(estimate.as_of).isoformat()
                if not estimate.source.strip():
                    raise ValueError("risk estimate source must not be blank")
        return self


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise ValueError(f"duplicate manifest key: {key}")
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")
