"""Current Yahoo Finance RSS headlines; collection time is the knowledge floor."""
from __future__ import annotations

import hashlib
import json
import signal
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import pandas as pd

from algua.data.news_schema import explode_news_symbols, to_news_schema
from algua.data.providers.errors import ProviderError
from algua.data.store.identity import normalize_symbols

URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
MAX_BYTES = 2 * 1024**2
LIMITATIONS = (
    "historical_availability_unknown",
    "current_feed_not_exhaustive_history",
    "aggregator_publication_times_not_independently_verified",
    "feed_ticker_association_not_verified_mentions",
    "headlines_only_no_fulltext_or_sentiment",
)


@dataclass(frozen=True)
class CollectedNews:
    frame: pd.DataFrame
    as_of: str
    source_metadata: dict[str, str]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _timeout(_signum, _frame):
    raise ProviderError("Yahoo Finance RSS exceeded the 10-second feed deadline")


def _download(symbol: str) -> bytes:
    request = urllib.request.Request(URL + "?" + urlencode({
        "s": symbol, "region": "US", "lang": "en-US",
    }), headers={"User-Agent": "Algua/0.1 current-news research"})
    opener = urllib.request.build_opener(_NoRedirect)
    started = time.monotonic()
    previous = signal.signal(signal.SIGALRM, _timeout)
    timer = signal.setitimer(signal.ITIMER_REAL, 10)
    try:
        with opener.open(request, timeout=10) as response:
            if response.status != 200:
                raise ProviderError("Yahoo Finance RSS returned a non-200 response")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ProviderError("Yahoo Finance RSS exceeded the 2 MiB feed limit")
            return body
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        remaining = max(0.000001, timer[0] - (time.monotonic() - started)) if timer[0] else 0
        signal.setitimer(signal.ITIMER_REAL, remaining, timer[1])


def _articles(body: bytes) -> list[dict]:
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ProviderError("Yahoo Finance RSS must not contain document/entity declarations")
    root = ET.fromstring(body)
    channels = root.findall("channel")
    if root.tag != "rss" or root.get("version") != "2.0" or len(channels) != 1:
        raise ProviderError("Yahoo Finance RSS has an unsupported feed shape")
    items = channels[0].findall("item")
    if not items:
        raise ProviderError("Yahoo Finance RSS returned no news")
    articles, seen = [], set()
    for item in items:
        fields = {key: (item.findtext(key) or "").strip()
                  for key in ("guid", "title", "link", "pubDate")}
        if not all(fields.values()) or fields["guid"] in seen:
            raise ProviderError("Yahoo Finance RSS has missing fields or duplicate article IDs")
        published = parsedate_to_datetime(fields["pubDate"])
        if published.tzinfo is None:
            raise ProviderError("Yahoo Finance RSS publication time must include a timezone")
        seen.add(fields["guid"])
        articles.append({"source": "yahoo_finance_rss", "article_id": fields["guid"],
                         "headline": fields["title"], "url": fields["link"], "body": None,
                         "published_at": published.astimezone(UTC)})
    return articles


def fetch_news(symbols: list[str]) -> CollectedNews:
    """CLI-main-thread collection; persist nothing unless every requested feed validates."""
    symbols = normalize_symbols(symbols)
    started = datetime.now(UTC).isoformat()
    articles: dict[str, dict] = {}
    hashes = {}
    try:
        for symbol in symbols:
            body = _download(symbol)
            hashes[symbol] = hashlib.sha256(body).hexdigest()
            for article in _articles(body):
                identity = article["article_id"]
                if identity in articles:
                    prior = {key: value for key, value in articles[identity].items()
                             if key != "symbols"}
                    if prior != article:
                        raise ProviderError("Yahoo Finance RSS article conflicts across feeds")
                    articles[identity]["symbols"].append(symbol)
                else:
                    articles[identity] = {**article, "symbols": [symbol]}
        collected = datetime.now(UTC)
        frame = pd.DataFrame(articles.values())
        frame["knowable_at"] = collected
        to_news_schema(explode_news_symbols(frame))
        if any(stamp > collected for stamp in frame["published_at"]):
            raise ProviderError("Yahoo Finance RSS returned a future publication time")
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 - network/XML faults use the existing JSON provider code
        raise ProviderError(f"Yahoo Finance RSS collection failed: {exc}") from exc
    as_of = collected.isoformat()
    return CollectedNews(frame, as_of, {
        "endpoint": URL, "region": "US", "language": "en-US",
        "requested_symbols": ",".join(symbols), "retrieval_started_at": started,
        "collection_completed_at": as_of, "knowable_at_method": "collection_completed_at",
        "historical_availability": "UNKNOWN", "feed_sha256": json.dumps(hashes, sort_keys=True),
        "symbol_association": "requested_feed_ticker_only", "content_scope": "headline_link_only",
        "limitations": json.dumps(LIMITATIONS),
    })
