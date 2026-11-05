"""Small current-vintage acquisition commands, composed under `data` in main."""
from __future__ import annotations

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.data.providers.yahoo_news import fetch_news
from algua.data.providers.yfinance_fundamentals import fetch_fundamentals
from algua.data.store import DataStore, normalize_symbols

context_data_app = typer.Typer()


@context_data_app.command("fetch-fundamentals")
@json_errors
def fetch_fundamentals_cmd(
    symbols: str = typer.Option(..., "--symbols", help="comma-separated issuer symbols"),
) -> None:
    """Collect current yfinance quarterly statements; all rows become knowable only now.

    Persists revenue, diluted EPS and net income in the existing immutable fundamentals store.
    There is no historical --as-of override or inferred filing timestamp.
    """
    requested = normalize_symbols(symbols.split(","))
    collected = fetch_fundamentals(requested)
    rec = DataStore(get_settings().data_dir).ingest_fundamentals(
        provider="yfinance", symbols=requested, as_of=collected.as_of, source="yahoo_finance",
        frame=collected.frame, source_metadata=collected.source_metadata,
    )
    emit(ok({"snapshot": rec.to_dict()}))


@context_data_app.command("fetch-news")
@json_errors
def fetch_news_cmd(
    symbols: str = typer.Option(..., "--symbols", help="comma-separated Yahoo feed tickers"),
) -> None:
    """Collect current Yahoo RSS headlines, with collection-time availability only.

    No historical --as-of override, sentiment inference or full-article scraping is performed.
    """
    collected = fetch_news(normalize_symbols(symbols.split(",")))
    rec = DataStore(get_settings().data_dir).ingest_news(
        provider="yahoo_finance_rss", as_of=collected.as_of,
        frame=collected.frame, source_metadata=collected.source_metadata,
    )
    emit(ok({"snapshot": rec.to_dict()}))
