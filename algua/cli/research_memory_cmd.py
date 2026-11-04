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
from algua.operator.research_cycle import ResearchCycle
from algua.operator.research_memory import ResearchMemory
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
    with _memory(run) as memory:
        payload = memory.read()
    emit(ok(payload))


@memory_app.command("cleanup-check")
@json_errors
def cleanup_check(
    run: str = typer.Option(..., "--run"),
    worker_root: Path = typer.Option(..., "--worker-root"),
) -> None:
    """Exit zero only after verifying the archive and fresh source; never remove the worker."""
    with _memory(run) as memory:
        verified = memory.cleanup_allowed(worker_root)
    if not verified:
        raise ValueError("research memory is unverified; retain the worker worktree")
    emit(ok({"research_cycle_id": run, "cleanup_allowed": True}))
