"""Direct Sharadar research ingestion. Availability assumptions never certify PIT evidence."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

import algua
from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.data.providers.sharadar_client import SharadarClient
from algua.data.providers.sharadar_fundamentals import fetch_fundamentals
from algua.data.sharadar_bars_prep import prepare_bars
from algua.data.sharadar_identity import compile_identity_artifact, write_private_new
from algua.data.sharadar_metadata import (
    SCHEMA as METADATA_SCHEMA,
)
from algua.data.sharadar_metadata import (
    prepare_metadata,
    publish_metadata,
)
from algua.data.sharadar_universe import compute_universe_preview
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


@sharadar_app.command("prepare-metadata")
@json_errors
def prepare_metadata_cmd(
    tickers: Path = typer.Option(..., "--tickers", help="local TICKERS CSV export"),
    out: Path = typer.Option(..., "--out",
                             help="NEW private artifact path outside every checkout"),
) -> None:
    """Preserve every TICKERS row as unqualified metadata (no join, no PIT certification).

    Offline: no network, key, DB, store or feed change. The artifact (0600) holds the rows;
    stdout carries only schema, status, row count, hashes and the path.
    """
    root = Path(algua.__file__).resolve().parents[1]
    art = prepare_metadata(tickers)
    path = publish_metadata(out, art.body, repo_root=root)
    emit(ok({"schema": METADATA_SCHEMA, "status": "unqualified", "row_count": art.row_count,
             "tickers_sha256": art.tickers_sha256, "artifact_sha256": art.artifact_sha256,
             "artifact_path": str(path)}))


@sharadar_app.command("prepare-bars")
@json_errors
def prepare_bars_cmd(
    sep: Path = typer.Option(..., "--sep", help="local SEP CSV export"),
    tickers: Path = typer.Option(..., "--tickers", help="TICKERS CSV used for the identities"),
    actions: Path = typer.Option(..., "--actions", help="ACTIONS CSV used for the identities"),
    identities: Path = typer.Option(..., "--identities", help="compile-identities artifact"),
    as_of: str = typer.Option(..., "--as-of", help="operator-declared as-of ISO datetime"),
) -> None:
    """Freeze an UNQUALIFIED stable-identity raw bars snapshot (stage 1)."""
    prepared = prepare_bars(sep, tickers, actions, identities, as_of=as_of,
                            store=DataStore(get_settings().data_dir))
    emit(ok({"schema": "algua.sharadar.prepared_bars.v1", "status": "unqualified",
             "snapshot_id": prepared.snapshot_id, "content_hash": prepared.content_hash,
             "identity_count_mapped": prepared.identity_count_mapped,
             "sep_rows": prepared.sep_rows, "sep_sha256": prepared.sep_sha256,
             "tickers_sha256": prepared.tickers_sha256, "actions_sha256": prepared.actions_sha256,
             "identity_artifact_sha256": prepared.identity_artifact_sha256}))


@sharadar_app.command("compute-universe")
@json_errors
def compute_universe_cmd(
    bars_snapshot: str = typer.Option(..., "--bars-snapshot", help="stage-1 snapshot id"),
    identities: Path = typer.Option(..., "--identities", help="compile-identities artifact"),
    rules: Path = typer.Option(..., "--rules", help="frozen us-liquid-common-v1.json"),
    evidence: Path = typer.Option(..., "--evidence", help="dated eligibility/coverage evidence"),
    start: str = typer.Option(..., "--start", help="first XNYS session label YYYY-MM-DD"),
    end: str = typer.Option(..., "--end", help="exclusive end YYYY-MM-DD"),
    out: Path = typer.Option(..., "--out", help="NEW private preview path outside the repo"),
) -> None:
    """PRIVATE PREVIEW of the frozen daily universe (stage 2). Unknown inputs refuse the date;
    the export is unqualified, not imported, never verified_pit."""
    root = Path(algua.__file__).resolve().parents[1]
    preview = compute_universe_preview(
        store=DataStore(get_settings().data_dir), snapshot_id=bars_snapshot,
        identities=identities, rules=rules, evidence=evidence, start=date.fromisoformat(start),
        end=date.fromisoformat(end), out=out, repo_root=root)
    emit(ok({"schema": "algua.sharadar.universe_preview.v1",
             "status": "private_preview_unqualified",
             "verified_pit": False, "computed_dates": preview.computed_dates,
             "refused_dates": preview.refused_dates, "interval_count": preview.interval_count,
             "artifact_sha256": preview.artifact_sha256, "artifact_path": str(preview.path),
             **preview.hashes}))
