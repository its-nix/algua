"""Synthetic characterization of what the TICKERS table can/cannot say about identity.

Preparation for the stable-identity slice (spec 2026-11-12 §4.15). Pins facts about EXISTING
`read_tickers` behaviour with invented rows only; it adds no production behaviour. See
DATA_WAVE3_REPORT.md for why dated aliases are not derivable from this table alone.
"""
import pandas as pd

from algua.data.importers.sharadar_tables import TICKERS_COLUMNS, read_tickers

# ZZRU was reused: permaticker 9001 traded to 2019-06-28, permaticker 9002 took the ticker later.
# 9003 renamed (ZZOLD -> ZZNEW) but TICKERS carries only the current name.
CAT = "Domestic Common Stock"
ROWS = [
    ("SEP", "9001", "ZZRU", "Synthetic One", "NYSE", "Y", CAT, "2010-01-04", "2019-06-28"),
    ("SEP", "9002", "ZZRU", "Synthetic Two", "NYSE", "N", CAT, "2020-02-03", "2026-11-13"),
    ("SEP", "9003", "ZZNEW", "Synthetic Three", "NYSE", "N", CAT, "2012-03-01", "2026-11-13"),
]


def _tickers(tmp_path):
    p = tmp_path / "tickers.csv"
    pd.DataFrame(ROWS, columns=list(TICKERS_COLUMNS)).to_csv(p, index=False)
    return read_tickers(p)


def test_reused_ticker_is_distinct_permatickers_with_disjoint_price_spans(tmp_path):
    t = _tickers(tmp_path)
    zzru = t[t["ticker"] == "ZZRU"].sort_values("firstpricedate")
    assert zzru["permaticker"].tolist() == [9001, 9002]
    assert zzru.iloc[0]["lastpricedate"] < zzru.iloc[1]["firstpricedate"]


def test_tickers_holds_one_current_ticker_per_permaticker(tmp_path):
    """No prior-name column: a rename (9003's ZZOLD) is invisible here, so historical aliases
    cannot be derived from this table; they need an explicit trusted dated source."""
    t = _tickers(tmp_path)
    assert t["permaticker"].is_unique
    assert "ZZOLD" not in set(t["ticker"])
    assert not {"previous_ticker", "relatedtickers"} & set(t.columns)
