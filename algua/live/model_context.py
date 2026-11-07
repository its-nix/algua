"""Compose the model planner's context from captured values, without I/O."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from algua.contracts.strategy_context import AsOfContext
from algua.live.frozen_model_wire import model_extension
from algua.live.planner_contract import EarlyPlannerInput
from algua.strategies.base import LoadedStrategy
from algua.strategies.context_inputs import build_context


def build_model_decision_context(
    strategy: LoadedStrategy, early: EarlyPlannerInput, view: pd.DataFrame, decision_ts: datetime,
) -> AsOfContext | None:
    if early.boundary_version == 1:
        return None
    if early.boundary_version != 2 or strategy.strategy_interface != "context_v1":
        raise ValueError("unsupported model planner profile")
    model_extension(early.resolved_config_json, early.bars_snapshot_id)
    return build_context(strategy, decision_ts=pd.Timestamp(decision_ts),
        first_decision_ts=pd.Timestamp(decision_ts), universe=early.gate_universe,
        bars=view, bars_snapshot_id=early.bars_snapshot_id,
        fundamentals=None, fundamentals_snapshot_id=None, news=None, news_snapshot_id=None)
