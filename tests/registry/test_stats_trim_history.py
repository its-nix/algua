"""Lean trim step 7: historical gate rows stay readable after the statistics stack is removed.

An OLD-shape ``gate_evaluations`` row carries real ``fdr_*`` column values and the family / regime
/ IR / haircut keys in ``decision_json``; a NEW-shape row has those columns NULL and those keys
absent. Every reader (``strategy_gate_history``, ``gate_evaluation_history``, ``runs show``) must
render both without error, and the old row's historical values must still be visible.
Synthetic fixtures only.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from algua.registry.db.migrate import migrate
from algua.registry.gate_history import gate_evaluation_history, strategy_gate_history
from algua.registry.run_views import run_detail_payload
from algua.registry.store import SqliteStrategyRepository

_BASE_CHECKS = [
    {"name": "holdout_sharpe", "value": 1.1, "threshold": 0.9, "op": ">=", "passed": True,
     "advisory": True},
    {"name": "holdout_return", "value": 0.05, "threshold": 0.0, "op": ">", "passed": True,
     "advisory": True},
    {"name": "min_holdout_observations", "value": 100.0, "threshold": 63.0, "op": ">=",
     "passed": True},
    {"name": "holdout_sharpe_floor", "value": 1.1, "threshold": 0.0, "op": ">", "passed": True},
    {"name": "pit_required", "passed": True},
]

# Every key an old (pre-trim) decision_json carried for the removed subsystems.
OLD_FDR_KEYS = {
    "fdr_binding": True, "fdr_p_value": 0.01, "fdr_alpha_level": 0.02, "fdr_test_index": 3,
    "fdr_rejected": True, "fdr_skip_reason": None, "fdr_cohort": 0, "fdr_cohorts_completed": 0,
    "fdr_binding_tests": 3, "fdr_discoveries": 1, "fdr_expected_false_discoveries": 0.0,
    "fdr_throttle_window_binding": 2, "fdr_throttle_tripped": False,
    "fdr_active_cohort_position": 3, "fdr_active_cohort_applied_alpha": 0.05,
    "fdr_expected_false_discoveries_incl_active": 0.05,
}
OLD_STATS_KEYS = {
    "regime_method": "vol_tertile", "n_regimes_attempted": 3, "n_regimes_surviving": 3,
    "per_regime_sharpes": [0.4, 0.5, 0.6], "regime_robustness_binding": True,
    "ir_method": "capm_appraisal", "ir_binding": True, "ir_overlap_n": 100, "market_beta": 0.3,
    "ir_alpha_ann": 0.04, "ir_residual_vol_ann": 0.1, "appraisal_ratio": 0.4,
    "effective_min_holdout_sharpe": 0.9, "haircut_would_have_blocked": False,
    "phase3_component_mask": 31,
}
OLD_CHECKS = [
    *_BASE_CHECKS,
    {"name": "pct_positive_windows", "value": 0.75, "threshold": 0.6, "op": ">=",
     "passed": True, "advisory": True},
    {"name": "min_window_sharpe", "value": 0.2, "threshold": 0.0, "op": ">=", "passed": True,
     "advisory": True},
    {"name": "regime_robustness", "value": None, "threshold": 0.0, "op": ">=", "passed": True,
     "advisory": True},
    {"name": "idiosyncratic_alpha", "value": 0.4, "threshold": 0.0, "op": ">=", "passed": True,
     "advisory": True},
]


def _old_decision() -> dict:
    return {"passed": True, "checks": OLD_CHECKS, "n_combos": 12,
            "base_min_holdout_sharpe": 0.5, "dsr_binding": True, "dsr_n_trials": 12,
            **OLD_FDR_KEYS, **OLD_STATS_KEYS}


def _new_decision() -> dict:
    return {"passed": True, "checks": _BASE_CHECKS, "n_combos": 12,
            "base_min_holdout_sharpe": 0.5, "dsr_binding": True, "dsr_n_trials": 12}


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _insert_gate(conn: sqlite3.Connection, strategy_id: int, decision: dict, *,
                 fdr: tuple | None, family_id: int | None) -> int:
    cols = {
        "strategy_id": strategy_id, "passed": 1, "n_funnel": 12, "own_lifetime_combos": 12,
        "windowed_total_combos": 30, "funnel_window_days": 90, "breadth_provenance": "measured",
        "pit_ok": 1, "holdout_n_bars": 100, "min_holdout_observations": 63, "code_hash": "c",
        "config_hash": "cfg", "dependency_hash": "dep", "data_source": "snapshot",
        "snapshot_id": "snap-1", "period_start": "2020-01-01", "period_end": "2024-01-01",
        "holdout_frac": 0.2, "actor": "agent", "decision_json": json.dumps(decision),
        "created_at": "2026-01-01T00:00:00+00:00", "family_id": family_id,
        "family_lifetime_effective": 40 if family_id is not None else None,
    }
    if fdr is not None:
        cols.update(zip(("fdr_binding", "fdr_p_value", "fdr_alpha_level", "fdr_rejected",
                         "fdr_test_index", "fdr_cohort"), fdr, strict=True))
    cur = conn.execute(
        f"INSERT INTO gate_evaluations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
        tuple(cols.values()))
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def _insert_old_family(conn: sqlite3.Connection, founder: str) -> int:
    """An old #222/#524 family graph: the tables stay in the schema as history."""
    cur = conn.execute(
        "INSERT INTO families(name, created_at, created_by_actor, created_by_strategy,"
        " seeded_prior_combos) VALUES ('fam_old', '2026-01-01T00:00:00+00:00', 'agent', ?, 40)",
        (founder,))
    fid = cur.lastrowid
    conn.execute(
        "INSERT INTO family_members(family_id, strategy_name, joined_at, joined_by_actor)"
        " VALUES (?, ?, '2026-01-01T00:00:00+00:00', 'agent')", (fid, founder))
    conn.execute(
        "INSERT INTO family_events(event_type, family_id, strategy_name, actor, created_at)"
        " VALUES ('family_created', ?, ?, 'agent', '2026-01-01T00:00:00+00:00')", (fid, founder))
    conn.commit()
    assert fid is not None
    return fid


def _seed(conn: sqlite3.Connection) -> tuple[SqliteStrategyRepository, int, int, int]:
    repo = SqliteStrategyRepository(conn)
    rec = repo.add("alpha")
    fid = _insert_old_family(conn, "alpha")
    old_id = _insert_gate(conn, rec.id, _old_decision(), fdr=(1, 0.01, 0.02, 1, 3, 0),
                          family_id=fid)
    new_id = _insert_gate(conn, rec.id, _new_decision(), fdr=None, family_id=None)
    return repo, rec.id, old_id, new_id


def test_old_and_new_gate_rows_render(conn: sqlite3.Connection) -> None:
    repo, sid, old_id, new_id = _seed(conn)
    gates, _forwards = strategy_gate_history(conn, sid)
    by_id = {g["id"]: g for g in gates}
    assert set(by_id) == {old_id, new_id}
    assert by_id == {g["id"]: g for g in gate_evaluation_history(conn, sid)}

    old, new = by_id[old_id], by_id[new_id]
    # Historical FDR column values still show on the old row; NULL on the new row.
    assert (old["fdr_binding"], old["fdr_p_value"], old["fdr_alpha_level"], old["fdr_rejected"],
            old["fdr_test_index"], old["fdr_cohort"]) == (1, 0.01, 0.02, 1, 3, 0)
    assert all(new[k] is None for k in ("fdr_binding", "fdr_p_value", "fdr_cohort"))
    # Historical decision keys stay visible (not dropped) on the old row.
    for key, value in OLD_FDR_KEYS.items():
        assert old["decision"][key] == value, key
    assert not (set(OLD_FDR_KEYS) & set(old["decision_dropped_keys"]))
    assert new["decision_dropped_keys"] == []
    assert not any(k.startswith("fdr_") for k in new["decision"])

    # runs show renders both rows' projected decisions.
    for gid in (old_id, new_id):
        run_id = repo.record_run("gate", "alpha", strategy_id=sid, gate_id=gid)
        payload = run_detail_payload(repo, run_id)
        assert payload["gate_decision"]["passed"] is True
        assert "gate_decision_error" not in payload
    old_run = run_detail_payload(
        repo, repo.record_run("gate", "alpha", strategy_id=sid, gate_id=old_id))
    assert old_run["gate_decision"]["fdr_p_value"] == 0.01

    # Regime / IR keys (Task 3) stay visible on the old row; per_regime_sharpes was never
    # projected (a bare float list) and is still dropped. The old row's window-stability and
    # regime/IR checks still render.
    regime_ir = {k: v for k, v in OLD_STATS_KEYS.items()
                 if k.startswith(("regime_", "n_regimes", "ir_")) or k in (
                     "market_beta", "appraisal_ratio")}
    for key, value in regime_ir.items():
        if key == "per_regime_sharpes":
            continue
        assert old["decision"][key] == value, key
    assert old["decision_dropped_keys"] == ["per_regime_sharpes"]
    assert [c["name"] for c in old["decision"]["checks"]] == [c["name"] for c in OLD_CHECKS]
    assert old_run["gate_decision"]["appraisal_ratio"] == 0.4


def test_historical_keys_are_disjoint_from_current_fields() -> None:
    from algua.registry.gate_history import (
        GATE_DECISION_ALLOWLIST,
        GATE_DECISION_EXCLUDED,
        GATE_DECISION_HISTORICAL,
        GATE_DECISION_PROJECTION,
    )
    assert not GATE_DECISION_HISTORICAL & GATE_DECISION_ALLOWLIST
    assert not GATE_DECISION_HISTORICAL & GATE_DECISION_EXCLUDED
    assert GATE_DECISION_PROJECTION == GATE_DECISION_ALLOWLIST | GATE_DECISION_HISTORICAL


def test_old_family_tables_stay_as_history(conn: sqlite3.Connection) -> None:
    """Strategy-family governance is gone, but its tables and rows stay (no destructive
    migration): a re-migrate keeps them, and the old gate row keeps its family columns."""
    _repo, sid, old_id, new_id = _seed(conn)
    migrate(conn)
    for table in ("families", "family_members", "family_events"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1, table
    rows = {r["id"]: r for r in conn.execute(
        "SELECT id, family_id, family_lifetime_effective FROM gate_evaluations")}
    assert rows[old_id]["family_id"] is not None and rows[old_id]["family_lifetime_effective"] == 40
    assert rows[new_id]["family_id"] is None
    gates, _ = strategy_gate_history(conn, sid)
    assert {g["id"] for g in gates} == {old_id, new_id}
