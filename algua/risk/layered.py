"""Pure, fixed-capital risk policy. Exposure restoration is never inferred from a price bounce."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation


def decimal(value: object) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not a risk quantity")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid risk quantity") from exc
    if not out.is_finite():
        raise ValueError("risk quantity must be finite")
    return out


@dataclass(frozen=True)
class DrawdownPolicy:
    normal_capital: str
    reduce_at: str = "0.10"
    reduced_fraction: str = "0.50"
    halt_at: str = "0.20"
    quote_age_seconds: str = "10"
    max_spread: str = "0.01"
    limit_offset: str = "0.0025"
    feed: str = "iex"
    permitted_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for key in asdict(self):
            if key not in ("feed", "permitted_symbols"):
                object.__setattr__(self, key, str(decimal(getattr(self, key))))
        symbols = self.permitted_symbols
        if (
            not isinstance(symbols, (tuple, list))
            or any(
                not isinstance(s, str) or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s) is None
                for s in symbols
            )
            or len(set(symbols)) != len(symbols)
        ):
            raise ValueError("invalid permitted instruments")
        object.__setattr__(self, "permitted_symbols", tuple(symbols))
        if (
            decimal(self.normal_capital) <= 0
            or not 0 < decimal(self.reduce_at) < decimal(self.halt_at) <= 1
            or not 0 < decimal(self.reduced_fraction) < 1
            or not 0 < decimal(self.quote_age_seconds) <= 60
            or not 0 < decimal(self.max_spread) <= Decimal(".02")
            or not 0 <= decimal(self.limit_offset) <= Decimal(".01")
            or self.feed not in ("iex", "sip")
        ):
            raise ValueError("invalid layered drawdown policy")

    def to_dict(self) -> dict:
        return asdict(self) | {"permitted_symbols": list(self.permitted_symbols)}


@dataclass(frozen=True)
class Assessment:
    peak: Decimal
    drawdown: Decimal
    severity: int
    fraction: Decimal


def evaluate(policy: DrawdownPolicy, nav: Decimal, peak: Decimal, severity: int) -> Assessment:
    nav, peak = decimal(nav), decimal(peak)
    if severity not in (0, 1, 2) or peak <= 0:
        raise ValueError("invalid persisted risk state")
    peak = max(peak, nav)
    drawdown = max(Decimal(0), 1 - nav / peak)
    level = (
        2
        if nav <= 0 or drawdown >= decimal(policy.halt_at)
        else (1 if drawdown >= decimal(policy.reduce_at) else 0)
    )
    level = max(severity, level)
    return Assessment(
        peak, drawdown, level, (Decimal(1), decimal(policy.reduced_fraction), Decimal(0))[level]
    )
