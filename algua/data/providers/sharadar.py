"""Normalize direct Sharadar daily stock history into the frozen raw bar contract."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import pandas as pd

from algua.data.contracts import BarRequest, ProviderBars
from algua.data.importers.sharadar_tables import SEP_COLUMNS
from algua.data.providers.errors import ProviderError
from algua.data.providers.sharadar_client import SharadarClient, iso_date, validate_symbols
from algua.data.schema import FLOAT_COLUMNS, to_bar_schema
from algua.data.sharadar_price_checks import check_raw_units


class SharadarBarProvider:
    name = "sharadar"

    def __init__(self, *, api_key: str):
        self.client = SharadarClient(api_key=api_key)

    def get_bars(self, request: BarRequest) -> ProviderBars:
        if request.timeframe != "1d" or request.adjustment not in {"none", "raw"}:
            raise ProviderError("Sharadar supports only 1d with adjustment=none/raw")
        start, end = iso_date(request.start), iso_date(request.end)
        today = datetime.now(UTC).date()
        if start >= min(end, today):
            raise ProviderError("Sharadar requires a nonempty, closed-bar date window")
        validate_symbols(request.symbols)
        frames = []
        receipts = {}
        for ticker in request.symbols:
            raw, meta = self.client.fetch("stocks", ticker, start.isoformat(),
                                         (min(end, today) - timedelta(days=1)).isoformat())
            normalized = normalize_prices(raw, ticker, start.isoformat(),
                                          min(end, today).isoformat())
            actions, action_meta = self.client.fetch("actions", ticker, start.isoformat(),
                                                     today.isoformat())
            check_actions(raw, actions, ticker)
            frames.append(normalized)
            meta["actions"] = action_meta
            receipts[ticker] = meta
        return ProviderBars(frame=pd.concat(frames, ignore_index=True), source_metadata={
            "endpoint": "https://api.sharadar.com/v1.0/data/stocks",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "response_receipts": json.dumps(receipts, sort_keys=True),
            "pit_status": "unverified_vendor_history",
            "adjustments": "raw_OHLCV_reconstructed;closeadj_includes_dividends_and_spinoffs",
            "coverage": "missing_sessions_not_filled_or_certified",
            "security_identity": "exact_vendor_ticker;historical_identity_not_verified",
            "actions": "raw_split_units_checked;spinoffs_refused;coverage_not_certified",
        })


def check_actions(prices: pd.DataFrame, actions: pd.DataFrame, ticker: str) -> None:
    try:
        if not {"ticker", "date", "action", "value"} <= set(actions.columns):
            raise ValueError
        if not actions["ticker"].eq(ticker).all():
            raise ValueError
        actions = actions.copy()
        actions["action"] = actions["action"].astype(str).str.lower()
        if actions["action"].str.contains("spinoff").any():
            raise ProviderError("Sharadar spinoff history requires reviewed adjustment mapping")
        actions["date"] = pd.to_datetime(actions["date"].map(iso_date), utc=True)
        actions["value"] = pd.to_numeric(actions["value"].replace("", None), errors="raise")
        prices = prices.copy()
        prices["date"] = pd.to_datetime(prices["date"].map(iso_date), utc=True)
        for name in ("close", "closeunadj"):
            prices[name] = pd.to_numeric(prices[name], errors="raise")
        if check_raw_units(prices, actions).status != "pass":
            raise ProviderError("Sharadar prices and split actions do not reconcile")
    except (ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, ProviderError):
            raise
        raise ProviderError("Sharadar has invalid corporate actions") from None


def normalize_prices(raw: pd.DataFrame, ticker: str, start: str, end: str) -> pd.DataFrame:
    try:
        if raw.empty or not set(SEP_COLUMNS) <= set(raw.columns):
            raise ValueError
        if not raw["ticker"].eq(ticker).all():
            raise ValueError
        dates = raw["date"].map(iso_date)
        if dates.duplicated().any():
            raise ValueError
        frame = raw[(dates >= iso_date(start)) & (dates < iso_date(end))].copy()
        if frame.empty:
            raise ValueError
        for column in ("open", "high", "low", "close", "closeunadj", "closeadj", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
            if not frame[column].map(math.isfinite).all():
                raise ValueError
        if ((frame[["open", "high", "low", "close", "closeunadj", "closeadj"]] <= 0)
                .any().any() or (frame["volume"] < 0).any()):
            raise ValueError
        factor = frame["closeunadj"] / frame["close"]
        out = pd.DataFrame({"ts": pd.to_datetime(frame["date"], utc=True),
                            "symbol": ticker, "close": frame["closeunadj"],
                            "adj_close": frame["closeadj"], "volume": frame["volume"] / factor})
        for column in ("open", "high", "low"):
            out[column] = frame[column] * factor
        if not out[FLOAT_COLUMNS].map(math.isfinite).all().all():
            raise ValueError
        if ((out.low > out[["open", "close"]].min(axis=1)) |
                (out.high < out[["open", "close"]].max(axis=1))).any():
            raise ValueError
        return to_bar_schema(out, timeframe="1d").reset_index().rename(columns={"timestamp": "ts"})
    except (ValueError, TypeError, KeyError, OverflowError):
        raise ProviderError("Sharadar has missing or invalid price rows") from None
