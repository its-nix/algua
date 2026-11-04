"""Durable public exploration survives disposable fixture worktrees without gate authority."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.operator.research_memory import MemoryLimits, ResearchMemory
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository
from algua.tracking.research_archive import LocalResearchArchive
from tests.campaign_fixtures import add_idea


@pytest.fixture
def memory_case(tmp_path, request):
    authority = connect(tmp_path / "authority.db")
    migrate(authority)
    add_idea(authority, "SYNTHETIC_FIXTURE retention hypothesis", family="retention")
    with authority:
        SqliteStrategyRepository(authority).record_run(
            "backtest", "inherited", metrics={"sharpe_is": 0.8})
        if getattr(request, "param", None) == "seeded-sweep":
            SqliteStrategyRepository(authority).record_run(
                "sweep", "inherited sweep", extra_metrics={"mean_trial_sharpe": -0.7})
    cycle = ResearchCycle(authority, tmp_path / "cycles", "fixture-memory")
    cycle.start(limits=CycleLimits(max_hypotheses=1), context={"evidence_mode": "FIXTURE"},
                ttl_minutes=1440)
    worker = tmp_path / "disposable-worker"
    source = worker / ".funnel-scratch/data/algua.db"
    source.parent.mkdir(parents=True)
    with sqlite3.connect(source) as destination:
        authority.backup(destination)
    archive = LocalResearchArchive(f"sqlite:///{tmp_path / 'tracking.db'}")
    memory = ResearchMemory(cycle, archive)
    memory.seed(worker)
    yield authority, cycle, worker, source, archive, memory
    authority.close()


def _explore(source: Path) -> list[int]:
    conn = connect(source)
    repo = SqliteStrategyRepository(conn)
    with conn:
        backtest = repo.record_run("backtest", "rejected-rule", config={"params": {"n": 3}},
                                  metrics={"total_return_is": -0.3, "sharpe_is": -0.5})
        sweep = repo.record_run("sweep", "rejected-rule", config={"grid": {"n": [2, 3]}},
                               trials_truncated_at=None)
    repo.record_sweep_trials(sweep, "rejected-rule", [
        {"config": {"params": {"n": n}}, "config_hash": f"fixture-{n}",
         "metrics": {"mean_window_sharpe": score}}
        for n, score in [(2, -0.4), (3, -0.7)]])
    conn.close()
    return [backtest, sweep]


def _artifact(archive, receipt):
    uri = archive.client.get_run(receipt["run_id"]).info.artifact_uri
    return Path(unquote(urlsplit(uri).path)) / "public-evidence.json"


def test_capture_readback_and_cleanup_preserve_negative_variants(memory_case):
    authority, cycle, worker, source, archive, memory = memory_case
    _explore(source)
    before = list(authority.iterdump())

    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()

    assert list(authority.iterdump()) == before
    assert payload["evidence_mode"] == "UNVERIFIED_WORKER"
    assert payload["authority"] == "none"
    assert [row["kind"] for row in payload["evaluations"]] == [
        "backtest", "sweep", "sweep_trial", "sweep_trial"]
    assert all(row["strategy_name"] != "inherited" for row in payload["evaluations"])
    assert payload["evaluations"][0]["metrics"]["total_return_is"] == -0.3
    parent = payload["evaluations"][1]["source_ref"]
    assert payload["evaluations"][2]["parent_refs"] == [parent]
    assert payload["coverage"]["unrecorded_variant_failures"] == "UNKNOWN"
    assert payload["coverage"]["model_bytes_preserved"] is False
    assert hashlib.sha256(_artifact(archive, receipt).read_bytes()).hexdigest() == receipt["sha256"]

    report = worker / "report.md"
    report.write_text('```json\n{"hypotheses":[{"idea_id":1,"title":"fixture",'
                      '"outcome":"sweep_unstable","reason":"SYNTHETIC_FIXTURE negative"}]}\n```')
    cycle.finish(phase="completed", worker_exit=0, report=report,
                 evidence_ref=receipt["reference"])
    attempt = authority.execute("SELECT evidence_ref,outcome FROM idea_attempts").fetchone()
    assert tuple(attempt) == (receipt["reference"], "sweep_unstable")
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    assert memory.read() == payload


def test_seed_and_capture_are_immutable_and_retryable(memory_case, tmp_path):
    _, cycle, worker, source, archive, memory = memory_case
    seed = json.loads(cycle.path.read_text())["research_memory"]["seed"]
    _explore(source)
    memory.seed(worker)
    assert json.loads(cycle.path.read_text())["research_memory"]["seed"] == seed
    first = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert memory.capture(worker, worker_exit=0, source_commit="b" * 40) == first
    assert len(archive.client.search_runs([archive.experiment_id])) == 1
    other = tmp_path / "different-worker"
    with pytest.raises(ValueError):
        memory.seed(other)
    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=1, source_commit="b" * 40)


def test_tracking_publish_without_receipt_recovers_without_duplicate(memory_case, monkeypatch):
    _, _, worker, source, archive, memory = memory_case
    _explore(source)
    append = memory._append

    def crash(key, value):
        if key == "receipt":
            raise OSError("SYNTHETIC_FIXTURE crash after publication")
        return append(key, value)

    monkeypatch.setattr(memory, "_append", crash)
    with pytest.raises(OSError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    monkeypatch.setattr(memory, "_append", append)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert memory.cleanup_allowed(worker)
    assert len(archive.client.search_runs([archive.experiment_id])) == 1
    assert receipt["sha256"]


@pytest.mark.parametrize("fault", [
    "missing", "changed", "corrupt-receipt", "corrupt-reference", "corrupt-seed", "new-source-row",
])
def test_cleanup_revalidates_artifact_and_source(memory_case, fault):
    _, cycle, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    if fault == "missing":
        _artifact(archive, receipt).unlink()
    elif fault == "changed":
        _artifact(archive, receipt).write_text("SYNTHETIC_FIXTURE corrupted artifact")
    elif fault in ("corrupt-receipt", "corrupt-reference", "corrupt-seed"):
        metadata = json.loads(cycle.path.read_text())
        if fault == "corrupt-seed":
            metadata["research_memory"]["seed"]["runs_max_id"] += 1
        else:
            key = "sha256" if fault == "corrupt-receipt" else "reference"
            metadata["research_memory"]["receipt"][key] = "0" * 64
        cycle.path.write_text(json.dumps(metadata))
    else:
        _explore(source)

    assert not memory.cleanup_allowed(worker)
    assert worker.is_dir()


def test_read_rejects_changed_valid_json_after_source_is_gone(memory_case):
    _, _, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    artifact = _artifact(archive, receipt)
    changed = json.loads(artifact.read_bytes())
    changed["evaluations"][0]["metrics"]["total_return_is"] = 0.9
    artifact.write_text(json.dumps(changed, sort_keys=True))

    with pytest.raises(ValueError, match="digest mismatch"):
        memory.read()


def test_private_gate_claim_and_unknown_diagnostics_are_not_archived(memory_case):
    authority, _, worker, source, _, memory = memory_case
    _explore(source)
    token = authority.execute("SELECT claim_token FROM idea_attempts").fetchone()[0]
    conn = connect(source)
    with conn:
        conn.execute("INSERT INTO run_metrics(run_id,key,value) "
                     "VALUES (2,'holdout_secret',999.123)")
        SqliteStrategyRepository(conn).record_run("gate", "PRIVATE_GATE_NAME",
                                                config={"secret": "PRIVATE_GATE_VALUE"})
        row = SqliteStrategyRepository(conn).record_run("walk_forward", "ordinary",
                    config={"params": {"n": 3}},
                    metrics={"mean_window_sharpe": -0.8})
        conn.execute("UPDATE runs SET sharpe_oos=999.123,series_holdout_id=999 WHERE id=?", (row,))
    conn.close()

    memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    text = json.dumps(memory.read(), sort_keys=True)

    assert "PRIVATE_" not in text
    assert str(token) not in text
    assert "999.123" not in text
    assert "series_holdout_id" not in text
    assert "gate_id" not in text
    assert "sharpe_oos" not in text


def test_wal_rows_survive_capture_without_source_writes(memory_case):
    _, _, worker, source, _, memory = memory_case
    conn = connect(source)
    with conn:
        SqliteStrategyRepository(conn).record_run("backtest", "wal-result",
                                                metrics={"total_return_is": -0.2})
    files = [source, Path(str(source) + "-wal"), Path(str(source) + "-shm")]
    before = {p: p.read_bytes() for p in files if p.exists()}

    memory.capture(worker, worker_exit=124, source_commit="b" * 40)

    assert {p: p.read_bytes() for p in files if p.exists()} == before
    assert memory.read()["worker_exit"] == 124
    assert memory.read()["evaluations"][0]["strategy_name"] == "wal-result"
    conn.close()


@pytest.mark.parametrize("fault", [
    "schema", "rows", "bytes", "json", "window-json", "config", "archive-bytes",
])
def test_source_errors_retain_worktree_without_receipt(memory_case, fault):
    _, cycle, worker, source, archive, _ = memory_case
    _explore(source)
    limits = (MemoryLimits(max_rows=1) if fault == "rows" else
              MemoryLimits(max_database_bytes=16) if fault == "bytes" else
              MemoryLimits(max_config_bytes=4) if fault == "config" else
              MemoryLimits(max_archive_bytes=50) if fault == "archive-bytes" else MemoryLimits())
    if fault in ("schema", "json", "window-json"):
        conn = connect(source)
        with conn:
            if fault == "schema":
                conn.execute("PRAGMA user_version=999")
            else:
                conn.execute("UPDATE runs SET config_json='not-json' WHERE id=2")
                if fault == "window-json":
                    conn.execute("UPDATE runs SET kind='walk_forward' WHERE id=2")
        conn.close()
    memory = ResearchMemory(cycle, archive, limits=limits)

    with pytest.raises((ValueError, sqlite3.Error)):
        memory.capture(worker, worker_exit=1, source_commit="b" * 40)

    assert not memory.cleanup_allowed(worker)
    assert worker.exists()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]


def test_disabled_or_remote_tracking_cannot_admit_cleanup(memory_case, monkeypatch):
    _, _, worker, source, archive, memory = memory_case
    _explore(source)

    def fail(*args, **kwargs):
        raise OSError("SYNTHETIC_FIXTURE tracking unavailable")

    monkeypatch.setattr(archive, "publish", fail)
    with pytest.raises(OSError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    with pytest.raises(ValueError):
        LocalResearchArchive("https://tracking.invalid")
    with pytest.raises(ValueError):
        LocalResearchArchive("unused.db", backend="noop")


def test_missing_seed_never_imports_inherited_history(memory_case):
    _, cycle, worker, source, archive, _ = memory_case
    metadata = json.loads(cycle.path.read_text())
    metadata.pop("research_memory")
    cycle.path.write_text(json.dumps(metadata))
    memory = ResearchMemory(cycle, archive)

    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    assert source.exists()


def test_model_references_survive_without_resolving_or_copying_model_bytes(memory_case):
    _, _, worker, source, _, memory = memory_case
    ref = {"name": "fixture-model", "version": 1, "digest": "a" * 64,
           "training_as_of": "2026-01-01T00:00:00+00:00", "provenance_digest": "b" * 64}
    conn = connect(source)
    with conn:
        SqliteStrategyRepository(conn).record_run("backtest", "model-fixture", components=[ref])
    conn.close()

    memory.capture(worker, worker_exit=0, source_commit="b" * 40)

    payload = memory.read()
    assert payload["evaluations"][0]["model_refs"] == [ref]
    assert payload["coverage"]["model_bytes_preserved"] is False


def test_source_changes_during_copy_refuse_retention_receipt(memory_case, monkeypatch):
    from algua.registry import read_snapshot

    _, cycle, worker, source, _, memory = memory_case
    _explore(source)
    copy = read_snapshot.shutil.copyfile

    def changed(src, dst):
        result = copy(src, dst)
        if Path(src) == source:
            with source.open("ab") as stream:
                stream.write(b"SYNTHETIC_FIXTURE changed source")
        return result

    monkeypatch.setattr(read_snapshot.shutil, "copyfile", changed)
    with pytest.raises(sqlite3.OperationalError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
    assert worker.exists()


def test_existing_sweep_truncation_is_not_reported_as_complete(memory_case):
    _, _, worker, source, _, memory = memory_case
    conn = connect(source)
    with conn:
        SqliteStrategyRepository(conn).record_run("sweep", "capped-fixture",
                                                trials_truncated_at=10000)
    conn.close()

    memory.capture(worker, worker_exit=0, source_commit="b" * 40)

    coverage = memory.read()["coverage"]
    assert coverage["truncated_sweeps"] == [{
        "source_ref": "scratch:fixture-memory:runs:2", "retained_limit": 10000}]
    assert coverage["unrecorded_variant_failures"] == "UNKNOWN"


@pytest.mark.parametrize("location", ["database", "artifacts", "metadata"])
def test_retention_cannot_delete_its_own_evidence(memory_case, location):
    _, cycle, worker, source, _, _ = memory_case
    _explore(source)
    disposable = LocalResearchArchive(f"sqlite:///{worker.parent / 'other.db'}")
    if location == "database":
        disposable = LocalResearchArchive(f"sqlite:///{worker / 'scratch-tracking.db'}")
    elif location == "artifacts":
        disposable.artifact_root = worker / "disposable-artifacts"
    else:
        destination = worker / "disposable-cycle.json"
        cycle.path.rename(destination)
        cycle.path = destination
    memory = ResearchMemory(cycle, disposable)

    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    assert not disposable.database.exists()


def test_actual_sweep_parent_mean_survives_truncated_trial_round_trip(memory_case, monkeypatch):
    from algua.backtest.sweep import SweepResult
    from algua.registry import runs
    from algua.registry.store import runs as store_runs

    _, _, worker, source, _, memory = memory_case
    # Exercise the real recorder's cap and parent stamp with a small fixture distribution.
    monkeypatch.setattr(runs, "MAX_PERSISTED_TRIALS", 2)
    monkeypatch.setattr(store_runs, "MAX_PERSISTED_TRIALS", 2)
    ranked = [{"params": {"n": n}, "config_hash": f"fixture-{n}",
               "stability": {"mean_sharpe": score}}
              for n, score in [(2, -0.1), (3, -0.2), (4, -1.5)]]
    result = SweepResult(
        strategy="SYNTHETIC_FIXTURE capped sweep", data_source="fixture", snapshot_id=None,
        timeframe="1d", seed=7, period={"start": "2026-01-01", "end": "2026-02-01"},
        windows=2, holdout_frac=0.2, grid={"n": [2, 3, 4]}, n_combos=3,
        rank_by="mean_sharpe", ranked=ranked, best=ranked[0],
        trial_sharpe_count=3, trial_sharpe_mean=-0.6)
    conn = connect(source)
    with conn:
        recorded = runs.record_sweep_run(SqliteStrategyRepository(conn), result.strategy, result)
        conn.execute("INSERT INTO run_metrics(run_id,key,value) VALUES (?, ?, ?)",
                     (recorded["run_id"], "private_holdout_diagnostic", 999.123))
    conn.close()
    assert recorded["trials_written"] == recorded["trials_truncated_at"] == 2

    memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    payload = memory.read()
    parent, *children = payload["evaluations"]

    assert parent["extra_metrics"] == {"mean_trial_sharpe": -0.6}
    assert len(children) == 2
    assert [child["inputs"]["params"] for child in children] == [{"n": 2}, {"n": 3}]
    assert payload["coverage"]["truncated_sweeps"] == [{
        "source_ref": parent["source_ref"], "retained_limit": 2}]
    assert "private_holdout_diagnostic" not in json.dumps(payload)
    assert "999.123" not in json.dumps(payload)
    assert memory.cleanup_allowed(worker)
    shutil.rmtree(worker)
    assert memory.read() == payload


@pytest.mark.parametrize("kind, config", [
    ("backtest", {"portfolio_replay": {"symbols": ["FIXTURE"], "weights": [1.0]}}),
    ("walk_forward", {"portfolio_replay": {"symbols": ["FIXTURE"]}}),
    ("backtest", {"future_input_namespace": {"cost": 0.03}}),
])
def test_unsupported_input_namespaces_refuse_cleanup(memory_case, kind, config):
    _, cycle, worker, source, _, memory = memory_case
    conn = connect(source)
    with conn:
        run_id = SqliteStrategyRepository(conn).record_run(kind, "SYNTHETIC_FIXTURE new inputs")
        # The worker database can contain a newer/legacy shape than its public reader knows.
        conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps(config), run_id))
    conn.close()

    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    assert source.exists()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]


@pytest.mark.parametrize("lineage", ["not-json", '{}', '[true]', '[0]', '[-1]'])
def test_raw_window_lineage_cannot_be_silently_salvaged(memory_case, lineage):
    _, cycle, worker, source, _, memory = memory_case
    conn = connect(source)
    with conn:
        row = SqliteStrategyRepository(conn).record_run("walk_forward", "fixture-lineage")
        conn.execute("UPDATE runs SET derived_from=? WHERE id=?", (lineage, row))
    conn.close()

    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    assert source.exists()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]


@pytest.mark.parametrize("change", ["reset", "mutate", "delete"])
def test_seeded_prefix_changes_or_reset_reused_ids_cannot_look_inherited(memory_case, change):
    _, cycle, worker, source, _, memory = memory_case
    if change == "reset":
        for path in (source, Path(str(source) + "-wal"), Path(str(source) + "-shm")):
            path.unlink(missing_ok=True)
    conn = connect(source)
    migrate(conn)
    with conn:
        if change == "reset":
            reused = SqliteStrategyRepository(conn).record_run(
                "backtest", "SYNTHETIC_FIXTURE reused id", metrics={"total_return_is": -0.8})
            assert reused == 1
        elif change == "mutate":
            conn.execute("UPDATE runs SET strategy_name='changed inherited run' WHERE id=1")
        else:
            conn.execute("DELETE FROM runs WHERE id=1")
    conn.close()

    with pytest.raises(ValueError):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    assert source.exists()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]


@pytest.mark.parametrize("memory_case", ["seeded-sweep"], indirect=True)
def test_inherited_public_overflow_is_part_of_the_seed_checkpoint(memory_case):
    _, cycle, worker, source, _, memory = memory_case
    conn = connect(source)
    with conn:
        conn.execute("UPDATE run_metrics SET value=-0.3 WHERE run_id=2 "
                     "AND key='mean_trial_sharpe'")
    conn.close()

    with pytest.raises(ValueError, match="inherited prefix changed"):
        memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    assert not memory.cleanup_allowed(worker)
    assert source.exists()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
