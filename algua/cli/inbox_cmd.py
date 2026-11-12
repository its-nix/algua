"""`research inbox intake` — the owner's Inbox Sheet into the inspirations funnel, exactly once
(spec 2026-11-12 §6.4). Driver-facing: `leap.sh` runs it on every firing, before any gate."""
from __future__ import annotations

from datetime import UTC, datetime

import typer

from algua.cli._common import ok
from algua.cli._drive import drive_session
from algua.cli.app import emit
from algua.knowledge.drive.inbox import intake
from algua.knowledge.drive.tables import CategoriesTable

inbox_app = typer.Typer(help="The owner's Drive inbox of ideas.", no_args_is_help=True)


@inbox_app.command("intake")
def intake_cmd() -> None:
    """Turn new Inbox rows into `source_kind: human` inspirations and mark them taken."""
    with drive_session() as (_settings, client):
        lines = CategoriesTable(client).lines()
        categories = {line.split()[0] for line in lines if not line.startswith("#")}
        result = intake(client, today=datetime.now(UTC).date(), categories=categories)
    emit(ok(result))
