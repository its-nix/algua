"""`research steering` — the Drive Steering/Inspirations snapshot and the one-time migration
(spec 2026-11-12 §4, §6.7). Driver-facing: drivers export at run start; an operator migrates once.
"""
from __future__ import annotations

from pathlib import Path

import typer

from algua.cli._common import ok
from algua.cli._drive import drive_session
from algua.cli.app import emit
from algua.knowledge.drive.snapshot import export_snapshot, migrate_files
from algua.research.categories import CATEGORIES_REL, categories_file_default

steering_app = typer.Typer(
    help="Drive steering: export a run-start snapshot; migrate the steering files into Drive.",
    no_args_is_help=True,
)


@steering_app.command("export")
def export(to: Path = typer.Option(..., "--to", help="snapshot directory to (re)create")) -> None:
    """Export Categories, Sources and Inspirations from Drive into files (all or nothing)."""
    with drive_session() as (_settings, client):
        counts = export_snapshot(client, to)
    emit(ok({"dir": str(to), **counts}))


@steering_app.command("migrate")
def migrate(
    categories_file: Path = typer.Option(
        None, "--categories-file", help=f"default: {CATEGORIES_REL} at the repo root"),
    from_kb: Path = typer.Option(
        None, "--from-kb", help="inspirations dir; default: <knowledge_dir>/inspirations"),
) -> None:
    """Copy categories, the sources registry and vault notes into Drive. Safe to re-run."""
    with drive_session() as (settings, client):
        cats = categories_file or categories_file_default()
        notes = from_kb or settings.knowledge_dir / "inspirations"
        result = migrate_files(client, categories_file=cats, inspirations_dir=notes)
    emit(ok(result))
