"""Automatic experimental qualification; no strict promotion or live permission is minted."""
from __future__ import annotations

from datetime import UTC, datetime

import typer

from algua.calendar.factory import get_calendar
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.contracts.lifecycle import Actor
from algua.registry.artifact_verification import verify_frozen_artifact
from algua.registry.db import registry_conn
from algua.registry.experimental_qualification import qualification_report, record_qualification
from algua.registry.store import SqliteStrategyRepository


def register_experimental(app: typer.Typer) -> None:
    @app.command('qualify-experimental')
    @json_errors
    def qualify(name: str, actor: str = typer.Option('agent', '--actor',
                    help='Reported author only; supplies no live authority.'),
                actor_signature: str | None = typer.Option(None, '--actor-signature',
                    help='Deprecated compatibility option; ignored for paper evidence.'),
                preview: bool = typer.Option(False, '--preview',
                    help='Inspect eligibility without recording a qualification.')) -> None:
        """Record passing historical + five-session evidence; LIVE still needs human signing."""
        who = Actor(actor)
        with registry_conn() as conn:
            now, calendar = datetime.now(UTC), get_calendar()
            report = qualification_report(conn, name, calendar=calendar, now=now)
            if not report['passed']:
                emit({'ok': False, **report, 'recorded': False})
                raise typer.Exit(1)
            verify_frozen_artifact(SqliteStrategyRepository(conn), report['manifest_digest'],
                                   store_root=get_settings().data_dir)
            if preview:
                emit({'ok': True, **report, 'recorded': False})
                return
            rid = record_qualification(conn, name, calendar=calendar, now=now,
                                       expected=report, actor=who)
            emit({'ok': True, **report, 'recorded': True, 'experimental_qualification_id': rid})
