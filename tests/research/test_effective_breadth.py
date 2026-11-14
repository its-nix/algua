"""DSR trial count after the statistics trim (lean trim step 7, spec 2026-11-12 §4.7).

``effective_funnel_breadth`` is ``max(own lifetime combos, funnel-wide windowed combos)``: no
family term. The windowed count is every recorded sweep in the window, funnel-wide — failed gates
and human-labelled runs included — and it is what reaches the DSR as ``n_trials``. Strategy
families (#222/#524) are gone, so a promote never touches the family tables.
"""
from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime

import pytest

from algua.backtest._sample import SyntheticProvider
from algua.backtest.walkforward import WalkForwardResult
from algua.contracts.lifecycle import Actor, Stage
from algua.registry.db import connect, migrate
from algua.registry.promotion import promotion_preflight, run_gate
from algua.registry.store import SqliteStrategyRepository
from algua.research.dsr import effective_funnel_breadth
from algua.research.gates import FUNNEL_WINDOW_DAYS, GateCriteria

pytestmark = pytest.mark.serial  # promotion_preflight loads a bundled strategy module

_NAME = "cross_sectional_momentum"  # a bundled module: run_gate recomputes its artifact identity


def test_breadth_is_max_of_own_and_windowed() -> None:
    assert effective_funnel_breadth(5, 12) == 12
    assert effective_funnel_breadth(9, 3) == 9
    assert list(inspect.signature(effective_funnel_breadth).parameters) == [
        "own_lifetime", "windowed_total"]


def test_gate_evaluations_family_columns_stay_in_schema() -> None:
    """No destructive migration: the family audit columns stay (new rows write NULL)."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate(conn)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(gate_evaluations)")}
    assert {"family_id", "family_lifetime_effective"} <= cols


def _repo(tmp_path) -> SqliteStrategyRepository:
    conn = connect(tmp_path / "p.db")
    migrate(conn)
    return SqliteStrategyRepository(conn)


def _wf() -> WalkForwardResult:
    return WalkForwardResult(
        strategy=_NAME, config_hash="c", data_source="synthetic", snapshot_id=None,
        timeframe="1d", seed=None,
        period={"start": "2024-01-01", "end": "2024-06-01"}, windows=4, holdout_frac=0.2,
        window_metrics=[],
        holdout_metrics={"sharpe": 2.0, "total_return": 0.1, "n_bars": 252, "skewness": 0.0,
                         "kurtosis": 3.0},
        stability={"pct_positive_windows": 0.8, "min_sharpe": 0.1})


def _promote(repo: SqliteStrategyRepository):
    rec = repo.get(_NAME)
    if rec.stage is not Stage.BACKTESTED:
        repo.apply_transition(rec, Stage.BACKTESTED, Actor.AGENT, "bt")
    start, end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC)
    breadth = promotion_preflight(repo, _NAME, actor=Actor.AGENT,
                                  provider=SyntheticProvider(seed=0), start=start, end=end)
    return run_gate(
        repo, _wf(), name=_NAME, actor=Actor.AGENT, criteria=GateCriteria(), breadth=breadth,
        universe_name="pit_u",
        universe_snapshots=[{"snapshot_id": "u1", "effective_date": "2020-01-01"}],
        period_start=date(2024, 1, 1), period_end=date(2024, 6, 1), holdout_frac=0.2,
        data_source="synthetic", snapshot_id=None)


def _failed_gate_row(repo: SqliteStrategyRepository, name: str, *, actor: str) -> None:
    rec = repo.add(name)
    repo.record_gate_evaluation(
        rec.id, passed=False, n_funnel=1, own_lifetime_combos=1, windowed_total_combos=1,
        funnel_window_days=FUNNEL_WINDOW_DAYS, breadth_provenance="measured", pit_ok=True,
        pit_override=False, holdout_n_bars=63, min_holdout_observations=63, code_hash="c",
        config_hash="cfg", dependency_hash="d", data_source="synthetic", snapshot_id=None,
        period_start="2024-01-01", period_end="2024-06-01", holdout_frac=0.2, actor=actor,
        decision_json='{"passed": false}')


def test_windowed_breadth_counts_failed_and_human_runs(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.add(_NAME)
    # Strategy A's gate FAILED; strategy B's runs are human-labelled. Both sweeps count.
    repo.record_search_trial("strat_a", 40, "{}")
    _failed_gate_row(repo, "strat_a", actor="agent")
    repo.record_search_trial("strat_b", 25, "{}")
    _failed_gate_row(repo, "strat_b", actor="human")
    repo.record_search_trial(_NAME, 5, "{}", trial_sharpe_count=5, trial_sharpe_mean=0.5,
                             trial_sharpe_var_ann=0.04)
    windowed = repo.windowed_search_combos(FUNNEL_WINDOW_DAYS)
    assert windowed == 40 + 25 + 5

    outcome = _promote(repo)
    row = repo._conn.execute(
        "SELECT n_funnel, own_lifetime_combos, windowed_total_combos, decision_json"
        " FROM gate_evaluations WHERE strategy_id=? ORDER BY id DESC LIMIT 1",
        (repo.get(_NAME).id,)).fetchone()
    decision = json.loads(row["decision_json"])
    # Windowed (70) is strictly greater than C's own lifetime combos (5): the max picks it.
    assert row["own_lifetime_combos"] == 5 and row["windowed_total_combos"] == windowed
    assert row["n_funnel"] == windowed
    assert decision["dsr_n_trials"] == windowed
    assert outcome.decision.dsr_n_trials == windowed


def test_promote_on_empty_registry_has_no_family_step(tmp_path) -> None:
    repo = _repo(tmp_path)
    repo.add(_NAME)
    repo.record_search_trial(_NAME, 5, "{}", trial_sharpe_count=5, trial_sharpe_mean=0.5,
                             trial_sharpe_var_ann=0.04)
    outcome = _promote(repo)
    assert outcome.promoted is True
    assert repo.get(_NAME).stage is Stage.CANDIDATE
    for table in ("families", "family_members", "family_events", "family_parents"):
        assert repo._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    row = repo._conn.execute(
        "SELECT family_id, family_lifetime_effective FROM gate_evaluations").fetchone()
    assert tuple(row) == (None, None)
