"""Readers for three Sharadar (Nasdaq Data Link) table exports: SEP prices, ACTIONS, TICKERS.

Pure parsing and validation of local CSV exports into typed frames; no network, no store writes.
Column names follow the vendor's published table documentation and are confirmed on the first real
download: a missing column fails closed with `SharadarSchemaError` naming it. Extra columns are
dropped. Used by the PIT sample check (`algua.data.sharadar_check`); the bar importer built on top
of these readers comes later (see docs/superpowers/plans/2026-11-12-pit-data-pipeline.md).
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

SEP_COLUMNS = ("ticker", "date", "open", "high", "low", "close", "volume", "closeadj",
               "closeunadj", "lastupdated")
ACTIONS_COLUMNS = ("date", "action", "ticker", "name", "value", "contraticker", "contraname")
TICKERS_COLUMNS = ("table", "permaticker", "ticker", "name", "exchange", "isdelisted", "category",
                   "firstpricedate", "lastpricedate")

_SEP_NUMERIC = ("open", "high", "low", "close", "volume", "closeadj", "closeunadj")


class SharadarSchemaError(ValueError):
    """A Sharadar export does not have the expected shape or values."""


def _load(path: Path, columns: Iterable[str], label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    cols = list(columns)
    missing = [c for c in cols if c not in frame.columns]
    if missing:
        raise SharadarSchemaError(f"{label} export {path.name} is missing columns {missing}")
    return frame[cols].copy()


def _dates(col: pd.Series, name: str, *, allow_missing: bool = False) -> pd.Series:
    stripped = col.str.strip()
    if not allow_missing and (stripped == "").any():
        raise SharadarSchemaError(f"column {name!r} has empty dates")
    try:
        parsed = pd.to_datetime(stripped.replace("", None), format="%Y-%m-%d", utc=True)
    except (ValueError, TypeError):
        # No cell text in the message: errors reach stdout, and cells are licensed vendor data.
        raise SharadarSchemaError(f"column {name!r} has a non YYYY-MM-DD date") from None
    return parsed


def _numbers(col: pd.Series, name: str, *, allow_missing: bool = False) -> pd.Series:
    stripped = col.str.strip()
    if not allow_missing and (stripped == "").any():
        raise SharadarSchemaError(f"column {name!r} has empty values")
    try:
        return pd.to_numeric(stripped.replace("", None), errors="raise").astype("float64")
    except (ValueError, TypeError):
        raise SharadarSchemaError(f"column {name!r} has a non-numeric value") from None


def _upper(col: pd.Series) -> pd.Series:
    return col.str.strip().str.upper()


def _optional_text(col: pd.Series, *, upper: bool = False) -> pd.Series:
    stripped = col.str.strip()
    if upper:
        stripped = stripped.str.upper()
    return pd.Series([None if v == "" else v for v in stripped], index=col.index, dtype=object)


def read_sep(path: Path) -> pd.DataFrame:
    """SEP daily prices: UTC-midnight `date`, upper-cased `ticker`, float prices, sorted."""
    frame = _load(path, SEP_COLUMNS, "SEP")
    frame["ticker"] = _upper(frame["ticker"])
    frame["date"] = _dates(frame["date"], "date")
    for name in _SEP_NUMERIC:
        frame[name] = _numbers(frame[name], name)
    if bool(frame.duplicated(subset=["ticker", "date"]).any()):
        raise SharadarSchemaError("SEP export has duplicate (ticker, date) rows")
    return frame.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)


def read_actions(path: Path) -> pd.DataFrame:
    """ACTIONS: UTC `date`, lower-cased `action`, float `value` (NaN allowed), optional contra."""
    frame = _load(path, ACTIONS_COLUMNS, "ACTIONS")
    frame["date"] = _dates(frame["date"], "date")
    frame["action"] = frame["action"].str.strip().str.lower()
    frame["ticker"] = _upper(frame["ticker"])
    frame["value"] = _numbers(frame["value"], "value", allow_missing=True)
    frame["contraticker"] = _optional_text(frame["contraticker"], upper=True)
    frame["contraname"] = _optional_text(frame["contraname"])
    return frame.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)


def read_tickers(path: Path) -> pd.DataFrame:
    """TICKERS rows for the SEP table: int `permaticker`, bool `isdelisted`, UTC price dates."""
    frame = _load(path, TICKERS_COLUMNS, "TICKERS")
    frame = frame[frame["table"].str.strip() == "SEP"].reset_index(drop=True)
    try:
        frame["permaticker"] = frame["permaticker"].str.strip().astype("int64")
    except ValueError:
        raise SharadarSchemaError("column 'permaticker' has a non-integer value") from None
    flags = frame["isdelisted"].str.strip().str.upper()
    if not flags.isin(["Y", "N"]).all():
        raise SharadarSchemaError("column 'isdelisted' must be Y or N")
    frame["isdelisted"] = flags == "Y"
    frame["ticker"] = _upper(frame["ticker"])
    for name in ("firstpricedate", "lastpricedate"):
        frame[name] = _dates(frame[name], name, allow_missing=True)
    if bool(frame["permaticker"].duplicated().any()):
        raise SharadarSchemaError("TICKERS export has duplicate SEP permatickers")
    return frame
