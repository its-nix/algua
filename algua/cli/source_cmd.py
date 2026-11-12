"""Trusted source-selection adapters plus advisory pre-authoring recipe checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.operator.research_memory_checkpoint import strict_json
from algua.operator.research_profile import load_research_profile
from algua.operator.source_recipe import assess_recipe
from algua.operator.source_selection import record_source_pass, review_sources, source_plan
from algua.registry.ideas import IdeaRepository
from algua.registry.read_snapshot import registry_snapshot
from algua.tracking.bounded_local_read import read_local_file

source_app = typer.Typer()


def _read(path: Path) -> Any:
    return strict_json(read_local_file(path, root=path.absolute().parent, max_bytes=256 * 1024))


@source_app.command("plan")
@json_errors
def plan(
    code: str = typer.Option(...), limit: int = typer.Option(3, min=1, max=3), force: bool = False
) -> None:
    settings = get_settings()
    profile = load_research_profile(settings.data_dir)
    if profile is None:
        raise ValueError("source_selection:configured_profile_required")
    emit(ok(source_plan(settings, profile, code=code, limit=limit, force=force)))


@source_app.command("preflight")
@json_errors
def preflight(recipe: Path = typer.Option(...), profile: Path = typer.Option(...)) -> None:
    """Plan only: no authored import, simulation, registration or qualification."""
    emit(ok(assess_recipe(_read(recipe), _read(profile))))


@source_app.command("review")
@json_errors
def review(
    plan: Path = typer.Option(...),
    reviews: Path = typer.Option(...),
    scratch_db: Path = typer.Option(...),
    seeded_max_id: int = typer.Option(..., min=0),
) -> None:
    captured = _read(plan)
    with registry_snapshot(scratch_db, label="source selection scratch") as snapshot:
        repo = IdeaRepository(snapshot.connection)
        ideas = [
            SimpleNamespace(
                inspirations=repo.inspirations_of(i.id),
                market=i.market,
                horizon=i.horizon,
                required_data=i.required_data,
            )
            for i in repo.list()
            if i.id > seeded_max_id
        ]
    emit(ok(review_sources(captured, _read(reviews), new_ideas=ideas)))


@source_app.command("record")
@json_errors
def record(
    result: Path = typer.Option(...),
    import_result: Path = typer.Option(...),
    worker_exit: int = typer.Option(...),
    import_exit: int = typer.Option(...),
) -> None:
    settings = get_settings()
    payload = _read(result)
    try:
        imported = _read(import_result)
    except (ValueError, OSError):
        imported = None
    clean = (
        worker_exit == import_exit == 0
        and isinstance(imported, dict)
        and imported.get("ok") is True
        and imported.get("critic_errors", 0) == 0
        and isinstance(imported.get("imported"), list)
        and all(type(v) is int and v > 0 for v in imported["imported"])
    )
    sources: set[str] = set()
    if clean:
        with registry_snapshot(settings.db_path, label="source selection registry") as snapshot:
            repo = IdeaRepository(snapshot.connection)
            for identity in imported.get("imported", []):
                sources.update(link.inspiration_id for link in repo.inspirations_of(identity))
    record_source_pass(settings.data_dir, payload, clean=clean, imported_sources=sources)
    emit(
        ok(
            {
                "recorded": clean,
                "complete": payload["complete"],
                "missing_sources": payload["missing_sources"],
            }
        )
    )
