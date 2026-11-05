"""Trusted research-driver retention commands; evidence remains non-authoritative."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.operator.campaign_memory import capture_public_memory
from algua.operator.research_cycle import ResearchCycle
from algua.operator.research_memory import ResearchMemory
from algua.operator.research_memory_index import list_retained_research, read_retained_research
from algua.registry.campaign_read import read_campaign_scorecard
from algua.registry.db import registry_conn
from algua.tracking.research_archive import LocalResearchArchive

memory_app = typer.Typer(
    no_args_is_help=True,
    help="Retain and verify public worker experiments before disposable research cleanup. "
         "Unverified worker evidence grants no promotion authority; these commands delete nothing.",
)


@contextmanager
def _memory(run: str) -> Iterator[ResearchMemory]:
    settings = get_settings()
    archive = LocalResearchArchive(settings.mlflow_tracking_uri, backend=settings.tracking_backend)
    with registry_conn() as conn:
        yield ResearchMemory(
            ResearchCycle(conn, settings.data_dir / "research-cycles", run), archive)


@memory_app.command("seed")
@json_errors
def seed(
    run: str = typer.Option(..., "--run"),
    worker_root: Path = typer.Option(..., "--worker-root"),
) -> None:
    """Checkpoint the actual copied registry before the worker starts; never advance a seed."""
    with _memory(run) as memory:
        checkpoint = memory.seed(worker_root)
    emit(ok({"research_cycle_id": run, "seed": checkpoint}))


@memory_app.command("capture")
@json_errors
def capture(
    run: str = typer.Option(..., "--run"),
    worker_root: Path = typer.Option(..., "--worker-root"),
    worker_exit: int = typer.Option(..., "--worker-exit"),
    source_commit: str = typer.Option(..., "--source-commit"),
) -> None:
    """Publish public evidence, verify actual archive readback, and append the cycle receipt."""
    with _memory(run) as memory:
        receipt = memory.capture(worker_root, worker_exit=worker_exit, source_commit=source_commit)
    emit(ok({"research_cycle_id": run, "receipt": receipt}))


@memory_app.command("show")
@json_errors
def show(run: str = typer.Option(..., "--run")) -> None:
    """Read and verify retained public evidence, including after the worker is removed."""
    settings = get_settings()
    payload = read_retained_research(
        run, database=settings.db_path, data_dir=settings.data_dir,
        tracking_uri=settings.mlflow_tracking_uri, tracking_backend=settings.tracking_backend)
    emit(ok(payload))


@memory_app.command("list")
@json_errors
def list_(limit: int = typer.Option(20, "--limit", min=1, max=100)) -> None:
    """List unverified terminal attempt references without opening or migrating authority."""
    emit(ok(list_retained_research(get_settings().db_path, limit=limit)))


@memory_app.command("cleanup-check")
@json_errors
def cleanup_check(
    run: str = typer.Option(..., "--run"),
    worker_root: Path = typer.Option(..., "--worker-root"),
) -> None:
    """Verify cleanup admission; retain models or uncertainty and never remove the worker."""
    with _memory(run) as memory:
        reason = memory.cleanup_retention_reason(worker_root)
    if reason == "evidence_unverified":
        raise ValueError("research memory is unverified; retain the worker worktree")
    if reason is not None:
        raise ValueError(f"research memory cleanup refused: {reason}; retain the worker worktree")
    emit(ok({"research_cycle_id": run, "cleanup_allowed": True}))


@memory_app.command("prompt-context")
@json_errors
def prompt_context() -> None:
    """Read bounded recent public numerical context without claiming or migrating authority."""
    settings = get_settings()
    menu = {"request": {"database": str(settings.db_path.resolve())}, "choices": [],
            "scorecard": read_campaign_scorecard(settings.db_path)}
    snapshot = capture_public_memory(
        menu, cycle_directory=settings.data_dir / "research-cycles",
        tracking_uri=settings.mlflow_tracking_uri, tracking_backend=settings.tracking_backend)
    emit(ok({"public_research_memory": snapshot}))
