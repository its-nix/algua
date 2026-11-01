"""Read-only research campaign feedback; the command never claims or executes work."""
from __future__ import annotations

from dataclasses import asdict

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.registry.campaign_read import read_campaign_scorecard
from algua.research.campaign_policy import campaign_exclusions, campaign_menu

campaign_app = typer.Typer()


@campaign_app.command("campaign-menu")
@json_errors
def menu(budget: int = typer.Option(..., "--budget"),
         novelty_min: int = typer.Option(1, "--novelty-min"),
         novelty_max: int | None = typer.Option(None, "--novelty-max")) -> None:
    """Read lifetime evidence and suggest bounded attempt slots. No DB writes or migration."""
    history = read_campaign_scorecard(get_settings().db_path)
    choices = campaign_menu(history, budget=budget, novelty_min=novelty_min,
                            novelty_max=novelty_max)
    emit(ok({"choices": [asdict(c) for c in choices], "scorecard": history,
             "exclusions": campaign_exclusions(history),
             "budget": budget, "novelty_min": novelty_min, "novelty_max": novelty_max,
             "unallocated_budget": budget - sum(c.budget for c in choices)}))
