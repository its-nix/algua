"""Persist fixture ideas/outcomes through the existing repositories."""
from algua.contracts.idea import (
    DataCapability,
    Horizon,
    IdeaStatus,
    Market,
    SourceType,
)
from algua.registry.idea_attempts import IdeaAttemptsRepository
from algua.registry.ideas import IdeaRepository


def add_idea(conn, text, *, family=None, category=None, **kwargs):
    fields = dict(title=text, hypothesis=text, family=family, category=category or family or text,
        tags=["SYNTHETIC_FIXTURE"], source_type=SourceType.MANUAL,
        source_ref="SYNTHETIC_FIXTURE", source_date=None, source_note=None,
        required_data=[DataCapability.OHLCV], status=IdeaStatus.OPEN,
        market=Market.US_EQUITIES, horizon=Horizon.DAILY, falsification="fixture only")
    fields.update(kwargs)
    return IdeaRepository(conn).add(**fields)


def attempt(conn, idea, outcome=None, *, reason="SYNTHETIC_FIXTURE", evidence_ref=None):
    repo = IdeaAttemptsRepository(conn)
    (claimed,) = repo.claim(run_stamp="SYNTHETIC_FIXTURE", limit=1, ttl_minutes=180,
                            category=idea.category)
    assert claimed.id == idea.id
    if outcome is not None:
        repo.record_outcome(idea.id, token=claimed.claim_token, outcome=outcome,
                            reason=reason, evidence_ref=evidence_ref)
    return claimed


def invoke_menu(budget: int):
    """Run the old `campaign-menu` body against ALGUA_DB_PATH; returns the typer Result.

    Test-only stand-in for the removed CLI command. Imports are local so importing this
    fixture module stays cheap.
    """
    from dataclasses import asdict

    import typer
    from typer.testing import CliRunner

    from algua.cli._common import ok
    from algua.cli.app import emit
    from algua.cli.errors import json_errors
    from algua.config.settings import get_settings
    from algua.registry.campaign_read import read_campaign_scorecard
    from algua.research.campaign_policy import campaign_exclusions, campaign_menu

    menu_app = typer.Typer()

    @menu_app.command()
    @json_errors
    def _menu(budget: int = typer.Option(..., "--budget")) -> None:
        history = read_campaign_scorecard(get_settings().db_path)
        choices = campaign_menu(history, budget=budget, novelty_min=1, novelty_max=None)
        emit(ok({"choices": [asdict(c) for c in choices], "scorecard": history,
                 "exclusions": campaign_exclusions(history),
                 "budget": budget,
                 "unallocated_budget": budget - sum(c.budget for c in choices)}))

    return CliRunner().invoke(menu_app, ["--budget", str(budget)])
