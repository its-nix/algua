"""Explicit experimental qualification; no strict promotion or live permission is minted."""
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
from algua.registry.human_actor import authenticate_actor, canonical_run_context
from algua.registry.repository import ArtifactIdentity
from algua.registry.store import SqliteStrategyRepository


def register_experimental(app: typer.Typer) -> None:
    @app.command('qualify-experimental')
    @json_errors
    def qualify(name: str, actor: str = typer.Option('agent', '--actor'),
                actor_signature: str | None = typer.Option(None, '--actor-signature')) -> None:
        """Preview five-session eligibility; authenticated human records the exact evidence."""
        who = Actor(actor)
        if who not in (Actor.AGENT, Actor.HUMAN):
            raise ValueError('experimental qualification accepts agent preview or human signing')
        with registry_conn() as conn:
            now, calendar = datetime.now(UTC), get_calendar()
            report = qualification_report(conn, name, calendar=calendar, now=now)
            if not report['passed']:
                emit({'ok': False, **report, 'recorded': False})
                raise typer.Exit(1)
            repo = SqliteStrategyRepository(conn)
            rec = repo.get(name)
            verify_frozen_artifact(
                repo, report['manifest_digest'], store_root=get_settings().data_dir)
            if who is Actor.AGENT:
                emit({'ok': True, **report, 'recorded': False})
                return
            who = authenticate_actor(conn, command='paper qualify-experimental', name=name,
                rec=rec, stage_to=rec.stage.value, declared_actor=who,
                actor_signature=actor_signature, run_context=canonical_run_context(report),
                identity=lambda: ArtifactIdentity(report['code_hash'], report['config_hash'],
                                                  report['dependency_hash']))
            rid = record_qualification(conn, name, calendar=calendar, now=now,
                                       expected=report, actor=who)
            emit({'ok': True, **report, 'recorded': True, 'experimental_qualification_id': rid})
