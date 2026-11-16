"""Direct Sharadar research ingestion. Availability assumptions never certify PIT evidence."""
from __future__ import annotations

from pathlib import Path

import typer

import algua
from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.data.providers.sharadar_client import SharadarClient
from algua.data.providers.sharadar_fundamentals import fetch_fundamentals
from algua.data.sharadar_identity import compile_identity_artifact, write_private_new
from algua.data.store import DataStore, normalize_symbols
from algua.primitives.timeparse import now_iso

sharadar_app = typer.Typer(help="Sharadar research inputs (unverified vendor history)")


@sharadar_app.command("ingest-fundamentals")
@json_errors
def ingest_fundamentals(
    symbols: str = typer.Option(..., "--symbols", help="comma-separated exact Sharadar tickers"),
    start: str = typer.Option(..., "--start", help="inclusive assumed availability date"),
    end: str = typer.Option(..., "--end", help="exclusive assumed availability date"),
    metric: list[str] = typer.Option(..., "--metric", help="numeric field; repeat for each metric"),
    filing_lag_days: int = typer.Option(3, "--filing-lag-days", min=3, max=31,
        help="ASSUMED calendar-day lag after filing date; not a vendor availability timestamp"),
) -> None:
    """Fetch selected as-reported quarterly facts and freeze a typed fundamentals snapshot."""
    settings = get_settings()
    if not settings.sharadar_api_key:
        raise ValueError("Sharadar requires ALGUA_SHARADAR_API_KEY")
    wanted = tuple(normalize_symbols(symbols.split(",")))
    frame, metadata = fetch_fundamentals(SharadarClient(api_key=settings.sharadar_api_key),
        symbols=wanted, start=start, end=end, metrics=tuple(metric),
        filing_lag_days=filing_lag_days)
    rec = DataStore(settings.data_dir).ingest_fundamentals(
        provider="sharadar", symbols=list(wanted), as_of=now_iso(),
        source="sharadar:ARQ:assumed_availability_not_verified_pit", frame=frame,
        source_metadata=metadata,
    )
    emit(ok({"snapshot": rec.to_dict()}))


@sharadar_app.command("compile-identities")
@json_errors
def compile_identities(
    tickers: Path = typer.Option(..., "--tickers", help="local TICKERS CSV export"),
    actions: Path = typer.Option(..., "--actions", help="local ACTIONS CSV export"),
    out: Path = typer.Option(..., "--out", help="NEW private artifact path outside the repo"),
) -> None:
    """Compile private stable identities + explicit ticker-change events (unqualified input).

    Offline: no network, key, DB or feed change. The artifact (0600) holds the detail; stdout
    carries only counts, hashes and the path. Coverage/completeness stay unverified.
    """
    art = compile_identity_artifact(tickers, actions)
    root = Path(algua.__file__).resolve().parents[1]
    path = write_private_new(out, art.body, repo_root=root)
    emit(ok({"schema": "algua.sharadar.identity_events.v1", "coverage": "unverified",
             "identity_count": art.identity_count, "event_count": art.event_count,
             "tickers_sha256": art.tickers_sha256, "actions_sha256": art.actions_sha256,
             "artifact_sha256": art.artifact_sha256, "artifact_path": str(path)}))
