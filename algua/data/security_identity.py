"""Stable security keys and dated ticker aliases (spec 2026-11-12 §4.15) — PREPARATORY.

Pure functions, no I/O, no store or schema access. The frozen bar schema stays keyed on `symbol`;
imported research data would use `stable_symbol(permaticker)` as that symbol, and `AliasTable`
maps it to/from the broker ticker on a given date. Renames keep one stable key; a reused ticker
resolves to different stable keys in disjoint date ranges.

Boundaries (deliberate): nothing here is wired into an importer, provider, universe store or
`verified_pit`. Alias spans describe which ticker a security TRADED under, never universe
membership; do not infer historical membership from them. Intervals are half-open
`[start, end)`; `end=None` means still current.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

STABLE_PREFIX = "SHR_"


class AliasError(ValueError):
    """The alias data is inconsistent (overlap, bad span) — fail closed."""


class UnknownAlias(LookupError):
    """No alias covers the requested ticker/key on the requested date."""


def stable_symbol(permaticker: int) -> str:
    """The Algua security key for a vendor permanent identifier."""
    if isinstance(permaticker, bool) or not isinstance(permaticker, int) or permaticker <= 0:
        raise AliasError("permaticker must be a positive integer")
    return f"{STABLE_PREFIX}{permaticker}"


def _day(value: object) -> date:
    ts = pd.Timestamp(value)
    return date(ts.year, ts.month, ts.day)


@dataclass(frozen=True)
class AliasInterval:
    stable: str
    ticker: str
    start: date
    end: date | None  # exclusive; None = open

    def covers(self, day: date) -> bool:
        return self.start <= day and (self.end is None or day < self.end)


@dataclass(frozen=True)
class Rename:
    """`old_ticker` was the ticker until `until` (exclusive); the next name starts then."""
    permaticker: int
    old_ticker: str
    until: date


def _disjoint(items: list[AliasInterval], what: str) -> None:
    items = sorted(items, key=lambda i: i.start)
    for a, b in zip(items, items[1:], strict=False):
        if a.end is None or b.start < a.end:
            raise AliasError(f"overlapping alias intervals for {what}")


class AliasTable:
    """Validated dated aliases: per ticker and per stable key the intervals never overlap."""

    def __init__(self, intervals: Iterable[AliasInterval]) -> None:
        items = list(intervals)
        by_ticker: dict[str, list[AliasInterval]] = {}
        by_stable: dict[str, list[AliasInterval]] = {}
        for i in items:
            if not i.ticker or i.ticker != i.ticker.strip().upper():
                raise AliasError("alias tickers must be non-empty, trimmed, upper-case")
            if i.end is not None and i.end <= i.start:
                raise AliasError("alias interval must have end after start")
            by_ticker.setdefault(i.ticker, []).append(i)
            by_stable.setdefault(i.stable, []).append(i)
        for v in by_ticker.values():
            _disjoint(v, "one ticker")
        for v in by_stable.values():
            _disjoint(v, "one security")
        self._by_ticker = {k: sorted(v, key=lambda i: i.start) for k, v in by_ticker.items()}
        self._by_stable = {k: sorted(v, key=lambda i: i.start) for k, v in by_stable.items()}

    def stable_for(self, ticker: str, on: object) -> str:
        """The security that held `ticker` on `on` (a reused ticker differs across eras)."""
        day = _day(on)
        for i in self._by_ticker.get(ticker.strip().upper(), ()):
            if i.covers(day):
                return i.stable
        raise UnknownAlias("no security held this ticker on that date")

    def ticker_for(self, stable: str, on: object) -> str:
        """The ticker `stable` traded under on `on` (the execution-edge mapping)."""
        day = _day(on)
        for i in self._by_stable.get(stable, ()):
            if i.covers(day):
                return i.ticker
        raise UnknownAlias("security has no ticker on that date")

    def history(self, stable: str) -> tuple[AliasInterval, ...]:
        return tuple(self._by_stable.get(stable, ()))


def alias_table_from_tickers(
    tickers: pd.DataFrame, renames: Iterable[Rename] = ()
) -> AliasTable:
    """Build aliases from a parsed TICKERS frame (`sharadar_tables.read_tickers`) plus renames.

    TICKERS carries only each security's current ticker and its first/last price dates, so one
    span per permaticker covers first price date .. last price date (inclusive -> exclusive end;
    open when not delisted). Earlier names need explicit `Rename` records. A missing first price
    date refuses rather than guessing.
    """
    by_perma: dict[int, list[Rename]] = {}
    for r in renames:
        by_perma.setdefault(r.permaticker, []).append(r)
    known = {int(p) for p in tickers["permaticker"]}
    if set(by_perma) - known:
        raise AliasError("rename for a permaticker absent from TICKERS")
    out: list[AliasInterval] = []
    for row in tickers.itertuples(index=False):
        perma = int(row.permaticker)
        if pd.isna(row.firstpricedate):
            raise AliasError("security without a first price date cannot be aliased")
        start = _day(row.firstpricedate)
        end: date | None = None
        if bool(row.isdelisted):
            if pd.isna(row.lastpricedate):
                raise AliasError("delisted security without a last price date")
            end = _day(row.lastpricedate) + timedelta(days=1)
        stable = stable_symbol(perma)
        cursor = start
        for r in sorted(by_perma.get(perma, ()), key=lambda r: r.until):
            out.append(AliasInterval(stable, r.old_ticker.strip().upper(), cursor, r.until))
            cursor = r.until
        out.append(AliasInterval(stable, str(row.ticker).strip().upper(), cursor, end))
    return AliasTable(out)

