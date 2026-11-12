"""Synthetic Sharadar-shaped tables for tests.

Everything here is INVENTED (tickers `ZZ*`, permatickers >= 900000, made-up prices). The repository
is public and the Sharadar licence forbids redistribution: never paste real vendor rows here.

The sample holds one of each adversarial case the sample check requires:
- ZZSP (900001): active; 2:1 split ex 2020-01-06 and a 0.50 cash dividend ex 2020-01-08.
- ZZBK (900002): delisted; zero-recovery bankruptcy (`bankruptcyliquidation`).
- ZZAQ (900003): delisted; acquired by ZZSP for cash + stock (`acquisitionby`, contraticker ZZSP).
- ZZRU (900004): delisted (`delisted`); its ticker is later REUSED by
- ZZRU (900005): a new, active security with non-overlapping price dates.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from algua.data.corpactions import Dividend, Split, back_adjust

_SESSIONS = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08",
             "2020-01-09", "2020-01-10"]


def _ts(d: str) -> pd.Timestamp:
    return pd.Timestamp(d, tz="UTC")


def _rows(ticker: str, dates: list[str], unadj: list[float], split_div: float = 1.0,
          split_before: str | None = None, events: list | None = None) -> pd.DataFrame:
    ts = [_ts(d) for d in dates]
    # Sharadar `close` is split-adjusted to the latest split: rows before the split are divided.
    close = [u / split_div if split_before is not None and d < split_before else u
             for d, u in zip(dates, unadj, strict=True)]
    adj = back_adjust(pd.DataFrame({"ts": ts, "close": unadj}), events or [])["adj_close"]
    return pd.DataFrame({
        "ticker": ticker, "date": ts, "open": close, "high": close, "low": close, "close": close,
        "volume": 1000.0, "closeadj": list(adj), "closeunadj": unadj, "lastupdated": "2020-01-11",
    })


def sample_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(sep, actions, tickers) in the parsed form the `sharadar_tables` readers return."""
    sp_events = [Split(ex_date=_ts("2020-01-06"), ratio=2.0),
                 Dividend(ex_date=_ts("2020-01-08"), cash=0.5)]
    sep = pd.concat([
        _rows("ZZSP", _SESSIONS, [100.0, 102.0, 51.0, 52.0, 51.5, 52.0, 53.0], split_div=2.0,
              split_before="2020-01-06", events=sp_events),
        _rows("ZZBK", _SESSIONS[:4], [5.0, 4.0, 3.0, 2.0]),
        _rows("ZZAQ", _SESSIONS[:5], [10.0, 10.5, 11.0, 11.5, 12.0]),
        _rows("ZZRU", _SESSIONS[:2], [20.0, 21.0]),
        _rows("ZZRU", _SESSIONS[4:], [30.0, 31.0, 32.0]),
    ]).sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)
    sep["volume"] = sep["volume"].astype("float64")

    actions = pd.DataFrame([
        {"date": _ts("2020-01-06"), "action": "split", "ticker": "ZZSP", "name": "ZZ Split Co",
         "value": 2.0, "contraticker": None, "contraname": None},
        {"date": _ts("2020-01-08"), "action": "dividend", "ticker": "ZZSP", "name": "ZZ Split Co",
         "value": 0.5, "contraticker": None, "contraname": None},
        {"date": _ts("2020-01-08"), "action": "bankruptcyliquidation", "ticker": "ZZBK",
         "name": "ZZ Bankrupt Co", "value": float("nan"), "contraticker": None, "contraname": None},
        {"date": _ts("2020-01-09"), "action": "acquisitionby", "ticker": "ZZAQ",
         "name": "ZZ Acquired Co", "value": 12.5, "contraticker": "ZZSP",
         "contraname": "ZZ Split Co"},
        {"date": _ts("2020-01-06"), "action": "delisted", "ticker": "ZZRU", "name": "ZZ Old Co",
         "value": float("nan"), "contraticker": None, "contraname": None},
    ]).sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)

    def _t(perma: int, ticker: str, name: str, delisted: bool, first: str, last: str) -> dict:
        return {"table": "SEP", "permaticker": perma, "ticker": ticker, "name": name,
                "exchange": "NYSE", "isdelisted": delisted, "category": "Domestic Common Stock",
                "firstpricedate": _ts(first), "lastpricedate": _ts(last)}

    tickers = pd.DataFrame([
        _t(900001, "ZZSP", "ZZ Split Co", False, "2020-01-02", "2020-01-10"),
        _t(900002, "ZZBK", "ZZ Bankrupt Co", True, "2020-01-02", "2020-01-07"),
        _t(900003, "ZZAQ", "ZZ Acquired Co", True, "2020-01-02", "2020-01-08"),
        _t(900004, "ZZRU", "ZZ Old Co", True, "2020-01-02", "2020-01-03"),
        _t(900005, "ZZRU", "ZZ New Co", False, "2020-01-08", "2020-01-10"),
    ])
    tickers["permaticker"] = tickers["permaticker"].astype("int64")
    return sep, actions, tickers


def _iso(col: pd.Series) -> pd.Series:
    return col.map(lambda t: "" if pd.isna(t) else t.strftime("%Y-%m-%d"))


def write_tables(tmp_path: Path, sep: pd.DataFrame, actions: pd.DataFrame,
                 tickers: pd.DataFrame) -> dict[str, Path]:
    """Serialize parsed-form frames as vendor-style CSVs (dates YYYY-MM-DD, isdelisted Y/N)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    sep_out = sep.assign(date=_iso(sep["date"]))
    act_out = actions.assign(date=_iso(actions["date"]))
    tick_out = tickers.assign(
        isdelisted=tickers["isdelisted"].map({True: "Y", False: "N"}),
        firstpricedate=_iso(tickers["firstpricedate"]),
        lastpricedate=_iso(tickers["lastpricedate"]),
    )
    # A fundamentals-table row the reader must drop (TICKERS covers several Sharadar tables).
    sf1 = tick_out.iloc[[0]].assign(table="SF1")
    tick_out = pd.concat([tick_out, sf1], ignore_index=True)
    paths = {"sep": tmp_path / "SEP.csv", "actions": tmp_path / "ACTIONS.csv",
             "tickers": tmp_path / "TICKERS.csv"}
    sep_out.to_csv(paths["sep"], index=False)
    act_out.to_csv(paths["actions"], index=False)
    tick_out.to_csv(paths["tickers"], index=False)
    return paths


def write_csvs(tmp_path: Path) -> dict[str, Path]:
    """Write the clean `sample_tables()` as CSVs; keys "sep", "actions", "tickers"."""
    return write_tables(tmp_path, *sample_tables())
