"""Bounded direct Sharadar API downloads. No Nasdaq SDK or implicit sample credentials."""
from __future__ import annotations

import hashlib
import io
import re
import time
from datetime import date
from typing import Any

import pandas as pd
import requests

from algua.data.providers.errors import ProviderError
from algua.primitives.retry import RetriesExhausted, call_with_backoff


def iso_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        raise ProviderError("Sharadar dates must be YYYY-MM-DD") from None


def validate_symbols(symbols: tuple[str, ...]) -> None:
    if (not symbols or len(set(symbols)) != len(symbols)
            or any(not re.fullmatch(r"[A-Z][A-Z0-9.:-]{0,31}", s) for s in symbols)):
        raise ProviderError("Sharadar requires unique, nonempty exact vendor tickers")


class SharadarClient:
    def __init__(self, *, api_key: str, page_size: int = 1000, max_pages: int = 50):
        if not api_key.strip():
            raise ProviderError("Sharadar requires ALGUA_SHARADAR_API_KEY")
        if not 1 <= page_size <= 10000 or not 1 <= max_pages <= 100:
            raise ProviderError("Invalid Sharadar pagination bounds")
        self._key = api_key
        self.page_size = page_size
        self.max_pages = max_pages

    def fetch(self, table: str, ticker: str, start: str, end: str, *,
              dimension: str | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Fetch one ticker in an inclusive vendor date window, following every CSV page."""
        if table not in {"stocks", "fundamentals", "actions"}:
            raise ProviderError("Unsupported Sharadar table")
        validate_symbols((ticker,))
        if iso_date(start) > iso_date(end):
            raise ProviderError("Invalid Sharadar date window")
        pages = []
        hashes = []
        for page_no in range(self.max_pages):
            params: dict[str, Any] = {
                "api_key": self._key, "ticker": ticker, "from": start, "to": end,
                "format": "csv", "limit": self.page_size, "skip": page_no * self.page_size,
                "sort": "date.asc",
            }
            if dimension is not None:
                params["dimension"] = dimension
            payload = self._request(table, params)
            digest = hashlib.sha256(payload).hexdigest()
            try:
                frame = pd.read_csv(io.BytesIO(payload), keep_default_na=False,
                                    dtype={"ticker": str, "date": str, "reportperiod": str})
            except (ValueError, pd.errors.ParserError):
                raise ProviderError("Sharadar returned invalid CSV") from None
            if not {"ticker", "date"} <= set(frame.columns):
                raise ProviderError("Sharadar response lacks ticker/date columns")
            if len(frame) > self.page_size:
                raise ProviderError("Sharadar page exceeded requested row limit")
            if len(frame) and digest in hashes:
                raise ProviderError("Sharadar repeated a page; refusing truncated history")
            hashes.append(digest)
            pages.append(frame)
            if len(frame) < self.page_size:
                return pd.concat(pages, ignore_index=True), {"page_sha256": hashes}
        raise ProviderError("Sharadar page bound reached; refusing partial history")

    def _request(self, table: str, params: dict[str, Any]) -> bytes:
        def send() -> tuple[int, bytes]:
            started = time.monotonic()
            with requests.get(f"https://api.sharadar.com/v1.0/data/{table}", params=params,
                              timeout=30, allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    return response.status_code, b""
                payload = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if time.monotonic() - started > 60:
                        raise ProviderError("Sharadar response exceeded streaming deadline")
                    if len(payload) + len(chunk) > 8 * 1024 * 1024:
                        raise ProviderError("Sharadar page exceeds response-size bound")
                    payload.extend(chunk)
                return response.status_code, bytes(payload)
        try:
            status, payload = call_with_backoff(
                send, attempts=3, backoff_base=0.5,
                retryable_exceptions=(requests.RequestException,),
                retry_result=lambda r: r[0] in {429, 500, 502, 503, 504},
            )
        except RetriesExhausted:
            # requests exceptions include credential-bearing URLs. Never print their text.
            raise ProviderError("Sharadar transport failed after bounded retries") from None
        if status != 200:
            raise ProviderError(f"Sharadar HTTP {status}; check plan access")
        return payload
