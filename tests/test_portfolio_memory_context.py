"""Public record bindings and whole-input budgets on explicitly unverified data fixtures."""
from __future__ import annotations

import copy
import json

import pytest

from algua.contracts.types import ExecutionContract
from algua.operator.campaign_memory_schema import observation
from algua.operator.campaign_memory_worker import project_snapshot
from algua.operator.research_memory_checkpoint import canonical
from algua.operator.research_memory_inputs import context_input_limit, public_memory_inputs
from algua.registry.db import connect
from algua.registry.db.constants import SCHEMA_VERSION
from algua.registry.store import SqliteStrategyRepository
from algua.strategies.base import StrategyConfig, strategy_config_hash
from tests.test_portfolio_memory_inputs import portfolio_input as portfolio_input
from tests.test_portfolio_memory_inputs import seal
from tests.test_research_memory import memory_case as memory_case

CYCLE = "portfolio-context-fixture"


def _row(config, identity=1):
    payload = config["portfolio_replay"]
    provenance, metrics = payload["provenance"], payload["metrics"]
    values = {key: provenance[key] for key in (
        "code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id", "seed")}
    values.update(timeframe="1d", period_start=payload["manifest"]["start"],
        period_end=payload["manifest"]["end"], universe_name=None, fundamentals_snapshot=None,
        news_snapshot=None, delisting_snapshot=None)
    return {"source_ref": f"scratch:{CYCLE}:runs:{identity}", "source_run_id": identity,
        "strategy_name": payload["portfolio_name"], "strategy_local_id": None,
        "created_at": "2024-01-06T00:00:00+00:00", "kind": "backtest", "parent_refs": [],
        "model_refs": [], "inputs": config, "provenance": values,
        "metrics": {"sharpe_is": metrics["sharpe"], "sortino_is": metrics["sortino"],
            "total_return_is": metrics["total_return"], "max_drawdown_is": metrics["max_drawdown"],
            "ann_vol_is": metrics["ann_volatility"], "cagr_is": metrics["cagr"],
            "calmar_is": metrics["calmar"], "n_obs_is": provenance["replay"]["sessions"]},
        "extra_metrics": {}}


def _project(rows):
    receipt = {"research_cycle_id": CYCLE, "reference": "mlflow:" + "a" * 32
        + "/public-evidence.json#sha256=" + "b" * 64, "sha256": "b" * 64}
    payload = {"schema_version": "research-memory/v1", "research_cycle_id": CYCLE,
        "evidence_mode": "UNVERIFIED_WORKER", "authority": "none", "source_commit": "c" * 40,
        "worker_exit": 0, "controller_context_digest": "d" * 64,
        "seed": {"runs_max_id": 0, "inherited_run_count": 0, "registry_digest": "e" * 64,
            "inherited_runs_digest": "f" * 64, "schema_version": SCHEMA_VERSION},
        "attempt_refs": [{"evidence_id": "idea_attempts:1", "idea_id": 1}],
        "evaluations": rows, "coverage": {"retained_evaluations": len(rows),
            "kind_counts": {"backtest": len(rows)}, "inherited_run_count": 0,
            "truncated_sweeps": [], "unrecorded_variant_failures": "UNKNOWN",
            "model_bytes_preserved": False, "evaluated_worktree_verified": False}}
    return project_snapshot([{"receipt": receipt, "payload": payload}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri="sqlite:////fixture.db")


def _padded(config, size):
    value = copy.deepcopy(config)
    provenance = value["portfolio_replay"]["provenance"]
    raw = provenance["sleeve_configs"]["fixture_rule"]
    raw["params"] = {"unicode": "雪", "whole": ""}

    def reseal():
        parsed = StrategyConfig(**(raw | {"execution": ExecutionContract(**raw["execution"])}))
        digest = strategy_config_hash(parsed)
        provenance["strategies"]["fixture_rule"] = digest
        provenance["sleeve_identities"]["fixture_rule"]["config_hash"] = digest
        seal(value)

    reseal()
    raw["params"]["whole"] = "x" * (size - len(canonical(value)))
    reseal()
    assert len(canonical(value)) == size
    return value


@pytest.mark.parametrize("size,included", [(16384, True), (16385, False)])
def test_complete_portfolio_input_byte_boundary_is_not_truncation(portfolio_input, size, included):
    inputs = _padded(portfolio_input, size)
    assert public_memory_inputs("backtest", inputs) == inputs
    view = _project([_row(inputs)])
    assert len(canonical(view)) <= 24 * 1024
    assert view["coverage"]["omitted_for_input_bytes"] == int(not included)
    assert view["coverage"]["omitted_for_context_bytes"] == 0
    assert view["coverage"]["included_observations"] == int(included)
    if included:
        assert view["observations"][0]["inputs"] == inputs
        assert len(canonical(view["observations"][0]["inputs"])) == 16384
    else:
        assert view["observations"] == [] and view["status"] == "unavailable"


@pytest.mark.parametrize("size,included", [(4096, True), (4097, False)])
def test_ordinary_input_keeps_its_four_kib_boundary(portfolio_input, size, included):
    row = _row(portfolio_input)
    row["strategy_name"] = "SYNTHETIC_FIXTURE ordinary"
    row["inputs"] = {"params": {"whole": ""}}
    row["inputs"]["params"]["whole"] = "x" * (size - len(canonical(row["inputs"])))
    assert len(canonical(row["inputs"])) == size
    assert context_input_limit("backtest", row["inputs"]) == 4096
    view = _project([row])
    assert view["coverage"]["omitted_for_input_bytes"] == int(not included)
    assert view["coverage"]["included_observations"] == int(included)
    if included:
        assert view["observations"][0]["inputs"] == row["inputs"]


@pytest.mark.parametrize("kind", ["walk_forward", "sweep", "sweep_trial"])
def test_windowed_replay_namespace_never_receives_admission_or_larger_budget(portfolio_input, kind):
    assert context_input_limit(kind, portfolio_input) == 4096
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        public_memory_inputs(kind, portfolio_input)


@pytest.mark.parametrize("fault", ["name", "local-id", "parent", "model", "extra",
    "snapshot", "code", "config", "dependency", "seed", "period", "sidecar", "metric",
    "count"])
def test_archive_outer_bindings_refuse_tampering(portfolio_input, fault):
    row = _row(portfolio_input)
    if fault == "name":
        row["strategy_name"] = "another-strategy"
    elif fault == "local-id":
        row["strategy_local_id"] = 4
    elif fault in ("parent", "model", "extra"):
        row[{"parent": "parent_refs", "model": "model_refs", "extra": "extra_metrics"}[fault]] = (
            [f"scratch:{CYCLE}:runs:2"] if fault == "parent" else [{}] if fault == "model"
            else {"mean_trial_sharpe": 1.0})
    elif fault in ("metric", "count"):
        row["metrics"]["total_return_is" if fault == "metric" else "n_obs_is"] = 7
    else:
        key = {"snapshot": "snapshot_id", "code": "code_hash", "config": "config_hash",
            "dependency": "dependency_hash", "seed": "seed", "period": "period_end",
            "sidecar": "news_snapshot"}[fault]
        row["provenance"][key] = 1 if fault == "seed" else "foreign"
    with pytest.raises(ValueError):
        observation(row, CYCLE, archived=True)


def test_large_invalid_input_refuses_before_omission(portfolio_input):
    inputs = _padded(portfolio_input, 16385)
    inputs["portfolio_replay"]["provenance"]["PRIVATE_DIAGNOSTIC"] = "NEVER_CONTEXT"
    seal(inputs)
    with pytest.raises(ValueError, match="artifact_payload_invalid"):
        _project([_row(inputs)])


def test_complete_context_drops_only_whole_tail_without_backfill(portfolio_input):
    first = _row(_padded(portfolio_input, 16384))
    second = _row(portfolio_input, 2)
    second.update(strategy_name="SYNTHETIC_FIXTURE ordinary",
                  inputs={"params": {"whole": "x" * 1800}})
    third = _row(_padded(portfolio_input, 8192), 3)
    fourth = _row(portfolio_input, 4)
    fourth.update(strategy_name="SYNTHETIC_FIXTURE later-small", inputs={"params": {"n": 1}})
    view = _project([first, second, third, fourth])
    assert [row["source_ref"] for row in view["observations"]] == [
        first["source_ref"], second["source_ref"]]
    assert view["observations"][0]["inputs"] == first["inputs"]
    assert view["coverage"]["omitted_for_context_bytes"] == 2
    assert view["coverage"]["omitted_for_input_bytes"] == 0
    assert view["coverage"]["omitted_for_count"] == 0
    assert view["coverage"]["retained_public_observations"] == (
        view["coverage"]["included_observations"] + view["coverage"]["omitted_observations"])


@pytest.mark.parametrize("size,retained", [(16385, True), (65536, True), (65537, False)])
def test_large_valid_fixture_keeps_source_and_context_bounds_distinct(
        memory_case, portfolio_input, size, retained):
    _, cycle, worker, source, _, memory = memory_case
    row = _row(_padded(portfolio_input, size))
    conn = connect(source)
    with conn:
        identity = SqliteStrategyRepository(conn).record_run(
            "backtest", row["strategy_name"], provenance=row["provenance"], metrics=row["metrics"])
        conn.execute("UPDATE runs SET config_json=? WHERE id=?",
                     (canonical(row["inputs"]).decode(), identity))
    conn.close()
    if not retained:
        with pytest.raises(ValueError, match="input JSON exceeds"):
            memory.capture(worker, worker_exit=0, source_commit="b" * 40)
        assert source.exists() and not memory.cleanup_allowed(worker)
        assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
        return
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()
    assert payload["evaluations"][0]["inputs"] == row["inputs"]
    assert len(canonical(payload["evaluations"][0]["inputs"])) == size
    assert memory.cleanup_allowed(worker)
    view = project_snapshot([{"receipt": receipt, "payload": payload}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=memory.archive.tracking_uri)
    assert view["observations"] == [] and view["coverage"]["omitted_for_input_bytes"] == 1
