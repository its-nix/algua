"""Standalone CLI adapter over actual fixture cycles, SQLite and local MLflow artifacts."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from typer.testing import CliRunner

from algua.cli.research_memory_cmd import memory_app
from algua.config.settings import Settings
from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository
from algua.tracking.research_archive import LocalResearchArchive
from tests.campaign_fixtures import add_idea

runner = CliRunner()
_RUN = "fixture-cli-memory"
_COMMIT = "b" * 40


@pytest.fixture
def cli_memory(tmp_path, monkeypatch):
    # Never inherit a developer dotenv or configured store. The child app creates no settings
    # at import time; explicit process configuration below is all these invocations may use.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ALGUA_TRACKING_BACKEND=noop\n"
                                   "ALGUA_MLFLOW_TRACKING_URI=DOTENV_MUST_NOT_BE_READ.db\n")
    data = tmp_path / "authority-data"
    data.mkdir()
    database = data / "algua.db"
    tracking = tmp_path / "configured-tracking.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(database))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{tracking}")
    authority = connect(database)
    migrate(authority)
    add_idea(authority, "SYNTHETIC_FIXTURE CLI retention hypothesis", family="cli-retention")
    with authority:
        SqliteStrategyRepository(authority).record_run("backtest", "inherited-fixture")
    cycle = ResearchCycle(authority, data / "research-cycles", _RUN)
    cycle.start(limits=CycleLimits(max_hypotheses=1), context={"evidence_mode": "FIXTURE"},
                ttl_minutes=1440)
    worker = tmp_path / "disposable-worker"
    source = worker / ".funnel-scratch/data/algua.db"
    source.parent.mkdir(parents=True)
    with sqlite3.connect(source) as destination:
        authority.backup(destination)
    yield authority, cycle, worker, source, tracking
    authority.close()


def _invoke(command, worker=None, *, run=_RUN, **options):
    arguments = [command, "--run", run]
    if worker is not None:
        arguments.extend(["--worker-root", str(worker)])
    for key, value in options.items():
        arguments.extend(["--" + key.replace("_", "-"), str(value)])
    result = runner.invoke(memory_app, arguments)
    return result, json.loads(result.stdout)


def _seed_and_explore(worker: Path, source: Path):
    result, seed = _invoke("seed", worker)
    assert result.exit_code == 0, result.output
    assert seed["ok"] is True
    conn = connect(source)
    with conn:
        SqliteStrategyRepository(conn).record_run(
            "backtest", "SYNTHETIC_FIXTURE negative-result", config={"params": {"n": 3}},
            metrics={"sharpe_is": -0.7, "total_return_is": -0.25})
    conn.close()
    return seed


def _capture(worker):
    return _invoke("capture", worker, worker_exit=0, source_commit=_COMMIT)


def test_seed_capture_show_and_cleanup_check_use_actual_configured_store(cli_memory):
    authority, cycle, worker, source, tracking = cli_memory
    before = list(authority.iterdump())
    seed = _seed_and_explore(worker, source)
    assert seed["research_cycle_id"] == _RUN
    assert seed["seed"]["runs_max_id"] == 1

    result, captured = _capture(worker)
    assert result.exit_code == 0, result.output
    assert captured["ok"] is True
    receipt = captured["receipt"]
    assert receipt["tracking_uri"] == f"sqlite:///{tracking}"
    assert json.loads(cycle.path.read_text())["research_memory"]["receipt"] == receipt
    result, repeated = _capture(worker)
    assert result.exit_code == 0 and repeated == captured
    archive = LocalResearchArchive(f"sqlite:///{tracking}")
    assert len(archive.client.search_runs([archive.experiment_id])) == 1

    result, shown = _invoke("show")
    assert result.exit_code == 0, result.output
    assert shown["ok"] is True
    assert shown["evidence_mode"] == "UNVERIFIED_WORKER" and shown["authority"] == "none"
    assert shown["source_commit"] == _COMMIT and shown["worker_exit"] == 0
    assert [row["strategy_name"] for row in shown["evaluations"]] == [
        "SYNTHETIC_FIXTURE negative-result"]
    assert shown["evaluations"][0]["metrics"]["total_return_is"] == -0.25
    assert shown["evaluations"][0]["inputs"] == {"params": {"n": 3}}
    result, checked = _invoke("cleanup-check", worker)
    assert result.exit_code == 0, result.output
    assert checked == {"ok": True, "research_cycle_id": _RUN, "cleanup_allowed": True}
    assert worker.exists()  # The CLI proves retention; its caller owns actual cleanup.
    shutil.rmtree(worker)
    result, after_cleanup = _invoke("show")
    assert result.exit_code == 0 and after_cleanup == shown
    assert list(authority.iterdump()) == before
    assert not (tracking.parent / "DOTENV_MUST_NOT_BE_READ.db").exists()


@pytest.mark.parametrize("command", ["seed", "capture", "show", "cleanup-check"])
def test_unknown_cycle_is_json_error_and_never_created(cli_memory, command):
    authority, cycle, worker, _, tracking = cli_memory
    before = list(authority.iterdump())
    options = {"worker_exit": 0, "source_commit": _COMMIT} if command == "capture" else {}
    result, payload = _invoke(command, None if command == "show" else worker,
                              run="unknown-fixture-cycle", **options)

    assert result.exit_code != 0
    assert payload["ok"] is False
    assert {"error", "code", "retryable"} <= payload.keys()
    assert not (cycle.directory / "unknown-fixture-cycle.json").exists()
    assert not tracking.exists()
    assert list(authority.iterdump()) == before
    assert worker.exists()


@pytest.mark.parametrize("fault", ["no-seed", "missing-archive", "changed-archive", "new-source"])
def test_cleanup_check_refuses_unverified_evidence_with_json_and_nonzero(cli_memory, fault):
    _, _, worker, source, tracking = cli_memory
    if fault != "no-seed":
        _seed_and_explore(worker, source)
        captured_result, captured = _capture(worker)
        assert captured_result.exit_code == 0, captured_result.output
        if fault == "new-source":
            conn = connect(source)
            with conn:
                SqliteStrategyRepository(conn).record_run("backtest", "new-unarchived-fixture")
            conn.close()
        else:
            archive = LocalResearchArchive(f"sqlite:///{tracking}")
            uri = archive.client.get_run(captured["receipt"]["run_id"]).info.artifact_uri
            artifact = Path(unquote(urlsplit(uri).path)) / "public-evidence.json"
            if fault == "missing-archive":
                artifact.unlink()
            else:
                changed = json.loads(artifact.read_bytes())
                changed["worker_exit"] = 7
                artifact.write_text(json.dumps(changed))

    result, payload = _invoke("cleanup-check", worker)

    assert result.exit_code != 0
    assert payload["ok"] is False and payload["code"] == "invalid_input"
    assert "retain" in payload["error"].lower()
    assert worker.exists()


@pytest.mark.parametrize("backend, uri", [
    ("noop", None), ("mlflow", None), ("mlflow-sqlite", "https://tracking.invalid"),
])
def test_unsupported_configured_tracking_refuses_capture(cli_memory, monkeypatch, backend, uri):
    _, cycle, worker, source, tracking = cli_memory
    _seed_and_explore(worker, source)
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", backend)
    if uri is not None:
        monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", uri)

    result, payload = _capture(worker)

    assert result.exit_code != 0
    assert payload["ok"] is False and payload["code"] == "invalid_input"
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
    assert not tracking.exists()
    assert worker.exists()


def test_actual_broken_local_store_returns_json_and_retains_source(cli_memory):
    _, cycle, worker, source, tracking = cli_memory
    _seed_and_explore(worker, source)
    tracking.write_text("SYNTHETIC_FIXTURE not a SQLite database")

    result, payload = _capture(worker)

    assert result.exit_code != 0
    assert payload["ok"] is False
    assert {"error", "code", "retryable"} <= payload.keys()
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
    assert source.exists()


@pytest.mark.parametrize("options", [
    {"worker_exit": 0, "source_commit": "not-a-commit"},
    {"worker_exit": 999, "source_commit": _COMMIT},
])
def test_capture_invalid_inputs_are_json_errors_without_publication(cli_memory, options):
    _, cycle, worker, source, tracking = cli_memory
    _seed_and_explore(worker, source)

    result, payload = _invoke("capture", worker, **options)

    assert result.exit_code != 0
    assert payload["ok"] is False and payload["code"] == "invalid_input"
    assert "receipt" not in json.loads(cycle.path.read_text())["research_memory"]
    assert not tracking.exists()
    assert source.exists()


@pytest.mark.parametrize("arguments", [
    ["seed", "--worker-root", "."],
    ["seed", "--run", _RUN],
    ["capture", "--run", _RUN, "--worker-root", ".", "--source-commit", _COMMIT],
    ["capture", "--run", _RUN, "--worker-root", ".", "--worker-exit", "0"],
    ["show"],
    ["cleanup-check", "--run", _RUN],
])
def test_required_options_are_rejected_by_standalone_typer_app(arguments):
    # Argument-parse JSON wrapping belongs to the existing main composition root, which this
    # isolated adapter does not alter. The options themselves must already be required here.
    result = runner.invoke(memory_app, arguments)
    assert result.exit_code != 0
