"""Research portfolio replay; mounted by the CLI composition root."""
from __future__ import annotations

from pathlib import Path

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.evaluation.portfolio_run import run_portfolio_replay

portfolio_app = typer.Typer()


@portfolio_app.command("portfolio")
@json_errors
def portfolio_replay(
    manifest: Path = typer.Option(..., "--manifest", help="Strict portfolio-replay/v1 JSON file."),
) -> None:
    """Replay an explicit account on a pinned snapshot; record in-sample research only."""
    emit(ok(run_portfolio_replay(manifest)))
