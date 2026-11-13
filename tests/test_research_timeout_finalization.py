"""Trusted timeout recovery fixtures; no inference, market calculation or qualification."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from algua.operator.research_cycle import CycleLimits

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / ".opencode/scripts/run-research-loop.sh"


def test_timeout_recovery_starts_only_after_owned_workers_are_reaped(tmp_path, monkeypatch):
    import algua.operator.research_cycle_worker as supervisor

    monkeypatch.setenv("ALGUA_RESEARCH_CYCLE_ID", "fixture-timeout")
    data = tmp_path / "data"
    (data / "research-cycles").mkdir(parents=True)
    (data / "research-cycles/fixture-timeout.json").write_text("{}")
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    fixture = tmp_path / "driver.py"
    fixture.write_text('''import json,os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[1])
if "--recover-timeout" in sys.argv:
    pid=int((root/"child.pid").read_text())
    assert not Path(f"/proc/{pid}").exists(), "recovery raced live worker"
    (root/"recovered.json").write_text(json.dumps({"exit":sys.argv[-1],
        "cycle":os.environ["ALGUA_RESEARCH_CYCLE_ID"]}))
    raise SystemExit(7)
child=("import os,time;from pathlib import Path;Path("+repr(str(root/"child.pid"))
       +").write_text(str(os.getpid()));time.sleep(30)")
subprocess.Popen([sys.executable,"-c",child],start_new_session=True)
time.sleep(30)
''')
    driver = tmp_path / "driver.sh"
    driver.write_text("#!/bin/bash\nexec " + shlex.join([sys.executable, str(fixture)])
                      + ' "$@"\n')
    monkeypatch.setattr(supervisor, "RESEARCH_DRIVER", driver)
    code = supervisor.run_driver([str(tmp_path)], CycleLimits(max_wall_seconds=1, memory_mb=512))
    assert code == 124  # Failed recovery never changes the actual timeout or retries inference.
    assert json.loads((tmp_path / "recovered.json").read_text()) == {
        "exit": "124", "cycle": "fixture-timeout"}


def test_success_does_not_launch_recovery(tmp_path, monkeypatch):
    import algua.operator.research_cycle_worker as supervisor

    marker = tmp_path / "invocations"
    source = ("from pathlib import Path;"
              f"p=Path({str(marker)!r});p.write_text(p.read_text()+'x' if p.exists() else 'x')")
    driver = tmp_path / "driver.sh"
    driver.write_text("#!/bin/bash\nexec " + shlex.join([sys.executable, "-c", source]) + "\n")
    monkeypatch.setattr(supervisor, "RESEARCH_DRIVER", driver)
    assert supervisor.run_driver([], CycleLimits(memory_mb=512)) == 0
    assert marker.read_text() == "x"


def test_term_trap_defers_outcomes_until_post_reap_capture(tmp_path):
    from tests.test_research_memory_driver import _function

    text = DRIVER.read_text()
    cleanup = _function(text, "cleanup_setup", "\nrecover_interrupted_cycle")
    marker = tmp_path / "premature_outcome"
    command = ("set -euo pipefail\nCYCLE_PHASE=driver_failed\n"
               + f"record_outcomes() {{ touch {shlex.quote(str(marker))}; }}\n"
               + cleanup + "\ntrap cleanup_setup EXIT\n"
               + "trap 'CYCLE_PHASE=driver_interrupted; exit 143' TERM\nkill -TERM $$\n")
    result = subprocess.run(["bash", "-c", command], capture_output=True, timeout=10)
    assert result.returncode == 143
    assert not marker.exists()


@pytest.mark.parametrize("worker_exit,fault", [
    (124, None), (143, None), (124, "tracked_source"), (124, "tracked_kb"), (124, "capture"),
])
@pytest.mark.slow
def test_real_recovery_archives_completed_rows_before_terminal_outcomes(
    tmp_path, monkeypatch, worker_exit, fault,
):
    from algua.operator.research_memory import ResearchMemory
    from algua.registry.db import connect
    from algua.registry.store import SqliteStrategyRepository
    from tests.test_research_memory_driver import (
        STAMP,
        _function,
        _git,
        _preamble,
        prepare_memory,
    )

    repo = tmp_path / "main"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "SYNTHETIC_FIXTURE")
    (repo / "algua/strategies/fixture").mkdir(parents=True)
    old = (Path("kb/principles/methodology.md") if fault == "tracked_kb"
           else Path("algua/strategies/fixture/existing.py"))
    (repo / old).parent.mkdir(parents=True, exist_ok=True)
    (repo / old).write_text("# SYNTHETIC_FIXTURE baseline\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture seed")
    worker = repo / ".runs" / STAMP
    _git(repo, "worktree", "add", "-b", f"research-run/{STAMP}", str(worker))
    metadata, archive = prepare_memory(repo, worker, claimed=True, retained=False)
    monkeypatch.setenv("ALGUA_DB_PATH", str(repo / "data/algua.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(repo / "data"))
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{repo / 'tracking.db'}")
    monkeypatch.setenv("ALGUA_RESEARCH_DIGEST_PATH", str(repo / "data/digest.jsonl"))
    from algua.operator.research_cycle import ResearchCycle

    authority = connect(repo / "data/algua.db")
    cycle = ResearchCycle(authority, metadata.parent, STAMP)
    memory = ResearchMemory(cycle, archive)
    memory.seed(worker)
    local = connect(worker / ".funnel-scratch/data/algua.db")
    with local:
        for n in range(13):
            SqliteStrategyRepository(local).record_run(
                "backtest", "SYNTHETIC_FIXTURE completed before timeout",
                config={"params": {"fixture": n}}, metrics={"total_return_is": -0.2})
    local.close()
    added = "algua/strategies/fixture/new_strategy.py"
    (worker / added).parent.mkdir(parents=True, exist_ok=True)
    (worker / added).write_text("# SYNTHETIC_FIXTURE authored before timeout\n")
    (worker / "unrelated.txt").write_text("never commit")
    (worker / "algua/strategies/fixture/unrelated.bin").write_bytes(b"never commit")
    if fault in ("tracked_source", "tracked_kb"):
        (worker / old).write_text("# modified baseline source must refuse capture\n")
    text = DRIVER.read_text()
    assert "recover_interrupted_cycle() {" in text
    functions = (_function(text, "append_digest", "\n# Close the ideation loop")
                 + _function(text, "record_outcomes", "\n# Lock BEFORE"))
    command = (_preamble(repo, worker) + functions
               + ("\ncapture_research_memory() { return 1; }\n" if fault == "capture" else "")
               + f"\nRECOVER_WORKER_EXIT={worker_exit}\nrecover_interrupted_cycle\n")
    if worker_exit == 124 and fault is None:
        # The real recovery-only script entry, after an actual fake-worker timeout; no
        # setup/claim/runtime route may re-enter when the supervisor runs it a second time.
        import algua.operator.research_cycle_worker as supervisor

        actual = repo / ".opencode/scripts/run-research-loop.sh"
        actual.parent.mkdir(parents=True)
        actual.write_text(text)
        prepared = repo / ".venv/bin/python"
        prepared.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + ' "$@"\n')
        prepared.chmod(0o755)
        cli = repo / ".venv/bin/algua"
        cli.rename(cli.with_name("algua-real"))
        log = repo / "cli-argv.jsonl"
        logger = ("import json,sys;from pathlib import Path;"
                  f"p=Path({str(log)!r});"
                  "p.open('a').write(json.dumps(sys.argv[1:])+'\\n')")
        cli.write_text("#!/bin/sh\n" + shlex.join([sys.executable, "-c", logger])
                       + ' "$@"\nexec ' + shlex.quote(str(cli.with_name("algua-real")))
                       + ' "$@"\n')
        cli.chmod(0o755)
        entry = repo / "fixture-driver.sh"
        entry.write_text("#!/bin/bash\n"
            + 'if [[ " $* " == *" --recover-timeout "* ]]; then\nexec bash '
            + shlex.quote(str(actual)) + ' "$@"\nfi\nexec sleep 30\n')
        monkeypatch.setattr(supervisor, "RESEARCH_DRIVER", entry)
        monkeypatch.setenv("ALGUA_RESEARCH_CYCLE_ID", STAMP)
        status = supervisor.run_driver(["--hypotheses", "1", "--timeout", "1s"],
                                       CycleLimits(max_wall_seconds=1))
        result = subprocess.CompletedProcess([], status, "", "")
        calls = [json.loads(line)[:3] for line in log.read_text().splitlines()]
        assert calls == [["research", "memory", "capture"],
                         ["research", "idea", "cycle-finish"]]
    else:
        result = subprocess.run(["bash", "-c", command], cwd=repo, env=os.environ.copy(),
                                capture_output=True, text=True, timeout=90)
    assert result.returncode == worker_exit, result.stdout + result.stderr
    if fault is None:
        payload = memory.read()
        assert len(payload["evaluations"]) == 13
        assert payload["worker_exit"] == worker_exit
        assert payload["source_commit"] == _git(worker, "rev-parse", "HEAD")
        assert _git(worker, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD") == added
        assert _git(worker, "diff", "--name-only") == ""
    else:
        assert "receipt" not in json.loads(metadata.read_text())["research_memory"]
        assert (worker / added).exists()
        assert "retaining all scratch" in result.stderr
        if fault in ("tracked_source", "tracked_kb"):
            assert _git(worker, "diff", "--name-only") == str(old)
            assert _git(worker, "ls-files", "--", added) == ""
    outcomes = cycle.rows()
    assert len(outcomes) == 1 and outcomes[0]["outcome"] == "run_error"
    phase = "wall_time_exhausted" if worker_exit == 124 else "driver_failed"
    assert outcomes[0]["reason"] == f"{phase}:{worker_exit}"
    if fault is None:
        assert outcomes[0]["evidence_ref"] == json.loads(metadata.read_text())[
            "research_memory"]["receipt"]["reference"]
    else:
        assert outcomes[0]["evidence_ref"] is None
    assert not cycle.summary(phase="wall_time_exhausted")["ok"]
    assert worker.exists()  # No deletion after interrupted inference.
    digest = json.loads((repo / "data/digest.jsonl").read_text())
    assert digest["exit_code"] == worker_exit
    assert digest["outcome"] == "driver_failed" and digest["hypotheses"] == []
    before = metadata.read_bytes(), list(cycle.rows()), (repo / "data/digest.jsonl").read_bytes()
    repeated = subprocess.run(["bash", "-c", command], cwd=repo, env=os.environ.copy(),
                              capture_output=True, text=True, timeout=90)
    assert repeated.returncode == worker_exit, repeated.stdout + repeated.stderr
    assert (metadata.read_bytes(), list(cycle.rows()),
            (repo / "data/digest.jsonl").read_bytes()) == before
    authority.close()
