"""Actual replay/ledger/retention integration on synthetic bars, never market acceptance."""
from __future__ import annotations

import json
import shutil
import sqlite3

import pytest

from algua.operator.campaign_memory_worker import project_snapshot
from algua.operator.research_memory_checkpoint import canonical
from tests.test_campaign_public_memory import _next_menu
from tests.test_cli_portfolio_replay import invoke
from tests.test_cli_portfolio_replay import replay as replay
from tests.test_research_memory import memory_case as memory_case


def _record(replay, source, monkeypatch, *, seed=19, cash_only=False):
    manifest, path, _ = replay
    manifest["seed"] = seed
    if cash_only:
        manifest["sleeves"] = []
    monkeypatch.setenv("ALGUA_DB_PATH", str(source))
    return invoke(manifest, path)


@pytest.mark.parametrize("seed", [None, 19])
@pytest.mark.parametrize("cash_only", [False, True])
def test_actual_public_replay_survives_capture_cleanup_and_readback(
        memory_case, replay, monkeypatch, seed, cash_only):
    authority, cycle, worker, source, archive, memory = memory_case
    result = _record(replay, source, monkeypatch, seed=seed, cash_only=cash_only)
    manifest = result["manifest"]
    with sqlite3.connect(source) as conn:
        stored = json.loads(conn.execute("SELECT config_json FROM runs WHERE id=?",
            (result["recorded_run"]["run_id"],)).fetchone()[0])
        conn.execute("UPDATE runs SET sharpe_oos=999.125 WHERE id=?",
                     (result["recorded_run"]["run_id"],))
    assert stored == {"portfolio_replay": {key: value for key, value in result.items()
                                          if key not in ("ok", "path", "recorded_run")}}
    assert stored["portfolio_replay"]["is_forward_test"] is False
    before = list(authority.iterdump())

    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()

    assert list(authority.iterdump()) == before
    assert payload["authority"] == "none" and payload["evidence_mode"] == "UNVERIFIED_WORKER"
    assert payload["coverage"]["retained_evaluations"] == 1
    observation, = payload["evaluations"]
    assert observation["inputs"] == stored
    assert observation["strategy_name"] == result["portfolio_name"]
    assert observation["strategy_local_id"] is None and observation["model_refs"] == []
    assert observation["provenance"]["snapshot_id"] == manifest["snapshot_id"]
    assert observation["provenance"]["seed"] == manifest["seed"]
    assert observation["metrics"]["total_return_is"] == result["metrics"]["total_return"]
    if cash_only:
        assert observation["metrics"]["sharpe_is"] is None
        assert observation["metrics"]["calmar_is"] is None
    assert "999.125" not in json.dumps(payload)
    assert observation["inputs"]["portfolio_replay"]["provenance"]["execution_costs"] == {
        "schema_version": "execution-costs/v1", "model": "vectorbt.from_orders",
        "fees": 0.001, "slippage": 0.002,
        "fees_unit": "fraction_of_trade_notional_per_side",
        "slippage_unit": "adverse_fill_price_fraction_per_side",
    }
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    assert memory.read() == payload
    assert archive.read(receipt) == payload
    assert json.loads(cycle.path.read_text())["research_memory"]["receipt"] == receipt
    snapshot = project_snapshot([{"receipt": receipt, "payload": payload}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=archive.tracking_uri)
    assert snapshot["observations"][0]["inputs"] == stored
    assert len(canonical(snapshot)) <= 24 * 1024
    assert snapshot["coverage"]["omitted_observations"] == 0


@pytest.mark.slow
def test_actual_contained_portfolio_context_survives_prune_with_no_authored_operations(
        memory_case, replay, monkeypatch):
    from algua.operator import campaign_memory as module

    authority, cycle, worker, source, archive, memory = memory_case
    result = _record(replay, source, monkeypatch)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    cycle.finish(phase="setup_failed", worker_exit=1, evidence_ref=receipt["reference"])
    menu = _next_menu(authority, cycle)
    before = list(authority.iterdump())
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    prefix = """from algua.config import settings
def forbidden(*args, **kwargs):
    raise AssertionError('configuration or authored/model operation must not run')
settings.Settings.__init__ = forbidden
settings.get_settings = forbidden
from algua.strategies import loader
loader.load_strategy = forbidden
loader._resolve_model_handle = forbidden
"""
    monkeypatch.setattr(module, "_BOOTSTRAP", prefix + module._BOOTSTRAP)
    snapshot = module.capture_public_memory(menu, cycle_directory=cycle.directory,
        tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite")
    observation = snapshot["observations"][0]
    assert observation["inputs"]["portfolio_replay"]["manifest"] == result["manifest"]
    assert observation["metrics"]["total_return_is"] == result["metrics"]["total_return"]
    assert snapshot["coverage"]["omitted_observations"] == 0
    assert snapshot["coverage"]["evaluated_worktree_verified"] is False
    assert snapshot["authority"] == "none" and len(canonical(snapshot)) <= 24 * 1024
    assert module.capture_public_memory(menu, cycle_directory=cycle.directory,
        tracking_uri=archive.tracking_uri, tracking_backend="mlflow-sqlite",
        phase="revalidate") == snapshot
    assert list(authority.iterdump()) == before
