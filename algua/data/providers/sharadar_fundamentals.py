"""Selected ARQ facts with an explicit assumed lag; no historical availability certification."""
from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from algua.data.fundamentals_schema import to_fundamentals_schema
from algua.data.providers.errors import ProviderError
from algua.data.providers.sharadar_client import SharadarClient, iso_date, validate_symbols


def fetch_fundamentals(
    client: SharadarClient, *, symbols: tuple[str, ...], start: str, end: str,
    metrics: tuple[str, ...], filing_lag_days: int = 3,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Window is half-open over assumed knowable_at; vendor query uses filing dates."""
    validate_symbols(symbols)
    first, last = iso_date(start), iso_date(end)
    now = datetime.now(UTC)
    if (first >= last or first > now.date() or type(filing_lag_days) is not int
            or not 3 <= filing_lag_days <= 31):
        raise ProviderError("Invalid Sharadar window or filing lag (minimum 3 calendar days)")
    identifiers = {"ticker", "date", "dimension", "reportperiod", "calendardate", "lastupdated",
                   "fiscalperiod", "symbol", "metric", "value", "knowable_at",
                   "fiscal_period_end", "source"}
    if (not metrics or any(
            not isinstance(m, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", m)
            or m in identifiers for m in metrics) or len(set(metrics)) != len(metrics)):
        raise ProviderError("Specify unique numeric Sharadar metric names")
    receipts: dict[str, Any] = {}
    frames = []
    lag = pd.Timedelta(days=filing_lag_days)
    for ticker in symbols:
        raw, meta = client.fetch("fundamentals", ticker,
            (first - timedelta(days=filing_lag_days)).isoformat(),
            min(last - timedelta(days=filing_lag_days + 1), now.date()).isoformat(),
            dimension="ARQ")
        try:
            required = {"ticker", "date", "dimension", "reportperiod", *metrics}
            if raw.empty or not raw.columns.is_unique or not required <= set(raw.columns):
                raise ValueError
            if not raw.ticker.eq(ticker).all() or not raw.dimension.eq("ARQ").all():
                raise ValueError
            if raw.duplicated(["ticker", "date", "dimension", "reportperiod"]).any():
                raise ValueError
            filings = raw["date"].map(iso_date)
            periods = raw["reportperiod"].map(iso_date)
            if (periods > filings).any():
                raise ValueError
            available = pd.to_datetime(filings, utc=True) + lag
            in_window = ((available >= pd.Timestamp(first, tz="UTC")) &
                         (available < pd.Timestamp(last, tz="UTC")))
            keep = in_window & (available <= now)
            raw = raw.loc[keep].copy()
            if raw.empty:
                raise ValueError
            raw["knowable_at"] = available.loc[keep]
            raw["fiscal_period_end"] = periods.loc[keep]
            raw["symbol"] = ticker
            for metric in metrics:
                if raw[metric].map(lambda v: isinstance(v, bool)).any():
                    raise ValueError
                raw[metric] = pd.to_numeric(raw[metric].replace("", None), errors="raise")
                if raw[metric].dropna().map(lambda v: not math.isfinite(v)).any():
                    raise ValueError
            facts = raw.melt(id_vars=["symbol", "fiscal_period_end", "knowable_at"],
                             value_vars=list(metrics), var_name="metric", value_name="value")
            facts["source"] = f"sharadar:ARQ:filing_date_plus_{filing_lag_days}_days_ASSUMED"
            frames.append(to_fundamentals_schema(facts))
            receipts[ticker] = {
                **meta, "deferred_filings": int((in_window & (available > now)).sum()),
                "missing_values": {m: int(raw[m].isna().sum()) for m in metrics},
            }
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ProviderError("Sharadar has missing or invalid ARQ facts/metrics") from None
    return to_fundamentals_schema(pd.concat(frames, ignore_index=True)), {
        "endpoint": "https://api.sharadar.com/v1.0/data/fundamentals",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "response_receipts": json.dumps(receipts, sort_keys=True),
        "dimension": "ARQ", "metrics": ",".join(metrics),
        "availability_policy": f"filing_date_plus_{filing_lag_days}_calendar_days_assumed",
        "pit_status": "unverified_vendor_history",
        "units": "vendor_native_units;no_currency_conversion;consult_metric_dictionary",
    }
