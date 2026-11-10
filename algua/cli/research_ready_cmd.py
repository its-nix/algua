"""Cheap systemd condition: eligible work and an unspent daily model-launch budget."""
from __future__ import annotations

import typer

from algua.cli._common import ok
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.operator.research_daily_budget import DailyResearchBudget
from algua.registry.campaign_read import read_campaign_scorecard
from algua.registry.campaign_selection import menu_from_history


@json_errors
def ready() -> None:
    """Read readiness; exit 1 for an idle/budget-exhausted unit, without spending a launch."""
    settings = get_settings()
    remaining = (None if settings.research_daily_cycle_limit is None else DailyResearchBudget(
        settings.data_dir, settings.db_path, settings.research_daily_cycle_limit).remaining())
    choices = []
    if remaining != 0:
        choices = menu_from_history(read_campaign_scorecard(settings.db_path), {
            'category': None, 'limits': {'max_hypotheses': 1}})['choices']
    due = bool(choices)
    reason = ('daily_budget_exhausted' if remaining == 0 else
              'eligible_ideas' if due else 'no_eligible_ideas')
    emit(ok({'ready': due, 'reason': reason, 'remaining_daily_cycles': remaining}))
    if not due:
        raise typer.Exit(1)
