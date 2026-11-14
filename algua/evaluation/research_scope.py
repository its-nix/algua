"""Resolve a development-only smoke period before executing a strategy."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from algua.backtest.walkforward import holdout_window
from algua.config.settings import get_settings
from algua.operator.research_profile import load_research_profile
from algua.primitives.timeparse import utc


def development_scope(strategy: Any, provider: Any, start: datetime, end: datetime, *,
                       snapshot: str | None, research_only: bool, holdout_frac: float,
                       universe_by_date: Any) -> tuple[datetime, dict | None]:
    if os.environ.get('ALGUA_RESEARCH_PROFILE') is not None:
        profile = load_research_profile(get_settings().data_dir)
        if profile is None or (snapshot, start.date().isoformat(), end.date().isoformat()) != (
                profile['snapshot_id'], profile['start'], profile['end']):
            raise ValueError('research_profile:backtest_inputs_mismatch')
        research_only, holdout_frac = True, profile['holdout_frac']
    if not research_only:
        return end, None
    if snapshot is None:
        raise ValueError('research-only smoke requires an immutable bars snapshot')
    boundary, _ = holdout_window(strategy, provider, start, end, holdout_frac=holdout_frac,
                                 universe_by_date=universe_by_date)
    cutoff = utc(boundary)
    if cutoff <= start:
        raise ValueError('research-only period has no development bars')
    return cutoff, {'mode': 'development_only', 'requested_end': end.date().isoformat(),
                    'reserved_holdout_start': boundary, 'holdout_frac': holdout_frac}
