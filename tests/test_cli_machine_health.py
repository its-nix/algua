"""Persisted FIXTURE artifacts exercise the public read-only machine surface."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from algua.cli.main import app

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)
runner = CliRunner()


def _run(minutes=0, **extra):
    return {"research_cycle_id": f"cycle-{minutes}", "stamp": f"cycle-{minutes}",
            "finished_at": (NOW - timedelta(minutes=minutes)).isoformat(),
            "exit_code": 0, "timed_out": False, "rate_limited": False,
            "outcome": "completed", **extra}


def _digest(directory, records):
    (directory / "research-runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records))


def _seed(directory, monkeypatch, records=None):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(directory))
    monkeypatch.setenv("ALGUA_DB_PATH", str(directory / "absent.db"))
    _digest(directory, records if records is not None else [_run()])
    (directory / "operator_sessions.json").write_text(json.dumps({"paper": {
        "rc": 0, "session": "2026-10-30", "recorded_at": NOW.isoformat()}}))
    (directory / "mergeback-queue.json").write_text('{"items": {}}')


def _tree(directory):
    return {str(path.relative_to(directory)): (
        "directory" if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest(),
        path.stat().st_mtime_ns,
    ) for path in sorted(directory.rglob("*"))}


def _invoke():
    return runner.invoke(app, ["ops", "machine-health", "--now", NOW.isoformat(), "--fixture"])


def test_machine_health_reads_persisted_negative_economics_without_writes(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_run(hypotheses=[
        {"outcome": "holdout_negative"}, {"outcome": "walkforward_refuted"},
        {"outcome": "sweep_unstable"}, {"outcome": "integrity_fail"},
    ])])
    before = _tree(tmp_path)
    result = _invoke()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["evidence_mode"] == "FIXTURE"
    assert payload["loops"] == {"research": "ok", "paper": "ok", "mergeback": "idle"}
    assert payload["incidents"] == []
    assert _tree(tmp_path) == before


def test_repeated_systemic_faults_deduplicate_retries_preserving_lineage(tmp_path, monkeypatch):
    first = _run(90, exit_code=1)
    second = _run(60, exit_code=1)
    retry = _run(30, exit_code=1, research_cycle_id=second["research_cycle_id"],
                 run_id="different-retry-id", branch="private-branch", prompt="private-prompt")
    records = [first, second, second, retry]
    _seed(tmp_path, monkeypatch, records)
    before = _tree(tmp_path)
    result = _invoke()
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert len(payload["incidents"]) == 1
    incident = payload["incidents"][0]
    assert incident["owner"] == "algua-lead"
    assert incident["severity"] == "important"
    assert incident["cause"] == "worker_failed"
    assert incident["first_seen"] == first["finished_at"]
    assert incident["last_seen"] == retry["finished_at"]
    assert incident["reproduction"] == {"method": "distinct_cycles", "observations": 2}
    assert len(set(incident["evidence_refs"])) == 2
    assert len(incident["fingerprint"]) == 64
    assert incident["required_action"] == "reproduce_test_repair_verify_deployment"
    assert incident["status"] == "open"
    assert incident["recovery"] == "unverified"
    assert _invoke().stdout == result.stdout
    assert _tree(tmp_path) == before

    _digest(tmp_path, [*records, _run(0, exit_code=1)])
    extended = json.loads(_invoke().stdout)["incidents"][0]
    assert extended["fingerprint"] == incident["fingerprint"]
    assert extended["first_seen"] == incident["first_seen"]
    assert extended["last_seen"] == NOW.isoformat()
    assert extended["reproduction"]["observations"] == 3
    assert set(incident["evidence_refs"]) < set(extended["evidence_refs"])


def test_one_cycle_retries_are_not_independent_reproduction(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [
        _run(60, exit_code=1, research_cycle_id="same-origin"),
        _run(30, exit_code=1, research_cycle_id="same-origin", run_id="retry-2"),
        _run(0, exit_code=1, research_cycle_id="same-origin", run_id="retry-3"),
    ])
    result = _invoke()
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["loops"]["research"] == "failing"
    assert payload["incidents"] == []


def test_merged_fix_and_claimed_recovery_cannot_close_incident(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_run(90, exit_code=1), _run(60, exit_code=1), _run(
        fix_merged=True, deployed=True, verified=True, recovery={
            "status": "recovered", "deployment": "claimed", "verification": "pass"})])
    result = _invoke()
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["loops"]["research"] == "ok"
    assert payload["incidents"][0]["status"] == "open"
    assert payload["incidents"][0]["recovery"] == "unverified"
    assert payload["evidence_mode"] == "FIXTURE"


@pytest.mark.parametrize("record", [
    _run(exit_code=False), _run(exit_code="0"), _run(timed_out="false"),
    _run(rate_limited="false"), _run(outcome="unrecognized"), _run(outcome=[]),
    _run(finished_at=None), _run(finished_at="not-a-time"),
    _run(finished_at=NOW.replace(tzinfo=None).isoformat()),
    _run(finished_at=(NOW + timedelta(hours=1)).isoformat()),
    _run(research_cycle_id=None),
])
def test_malformed_research_never_healthy(tmp_path, monkeypatch, record):
    _seed(tmp_path, monkeypatch, [record])
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["research"] == "unknown"


@pytest.mark.parametrize("suffix", ['{"torn":', '[]\n', 'null\n'])
def test_malformed_digest_tail_cannot_hide_behind_last_good_row(tmp_path, monkeypatch, suffix):
    _seed(tmp_path, monkeypatch)
    with (tmp_path / "research-runs.jsonl").open("a") as stream:
        stream.write(suffix)
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["research"] == "unknown"


@pytest.mark.parametrize("entry", [
    {"rc": False, "session": "2026-10-30", "recorded_at": NOW.isoformat()},
    {"rc": 0, "session": "bad", "recorded_at": NOW.isoformat()},
    {"rc": 0, "session": "2027-10-30", "recorded_at": NOW.isoformat()},
    {"rc": 0, "recorded_at": NOW.isoformat()},
    {"rc": 0, "session": "2026-10-30", "recorded_at": (NOW + timedelta(hours=1)).isoformat()},
])
def test_invalid_paper_marker_is_unknown(tmp_path, monkeypatch, entry):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "operator_sessions.json").write_text(json.dumps({"paper": entry}))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["paper"] == "unknown"


@pytest.mark.parametrize("items", [
    {"bad": None}, {"bad": {}},
    {"bad": {"attempts": False, "enqueued_at": NOW.isoformat()}},
    {"bad": {"attempts": -1, "enqueued_at": NOW.isoformat()}},
    {"bad": {"attempts": 1, "enqueued_at": "bad"}},
    {"bad": {"attempts": 1, "enqueued_at": (NOW + timedelta(hours=1)).isoformat()}},
])
def test_invalid_queue_item_is_unknown(tmp_path, monkeypatch, items):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "mergeback-queue.json").write_text(json.dumps({"items": items}))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["mergeback"] == "unknown"


@pytest.mark.parametrize("name,loop", [
    ("research-runs.jsonl", "research"), ("operator_sessions.json", "paper"),
    ("mergeback-queue.json", "mergeback"),
])
def test_missing_evidence_never_healthy_or_created(tmp_path, monkeypatch, name, loop):
    _seed(tmp_path, monkeypatch)
    (tmp_path / name).unlink()
    before = _tree(tmp_path)
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"][loop] == "unknown"
    assert _tree(tmp_path) == before


def test_stale_session_cannot_be_hidden_by_fresh_marker_write(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "operator_sessions.json").write_text(json.dumps({"paper": {
        "rc": 0, "session": "2026-01-02", "recorded_at": NOW.isoformat()}}))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["paper"] == "stale"


@pytest.mark.parametrize("name", [
    "research-runs.jsonl", "operator_sessions.json", "mergeback-queue.json",
])
def test_oversized_artifacts_fail_closed(tmp_path, monkeypatch, name):
    _seed(tmp_path, monkeypatch)
    (tmp_path / name).write_text(" " * (1024 * 1024 + 1))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_incident_lineage_includes_evidence_older_than_private_status_window(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_run(180, exit_code=1), _run(150, exit_code=1),
                                  *[_run(i) for i in range(100, -1, -1)]])
    result = _invoke()
    assert result.exit_code == 1
    incident = json.loads(result.stdout)["incidents"][0]
    assert incident["first_seen"] == _run(180)["finished_at"]
    assert incident["reproduction"]["observations"] == 2


@pytest.mark.parametrize("fault,extra", [
    ("worker_timeout", {"timed_out": True}),
    ("rate_limited", {"rate_limited": True, "exit_code": 1}),
    ("setup_failed", {"outcome": "setup_failed", "exit_code": 1}),
    ("claim_failed", {"outcome": "claim_failed", "exit_code": 1}),
])
def test_systemic_causes_have_distinct_stable_fingerprints(tmp_path, monkeypatch, fault, extra):
    _seed(tmp_path, monkeypatch, [_run(60, **extra), _run(0, **extra)])
    incident = json.loads(_invoke().stdout)["incidents"][0]
    assert incident["cause"] == fault
    expected = hashlib.sha256(json.dumps(
        ("machine-health/v1", "research", fault), separators=(",", ":")).encode()).hexdigest()
    assert incident["fingerprint"] == expected


def test_public_whitelist_without_delivery_or_registry_access(tmp_path, monkeypatch):
    import algua.cli.ops_cmd as ops_cmd
    import algua.operator.alerts as alerts

    def forbidden(*args, **kwargs):
        pytest.fail("read attempted registry access or external alert delivery")

    monkeypatch.setattr(ops_cmd, "registry_conn", forbidden)
    monkeypatch.setattr(alerts, "emit_alert", forbidden)
    monkeypatch.setenv("ALGUA_ALERT_CMD", "must-never-run")
    private = "/private/account-123: raw prompt\nTraceback: token-secret branch-secret"
    _seed(tmp_path, monkeypatch, [_run(60, exit_code=1, branch=private, prompt=private),
                                  _run(exit_code=1, arbitrary={"nested": private},
                                       stderr=private, traceback=private, report=private)])
    result = _invoke()
    assert result.exit_code == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert set(payload) == {"ok", "schema", "checked_at", "evidence_mode", "loops", "incidents"}
    incident = payload["incidents"][0]
    assert set(incident) == {"fingerprint", "severity", "source", "cause",
                             "first_seen", "last_seen",
                             "evidence_refs", "reproduction", "owner", "required_action",
                             "status", "recovery"}
    assert all(re.fullmatch("[0-9a-f]{64}", value)
               for value in [incident["fingerprint"], *incident["evidence_refs"]])
    assert private not in result.stdout
    assert str(tmp_path) not in result.stdout


def test_invalid_cli_time_and_settings_errors_never_echo_raw_values(tmp_path, monkeypatch):
    private = "/private/token-secret account prompt traceback"
    result = runner.invoke(app, ["ops", "machine-health", "--now", private])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["code"] == "machine_health_unavailable"
    assert private not in result.output
    _seed(tmp_path, monkeypatch)
    monkeypatch.setenv("ALGUA_PAPER_BOOK_CAPACITY", private)
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"] == "machine_health_unavailable"
    assert private not in result.output


def test_actual_console_cli_is_readonly_with_existing_and_missing_registry(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_run(60, exit_code=1), _run(exit_code=1)])
    # Even a registry that would require migration must remain byte-for-byte untouched.
    import sqlite3

    database = tmp_path / "registry.db"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE fixture_only (id INTEGER)")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / ".venv/bin/algua"), "ops", "machine-health",
               "--now", NOW.isoformat(), "--fixture"]
    outputs = []
    for db_path in (database, tmp_path / "missing" / "registry.db"):
        env["ALGUA_DB_PATH"] = str(db_path)
        before = _tree(tmp_path)
        result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
        assert result.returncode == 1, result.stderr
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert len(payload["incidents"]) == 1
        assert payload["evidence_mode"] == "FIXTURE"
        assert _tree(tmp_path) == before
        outputs.append(payload)
    assert outputs[0] == outputs[1]


def test_missing_data_directory_is_never_created(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "absent"))
    before = _tree(tmp_path)
    result = _invoke()
    assert result.exit_code == 1
    assert set(json.loads(result.stdout)["loops"].values()) == {"unknown"}
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("outcome", ["setup_failed", "claim_failed"])
def test_explicit_failure_outcome_with_zero_exit_never_healthy(tmp_path, monkeypatch, outcome):
    _seed(tmp_path, monkeypatch, [_run(outcome=outcome)])
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["research"] == "failing"


def test_pool_empty_driver_error_is_systemic_not_negative_economics(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch, [_run(60, outcome="pool_empty", exit_code=1),
                                  _run(outcome="pool_empty", exit_code=1)])
    result = _invoke()
    assert result.exit_code == 1
    incidents = json.loads(result.stdout)["incidents"]
    assert len(incidents) == 1
    assert incidents[0]["cause"] == "worker_failed"


@pytest.mark.parametrize("session,recorded_at", [
    ("2026-10-31", NOW),  # Saturday is not an XNYS session.
    ("2026-01-01", NOW),  # Exchange holiday.
    ("2026-10-30", datetime(2026, 10, 30, 12, tzinfo=UTC)),  # Before Friday's close.
])
def test_marker_requires_completed_exchange_session(tmp_path, monkeypatch, session, recorded_at):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "operator_sessions.json").write_text(json.dumps({"paper": {
        "rc": 0, "session": session, "recorded_at": recorded_at.isoformat()}}))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["paper"] == "unknown"


@pytest.mark.parametrize("status", [
    "promoted_allocated", "promoted_queued", "already_done", "terminal_failed",
])
def test_terminal_queue_history_is_not_active_work(tmp_path, monkeypatch, status):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "mergeback-queue.json").write_text(json.dumps({"items": {"old": {
        "status": status, "attempts": 1,
        "enqueued_at": (NOW - timedelta(days=30)).isoformat()}}}))
    result = _invoke()
    assert result.exit_code == 0
    assert json.loads(result.stdout)["loops"]["mergeback"] == "idle"


def test_unknown_queue_status_never_healthy(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "mergeback-queue.json").write_text(json.dumps({"items": {"bad": {
        "status": "private-unknown", "attempts": 1, "enqueued_at": NOW.isoformat()}}}))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["mergeback"] == "unknown"


@pytest.mark.parametrize("extra", [["/private/account-secret"], ["--unknown-private-token"]])
def test_cli_parse_errors_are_sanitized_locally(tmp_path, monkeypatch, extra):
    _seed(tmp_path, monkeypatch)
    result = runner.invoke(app, ["ops", "machine-health", *extra])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["code"] == "machine_health_unavailable"
    assert "private" not in result.output


def test_producer_driver_failed_retains_incident_handoff(tmp_path, monkeypatch):
    first = _run(90, outcome="driver_failed", exit_code=143)
    second = _run(60, outcome="driver_failed", exit_code=143)
    retry = _run(30, outcome="driver_failed", exit_code=143,
                 research_cycle_id=second["research_cycle_id"])
    _seed(tmp_path, monkeypatch, [first, second, retry])
    result = _invoke()
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["loops"]["research"] == "failing"
    assert len(payload["incidents"]) == 1
    incident = payload["incidents"][0]
    assert incident["cause"] == "worker_failed"
    assert incident["reproduction"] == {"method": "distinct_cycles", "observations": 2}
    assert incident["first_seen"] == first["finished_at"]
    assert incident["last_seen"] == retry["finished_at"]


@pytest.mark.parametrize("instants", [
    {"started_at": (NOW + timedelta(hours=1)).isoformat()},
    {"recorded_at": (NOW + timedelta(hours=1)).isoformat()},
    {"started_at": (NOW - timedelta(minutes=10)).isoformat(),
     "finished_at": (NOW - timedelta(minutes=20)).isoformat()},
    {"recorded_at": (NOW - timedelta(minutes=10)).isoformat()},
])
def test_supplied_research_instants_require_ordered_past_evidence(tmp_path, monkeypatch, instants):
    _seed(tmp_path, monkeypatch, [_run(**instants)])
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["research"] == "unknown"


def test_missing_queue_status_never_healthy(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    (tmp_path / "mergeback-queue.json").write_text(json.dumps({"items": {"missing-status": {
        "attempts": 1, "enqueued_at": NOW.isoformat()}}}))
    result = _invoke()
    assert result.exit_code == 1
    assert json.loads(result.stdout)["loops"]["mergeback"] == "unknown"


@pytest.mark.parametrize("instants", [
    {"started_at": NOW.isoformat(), "recorded_at": NOW.isoformat()},
    {"started_at": "2026-11-01T13:30:00+02:00", "recorded_at": "2026-11-01T14:00:00+02:00"},
])
def test_ordered_research_instants_preserve_offset_and_equal_time_compatibility(
    tmp_path, monkeypatch, instants,
):
    _seed(tmp_path, monkeypatch, [_run(**instants)])
    result = _invoke()
    assert result.exit_code == 0
    assert json.loads(result.stdout)["loops"]["research"] == "ok"
