"""Actual Bash admission/prompt adapters; fixture workers prove only primary input bytes."""
from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.operator.research_memory_checkpoint import canonical
from tests import test_research_driver_campaign_choice as driver
from tests import test_research_prompt_memory as pure_tests
from tests.test_research_prompt_memory import memory_case as memory_case

pure_admission = pure_tests.admission


@pytest.fixture
def admission(pure_admission):
    # The pure fixture permits any controller directory; the real CLI uses this fixed layout.
    # Move the whole disposable directory without altering the admitted request or its identity.
    response, stamp, database = pure_admission
    directory = Path(database).parent
    (directory / "cycles").rename(directory / "research-cycles")
    return response, stamp, database


def _parser():
    source = driver.DRIVER.read_text()
    return source[source.index('while [[ $#'):source.index('\nREPO_ROOT=')]


def _goal_blocks():
    source = driver.DRIVER.read_text()
    start = source.index("read -r -d '' GOAL <<EOF")
    end = source.index("\n# The runtime, the sandbox posture", start)
    baseline_end = source.index("\nEOF\n", start) + len("\nEOF\n")
    return source[start:baseline_end], source[baseline_end:end]


def _run(tmp_path, case, *, enabled=True, snapshot_change=None, goal_padding="",
         worker_exit=0, reconcile=False, forbid_prompt_helper=False):
    response, stamp, database = case
    response = copy.deepcopy(response)
    if snapshot_change:
        snapshot_change(response)
    source = driver.DRIVER.read_text()
    fixture_response = tmp_path / "admission.json"
    # Match the real CLI emit wire (ASCII JSON escapes), preserving decoded public values.
    fixture_response.write_text(json.dumps(response, indent=2, default=str), encoding="utf-8")
    calls = tmp_path / "commands.jsonl"
    cli = tmp_path / "fixture-cli.py"
    cli.write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        f"with Path({str(calls)!r}).open('a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1:4] == ['research','idea','cycle-start']:\n"
        f"    sys.stdout.buffer.write(Path({str(fixture_response)!r}).read_bytes())\n"
        "else:\n"
        "    from algua.config.settings import Settings\n"
        "    Settings.model_config['env_file']=None\n"
        "    from algua.cli.main import main\n"
        "    main()\n")
    worktree = tmp_path / "not-created-worker"
    prompt = tmp_path / "primary-prompt.md"
    worker = tmp_path / "fixture-worker.py"
    delivered = tmp_path / "fixture-primary-input.bin"
    worker.write_text("import sys\nfrom pathlib import Path\n"
                      f"Path({str(delivered)!r}).write_bytes(Path(sys.argv[1]).read_bytes())\n"
                      f"raise SystemExit({worker_exit})\n")
    helper_python = tmp_path / "forbidden-helper"
    helper_marker = tmp_path / "helper-called"
    helper_python.write_text("#!/bin/sh\nprintf called > "
                             + shlex.quote(str(helper_marker)) + "\nexit 88\n")
    helper_python.chmod(0o700)
    values = {
        "AUTH_DB": database, "AUTH_DATA_DIR": str(Path(database).parent), "STAMP": stamp,
        "REPO_ROOT": str(driver.ROOT),
        "PYTHON": str(helper_python) if forbid_prompt_helper else sys.executable,
        "DRY_RUN": "0",
        "CLAIMED_JSON": "[]", "N_CLAIMED": "0", "TIMEOUT": "45m",
        "N_HYPOTHESES": "3", "WORKER_LIMIT": "1", "CPU_SECONDS": "2700",
        "MEMORY_MB": "16384", "FILE_MB": "512", "MAX_COST": "", "CATEGORY": "",
        "CAMPAIGN": "", "CHOOSE_CAMPAIGN": "1", "PUBLIC_MEMORY_CONTEXT": "1",
        "RESEARCH_PUBLIC_MEMORY_CONTEXT": "1" if enabled else "0",
        "AUTH_TRACKING_BACKEND": "mlflow-sqlite", "AUTH_TRACKING_URI": "unused://fixture",
        "CYCLE_PHASE": "setup_failed", "CYCLE_ACTIVE": "1",
        "CYCLE_RESULT": str(tmp_path / "finish.json"), "WORKTREE": str(worktree),
        "ANTI_DUP_BLOCK": "", "RUNS_DIR": str(tmp_path),
        "PROMPT_FILE": str(prompt), "GOAL_PADDING": goal_padding,
    }
    command = "set -euo pipefail\n" + "\n".join(
        f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n"
    command += "AUTH_CLI=(" + shlex.join([sys.executable, str(cli)]) + ")\n"
    if reconcile:
        record = source[source.index("record_outcomes() {"):
                        source.index("\n# Armed before claiming")]
        cleanup = source[source.index("cleanup_setup() {"):
                         source.index("\n# Lock BEFORE any claim")]
        command += (record + "\n" + cleanup + "\n"
                    "remove_retained_worktree() { return 0; }\n"
                    "append_digest() { return 0; }\ntrap cleanup_setup EXIT\n")
    start = source.index('if [[ "${DRY_RUN}" -eq 1 ]]; then\n  echo "would claim')
    end = source.index("\n# Everything the agent reads/writes", start)
    command += source[start:end] + "\n"
    baseline, adapter = _goal_blocks()
    command += baseline + '\nGOAL="${GOAL}${GOAL_PADDING}"\nBEFORE_GOAL="${GOAL}"\n' + adapter
    command += '\nprintf "%s" "${BEFORE_GOAL}" > ' + shlex.quote(str(tmp_path / "before.bin"))
    command += '\nmkdir -p "${WORKTREE}"\n'
    command += "AGENT_CMD=(" + shlex.join([sys.executable, str(worker), str(prompt)]) + ")\n"
    start = source.index('RUN_LOG="${WORKTREE}/research-loop.log"')
    end = source.index('\nrate_limited=0', start)
    command += source[start:end] + '\nprintf "%s" "${WORKER_EXIT}" > '
    command += shlex.quote(str(tmp_path / "worker-exit.txt")) + "\ntrap - EXIT\n"
    command = command.replace("python3 -c", shlex.quote(sys.executable) + " -c")
    env = {**os.environ, "ALGUA_DB_PATH": database,
           "ALGUA_DATA_DIR": str(Path(database).parent), "PYTHONPATH": str(driver.ROOT)}
    result = subprocess.run(["bash", "-c", command], cwd=driver.ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    return result, delivered, calls


@pytest.mark.parametrize("args,expected", [([], 2), (["--choose-campaign"], 0),
    (["--public-memory-context"], 2), (["--choose-campaign", "--no-public-memory-context"], 2)])
def test_prompt_memory_requires_campaign_and_respects_explicit_optout(tmp_path, args, expected):
    command = driver._preamble(tmp_path) + "set -- " + shlex.join(
        [*args, "--research-public-memory-context"]) + "\n" + _parser()
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    assert result.returncode == expected
    if expected:
        assert ("requires --public-memory-context" in result.stderr
                or "excludes explicit memory flags" in result.stderr)
    assert not (tmp_path / "data").exists()


def test_enabled_primary_input_contains_exact_admitted_wrapper(admission, tmp_path):
    from algua.operator.research_prompt_memory import decode_admitted_memory

    result, delivered, calls = _run(tmp_path, admission)
    assert result.returncode == 0, result.stdout + result.stderr
    actual = delivered.read_bytes()
    wrapper = decode_admitted_memory(canonical(admission[0]), cycle_id=admission[1],
                                     database=admission[2])
    assert actual.startswith((tmp_path / "before.bin").read_bytes())
    assert actual.count(canonical(wrapper)) == 1 and len(actual) <= 96 * 1024
    assert actual.endswith(b"\n") and not actual.endswith(b"\n\n")
    assert all(idea["claim_token"].encode() not in actual for idea in admission[0]["claimed"])
    assert [json.loads(line)[:3] for line in calls.read_text().splitlines()] == [
        ["research", "idea", "cycle-start"]]
    assert b"author receipt or use" in actual and b"authority=none" in actual


def test_public_unicode_quotes_and_shell_text_remain_data(admission, tmp_path, monkeypatch):
    from tests.test_research_prompt_memory import reseal

    marker = tmp_path / "must-not-execute"
    opaque = "quote' `touch " + str(marker) + "`\n雪 $(touch " + str(marker) + ")"
    # This inherited stdio choice must not decode/transcode the driver's UTF-8 prompt transport.
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")

    def change(value):
        snapshot = value["campaign"]["menu"]["request"]["context"]["public_research_memory"]
        snapshot["observations"][0]["inputs"]["params"]["opaque"] = opaque
        reseal(value)

    result, delivered, _ = _run(tmp_path, admission, snapshot_change=change)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.dumps(opaque, ensure_ascii=False).encode() in delivered.read_bytes()
    assert not marker.exists()


@pytest.mark.parametrize("restart", [False, True])
def test_actual_empty_cycle_never_forwards_or_launches(
        admission, memory_case, tmp_path, restart):
    response, previous, database = admission
    authority = memory_case[0]
    directory = Path(database).parent / "research-cycles"
    ResearchCycle(authority, directory, previous).finish(phase="setup_failed", worker_exit=1)
    cycle = ResearchCycle(authority, directory, "empty-prompt-fixture")
    request = {"limits": CycleLimits(max_hypotheses=3), "ttl_minutes": 1440,
               "context": response["campaign"]["menu"]["request"]["context"]}
    menu = cycle.campaign_menu(**request)
    campaign = {"menu": menu, "selection": {"menu_id": menu["menu_id"], "choices": []}}
    claimed, empty = cycle.start(**request, campaign=campaign)
    if restart:
        claimed, empty = cycle.start(**request, campaign=campaign)
    assert claimed == [] and empty["phase"] == ("controller_restart" if restart else "pool_empty")
    empty["claimed"] = []
    result, delivered, _ = _run(tmp_path, (empty, cycle.cycle_id, database),
                               reconcile=True, forbid_prompt_helper=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not delivered.exists() and not (tmp_path / "primary-prompt.md").exists()
    assert not (tmp_path / "helper-called").exists() and cycle.rows() == []


def test_off_preserves_exact_goal_bytes_and_never_invokes_prompt_helper(admission, tmp_path):
    source = driver.DRIVER.read_text()
    _, adapter = _goal_blocks()
    assert "RESEARCH_PUBLIC_MEMORY_CONTEXT" in adapter
    result, delivered, _ = _run(tmp_path, admission, enabled=False, forbid_prompt_helper=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert delivered.read_bytes() == (tmp_path / "before.bin").read_bytes() + b"\n"
    assert not (tmp_path / "helper-called").exists()
    # Both pure-helper calls belong only to explicit opt-in branches, never the legacy GOAL.
    assert source.count("from algua.operator.research_prompt_memory import") == 2


@pytest.mark.parametrize("fault", ["missing-snapshot", "foreign-cycle", "credential", "overflow"])
def test_prelaunch_refusal_reconciles_same_claims_without_worker_result(
        admission, memory_case, tmp_path, fault):
    from tests.test_research_prompt_memory import reseal

    response, stamp, _ = admission
    ids = {idea["id"] for idea in response["claimed"]}

    def change(value):
        context = value["campaign"]["menu"]["request"]["context"]
        if fault == "missing-snapshot":
            context.pop("public_research_memory")
        elif fault == "foreign-cycle":
            value["research_cycle_id"] = "other"
        elif fault == "credential":
            context["public_research_memory"]["observations"][0]["inputs"]["params"][
                "opaque"] = value["claimed"][0]["claim_token"]
        reseal(value)

    result, delivered, calls = _run(tmp_path, admission, snapshot_change=change,
        goal_padding="雪" * 33000 if fault == "overflow" else "", reconcile=True)
    assert result.returncode == 1 and "research prompt memory" in result.stderr
    assert "Traceback" not in result.stderr and not delivered.exists()
    assert not (tmp_path / "primary-prompt.md").exists()
    assert not (tmp_path / "worker-exit.txt").exists()
    assert all(idea["claim_token"] not in result.stderr for idea in response["claimed"])
    commands = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [row[:3] for row in commands] == [
        ["research", "idea", "cycle-start"], ["research", "idea", "cycle-finish"]]
    assert "--phase" in commands[1] and "setup_failed" in commands[1]
    finished = json.loads((tmp_path / "finish.json").read_text())
    assert finished["phase"] == "setup_failed" and finished["unfinished_count"] == 0
    authority = memory_case[0]
    rows = authority.execute("SELECT idea_id, outcome, reason FROM idea_attempts "
                             "WHERE run_stamp=?", (stamp,)).fetchall()
    assert {row[0] for row in rows} == ids
    assert all(row[1] == "run_error" and row[2] == "setup_failed:1" for row in rows), [
        tuple(row) for row in rows]


@pytest.mark.parametrize("worker_exit", [0, 3, 124])
def test_real_pipeline_preserves_raw_fixture_worker_exit(admission, tmp_path, worker_exit):
    result, delivered, _ = _run(tmp_path, admission, worker_exit=worker_exit)
    assert result.returncode == 0, result.stdout + result.stderr
    assert delivered.is_file()
    assert (tmp_path / "worker-exit.txt").read_text() == str(worker_exit)


def test_dry_run_new_flag_has_no_claim_reader_prompt_or_worker(tmp_path):
    source = driver.DRIVER.read_text()
    start = source.index('if [[ "${DRY_RUN}" -eq 1 ]]; then\n  echo "would claim')
    end = source.index("\n# Everything the agent reads/writes", start)
    command = driver._preamble(tmp_path, DRY_RUN="0", PUBLIC_MEMORY_CONTEXT="0")
    command += ("set -- --choose-campaign --public-memory-context "
                "--research-public-memory-context --dry-run\n")
    command += _parser() + source[start:end]
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("would claim ") and not (tmp_path / "data").exists()
