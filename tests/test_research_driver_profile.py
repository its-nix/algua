"""Execute the actual Bash profile adapters; no chooser/model/worker is launched."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from algua.operator.research_memory_checkpoint import canonical
from tests.test_research_driver_campaign_choice import driver_pool as driver_pool
from tests.test_research_profile import configured as configured
from tests.test_research_profile import profile

DRIVER = Path(__file__).resolve().parents[1] / ".opencode/scripts/run-research-loop.sh"


def test_unconfigured_driver_profile_does_not_call_helper(tmp_path):
    source = DRIVER.read_text()
    block = source[source.index("# Optional pinned research profile"):
                   source.index("# Lock BEFORE any claim")]
    env = {k: v for k, v in os.environ.items() if k != "ALGUA_RESEARCH_PROFILE"}
    command = 'set -euo pipefail\nPYTHON=/must-not-execute\n' + block
    result = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout == result.stderr == ""
    assert not list(tmp_path.iterdir())


def test_configured_driver_requires_bound_campaign_before_claim(tmp_path):
    source = DRIVER.read_text()
    block = source[source.index("# Optional pinned research profile"):
                   source.index("# Lock BEFORE any claim")]
    result = subprocess.run(["bash", "-c", 'set -euo pipefail\n' + block],
        env={**os.environ, "ALGUA_RESEARCH_PROFILE": str(tmp_path / "missing")},
        capture_output=True, text=True)
    assert result.returncode != 0 and "requires campaign" in result.stderr
    assert not list(tmp_path.iterdir())


def test_driver_admission_and_goal_use_same_profile(configured, tmp_path):
    store, _, _, _ = configured
    receipt = profile.load_research_profile(store.data_dir)
    response = {"ok": True, "phase": "running", "research_cycle_id": "fixture",
        "campaign": {"menu": {"request": {"research_cycle_id": "fixture",
            "database": "/fixture.db", "context": {"research_profile": receipt}}}},
        "claimed": [{"id": 1, "hypothesis": "original", "claim_token": "secret-token"}]}
    source = DRIVER.read_text()
    begin = source.index("  # Bind the pinned profile to the same successful campaign admission.")
    block = source[begin:source.index("  unset CLAIM_START_JSON", begin)]
    begin = source.index("# Forward the configured profile before optional public memory.")
    goal = source[begin:source.index("# Default-off preserves", begin)]
    values = {"RESEARCH_PROFILE_JSON": canonical(receipt).decode(),
        "CLAIM_START_JSON": json.dumps(response), "CLAIMED_JSON": json.dumps(response["claimed"]),
        "CLAIMED_PROMPT_JSON": "[]", "STAMP": "fixture", "AUTH_DB": "/fixture.db",
        "PYTHON": sys.executable, "GOAL": "original goal", "rc": "0"}
    command = "set -euo pipefail\n" + "\n".join(
        f"{k}={shlex.quote(v)}" for k, v in values.items()) + "\n" + block + goal
    command += '\nprintf "%s" "$CLAIMED_PROMPT_JSON" > ' + shlex.quote(str(tmp_path / "claims"))
    command += '\nprintf "%s" "$GOAL" > ' + shlex.quote(str(tmp_path / "goal"))
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    claims = json.loads((tmp_path / "claims").read_text())
    assert claims[0]["evaluation_profile"] == receipt and "claim_token" not in claims[0]
    assert canonical(receipt).decode() in (tmp_path / "goal").read_text()
    assert "secret-token" not in (tmp_path / "goal").read_text()


def test_actual_driver_refuses_proxy_candidate_before_controller_finish(tmp_path):
    report = tmp_path / "report.md"
    report.write_text('```json\n{"hypotheses":[{"title":"fixture","idea_id":1,'
        '"outcome":"candidate_preview_pass","reason":"forged pass"}]}\n```\n')
    source = DRIVER.read_text()
    block = source[source.index("record_outcomes() {"):
                   source.index("\n# Armed before claiming")]
    output = tmp_path / "finish.json"
    fake_cli = tmp_path / "cli.py"
    fake_cli.write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
    values = {"RESEARCH_PROFILE_JSON": "configured", "PYTHON": sys.executable,
        "CYCLE_ACTIVE": "1", "STAMP": "fixture", "WORKER_EXIT": "0", "AUTH_DB": "/unused",
        "AUTH_DATA_DIR": str(tmp_path), "CYCLE_RESULT": str(output)}
    command = "set -euo pipefail\n" + "\n".join(
        f"{k}={shlex.quote(v)}" for k, v in values.items()) + "\n"
    command += "AUTH_CLI=(" + shlex.join([sys.executable, str(fake_cli)]) + ")\n" + block
    command += "\nrecord_outcomes " + shlex.quote(str(report)) + " completed\n"
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    args = json.loads(output.read_text())
    assert args[args.index("--phase") + 1] == "profile_refused"
    assert "--report" not in args
    assert "research profile report refused" in result.stderr


def test_bound_proxy_context_suppresses_mergeback_independent_of_report(tmp_path):
    from tests._research_driver_source import function_python
    from tests.test_research_run_digest import _ec

    report = tmp_path / "report.md"
    report.write_text("```json\n" + json.dumps({"hypotheses": [{
        "title": "fixture", "verdict": "candidate-preview-pass",
        "outcome": "candidate_preview_pass",
        "reason": "untrusted pass", "idea_id": 1, "merge_back": {"idea_id": 1,
            "strategy": "fixture_strategy", "universe": "fake-pit", "start": "2024-11-01",
            "end": "2026-11-08", "eval_context": _ec()}}]}) + "\n```\n")
    cycle = tmp_path / "cycle.json"
    cycle.write_text(json.dumps({"campaign": {"menu": {"request": {
        "context": {"research_profile": {"qualification_eligible": False}}}}}}))
    digest, queue = tmp_path / "digest", tmp_path / "queue"
    args = [str(digest), "completed", "fixture", "branch", "", "0", "0", "1", "1", "0",
            str(report), "fixture_strategy", str(DRIVER.parents[2]), str(queue),
            str(tmp_path / "queue.lock"), "", '[{"id":1,"claim_token":"secret"}]', str(cycle)]
    result = subprocess.run([sys.executable, "-", *args],
        input=function_python(DRIVER.read_text(), "append_digest"), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not queue.exists()
    assert json.loads(digest.read_text())["hypotheses"][0]["merge_back"] is None


def test_actual_chooser_menu_contains_verified_profile(
        configured, driver_pool, tmp_path, monkeypatch):
    from tests import test_research_driver_campaign_choice as chooser

    store, record, _, _ = configured
    expected = profile.load_research_profile(store.data_dir)
    # The separate CLI uses a genuine fixture snapshot ID; only the expected fixed ID changes.
    prefix = ('from algua.operator import research_profile\n'
              f'research_profile.SNAPSHOT_ID = {record.snapshot_id!r}\n')
    monkeypatch.setattr(chooser, "FIXTURE_CLI", prefix + chooser.FIXTURE_CLI)
    # Both fixtures share this private data directory; the CLI verifies its actual payload.
    assert store.data_dir == tmp_path / "data"
    result = chooser._driver_start(tmp_path, "--choose-campaign")
    assert result.returncode == 0, result.stderr
    calls = chooser._calls(tmp_path)
    assert len(calls) == 1
    assert calls[0]["menu"]["request"]["context"]["research_profile"] == expected
