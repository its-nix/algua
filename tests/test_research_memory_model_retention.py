"""Approved temporary worker retention; synthetic ledgers and operative cleanup adapters."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from algua.operator.research_cycle import ResearchCycle
from algua.operator.research_memory import ResearchMemory
from algua.registry.db import connect
from algua.registry.store import SqliteStrategyRepository
from tests.test_cli_research_memory import (
    _capture,
    _invoke,
    _seed_and_explore,
)
from tests.test_cli_research_memory import cli_memory as cli_memory
from tests.test_research_memory_driver import (
    DRIVER,
    STAMP,
    _bash,
    _git,
    _preamble,
    _queue_module,
)
from tests.test_research_memory_driver import driver_memory as driver_memory


def _reference(width=16):
    return {"name": "retention-fixture", "version": 1, "digest": "a" * width,
            "training_as_of": "2020-01-01", "provenance_digest": "b" * width}


def _record(source, *, width=16):
    conn = connect(source)
    try:
        with conn:
            SqliteStrategyRepository(conn).record_run(
                "backtest", "SYNTHETIC_FIXTURE metadata only", components=[_reference(width)])
    finally:
        conn.close()


@pytest.mark.parametrize("width", [16, 64])
def test_public_refs_alone_refuse_cleanup_and_preserve_terminal_outcome(cli_memory, width):
    authority, cycle, worker, source, _ = cli_memory
    _seed_and_explore(worker, source)
    _record(source, width=width)
    result, captured = _capture(worker)
    assert result.exit_code == 0, result.output
    cycle.finish(phase="setup_failed", worker_exit=1,
                 evidence_ref=captured["receipt"]["reference"])
    before = list(authority.iterdump())

    result, refused = _invoke("cleanup-check", worker)

    assert result.exit_code != 0
    assert refused["ok"] is False and refused["code"] == "invalid_input"
    assert "model_references" in refused["error"] and "retain" in refused["error"]
    assert worker.exists() and not (source.parent / "models").exists()
    assert list(authority.iterdump()) == before
    result, shown = _invoke("show")
    assert result.exit_code == 0 and shown["coverage"]["model_bytes_preserved"] is False
    assert shown["evaluations"][-1]["model_refs"] == [_reference(width)]
    attempt = authority.execute("SELECT outcome,reason FROM idea_attempts").fetchone()
    assert tuple(attempt) == ("run_error", "setup_failed:1")


@pytest.mark.parametrize("kind", ["empty", "artifact", "unreadable", "file", "symlink",
                                  "dangling", "fifo", "scratch-alias", "data-alias"])
def test_known_store_or_alias_retains_without_claiming_archived_bytes(cli_memory, kind):
    authority, _, worker, source, _ = cli_memory
    _seed_and_explore(worker, source)
    result, _ = _capture(worker)
    assert result.exit_code == 0, result.output
    store = source.parent / "models"
    if kind in {"empty", "artifact", "unreadable"}:
        store.mkdir()
        if kind == "artifact":
            (store / "opaque.bin").write_bytes(b"SYNTHETIC_FIXTURE unarchived bytes")
        elif kind == "unreadable":
            store.chmod(0)
    elif kind == "file":
        store.write_bytes(b"SYNTHETIC_FIXTURE not a directory")
    elif kind in {"symlink", "dangling"}:
        target = worker.parent / "external-model-fixture"
        if kind == "symlink":
            target.mkdir()
        store.symlink_to(target, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(store)
    else:
        original = worker / ".funnel-scratch" if kind == "scratch-alias" else source.parent
        target = worker / "aliased-scratch-fixture"
        original.rename(target)
        original.symlink_to(target, target_is_directory=True)
    before = list(authority.iterdump())

    result, refused = _invoke("cleanup-check", worker)

    assert result.exit_code != 0
    reason = "model_store_unverified" if kind.endswith("alias") else "model_store_present"
    assert refused["ok"] is False and reason in refused["error"]
    assert "retain" in refused["error"] and worker.exists()
    assert list(authority.iterdump()) == before
    result, shown = _invoke("show")
    assert result.exit_code == 0 and shown["coverage"]["model_bytes_preserved"] is False
    assert shown["evaluations"][0]["model_refs"] == []
    if kind == "unreadable":
        store.chmod(0o700)


def test_metadata_inspection_error_refuses_actual_cli(cli_memory, monkeypatch):
    _, _, worker, source, _ = cli_memory
    _seed_and_explore(worker, source)
    assert _capture(worker)[0].exit_code == 0
    original = Path.lstat

    def inaccessible(path, *args, **kwargs):
        if path == source.parent / "models":
            raise PermissionError("SYNTHETIC_FIXTURE metadata unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", inaccessible)
    result, payload = _invoke("cleanup-check", worker)
    assert result.exit_code != 0 and "model_store_unverified" in payload["error"]
    assert "metadata unavailable" not in payload["error"] and worker.exists()


def test_model_store_arriving_during_absence_probe_retains(cli_memory, monkeypatch):
    _, _, worker, source, _ = cli_memory
    _seed_and_explore(worker, source)
    assert _capture(worker)[0].exit_code == 0
    store, original = source.parent / "models", Path.lstat
    introduced = []

    def arriving(path, *args, **kwargs):
        if path == store and not introduced:
            introduced.append(True)
            store.mkdir()
            raise FileNotFoundError("SYNTHETIC_FIXTURE concurrent store arrival")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", arriving)
    result, payload = _invoke("cleanup-check", worker)
    assert introduced and result.exit_code != 0 and worker.exists()
    assert "model_store_unverified" in payload["error"] and store.is_dir()


def test_artifact_free_cleanup_keeps_existing_success_contract(cli_memory):
    authority, _, worker, source, _ = cli_memory
    _seed_and_explore(worker, source)
    assert _capture(worker)[0].exit_code == 0
    before = list(authority.iterdump())
    result, checked = _invoke("cleanup-check", worker)
    assert result.exit_code == 0, result.output
    assert checked == {"ok": True, "research_cycle_id": "fixture-cli-memory",
                       "cleanup_allowed": True}
    assert worker.exists() and not (source.parent / "models").exists()
    assert list(authority.iterdump()) == before


def test_retention_never_resolves_or_reads_a_model(cli_memory, monkeypatch):
    import algua.models as models
    import algua.models.registry as registry

    _, _, worker, source, _ = cli_memory
    _seed_and_explore(worker, source)
    _record(source)
    assert _capture(worker)[0].exit_code == 0

    def forbidden(*args, **kwargs):
        pytest.fail("retention attempted a model API")

    for module in (models, registry):
        for name in ("register", "get_version", "get_version_with_bytes", "load_artifact_bytes"):
            monkeypatch.setattr(module, name, forbidden)
    result, payload = _invoke("cleanup-check", worker)
    assert result.exit_code != 0 and "model_references" in payload["error"]


def _capture_driver_reference(case):
    repo, worker, _, archive = case
    authority = connect(repo / "data/algua.db")
    try:
        cycle = ResearchCycle(authority, repo / "data/research-cycles", STAMP)
        memory = ResearchMemory(cycle, archive)
        memory.seed(worker)
        _record(worker / ".funnel-scratch/data/algua.db")
        memory.capture(worker, worker_exit=0, source_commit=_git(repo, "rev-parse", "HEAD"))
    finally:
        authority.close()


def _probe_preamble(repo, worker):
    """Require real cleanup JSON, so an unavailable fixture executable cannot prove retention."""
    return (_preamble(repo, worker) + '\nset +e\nmemory_cli cleanup-check --run "$STAMP" '
        '--worker-root "$WORKTREE" > ' + shlex.quote(str(repo / "cleanup-probe.json"))
        + '\nprobe_rc=$?\nset -e\nprintf "%s" "$probe_rc" > '
        + shlex.quote(str(repo / "cleanup-probe.exit")) + '\n')


def _assert_probe(repo, reason):
    payload = json.loads((repo / "cleanup-probe.json").read_text())
    status = int((repo / "cleanup-probe.exit").read_text())
    if reason is None:
        assert status == 0 and payload == {"ok": True, "research_cycle_id": STAMP,
                                          "cleanup_allowed": True}
    else:
        assert status == 1 and payload["ok"] is False and payload["code"] == "invalid_input"
        assert reason in payload["error"]


@pytest.mark.parametrize("driver_memory", ["fresh"], indirect=True)
def test_actual_bash_cleanup_retains_refs_only(driver_memory):
    repo, worker, _, _ = driver_memory
    _capture_driver_reference(driver_memory)
    result = _bash(_probe_preamble(repo, worker)
                   + '\nremove_retained_worktree "$WORKTREE" "$STAMP"\n', repo)
    _assert_probe(repo, "model_references")
    assert result.returncode != 0 and worker.exists(), result.stdout + result.stderr
    assert not (worker / ".funnel-scratch/data/models").exists()


@pytest.mark.parametrize("driver_memory", [None, "legacy"], indirect=True)
def test_actual_zero_candidate_bash_retains_store_in_both_layouts(driver_memory):
    repo, worker, _, _ = driver_memory
    store = worker / ".funnel-scratch/data/models"
    store.mkdir()
    text = DRIVER.read_text()
    block = text[text.index('if [[ "${N_ENQUEUED:-}" == "0" ]]'):
                 text.index('\necho\necho "Done. Review')]
    result = _bash(_probe_preamble(repo, worker) + block, repo)
    _assert_probe(repo, "model_store_present")
    assert result.returncode == 0 and worker.exists(), result.stdout + result.stderr
    assert store.is_dir()  # Retention does not fabricate a worker/cycle failure.


def test_terminal_queue_retains_store_without_rewriting_terminal_result(driver_memory):
    repo, worker, _, _ = driver_memory
    (worker / ".funnel-scratch/data/models").mkdir()
    assert _bash(_probe_preamble(repo, worker), repo).returncode == 0
    _assert_probe(repo, "model_store_present")
    queue = _queue_module()
    path, lock, branch = repo / "data/queue.json", repo / "data/queue.lock", f"research-run/{STAMP}"
    queue.enqueue(path, lock, strategy="fixture", branch=branch, universe="fixture",
                  start="2024-01-01", end="2024-12-31",
                  eval_context={"demo": True, "sweep_grid": {"n": [1]}, "rank_by": "mean_sharpe"})
    queue.record_attempt(path, lock, key=f"fixture@{branch}",
                         stdout_text='{"ok":true,"status":"promoted_allocated"}')
    before = path.read_bytes()
    result = queue.cleanup_branch(path, lock, branch=branch, repo_root=repo)
    assert result["removed"] is False and worker.exists()
    assert result["skipped"] == "research_memory_unverified" and path.read_bytes() == before


def test_bash_fallback_rechecks_new_model_store_after_actual_git_refusal(driver_memory):
    repo, worker, _, _ = driver_memory
    (worker / ".git").unlink()
    store, marker = worker / ".funnel-scratch/data/models", repo / "git-refused"
    fault_bin = repo / "fault-bin"
    fault_bin.mkdir()
    git = shutil.which("git")
    assert git is not None
    fault = shlex.join([sys.executable, "-c",
        "from pathlib import Path;import sys;Path(sys.argv[1]).mkdir();"
        "Path(sys.argv[2]).write_text('SYNTHETIC_FIXTURE real Git refusal')",
        str(store), str(marker)])
    (fault_bin / "git").write_text(
        '#!/bin/sh\n' + shlex.quote(git) + ' "$@"\ncode=$?\n'
        + 'if [ "$3:$4" = worktree:remove ] && [ "$code" -ne 0 ]; then\n'
        + fault + '\nfi\nexit "$code"\n')
    (fault_bin / "git").chmod(0o755)
    command = _probe_preamble(repo, worker) + f'export PATH={shlex.quote(str(fault_bin))}:"$PATH"\n'
    result = _bash(command + '\nremove_retained_worktree "$WORKTREE" "$STAMP"\n', repo)
    _assert_probe(repo, None)
    assert marker.exists() and result.returncode != 0 and worker.exists(), (
        result.stdout + result.stderr)
    assert store.is_dir()
