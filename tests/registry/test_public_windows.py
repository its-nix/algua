"""Synthetic public/private sentinels at the recorder and identity-bound read seams."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from algua.registry.db import registry_conn
from algua.registry.research_runs import research_run_payload
from algua.registry.run_views import run_detail_payload
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests.registry.test_board_comparison import context
from tests.test_run_provenance import COSTS
from tests.test_wf_public_disclosure import PARAMS, PRIVATE, canonical_bars_record, wf_result


def sentinel_result():
    """Declared pilot metadata over synthetic input ONLY; no real-market evaluation."""
    from algua.provenance.research import PILOT_PROXY_LIMITATIONS
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    bars = canonical_bars_record()
    record = SnapshotRecord.from_dict(bars)
    source = dict(record.metadata.source_metadata)
    envelope = json.loads(source["research_provenance"])
    envelope.update(data_tier="pilot_real_proxy", limitations=sorted(PILOT_PROXY_LIMITATIONS))
    source["research_provenance"] = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    metadata = replace(record.metadata, source_metadata=source)
    bars = replace(record, metadata=metadata,
                   snapshot_id=compute_snapshot_id(metadata, record.content_hash)).to_dict()
    wf = wf_result()
    wf.bars_provenance, wf.snapshot_id = bars, bars["snapshot_id"]
    wf.execution_costs = dict(COSTS)
    wf.code_hash, wf.dependency_hash = "runtime-source", "deps"
    wf.data_source = "StoreBackedProvider"
    wf.execution_semantics = context()["execution"]
    wf.execution_semantics["symbol_order"] = ["SYNTHETIC"]
    wf.windows = 2
    wf.window_metrics = [
        {"start": "2023-01-02", "end": "2023-03-01", "n_bars": 40,
         "sharpe": -1.0, "total_return": -0.1},
        {"start": "2023-03-02", "end": "2023-04-28", "n_bars": 41,
         "sharpe": 1.0, "total_return": 0.1},
    ]
    wf.stability = {"mean_sharpe": 0.0, "std_sharpe": 1.0, "min_sharpe": -1.0,
                    "pct_positive_windows": 0.5}
    return wf


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "public.db"))


def record(repo, name="synthetic"):
    wf = sentinel_result()

    class PublicOnly:
        def __getattr__(self, key):
            if key in {"holdout_metrics", "holdout_returns", "market_returns"}:
                raise AssertionError(f"private attribute accessed: {key}")
            return getattr(wf, key)

    strategy = repo.add(name)
    run_id = record_walk_forward_run(
        repo, name, PublicOnly(), strategy_id=strategy.id, params=PARAMS,
        research_inputs={"delisting_snapshot": None, "assume_terminal_last_close": False})
    return strategy, run_id, wf


def test_public_record_persists_exact_inputs_and_windows_without_private_access():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, run_id, wf = record(repo)
        detail = run_detail_payload(repo, run_id)
        assert detail["config_json"]["params"] == PARAMS
        assert detail["config_json"]["run_provenance"]["bars"] == wf.bars_provenance
        assert detail["config_json"]["public_window_record"]["windows"] == wf.window_metrics
        output = research_run_payload(repo, strategy.id, run_id)
        assert output["latest_research"] == {
            "kind": "public_windows", "run_id": run_id, "created_at": detail["created_at"],
            "mean_window_sharpe": 0.0, "min_window_sharpe": -1.0,
            "std_window_sharpe": 1.0, "pct_positive_windows": 0.5}
        assert output["evidence"]["kind"] == "public_windows"
        assert output["evidence"]["public_interval"]["value"] == {
            "start": "2023-01-02", "end": "2023-04-28", "n_bars": 81, "n_windows": 2}
        assert output["evidence"]["comparison"]["status"] == "COMPARABLE"
        assert str(PRIVATE) not in json.dumps([detail, output])
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM gate_evaluations").fetchone()[0] == 0
        assert strategy_board_payload(repo)["rows"][0]["latest_gate"] is None


@pytest.mark.parametrize("field", [
    "identity", "config", "dependency", "snapshot", "timeframe", "period", "seed", "metric",
    "window_count", "window_interval", "window_value", "cost", "cost_unit", "bars",
    "execution", "simulation", "future", "provenance", "passed", "lineage", "components",
    "private_alias", "private_extra_alias", "private_vector", "invalid_numeric", "legacy_binding",
])
def test_independent_declarations_refuse_corruption_and_isolate_healthy_neighbor(field):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, run_id, _ = record(repo)
        healthy, healthy_id, _ = record(repo, "healthy")
        before = research_run_payload(repo, healthy.id, healthy_id)
        raw = conn.execute("SELECT config_json FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        config = json.loads(raw)
        public = config["public_window_record"]
        changes = {
            "identity": ("strategy_id", healthy.id), "config": ("config_hash", "wrong"),
            "dependency": ("dependency_hash", "wrong"), "snapshot": ("snapshot_id", "wrong"),
            "timeframe": ("timeframe", "1h"), "period": ("period_end", "2024-01-01"),
            "seed": ("seed", 999), "metric": ("mean_window_sharpe", -5),
            "passed": ("passed", 1), "lineage": ("derived_from", "[123]"),
            "components": ("components", '[{"model":"other"}]'),
            "private_alias": ("sharpe_oos", PRIVATE),
            "private_extra_alias": ("sharpe_realized", PRIVATE),
            "private_vector": ("components", json.dumps([{"returns": [PRIVATE]}])),
        }
        if field in changes:
            column, value = changes[field]
            conn.execute(f"UPDATE runs SET {column}=? WHERE id=?", (value, run_id))
        elif field == "window_count":
            config["windows"] += 1
        elif field == "window_interval":
            public["context"]["windows"][0]["end"] = "2023-03-02"
        elif field == "window_value":
            public["windows"][0]["sharpe"] = 9.0
        elif field == "cost":
            config["run_provenance"]["execution_costs"]["fees"] = 0.1
        elif field == "cost_unit":
            public["inputs"]["execution_costs"]["fees_unit"] = "bps"
        elif field == "bars":
            config["run_provenance"]["bars"]["source_metadata"]["raw_json"] = str(PRIVATE)
        elif field == "execution":
            public["context"]["execution"]["sizing"] = "shares"
        elif field == "simulation":
            public["context"]["execution"]["simulation"]["fixed_fees"] = True
        elif field == "future":
            public["context"]["raw_result"] = {"tail": [PRIVATE]}
        elif field == "provenance":
            public["provenance"]["config_hash"] = "wrong"
        elif field == "invalid_numeric":
            public["statistics"]["pct_positive_windows"] = True
        elif field == "legacy_binding":
            public["schema_version"] = "recorded-wf-scalars/v1"
            config["include_holdout"] = True
        conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), run_id))
        identity = strategy.id if field != "identity" else healthy.id
        output = research_run_payload(repo, identity, run_id)
        assert output["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert all(output["latest_research"][k] is None for k in (
            "mean_window_sharpe", "std_window_sharpe", "min_window_sharpe", "pct_positive_windows"))
        assert str(PRIVATE) not in json.dumps(output)
        assert research_run_payload(repo, healthy.id, healthy_id) == before
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


def test_newest_unknown_does_not_fall_back_but_pinned_run_survives_later_gate():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, good, _ = record(repo)
        default = strategy_board_payload(repo)
        bad = repo.record_run("walk_forward", strategy.name, strategy_id=strategy.id,
                              config={"research_record": {
                                  "schema_version": "recorded-wf-scalars/v1"}},
                              metrics={"mean_window_sharpe": 999})
        repo.record_run("gate", strategy.name, strategy_id=strategy.id,
                        derived_from=[bad], metrics={"sharpe_oos": 123})
        latest = research_run_payload(repo, strategy.id)
        assert latest["latest_research"]["run_id"] == bad
        assert latest["latest_research"]["mean_window_sharpe"] is None
        assert latest["evidence"]["comparison"]["status"] == "UNKNOWN"
        pinned = research_run_payload(repo, strategy.id, good)
        assert pinned["evidence"]["comparison"]["status"] == "COMPARABLE"
        assert default["rows"][0]["latest_gate"] is None
        assert strategy_board_payload(repo)["rows"][0]["latest_gate"]["sharpe_oos"] == 123


@pytest.mark.parametrize("field", ["row_count", "schema_version"])
@pytest.mark.parametrize("literal", ["1e999", "-1e999"])
def test_overflow_isolation_is_read_only(field, literal):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, bad, _ = record(repo)
        healthy, good, _ = record(repo, "healthy")
        before = research_run_payload(repo, healthy.id, good)
        config = json.loads(repo.get_run(bad)["config_json"])
        config["public_window_record"]["inputs"]["bars"][field] = "OVERFLOW"
        raw = json.dumps(config).replace('"OVERFLOW"', literal)
        conn.execute("UPDATE runs SET config_json=? WHERE id=?", (raw, bad))
        changes = conn.total_changes
        damaged = research_run_payload(repo, strategy.id, bad)
        assert damaged["evidence"]["comparison"]["status"] == "UNKNOWN"
        assert research_run_payload(repo, healthy.id, good) == before
        assert conn.total_changes == changes


def test_source_detachment_and_distinct_cohorts_exclude_outcomes():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, run_id, wf = record(repo)
        original = research_run_payload(repo, strategy.id)
        wf.window_metrics[0]["sharpe"] = PRIVATE
        wf.execution_costs["fees"] = PRIVATE
        assert research_run_payload(repo, strategy.id) == original
        other, other_id, _ = record(repo, "same_inputs")
        second = research_run_payload(repo, other.id)
        cohort = original["evidence"]["comparison"]["cohort_id"]
        assert second["evidence"]["comparison"]["cohort_id"] == cohort
        wf = sentinel_result()
        wf.execution_costs["fees"] = 0
        changed = record_walk_forward_run(
            repo, other.name, wf, strategy_id=other.id,
            research_inputs={"delisting_snapshot": None, "assume_terminal_last_close": False})
        new = research_run_payload(repo, other.id, changed)
        assert new["evidence"]["comparison"]["status"] == "COMPARABLE"
        assert new["evidence"]["comparison"]["cohort_id"] != cohort


@pytest.mark.parametrize("declaration", ["lag", "fill", "params"])
def test_wellformed_independent_declarations_must_agree(declaration):
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, run_id, _ = record(repo)
        config = json.loads(repo.get_run(run_id)["config_json"])
        context = config["public_window_record"]["context"]
        if declaration == "lag":
            context["execution"]["decision_lag_bars"] = 2
        elif declaration == "fill":
            context["execution"].update(fill_basis="adjusted_open", valuation_basis="adjusted_open")
        else:
            config["params"]["nested"]["anything"]["x"] = False
        conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), run_id))
        result = research_run_payload(repo, strategy.id)
        assert result["evidence"]["comparison"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("field", ["hash", "count", "symbols"])
def test_recomputed_input_identity_cannot_admit_invalid_source_semantics(field):
    from algua.provenance.snapshot import SnapshotRecord, compute_snapshot_id

    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy, run_id, _ = record(repo)
        config = json.loads(repo.get_run(run_id)["config_json"])
        public = config["public_window_record"]
        bars = config["run_provenance"]["bars"]
        if field == "hash":
            bars["content_hash"] = "not-a-digest"
        elif field == "count":
            bars["row_count"] = 2**60
        else:
            bars["symbols"] = ["SYNTHETIC", "SYNTHETIC"]
        rec = SnapshotRecord.from_dict(bars)
        bars["snapshot_id"] = compute_snapshot_id(rec.metadata, rec.content_hash)
        public["inputs"]["bars"] = bars
        public["provenance"]["snapshot_id"] = bars["snapshot_id"]
        conn.execute("UPDATE runs SET snapshot_id=?,config_json=? WHERE id=?",
                     (bars["snapshot_id"], json.dumps(config), run_id))
        result = research_run_payload(repo, strategy.id)
        assert result["evidence"]["comparison"]["status"] == "UNKNOWN"
