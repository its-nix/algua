"""Daily US bars, downloaded once and served later from immutable local snapshots."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import requests

from algua.data.contracts import BarRequest, ProviderBars
from algua.data.providers.errors import ProviderError
from algua.data.schema import FLOAT_COLUMNS, to_bar_schema
from algua.primitives.retry import RetriesExhausted, call_with_backoff

_SYMBOL = re.compile(r"[A-Z][A-Z0-9-]{0,31}")
_RETRYABLE = {429, 500, 502, 503, 504}


def _date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("expected YYYY-MM-DD")
    return parsed


class EodhdBarProvider:
    name = "eodhd"

    def __init__(self, *, api_key: str) -> None:
        if not api_key.strip():
            raise ProviderError("eodhd requires ALGUA_EODHD_API_KEY (use demo for public samples)")
        self._api_key = api_key

    def get_bars(self, request: BarRequest) -> ProviderBars:
        try:
            start, end = _date(request.start), _date(request.end)
        except (ValueError, TypeError):
            raise ProviderError("eodhd daily dates must be YYYY-MM-DD") from None
        if start >= end:
            raise ProviderError("eodhd requires start < end (end is exclusive)")
        if request.timeframe != "1d" or request.adjustment not in {"none", "raw"}:
            raise ProviderError("eodhd supports only 1d bars with adjustment=none/raw")
        if not request.symbols or len(set(request.symbols)) != len(request.symbols):
            raise ProviderError("eodhd requires nonempty, unique US symbols")
        if any(not _SYMBOL.fullmatch(symbol) for symbol in request.symbols):
            raise ProviderError("eodhd expects bare US symbols, e.g. AAPL or BRK-B; no suffixes")

        retrieved = datetime.now(UTC)
        today = retrieved.date()
        if start >= today:
            raise ProviderError("eodhd requires a start before today's unfinished daily bar")
        wire_end = min(end - timedelta(days=1), today - timedelta(days=1)).isoformat()
        frames = []
        digests = {}
        for symbol in request.symbols:
            bars, bars_hash = self._fetch("eod", symbol, request.start, wire_end)
            if not bars:
                raise ProviderError(f"eodhd returned no bars for {symbol}")
            # Volume is adjusted to current share units, including splits AFTER the requested
            # window. Fetch through retrieval day, not backtest end, to recover raw share volume.
            splits, splits_hash = self._fetch("splits", symbol, request.start, today.isoformat())
            frames.append(_normalize(bars, splits, symbol, start, end, today))
            digests[symbol] = {"bars": bars_hash, "splits": splits_hash}

        frame = pd.concat(frames, ignore_index=True)
        return ProviderBars(frame=frame, source_metadata={
            "endpoint": "https://eodhd.com/api/eod",
            "retrieved_at": retrieved.isoformat(),
            "response_sha256": json.dumps(digests, sort_keys=True),
            "symbol_mapping": json.dumps({s: f"{s}.US" for s in request.symbols}, sort_keys=True),
            "price_vintages": "current_only_not_historical_pit",
            "volume": "raw_reconstructed_from_vendor_split_adjusted_volume",
            "splits_through": today.isoformat(),
            "coverage": "missing_sessions_are_not_filled_or_certified",
        })

    def _fetch(self, endpoint: str, symbol: str, start: str, end: str
               ) -> tuple[list[dict[str, Any]], str]:
        def send() -> requests.Response:
            return requests.get(
                f"https://eodhd.com/api/{endpoint}/{symbol}.US",
                params={"api_token": self._api_key, "from": start, "to": end,
                        "fmt": "json", "order": "a"},
                timeout=30, allow_redirects=False,
            )

        try:
            response = call_with_backoff(
                send, attempts=3, backoff_base=0.5,
                retryable_exceptions=(requests.RequestException,),
                retry_result=lambda r: r.status_code in _RETRYABLE,
            )
        except RetriesExhausted:
            # requests exceptions contain the URL, including the API token. Never echo them.
            raise ProviderError(f"eodhd {endpoint} transport failed for {symbol}") from None
        if response.status_code != 200:
            raise ProviderError(
                f"eodhd {endpoint} HTTP {response.status_code} for {symbol}; "
                "check subscription access or retry later"
            )
        try:
            payload = response.json()
        except ValueError:
            raise ProviderError(f"eodhd {endpoint} returned malformed JSON for {symbol}") from None
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise ProviderError(f"eodhd {endpoint} returned a non-row response for {symbol}")
        return payload, hashlib.sha256(response.content).hexdigest()


def _normalize(
    bars: list[dict[str, Any]], splits: list[dict[str, Any]], symbol: str,
    start: date, end: date, today: date,
) -> pd.DataFrame:
    try:
        frame = pd.DataFrame(bars).rename(columns={"date": "ts", "adjusted_close": "adj_close"})
        if frame.empty:
            raise ValueError("no bars for requested symbol")
        # Strict dates prevent silently interpreting an intraday timestamp as a session date.
        days = frame["ts"].map(_date)
        if days.duplicated().any():
            raise ValueError("duplicate daily bars")
        frame["ts"] = pd.to_datetime(days, utc=True)
        frame = frame[(days >= start) & (days < end) & (days < today)].copy()
        if frame.empty:
            raise ValueError("no bars in requested window")
        frame["symbol"] = symbol
        for column in FLOAT_COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
            if not frame[column].map(math.isfinite).all():
                raise ValueError("nonfinite price/volume")
        if (frame["volume"] < 0).any() or (frame[FLOAT_COLUMNS[:-1]] <= 0).any().any():
            raise ValueError("nonpositive price or negative volume")
        if ((frame["low"] > frame[["open", "close"]].min(axis=1)) |
            (frame["high"] < frame[["open", "close"]].max(axis=1))).any():
            raise ValueError("invalid OHLC range")

        seen = set()
        for event in splits:
            day = _date(event["date"])
            if day in seen or not start <= day <= today:
                raise ValueError("duplicate or out-of-range split")
            seen.add(day)
            if not isinstance(event["split"], str):
                raise ValueError("invalid split ratio")
            numerator, denominator = map(float, event["split"].split("/"))
            if not all(math.isfinite(v) and v > 0 for v in (numerator, denominator)):
                raise ValueError("invalid split ratio")
            ratio = numerator / denominator
            if not math.isfinite(ratio) or ratio <= 0:
                raise ValueError("invalid split ratio")
            frame.loc[frame["ts"] < pd.Timestamp(day, tz="UTC"), "volume"] /= ratio
        if not frame["volume"].map(math.isfinite).all():
            raise ValueError("nonfinite reconstructed volume")
        return to_bar_schema(frame, timeframe="1d").reset_index().rename(
            columns={"timestamp": "ts"})
    except (ValueError, TypeError, KeyError, OverflowError, ZeroDivisionError):
        raise ProviderError(f"eodhd invalid or missing bars/splits for {symbol}") from None
