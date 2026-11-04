"""Operative retention adapters with real SQLite/MLflow/git and explicit fixture workers.

These are integration fixtures, never model calls or autonomous-cycle acceptance evidence.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.operator.research_memory import ResearchMemory
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository
from algua.tracking.research_archive import LocalResearchArchive
from tests.campaign_fixtures import add_idea

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / ".opencode/scripts/run-research-loop.sh"
QUEUE = ROOT / ".opencode/scripts/mergeback_queue.py"
STAMP = "20260101-000000"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def prepare_memory(repo, worker, *, stamp=STAMP, claimed=False, retained=True):
    """Install a real configured fixture archive; no authority is imported from the worker."""
    data = repo / "data"
    data.mkdir(exist_ok=True)
    conn = connect(data / "algua.db")
    migrate(conn)
    if claimed:
        add_idea(conn, "SYNTHETIC_FIXTURE driver memory hypothesis", family="memory-driver")
    cycle = ResearchCycle(conn, data / "research-cycles", stamp)
    cycle.start(limits=CycleLimits(max_hypotheses=1), context={"evidence_mode": "FIXTURE"},
                ttl_minutes=1440)
    source = worker / ".funnel-scratch/data/algua.db"
    source.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as destination:
        conn.backup(destination)
    archive = LocalResearchArchive(f"sqlite:///{repo / 'tracking.db'}")
    memory = ResearchMemory(cycle, archive)
    if retained:
        memory.seed(worker)
        local = connect(source)
        with local:
            SqliteStrategyRepository(local).record_run(
                "backtest", "SYNTHETIC_FIXTURE public negative", config={"params": {"n": 7}},
                metrics={"total_return_is": -0.2})
        local.close()
        memory.capture(worker, worker_exit=0, source_commit=_git(repo, "rev-parse", "HEAD"))
    conn.close()
    # The real main composition root is invoked from the trusted fake main CWD. No primitive,
    # archive, JSON formatter or command implementation is substituted.
    executable = repo / ".venv/bin/algua"
    executable.parent.mkdir(parents=True, exist_ok=True)
    program = (f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
               "from algua.config.settings import Settings; "
               "Settings.model_config['env_file']=None; "
               "from algua.cli.main import main; main()")
    executable.write_text("#!/bin/sh\nexec " + shlex.join([sys.executable, "-c", program])
                          + ' "$@"\n')
    executable.chmod(0o755)
    return cycle.path, archive


def canonical_worker(source: Path, expected: Path) -> None:
    """Actual backtest/recorder on explicitly synthetic flat bars, never market evidence."""
    from algua.backtest._sample import SyntheticProvider
    from algua.backtest.engine import run
    from algua.data.research_provenance import DataTier, ProvenanceDeclaration
    from algua.data.serve import StoreBackedProvider
    from algua.data.store import DataStore
    from algua.primitives.timeparse import utc
    from algua.registry.runs import record_backtest_run
    from algua.strategies.loader import load_strategy

    strategy = load_strategy("cross_sectional_momentum")
    start, end = "2024-01-01", "2024-12-31"
    frame = SyntheticProvider(seed=21, drift=0, vol=0).get_bars(
        strategy.universe, utc(start), utc(end), "1d")
    frame = frame[frame.index < utc(end)].reset_index().rename(columns={"timestamp": "ts"})
    store = DataStore(source.parent)
    rec = store.ingest_bars(
        provider="fixture", symbols=strategy.universe, start=start, end=end,
        as_of="2025-01-01T00:00:00+00:00", source="engineering-fixture", frame=frame,
        provenance=ProvenanceDeclaration(
            DataTier.SYNTHETIC_FIXTURE, "fixture/v1", ("synthetic_not_market_data",)))
    result = run(strategy, StoreBackedProvider(store, rec.snapshot_id), utc(start), utc(end))
    assert result.metrics["total_return"] <= 0
    conn = connect(source)
    with conn:
        record_backtest_run(SqliteStrategyRepository(conn), strategy.config.name, result,
                            params=strategy.config.params)
    conn.close()
    expected.write_text(json.dumps({
        "inputs": {"params": strategy.config.params,
                   "run_provenance": {"bars": rec.to_dict(),
                                      "execution_costs": result.execution_costs}},
        "total_return_is": result.metrics["total_return"], "snapshot_id": rec.snapshot_id,
        "seed": result.seed,
    }))


@pytest.fixture
def driver_memory(tmp_path, monkeypatch, request):
    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "SYNTHETIC_FIXTURE")
    (repo / "seed.txt").write_text("SYNTHETIC_FIXTURE\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "fixture seed")
    worker = (repo.parent / f"algua-research-{STAMP}"
              if getattr(request, "param", None) == "legacy" else repo / ".runs" / STAMP)
    (repo / ".runs").mkdir(exist_ok=True)
    _git(repo, "worktree", "add", "-b", f"research-run/{STAMP}", str(worker))
    metadata, archive = prepare_memory(repo, worker, claimed=True,
                                       retained=getattr(request, "param", None) != "fresh")
    monkeypatch.setenv("ALGUA_DB_PATH", str(repo / "data/algua.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(repo / "data"))
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{repo / 'tracking.db'}")
    return repo, worker, metadata, archive


def _artifact(metadata, archive):
    receipt = json.loads(metadata.read_text())["research_memory"]["receipt"]
    uri = archive.client.get_run(receipt["run_id"]).info.artifact_uri
    return Path(unquote(urlsplit(uri).path)) / "public-evidence.json"


def _function(text, name, end):
    return text[text.index(name + "() {"):text.index(end, text.index(name + "() {"))]


def _operative_seed(text):
    command = 'memory_cli seed --run "${STAMP}" --worker-root "${WORKTREE}"'
    assert text.count(command) == 1
    seed = text.index(command)
    backup = text.index("with dst: src.backup(dst)")
    scrub_done = text.index("dst.close()", backup)
    context_check = text.index("research idea cycle-check", scrub_done)
    worker = text.index('RUN_LOG="${WORKTREE}')
    assert backup < scrub_done < context_check < seed < worker
    return text[seed:text.index("\n", seed) + 1]


def _preamble(repo, worker):
    values = {
        "REPO_ROOT": str(repo), "RUNS_DIR": str(repo / ".runs"), "WORKTREE": str(worker),
        "STAMP": STAMP, "FINAL_BRANCH": f"research-run/{STAMP}",
        "DIGEST_BRANCH": f"research-run/{STAMP}", "AUTH_DB": str(repo / "data/algua.db"),
        "AUTH_DATA_DIR": str(repo / "data"), "AUTH_TRACKING_BACKEND": "mlflow-sqlite",
        "AUTH_TRACKING_URI": f"sqlite:///{repo / 'tracking.db'}", "N_ENQUEUED": "0",
        "RETENTION_DAYS": "7", "PYTHON": sys.executable,
        "AUTH_DIGEST": str(repo / "data/digest.jsonl"),
        "AUTH_QUEUE": str(repo / "data/queue.json"),
        "AUTH_QUEUE_LOCK": str(repo / "data/queue.lock"), "QUEUE_MOD": str(QUEUE),
        "BRANCH": f"research-run/{STAMP}", "CATEGORY": "", "CYCLE_CAMPAIGN": "",
        "CLAIMED_JSON": "[]", "CYCLE_ACTIVE": "1", "CYCLE_PHASE": "driver_failed",
        "CYCLE_RESULT": str(repo / f"data/research-cycles/{STAMP}.result.json"),
        "rc": "0", "WORKER_EXIT": "0", "wall_s": "1", "timed_out": "0",
        "rate_limited": "0", "n_strategy_files": "0", "STRATEGY_MODULE_NAMES": "",
        "DIGEST_REPORT_PATH": "", "N_CLAIMED": "1",
    }
    command = "set -euo pipefail\n" + "\n".join(
        f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n"
    command += "AUTH_CLI=(" + shlex.quote(str(repo / ".venv/bin/algua")) + ")\n"
    driver = DRIVER.read_text()
    if "memory_cli() {" in driver:
        command += _function(driver, "memory_cli", "\n# Durable feedback digest")
    command += _function(driver, "archive_run_log", "\n# BACKSTOP mtime pruner")
    return command


def _bash(command, repo):
    command = command.replace("python3 - ", shlex.quote(sys.executable) + " - ")
    return subprocess.run(["bash", "-c", command], cwd=repo, env=os.environ.copy(),
                          capture_output=True, text=True, timeout=60)


def test_zero_candidate_path_retains_missing_archive(driver_memory):
    repo, worker, metadata, archive = driver_memory
    _artifact(metadata, archive).unlink()
    text = DRIVER.read_text()
    block = text[text.index('if [[ "${N_ENQUEUED:-}" == "0" ]]'):
                 text.index('\necho\necho "Done. Review')]

    result = _bash(_preamble(repo, worker) + block, repo)

    assert worker.exists(), result.stdout + result.stderr


@pytest.mark.parametrize("legacy", [False, True])
def test_mtime_pruner_retains_missing_archive_in_both_locations(driver_memory, legacy):
    repo, worker, metadata, archive = driver_memory
    _artifact(metadata, archive).unlink()
    if legacy:
        target = repo.parent / f"algua-research-{STAMP}"
        _git(repo, "worktree", "move", str(worker), str(target))
        worker = target
    os.utime(worker, (time.time() - 10 * 86400,) * 2)
    text = DRIVER.read_text()
    block = text[text.index('RETENTION_DAYS="${RESEARCH_WORKTREE_RETENTION_DAYS'):
                 text.index('\necho "Creating worktree')]

    result = _bash(_preamble(repo, worker) + block, repo)

    assert worker.exists(), result.stdout + result.stderr


def test_setup_trap_retains_missing_archive(driver_memory):
    repo, worker, metadata, archive = driver_memory
    _artifact(metadata, archive).unlink()
    text = DRIVER.read_text()
    cleanup = _function(text, "cleanup_setup", "\n# Lock BEFORE any claim")
    command = (_preamble(repo, worker) + cleanup
               + '\nCYCLE_PHASE=setup_failed\nrecord_outcomes() { return 0; }\n'
               + 'append_digest() { return 0; }\ntrap cleanup_setup EXIT\nexit 17\n')

    result = _bash(command, repo)

    assert result.returncode == 17
    assert worker.exists(), result.stdout + result.stderr


def test_terminal_queue_retains_missing_archive(driver_memory):
    repo, worker, metadata, archive = driver_memory
    _artifact(metadata, archive).unlink()
    spec = importlib.util.spec_from_file_location("memory_fixture_queue", QUEUE)
    queue = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue)
    result = queue.cleanup_branch(repo / "data/queue.json", repo / "data/queue.lock",
                                  branch=f"research-run/{STAMP}", repo_root=repo)

    assert result["removed"] is False
    assert worker.exists()


@pytest.mark.parametrize("fault", ["missing-seed", "bad-config", "new-source", "changed", "root"])
def test_zero_candidate_path_refuses_other_unverified_states(driver_memory, fault):
    repo, worker, metadata, archive = driver_memory
    original = worker
    if fault == "missing-seed":
        value = json.loads(metadata.read_text())
        value["research_memory"].pop("seed")
        metadata.write_text(json.dumps(value))
    elif fault == "new-source":
        conn = connect(worker / ".funnel-scratch/data/algua.db")
        with conn:
            SqliteStrategyRepository(conn).record_run("backtest", "unarchived-fixture")
        conn.close()
    elif fault == "changed":
        artifact = _artifact(metadata, archive)
        value = json.loads(artifact.read_text())
        value["worker_exit"] = 7
        artifact.write_text(json.dumps(value))
    elif fault == "root":
        worker = repo / "wrong-prefix" / STAMP
        worker.mkdir(parents=True)
        (worker / "must-retain.txt").write_text("SYNTHETIC_FIXTURE wrong root")
    text = DRIVER.read_text()
    block = text[text.index('if [[ "${N_ENQUEUED:-}" == "0" ]]'):
                 text.index('\necho\necho "Done. Review')]
    command = _preamble(repo, worker)
    if fault == "bad-config":
        command += 'AUTH_TRACKING_BACKEND=noop\n'

    result = _bash(command + block, repo)

    assert original.exists() and worker.exists(), result.stdout + result.stderr


@pytest.mark.parametrize("driver_memory", [None, "legacy"], indirect=True)
def test_mtime_pruner_reclaims_verified_archive_in_both_locations(driver_memory):
    repo, worker, _, _ = driver_memory
    os.utime(worker, (time.time() - 10 * 86400,) * 2)
    text = DRIVER.read_text()
    block = text[text.index('RETENTION_DAYS="${RESEARCH_WORKTREE_RETENTION_DAYS'):
                 text.index('\necho "Creating worktree')]

    result = _bash(_preamble(repo, worker) + block, repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not worker.exists(), result.stdout + result.stderr


def _queue_module():
    spec = importlib.util.spec_from_file_location("memory_fixture_queue", QUEUE)
    queue = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(queue)
    return queue


def test_queue_fallback_revalidates_after_real_git_refusal(driver_memory, monkeypatch):
    repo, worker, metadata, archive = driver_memory
    (worker / ".git").unlink()  # Genuine unregistered-directory failure from git, not a fake git.
    artifact = _artifact(metadata, archive)
    queue = _queue_module()
    run = queue.subprocess.run
    git_failed = []

    def invalidate_after_git(command, **kwargs):
        result = run(command, **kwargs)
        if command[0] == "git" and command[3:5] == ["worktree", "remove"]:
            assert result.returncode != 0
            artifact.unlink()
            git_failed.append(True)
        return result

    monkeypatch.setattr(queue.subprocess, "run", invalidate_after_git)
    result = queue.cleanup_branch(repo / "data/queue.json", repo / "data/queue.lock",
                                  branch=f"research-run/{STAMP}", repo_root=repo)

    assert git_failed and worker.exists()
    assert result["skipped"] == "research_memory_unverified"


def test_queue_verification_timeout_retains_source_and_economic_status(driver_memory, monkeypatch):
    repo, worker, _, _ = driver_memory
    queue = _queue_module()
    path, lock = repo / "data/queue.json", repo / "data/queue.lock"
    branch = f"research-run/{STAMP}"
    queue.enqueue(path, lock, strategy="fixture", branch=branch, universe="fixture",
                  start="2024-01-01", end="2024-12-31",
                  eval_context={"demo": True, "sweep_grid": {"n": [1]}, "rank_by": "mean_sharpe"})
    queue.record_attempt(path, lock, key=f"fixture@{branch}",
                         stdout_text=json.dumps({"ok": True, "status": "promoted_allocated"}))
    before = path.read_bytes()
    run = queue.subprocess.run

    def timeout(command, **kwargs):
        if "cleanup-check" in command:
            assert kwargs["cwd"] == repo and kwargs["timeout"] == 30
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return run(command, **kwargs)

    monkeypatch.setattr(queue.subprocess, "run", timeout)
    result = queue.cleanup_branch(path, lock, branch=branch, repo_root=repo)

    assert result["skipped"] == "research_memory_unverified"
    assert worker.exists() and path.read_bytes() == before


def test_driver_fallback_revalidates_after_real_git_refusal(driver_memory):
    repo, worker, metadata, archive = driver_memory
    (worker / ".git").unlink()
    artifact = _artifact(metadata, archive)
    marker = repo / "fixture-git-refused"
    fault_bin = repo / "fault-bin"
    fault_bin.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    invalidate = shlex.join([sys.executable, "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).unlink(); "
        "Path(sys.argv[2]).write_text('SYNTHETIC_FIXTURE refusal')", str(artifact), str(marker)])
    # Real git returns the refusal. Only the between-check archive-loss fault is injected.
    (fault_bin / "git").write_text(
        '#!/bin/sh\n' + shlex.quote(real_git) + ' "$@"\ncode=$?\n'
        + 'if [ "$3:$4" = worktree:remove ] && [ "$code" -ne 0 ]; then\n'
        + invalidate + '\nfi\nexit "$code"\n')
    (fault_bin / "git").chmod(0o755)
    command = _preamble(repo, worker)
    command += f'export PATH={shlex.quote(str(fault_bin))}:"$PATH"\n'
    command += '\nremove_retained_worktree "$WORKTREE" "$STAMP"\n'

    result = _bash(command, repo)

    assert result.returncode != 0
    assert marker.exists() and worker.exists()


@pytest.mark.parametrize("driver_memory", ["fresh"], indirect=True)
def test_seed_failure_prevents_fixture_worker_and_retains_source(driver_memory):
    repo, worker, _, _ = driver_memory
    source = worker / ".funnel-scratch/data/algua.db"
    conn = connect(source)
    with conn:
        conn.execute("PRAGMA user_version=999")
    conn.close()
    marker = repo / "fixture-worker-started"
    text = DRIVER.read_text()
    cleanup = _function(text, "cleanup_setup", "\n# Lock BEFORE any claim")
    command = _preamble(repo, worker) + cleanup
    command += ('\nCYCLE_PHASE=setup_failed\nrecord_outcomes() { return 0; }\n'
                'append_digest() { return 0; }\ntrap cleanup_setup EXIT\n')
    command += '\n' + _operative_seed(text)
    command += 'touch ' + shlex.quote(str(marker)) + '\n'

    result = _bash(command, repo)

    assert result.returncode != 0 and worker.exists() and not marker.exists()


@pytest.mark.parametrize("driver_memory", ["fresh"], indirect=True)
@pytest.mark.parametrize("worker_exit, archive_failure, canonical", [
    (0, False, False), (3, False, False), (0, True, False), (0, False, True),
])
def test_actual_seed_worker_capture_finish_cleanup_and_show(
        driver_memory, worker_exit, archive_failure, canonical):
    repo, worker, metadata, _ = driver_memory
    driver = DRIVER.read_text()
    source = worker / ".funnel-scratch/data/algua.db"
    source.unlink()
    report = worker / f"kb/research-runs/{STAMP}.md"
    report.parent.mkdir(parents=True)
    report.write_text('```json\n' + json.dumps({"hypotheses": [{
        "idea_id": 1, "title": "SYNTHETIC_FIXTURE negative hypothesis",
        "outcome": "sweep_unstable", "reason": "SYNTHETIC_FIXTURE negative result"}]}) + '\n```')
    authored = worker / "algua/strategies/fixture_memory.py"
    authored.parent.mkdir(parents=True)
    authored.write_text("# SYNTHETIC_FIXTURE driver-scoped commit input, never executed.\n")
    # Worker .env and exported scratch routing must never steer trusted retention commands.
    (worker / ".env").write_text("ALGUA_TRACKING_BACKEND=noop\n")
    command = _preamble(repo, worker)
    authority = connect(repo / "data/algua.db")
    claim = dict(authority.execute(
        "SELECT idea_id AS id,claim_token FROM idea_attempts").fetchone())
    authority.close()
    command += 'CLAIMED_JSON=' + shlex.quote(json.dumps([claim])) + '\n'
    command += f'export ALGUA_DB_PATH={shlex.quote(str(source))}\n'
    command += f'export ALGUA_DATA_DIR={shlex.quote(str(source.parent))}\n'
    command += 'export ALGUA_TRACKING_BACKEND=noop\n'
    command += f'export ALGUA_MLFLOW_TRACKING_URI={shlex.quote(str(worker / "wrong.db"))}\n'
    command += 'ALLOW_EMPTY_FUNNEL=0\n'
    command += driver[driver.index('if [[ -f "${AUTH_DB}" ]]'):
                      driver.index('\n# Per-run COPY of the immutable snapshots')]
    command += '\n' + _operative_seed(driver)
    worker_program = (
        "import os; from pathlib import Path; from algua.registry.db import connect; "
        "from algua.registry.store import SqliteStrategyRepository; "
        "c=connect(Path(os.environ['ALGUA_DB_PATH'])); "
        "SqliteStrategyRepository(c).record_run('backtest','SYNTHETIC_FIXTURE public negative',"
        "config={'params':{'n':7}},metrics={'total_return_is':-0.2}); c.commit(); c.close(); "
        f"raise SystemExit({worker_exit})")
    if canonical:
        worker_program = (
            "import os; from pathlib import Path; "
            "from tests.test_research_memory_driver import canonical_worker; "
            "canonical_worker(Path(os.environ['ALGUA_DB_PATH']), "
            f"Path({str(worker / 'canonical-expected.json')!r}))")
    command += 'AGENT_CMD=(' + shlex.join([sys.executable, '-c', worker_program]) + ')\n'
    command += f'PROMPT_FILE={shlex.quote(str(worker / "fixture-prompt.txt"))}\nGOAL=FIXTURE\n'
    command += driver[driver.index('RUN_LOG="${WORKTREE}'):
                      driver.index("\n# The agent doesn't commit")]
    if canonical:
        command += 'cp "$WORKTREE/canonical-expected.json" "$REPO_ROOT/canonical-expected.json"\n'
    command += driver[driver.index('echo "Committing any authored strategies'):
                      driver.index('\n# Durable feedback digest: append the COMPLETED')]
    command += _function(driver, "record_outcomes", "\n# Armed before claiming")
    command += _function(driver, "append_digest", "\n# Close the ideation loop")
    if archive_failure:
        # A supported-schema but unprojected input is an actual capture refusal.
        command += shlex.join([sys.executable, '-c',
            "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
            "c.execute(\"UPDATE runs SET config_json='{\\\"portfolio_replay\\\":{}}'\"); "
            "c.commit(); c.close()", str(source)]) + '\n'
    command += driver[driver.index('echo "Appending run digest'):
                      driver.index('\n# The digest step may have RENAMED')]
    command += driver[driver.index('if [[ "${N_ENQUEUED:-}" == "0" ]]'):
                      driver.index('\necho\necho "Done. Review')]
    shown = repo / "retained-show.json"
    command += f'\nmemory_cli show --run "$STAMP" > {shlex.quote(str(shown))}\nexit "$rc"\n'

    result = _bash(command, repo)
    conn = connect(repo / "data/algua.db")
    attempt = conn.execute("SELECT outcome,reason,evidence_ref FROM idea_attempts").fetchone()
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    for table in ("strategies", "stage_transitions", "approvals"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    conn.close()
    digest = json.loads((repo / "data/digest.jsonl").read_text())
    if archive_failure:
        assert result.returncode != 0, result.stdout + result.stderr
        assert worker.exists() and attempt["outcome"] == "run_error"
        assert attempt["reason"] == "driver_failed:0"
        assert digest["outcome"] == "driver_failed" and digest["hypotheses"] == []
        assert "receipt" not in json.loads(metadata.read_text())["research_memory"]
    else:
        assert result.returncode == worker_exit, result.stdout + result.stderr
        assert not worker.exists()
        payload = json.loads(shown.read_text())
        assert payload["worker_exit"] == worker_exit
        evaluation = payload["evaluations"][0]
        if canonical:
            expected = json.loads((repo / "canonical-expected.json").read_text())
            assert evaluation["metrics"]["total_return_is"] == expected["total_return_is"] <= 0
            assert evaluation["inputs"] == expected["inputs"]
            assert evaluation["provenance"]["snapshot_id"] == expected["snapshot_id"]
            assert evaluation["provenance"]["seed"] == expected["seed"]
        else:
            assert evaluation["metrics"]["total_return_is"] == -0.2
        assert payload["authority"] == "none"
        assert attempt["evidence_ref"].startswith("mlflow:")
        assert attempt["outcome"] == ("sweep_unstable" if worker_exit == 0 else "run_error")
        assert digest["exit_code"] == worker_exit
    assert not (repo / "data/queue.json").exists()
