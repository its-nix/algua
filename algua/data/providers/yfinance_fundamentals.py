"""Current-vintage quarterly fundamentals; no historical availability reconstruction."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from algua.data.fundamentals_schema import to_fundamentals_schema
from algua.data.providers.errors import ProviderError
from algua.data.store.identity import normalize_symbols

METRICS = {"TotalRevenue": "revenue", "DilutedEPS": "eps_diluted", "NetIncome": "net_income"}
LIMITATIONS = (
    "historical_availability_unknown",
    "vendor_restatements_possible",
    "current_collection_only_no_historical_backfill",
    "limited_quarterly_income_statement_coverage",
    "currency_and_units_not_independently_verified",
)


@dataclass(frozen=True)
class CollectedFundamentals:
    frame: pd.DataFrame
    as_of: str
    source_metadata: dict[str, str]


def fetch_fundamentals(symbols: list[str]) -> CollectedFundamentals:
    """Fetch each requested issuer before returning any publishable data.

    Vendor period labels describe the figures, not their release dates. Every returned row is
    conservatively first knowable when this collection finishes; old statements are not backdated.
    """
    symbols = normalize_symbols(symbols)
    started = datetime.now(UTC).isoformat()
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ProviderError("yfinance is not installed") from exc
    rows = []
    try:
        for symbol in symbols:
            raw = yf.Ticker(symbol).get_income_stmt(freq="quarterly", pretty=False)
            if not isinstance(raw, pd.DataFrame) or raw.empty:
                raise ProviderError(f"yfinance returned no quarterly fundamentals for {symbol}")
            missing = sorted(set(METRICS) - set(raw.index))
            if missing:
                raise ProviderError(f"yfinance {symbol} missing required metrics: {missing}")
            for period in raw.columns:
                date = pd.Timestamp(period).date()
                for vendor_metric, metric in METRICS.items():
                    rows.append({"symbol": symbol, "fiscal_period_end": date, "metric": metric,
                                 "value": raw.loc[vendor_metric, period],
                                 "source": "yahoo_finance"})
        collected = datetime.now(UTC)
        frame = pd.DataFrame(rows)
        frame["knowable_at"] = collected
        frame = to_fundamentals_schema(frame)
        if any(period > collected.date() for period in frame["fiscal_period_end"]):
            raise ProviderError("yfinance returned a future fiscal period")
        for symbol in symbols:
            if frame.loc[frame["symbol"] == symbol, "value"].isna().all():
                raise ProviderError(f"yfinance returned no available metric values for {symbol}")
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - vendor failures must use the existing JSON error code
        raise ProviderError(f"yfinance fundamentals collection failed: {exc}") from exc
    as_of = collected.isoformat()
    return CollectedFundamentals(frame, as_of, {
        "library": "yfinance", "library_version": yf.__version__,
        "endpoint": "Ticker.get_income_stmt", "frequency": "quarterly",
        "requested_symbols": ",".join(symbols), "retrieval_started_at": started,
        "collection_completed_at": as_of, "knowable_at_method": "collection_completed_at",
        "historical_availability": "UNKNOWN", "metric_mapping": json.dumps(METRICS, sort_keys=True),
        "limitations": json.dumps(LIMITATIONS),
    })
