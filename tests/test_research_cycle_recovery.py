"""Disposable registries and trusted fixture workers; not autonomous research proof."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).resolve().parents[1] / ".opencode/scripts/run-research-loop.sh"


def _legacy_outcomes(tmp_path, monkeypatch, rows, *, worker_exit="0", fail_write=False):
    """Execute the actual driver's outcome code with a trusted CLI response fixture."""
    sources = re.findall(r"<<'PY'[^\n]*\n(.*?)\n^PY$", DRIVER.read_text(), re.S | re.M)
    report = tmp_path / "report.md"
    report.write_text("```json\n" + json.dumps(
        {"hypotheses": [{"title": "Fixture", **r} for r in rows]}) + "\n```\n")
    calls = []

    def record(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, int(fail_write), "", "fixture write failure")

    monkeypatch.setattr(subprocess, "run", record)
    monkeypatch.setattr(sys, "argv", ["-", '[{"id":7,"claim_token":"token"}]',
                                    str(report), "/disposable.db", "branch", "cycle", worker_exit,
                                    str(tmp_path), "completed"])
    namespace = {"__name__": "__main__"}
    try:
        exec(compile(sources[1], str(DRIVER), "exec"), namespace)
    except SystemExit as exc:
        return exc.code, calls
    return 0, calls


def test_outcome_write_failure_cannot_report_success(tmp_path, monkeypatch):
    code, calls = _legacy_outcomes(tmp_path, monkeypatch, [], fail_write=True)
    assert len(calls) == 1
    assert code == 1


def test_duplicate_report_is_error_not_last_wins(tmp_path, monkeypatch):
    row = {"idea_id": 7, "outcome": "candidate_preview_pass", "reason": "fixture"}
    code, calls = _legacy_outcomes(tmp_path, monkeypatch, [row, row])
    assert calls[0][calls[0].index("--outcome") + 1] == "run_error"


def test_provider_exhaustion_cannot_accept_partial_success(tmp_path, monkeypatch):
    row = {"idea_id": 7, "outcome": "candidate_preview_pass", "reason": "partial"}
    code, calls = _legacy_outcomes(tmp_path, monkeypatch, [row], worker_exit="3")
    assert calls[0][calls[0].index("--outcome") + 1] == "run_error"


@pytest.fixture
def cycle(tmp_path):
    from algua.operator.research_cycle import ResearchCycle
    from algua.registry.db import connect, migrate
    from algua.registry.ideas import IdeaRepository
    from tests.test_idea_attempts import _seed

    conn = connect(tmp_path / "fixture.db")
    migrate(conn)
    _seed(IdeaRepository(conn), n=3, category="momentum")
    yield ResearchCycle(conn, tmp_path / "cycles", "fixture-cycle")
    conn.close()


def _start(cycle, **kwargs):
    from algua.operator.research_cycle import CycleLimits
    return cycle.start(limits=kwargs.pop("limits", CycleLimits(max_hypotheses=2)),
                       context=kwargs.pop("context", {"snapshot": "fixture-pinned"}),
                       ttl_minutes=180, **kwargs)


def _report(tmp_path, rows):
    path = tmp_path / "report.md"
    path.write_text("```json\n" + json.dumps(
        {"hypotheses": [{"title": "Fixture", **r} for r in rows]}) + "\n```\n")
    return path


def test_identity_context_is_detached_and_immutable(cycle):
    context = {"snapshot": "fixture-pinned", "nested": {"seed": 42}}
    claimed, running = _start(cycle, context=context)
    assert len(claimed) == 2 and running["unfinished_count"] == 2
    stored = cycle.path.read_bytes()
    context["nested"]["seed"] = 43
    with pytest.raises(ValueError, match="immutable"):
        _start(cycle, context=context)
    assert cycle.path.read_bytes() == stored
    assert len(cycle.rows()) == 2


def test_scratch_inventory_and_setup_context_must_match(cycle, tmp_path):
    from algua.operator.research_cycle import file_hash

    data = tmp_path / "scratch-data"
    data.mkdir()
    manifest = data / "manifest.jsonl"
    manifest.write_text('{"snapshot_id":"fixture-pinned"}\n')
    context = {"data_manifest_sha256": file_hash(manifest), "seed": 42}
    _start(cycle, context=context)
    cycle.verify_context(context=context, scratch_data=data)
    with pytest.raises(ValueError, match="context changed"):
        cycle.verify_context(context={**context, "seed": 43}, scratch_data=data)
    manifest.write_text('{"snapshot_id":"different"}\n')
    with pytest.raises(ValueError, match="manifest differs"):
        cycle.verify_context(context=context, scratch_data=data)
    result = cycle.finish(phase="setup_failed", worker_exit=1)
    assert result["error_count"] == 2 and result["unfinished_count"] == 0


def test_restart_recovers_commit_with_lost_stdout_and_never_reclaims(cycle):
    from algua.operator.research_cycle import ResearchCycle

    _start(cycle)  # simulate SIGKILL immediately after the claim COMMIT
    restarted = ResearchCycle(cycle.conn, cycle.directory, cycle.cycle_id)
    claimed, result = _start(restarted)
    assert claimed == []
    assert result["terminal_count"] == result["error_count"] == 2
    assert result["unfinished_count"] == 0 and not result["ok"]
    again, repeat = _start(restarted)
    assert again == [] and repeat["attempts"] == result["attempts"]
    assert len(cycle.rows()) == 2


def test_new_firing_recovers_prior_crash_before_claiming(cycle):
    from algua.operator.research_cycle import ResearchCycle

    _start(cycle)
    following = ResearchCycle(cycle.conn, cycle.directory, "following-cycle")
    claimed, result = _start(following)
    assert len(claimed) == 2
    assert all(row["outcome"] == "run_error" for row in cycle.rows())
    assert result["research_cycle_id"] == "following-cycle"


@pytest.mark.parametrize("exit_code", [3, 124, 137, 1])
def test_worker_failure_closes_all_claims_despite_partial_report(cycle, tmp_path, exit_code):
    claimed, _ = _start(cycle)
    report = _report(tmp_path, [{"idea_id": claimed[0].id, "outcome": "candidate_preview_pass",
                               "reason": "incomplete worker"}])
    result = cycle.finish(phase="completed", worker_exit=exit_code, report=report)
    assert result["error_count"] == result["terminal_count"] == 2
    assert result["unfinished_count"] == 0 and not result["ok"]
    assert all(row["outcome"] == "run_error" for row in cycle.rows())


def test_duplicate_invalid_missing_and_valid_claims_have_truthful_denominator(cycle, tmp_path):
    from algua.operator.research_cycle import CycleLimits

    claimed, _ = _start(cycle, limits=CycleLimits(max_hypotheses=3))
    row = {"idea_id": claimed[0].id, "outcome": "candidate_preview_pass", "reason": "fixture"}
    report = _report(tmp_path, [row, row, {"idea_id": claimed[1].id, "outcome": "invented"}])
    result = cycle.finish(phase="completed", worker_exit=0, report=report)
    assert result["attempts_total"] == result["error_count"] == 3
    assert result["invalid_count"] == 3 and result["ok_count"] == 0
    assert result["terminal_count"] == 3 and result["unfinished_count"] == 0
    assert not result["ok"]
    assert all(row["outcome"] == "run_error" for row in cycle.rows())


def test_finish_retry_preserves_terminal_outcome_and_evidence(cycle, tmp_path):
    claimed, _ = _start(cycle)
    report = _report(tmp_path, [{"idea_id": i.id, "outcome": "walkforward_refuted",
                               "reason": "fixture evidence"} for i in claimed])
    result = cycle.finish(phase="completed", worker_exit=0, report=report,
                          evidence_ref="fixture://immutable-result")
    retry = cycle.finish(phase="controller_restart", worker_exit=1)
    assert result["ok"] and retry["ok"]
    assert retry["attempts"] == result["attempts"]
    assert len(cycle.rows()) == 2


def test_stale_token_cannot_overwrite_reaped_or_retried_attempt(cycle):
    from datetime import UTC, datetime, timedelta

    from algua.registry.idea_attempts import IdeaAttemptsRepository

    _start(cycle)
    future = datetime.now(UTC) + timedelta(hours=4)
    fresh = IdeaAttemptsRepository(cycle.conn).claim(run_stamp="other-driver", limit=3,
                                                    ttl_minutes=180, now=future)
    tokens = {i.id: i.claim_token for i in fresh}
    result = cycle.finish(phase="controller_restart", worker_exit=1)
    assert result["error_count"] == 2 and result["unfinished_count"] == 0
    assert all(row["outcome"] == "abandoned" for row in cycle.rows())
    assert tokens == {row["id"]: row["claim_token"] for row in cycle.conn.execute(
        "SELECT id, claim_token FROM ideas WHERE claimed_by='other-driver'")}


def test_write_failure_keeps_unfinished_count_and_retry_closes_once(cycle, monkeypatch):
    import sqlite3

    _start(cycle)
    original = cycle.attempts.record_outcome
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise sqlite3.OperationalError("trusted fixture write failure")
        patch.setattr(cycle.attempts, "record_outcome", fail)
        result = cycle.finish(phase="setup_failed", worker_exit=1)
    assert not result["ok"] and result["unfinished_count"] == 2
    assert result["terminal_count"] == result["error_count"] == 0
    assert len(result["write_errors"]) == 2
    assert cycle.attempts.record_outcome == original
    retry = cycle.finish(phase="controller_restart", worker_exit=1)
    assert retry["unfinished_count"] == 0 and retry["error_count"] == 2


def test_expired_cycle_does_not_accept_worker_success(cycle, tmp_path, monkeypatch):
    import time

    claimed, _ = _start(cycle)
    report = _report(tmp_path, [{"idea_id": i.id, "outcome": "candidate_preview_pass",
                               "reason": "late"} for i in claimed])
    deadline = json.loads(cycle.path.read_text())["deadline"]
    monkeypatch.setattr(time, "time", lambda: deadline + 1)
    result = cycle.finish(phase="completed", worker_exit=0, report=report)
    assert result["phase"] == "wall_time_exhausted" and result["error_count"] == 2


def test_unknown_cost_stays_null_and_explicit_cap_blocks_claim(cycle):
    from algua.operator.research_cycle import CycleLimits

    claimed, result = _start(cycle, limits=CycleLimits(max_cost=0))
    assert claimed == [] and cycle.rows() == []
    assert not result["ok"] and result["phase"] == "cost_unknown"
    assert result["monetary_cost"] is None and result["cost_gate_passed"] is False
    assert not cycle.finish(phase="pool_empty", worker_exit=0)["ok"]


def test_empty_queue_repeat_is_terminal_without_new_claim(cycle):
    cycle.conn.execute("UPDATE ideas SET status='discarded'")
    cycle.conn.commit()
    claimed, result = _start(cycle)
    assert claimed == [] and result["phase"] == "pool_empty"
    assert result["ok"] and result["attempts_total"] == 0
    assert _start(cycle)[0] == []


@pytest.mark.parametrize("kwargs", [{"max_hypotheses": 0}, {"max_hypotheses": 41},
                                  {"worker_limit": 2}, {"max_wall_seconds": 0},
                                  {"memory_mb": 0}, {"cpu_seconds": -1}, {"file_mb": 0},
                                  {"max_cost": float("nan")}])
def test_finite_resource_limits_fail_closed(kwargs):
    from algua.operator.research_cycle import CycleLimits
    with pytest.raises(ValueError):
        CycleLimits(**kwargs)


def test_trusted_worker_limits_and_timeout_kill_descendants(tmp_path):
    from algua.operator.research_cycle import CycleLimits
    from algua.operator.research_cycle_worker import run_bounded

    evidence = tmp_path / "limits.json"
    script = (
        "import json,resource,sys,time,subprocess\n"
        "from pathlib import Path\n"
        "limits={str(k):resource.getrlimit(k)[0] for k in "
        "[resource.RLIMIT_AS,resource.RLIMIT_CPU,resource.RLIMIT_FSIZE]}\n"
        "Path(sys.argv[1]).write_text(json.dumps(limits))\n"
        "subprocess.Popen([sys.executable,'-c',"
        "'import time;from pathlib import Path;time.sleep(2);Path(\"' + sys.argv[2] + "
        "'\").touch()'],start_new_session=True)\n"
        "time.sleep(20)\n"
    )
    escaped = tmp_path / "escaped"
    limits = CycleLimits(max_wall_seconds=1, cpu_seconds=2, memory_mb=512, file_mb=1)
    code = run_bounded([sys.executable, "-c", script, str(evidence), str(escaped)], limits,
                       grace_seconds=0.1)
    assert code == 124
    import resource
    measured = json.loads(evidence.read_text())
    assert measured == {str(resource.RLIMIT_AS): 512 * 1024**2,
                        str(resource.RLIMIT_CPU): 2, str(resource.RLIMIT_FSIZE): 1024**2}
    import time
    time.sleep(2)
    assert not escaped.exists()


@pytest.mark.parametrize("code", [0, 3, 7])
def test_worker_exit_is_preserved(code):
    from algua.operator.research_cycle import CycleLimits
    from algua.operator.research_cycle_worker import run_bounded
    assert run_bounded([sys.executable, "-c", f"raise SystemExit({code})"],
                       CycleLimits(memory_mb=512)) == code


def test_executable_supervisor_entrypoint_and_bounds():
    prefix = [sys.executable, "-m", "algua.operator.research_cycle_worker",
              "--timeout", "2s", "--hypotheses", "1", "--memory-mb", "512"]
    result = subprocess.run([*prefix, "--", sys.executable, "-c", "raise SystemExit(3)"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 3, result.stderr
    invalid = subprocess.run([*prefix, "--workers", "2", "--", sys.executable,
                             "-c", "print('must not launch')"],
                             capture_output=True, text=True, timeout=10)
    assert invalid.returncode == 2 and invalid.stdout == ""


def test_preview_outcome_stays_held_for_existing_drainer(cycle, tmp_path):
    claimed, _ = _start(cycle)
    report = _report(tmp_path, [{"idea_id": i.id, "outcome": "candidate_preview_pass",
                               "reason": "fixture preview"} for i in claimed])
    result = cycle.finish(phase="completed", worker_exit=0, report=report)
    assert result["ok"] and result["terminal_count"] == 2
    held = cycle.conn.execute("SELECT claim_token FROM ideas WHERE claimed_by=?",
                              (cycle.cycle_id,)).fetchall()
    assert {r[0] for r in held} == {i.claim_token for i in claimed}
    assert _start(cycle)[0] == []
    assert all(row["outcome"] == "candidate_preview_pass" for row in cycle.rows())


def test_claim_ttl_cannot_expire_inside_declared_wall_budget(cycle):
    from algua.operator.research_cycle import CycleLimits
    with pytest.raises(ValueError, match="TTL"):
        _start(cycle, limits=CycleLimits(max_wall_seconds=10801))
    assert cycle.rows() == [] and not cycle.path.exists()


def test_cycle_cli_returns_json_and_nonzero_for_errors(cycle, monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from algua.cli.main import app

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    args = ["research", "idea", "cycle-start", "--run", "cli-cycle", "--limit", "2"]
    started = runner.invoke(app, args)
    assert started.exit_code == 0, started.output
    response = json.loads(started.stdout)
    assert len(response["claimed"]) == 2
    assert response["monetary_cost"] is None and response["cost_gate_passed"] is False
    scratch = tmp_path / "copied-data"
    scratch.mkdir()
    checked = runner.invoke(app, ["research", "idea", "cycle-check", "--run", "cli-cycle",
                                  "--scratch-data", str(scratch),
                                  "--worker-root", str(DRIVER.parents[2])])
    assert checked.exit_code == 0 and json.loads(checked.stdout)["context_verified"]
    (scratch / "manifest.jsonl").write_text("changed inventory")
    refused = runner.invoke(app, ["research", "idea", "cycle-check", "--run", "cli-cycle",
                                  "--scratch-data", str(scratch),
                                  "--worker-root", str(DRIVER.parents[2])])
    assert refused.exit_code == 1 and not json.loads(refused.stdout)["ok"]
    stopped = runner.invoke(app, ["research", "idea", "cycle-finish", "--run", "cli-cycle",
                                  "--phase", "setup_failed", "--worker-exit", "1"])
    assert stopped.exit_code == 1, stopped.output
    assert json.loads(stopped.stdout)["error_count"] == 2
    retry = runner.invoke(app, args)
    assert retry.exit_code == 1 and json.loads(retry.stdout)["claimed"] == []


def _shell_parts():
    source = DRIVER.read_text()
    functions = source[source.index("record_outcomes() {"):source.index("# Lock BEFORE")]
    lock = source[source.index("# Lock BEFORE"):source.index("# Claim this run's ideas AUTHORITY")]
    claim_start = source.index('if [[ "${DRY_RUN}" -eq 1 ]]; then\n  echo "would claim')
    claims = source[claim_start:source.index("# Everything the agent reads/writes")]
    return functions, lock, claims


def test_competing_driver_loses_flock_before_claiming(cycle, tmp_path):
    import fcntl
    import shlex

    _, lock, _ = _shell_parts()
    (tmp_path / "data").mkdir()
    with (tmp_path / "data/research-loop.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preamble = (f"set -euo pipefail\nDRY_RUN=0\nREPO_ROOT={shlex.quote(str(tmp_path))}\n"
                    'append_digest() { echo "digest:$1"; }\n')
        process = subprocess.run(["bash", "-c", preamble + lock + '\necho claimed-unexpectedly'],
                                 text=True, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "digest:skipped_lock"
    assert cycle.rows() == []


def test_driver_recovers_claim_commit_before_broken_stdout(cycle, tmp_path):
    """Actual lock/claim/trap/functions; trusted CLI fixture, no uv, git or model launch."""
    import os
    import shlex

    fixture = tmp_path / "cli_fixture.py"
    fixture.write_text(
        "import subprocess,sys\n"
        "p=subprocess.run([sys.executable,'-c','from algua.cli.main import app; app()',"
        "*sys.argv[1:]],capture_output=True,text=True)\n"
        "if 'cycle-start' in sys.argv and p.returncode==0:\n"
        "    print('fixture: stdout lost AFTER claim commit')\n"
        "else:\n"
        "    print(p.stdout,end='')\n"
        "    print(p.stderr,end='',file=sys.stderr)\n"
        "raise SystemExit(p.returncode)\n")
    functions, lock, claims = _shell_parts()
    variables = {"REPO_ROOT": str(tmp_path), "AUTH_DATA_DIR": str(tmp_path),
                 "AUTH_DB": str(tmp_path / "fixture.db"), "DRY_RUN": "0",
                 "STAMP": "lost-stdout", "CATEGORY": "", "N_HYPOTHESES": "2",
                 "TIMEOUT": "45m", "WORKER_LIMIT": "1", "CPU_SECONDS": "2700",
                 "MEMORY_MB": "512", "FILE_MB": "1", "MAX_COST": "", "WORKTREE": "",
                 "CYCLE_PHASE": "setup_failed", "CLAIMED_JSON": "[]", "N_CLAIMED": "0"}
    preamble = "set -euo pipefail\n" + "\n".join(
        f"{k}={shlex.quote(v)}" for k, v in variables.items()) + "\n"
    preamble += (f"AUTH_CLI=({shlex.quote(sys.executable)} {shlex.quote(str(fixture))})\n"
                 f'python3() {{ {shlex.quote(sys.executable)} "$@"; }}\n'
                 'append_digest() { echo "digest:$1:rc=$rc"; }\n')
    proc = subprocess.run(["bash", "-c", preamble + functions + lock + claims],
                          cwd=DRIVER.parents[2], text=True, capture_output=True, timeout=45,
                          env={**os.environ, "PYTHONPATH": str(DRIVER.parents[2])})
    assert proc.returncode == 1, proc.stderr
    attempts = cycle.conn.execute(
        "SELECT * FROM idea_attempts WHERE run_stamp='lost-stdout'").fetchall()
    assert len(attempts) == 2, (proc.stdout, proc.stderr)
    assert all(row["outcome"] == "run_error" for row in attempts)
    assert "digest:setup_failed:rc=1" in proc.stdout
    remaining = cycle.conn.execute(
        "SELECT COUNT(*) FROM ideas WHERE claimed_by IS NOT NULL").fetchone()[0]
    assert remaining == 0


def test_quick_exit_detached_child_is_owned_and_reaped(tmp_path):
    """Trusted driver exits between polls; its new-session child must not outlive it."""
    import os
    import time

    from algua.operator.research_cycle import CycleLimits
    from algua.operator.research_cycle_worker import run_bounded

    marker, pid_file = tmp_path / "survived", tmp_path / "child.pid"
    child = ("import os,time;from pathlib import Path;"
             f"Path({str(pid_file)!r}).write_text(str(os.getpid()));"
             f"time.sleep(0.5);Path({str(marker)!r}).touch()")
    parent = ("import subprocess,sys;"
              f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True)")
    assert run_bounded([sys.executable, "-c", parent], CycleLimits(memory_mb=512)) == 0
    time.sleep(0.7)
    pid = int(pid_file.read_text()) if pid_file.exists() else None
    try:
        assert not marker.exists(), "detached child survived successful supervisor return"
        assert pid is None or not Path(f"/proc/{pid}").exists(), "owned child was not reaped"
    finally:
        if pid is not None:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("fault", ["title", "verdict", "falsification", "gate", "duplicate"])
def test_malformed_report_cannot_refute_or_publish_candidate(cycle, tmp_path, fault):
    from tests.test_research_run_digest import (
        _last_digest_row,
        _queue_items,
        _run_append_digest,
    )

    claimed, _ = _start(cycle)
    rows = [{"idea_id": i.id, "title": "Fixture", "outcome": "walkforward_refuted",
             "reason": "fixture evidence", "verdict": "discarded"} for i in claimed]
    # Include a real-shaped candidacy so rejecting malformed siblings also proves no enqueue.
    rows[1].update(outcome="candidate_preview_pass", verdict="candidate-preview-pass",
                   merge_back={"idea_id": claimed[1].id, "strategy": "fixture_strategy",
                               "universe": "sp500", "start": "2024-01-01", "end": "2024-06-01",
                               "eval_context": {"demo": True, "sweep_grid": {"lookback": [10]},
                                                "rank_by": "mean_sharpe"}})
    trailer = {"hypotheses": rows, "preview_gate": None}
    if fault == "duplicate":
        rows.append(dict(rows[0]))
    elif fault == "gate":
        trailer["preview_gate"] = {"passed": "yes", "failed_checks": []}
    else:
        field = {"title": "title", "verdict": "verdict",
                 "falsification": "falsification_assessment"}[fault]
        rows[0][field] = 42
    report = tmp_path / "report.md"
    report.write_text("```json\n" + json.dumps(trailer) + "\n```\n")
    result = cycle.finish(phase="completed", worker_exit=0, report=report)
    assert not result["ok"], "malformed report was accepted as a successful ledger outcome"
    assert result["error_count"] == result["invalid_count"] == len(claimed)
    assert all(a["outcome"] == "run_error" for a in result["attempts"])
    refuted = cycle.conn.execute("SELECT COUNT(*) FROM ideas WHERE status='refuted'")
    assert refuted.fetchone()[0] == 0
    proc, digest, queue = _run_append_digest(
        tmp_path, trailer=trailer, strategy_names="fixture_strategy",
        claimed=[{"id": i.id, "claim_token": i.claim_token} for i in claimed])
    assert proc.returncode == 0, proc.stderr
    assert _last_digest_row(digest)["trailer_parse_error"] is True
    assert _queue_items(queue) == {}


def test_cycle_cli_subdirectory_retains_required_source_identity(cycle, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli.main import app
    from algua.operator.research_cycle import file_hash

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    monkeypatch.chdir(DRIVER.parents[2] / "algua")
    started = CliRunner().invoke(app, ["research", "idea", "cycle-start", "--run", "subdir",
                                      "--limit", "1"])
    assert started.exit_code == 0, started.output
    metadata = json.loads((tmp_path / "research-cycles/subdir.json").read_text())
    context = metadata["request"]["context"]
    assert context["dependency_hash"] == file_hash(DRIVER.parents[2] / "uv.lock")
    assert context["runtime_seam_sha256"] == file_hash(DRIVER.parent / "run_agent.sh")


def test_missing_required_source_identity_refuses_before_claim(cycle, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli import idea_ops_cmd
    from algua.cli.main import app

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    # Simulate a required source unavailable to the identity reader, without altering the tree.
    original = idea_ops_cmd.file_hash
    monkeypatch.setattr(idea_ops_cmd, "file_hash",
                        lambda p: None if p.name == "uv.lock" else original(p))
    result = CliRunner().invoke(app, ["research", "idea", "cycle-start", "--run", "missing-source",
                                     "--limit", "1"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["ok"] is False
    assert cycle.conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0


def test_cycle_check_requires_actual_worker_checkout(cycle, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli.main import app

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(app, ["research", "idea", "cycle-start", "--run", "actual-worker",
                               "--limit", "1"]).exit_code == 0
    result = runner.invoke(app, ["research", "idea", "cycle-check", "--run", "actual-worker",
                                 "--scratch-data", str(tmp_path)])
    assert result.exit_code != 0, "authority checkout cannot attest an unspecified worker baseline"


def test_cycle_check_binds_actual_checkout_content_before_launch(cycle, tmp_path, monkeypatch):
    import shutil

    from typer.testing import CliRunner

    from algua.cli.main import app

    source = DRIVER.parents[2]
    worker = tmp_path / "worker"
    worker.mkdir()
    for directory in ("algua", ".opencode"):
        shutil.copytree(source / directory, worker / directory,
                        ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("uv.lock", "pyproject.toml"):
        shutil.copyfile(source / name, worker / name)
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "fixture.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    assert runner.invoke(app, ["research", "idea", "cycle-start", "--run", "worker-baseline",
                               "--limit", "1"]).exit_code == 0
    args = ["research", "idea", "cycle-check", "--run", "worker-baseline",
            "--scratch-data", str(tmp_path), "--worker-root", str(worker)]
    same = runner.invoke(app, args)
    assert same.exit_code == 0, same.output
    # A numerical module outside the original seven fingerprinted files also binds the baseline.
    with (worker / "algua/backtest/metrics.py").open("a") as stream:
        stream.write("\n# different worker baseline\n")
    drift = runner.invoke(app, args)
    assert drift.exit_code == 1 and "context changed" in drift.stdout
    (worker / "uv.lock").unlink()
    missing = runner.invoke(app, args)
    assert missing.exit_code == 1 and "missing required cycle source" in missing.stdout
    assert cycle.conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1


def test_settings_resolution_is_inside_overall_supervisor_deadline(tmp_path):
    """Execute the launch/setup prefix with a stalled trusted settings import; no uv/Git."""
    import os
    import shlex
    import signal

    marker = tmp_path / "settings-entered"
    (tmp_path / "sitecustomize.py").write_text(
        "import builtins,time\nfrom pathlib import Path\n"
        "original=builtins.__import__\n"
        "def tracked(name,*args,**kwargs):\n"
        "    if name=='algua.config.settings':\n"
        f"        Path({str(marker)!r}).touch()\n"
        "        time.sleep(20)\n"
        "    return original(name,*args,**kwargs)\n"
        "builtins.__import__=tracked\n")
    source = DRIVER.read_text()
    start = min(source.index("# Resolve the claim size"), source.index("# One process supervisor"))
    prefix = source[start:source.index('RUNS_DIR="')]
    # Map the legacy lookup to the prepared interpreter; never execute uv/bootstrap in a fixture.
    # This preserves the old ordering/deadline defect while staying inside the test permission.
    prefix = prefix.replace("uv run python", '"${PYTHON}"')
    values = {"REPO_ROOT": str(DRIVER.parents[2]), "PYTHON": sys.executable,
              "N_HYPOTHESES": "", "TIMEOUT": "1s", "WORKER_LIMIT": "1",
              "CPU_SECONDS": "2", "MEMORY_MB": "512", "FILE_MB": "1", "DRY_RUN": "0"}
    preamble = "set -euo pipefail\n" + "\n".join(
        f"{k}={shlex.quote(v)}" for k, v in values.items())
    preamble += '\nORIGINAL_ARGS=(--timeout 1s --memory-mb 512)\n'
    env = {**os.environ, "PYTHONPATH": f"{tmp_path}{os.pathsep}{DRIVER.parents[2]}"}
    env.pop("ALGUA_RESEARCH_HYPOTHESES_PER_RUN", None)
    env.pop("ALGUA_CYCLE_SUPERVISED", None)
    process = subprocess.Popen(["bash", "-c", preamble + prefix], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=4)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    assert marker.exists(), (stdout, stderr)
    assert process.returncode == 124, ("setup escaped overall deadline", stdout, stderr)
