"""Synthetic rename / reuse / date-boundary tests for the preparatory alias module."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from algua.data.security_identity import (
    AliasError,
    AliasInterval,
    AliasTable,
    Rename,
    UnknownAlias,
    alias_table_from_tickers,
    stable_symbol,
)
from tests._sharadar_fixtures import sample_tables


def _tickers() -> pd.DataFrame:
    return sample_tables()[2]


def _perma(ticker: str, delisted: bool) -> int:
    t = _tickers()
    return int(t[(t["ticker"] == ticker) & (t["isdelisted"] == delisted)]["permaticker"].iloc[0])


def test_stable_symbol_from_permaticker() -> None:
    assert stable_symbol(900001) == "SHR_900001"
    for bad in (0, -1, True):
        with pytest.raises(AliasError):
            stable_symbol(bad)  # type: ignore[arg-type]


def test_reused_ticker_resolves_to_distinct_securities() -> None:
    table = alias_table_from_tickers(_tickers())
    old, new = _perma("ZZRU", True), _perma("ZZRU", False)
    assert table.stable_for("ZZRU", "2020-01-02") == stable_symbol(old)
    assert table.stable_for("ZZRU", "2020-01-08") == stable_symbol(new)
    assert stable_symbol(old) != stable_symbol(new)


def test_date_boundaries_half_open() -> None:
    t = _tickers()
    old = t[(t["ticker"] == "ZZRU") & t["isdelisted"]].iloc[0]
    last = pd.Timestamp(old["lastpricedate"]).date()
    table = alias_table_from_tickers(t)
    assert table.stable_for("ZZRU", last) == stable_symbol(int(old["permaticker"]))
    with pytest.raises(UnknownAlias):  # day after the last price date: nobody holds it yet
        table.stable_for("ZZRU", last + pd.Timedelta(days=1))
    with pytest.raises(UnknownAlias):
        table.stable_for("ZZRU", "2019-12-31")


def test_rename_keeps_one_stable_key() -> None:
    t = _tickers()
    perma = _perma("ZZSP", False)
    table = alias_table_from_tickers(t, [Rename(perma, "zzold ", date(2020, 1, 6))])
    key = stable_symbol(perma)
    assert table.stable_for("ZZOLD", "2020-01-03") == key
    assert table.stable_for("ZZSP", "2020-01-06") == key
    assert table.ticker_for(key, "2020-01-03") == "ZZOLD"
    assert table.ticker_for(key, "2020-01-09") == "ZZSP"
    with pytest.raises(UnknownAlias):
        table.stable_for("ZZOLD", "2020-01-06")
    assert [i.ticker for i in table.history(key)] == ["ZZOLD", "ZZSP"]


def test_overlap_and_bad_inputs_fail_closed() -> None:
    a = AliasInterval("SHR_1", "AAA", date(2020, 1, 1), date(2020, 2, 1))
    with pytest.raises(AliasError):  # same ticker, two securities, overlapping
        AliasTable([a, AliasInterval("SHR_2", "AAA", date(2020, 1, 15), None)])
    with pytest.raises(AliasError):  # one security, two tickers at once
        AliasTable([a, AliasInterval("SHR_1", "BBB", date(2020, 1, 15), None)])
    with pytest.raises(AliasError):
        AliasTable([AliasInterval("SHR_1", "AAA", date(2020, 2, 1), date(2020, 2, 1))])
    with pytest.raises(AliasError):  # rename dated before the security's first price
        early = Rename(_perma("ZZSP", False), "OLD", date(2019, 1, 1))
        alias_table_from_tickers(_tickers(), [early])
    with pytest.raises(AliasError):
        alias_table_from_tickers(_tickers(), [Rename(1, "OLD", date(2020, 1, 6))])


def test_missing_first_price_date_refuses() -> None:
    t = _tickers().copy()
    t["firstpricedate"] = t["firstpricedate"].astype(object)
    t.loc[0, "firstpricedate"] = pd.NaT
    with pytest.raises(AliasError):
        alias_table_from_tickers(t)
