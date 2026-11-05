"""Public opt-in campaign routes; fixture runtimes never call a model/provider."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.config.settings import Settings
from algua.registry.db import connect, migrate
from tests.campaign_fixtures import add_idea
from tests.test_campaign_choice_producer import fake_runtime as fake_runtime
from tests.test_research_memory import memory_case as memory_case

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_new_family_admission_receives_recent_negative_archive_without_changing_choice_refs(
    memory_case, fake_runtime, tmp_path, monkeypatch,
):
    from algua.operator.research_memory_checkpoint import canonical
    from algua.operator.research_prompt_memory import decode_admitted_memory, render_research_goal
    from tests.test_campaign_public_memory import _finish
    from tests.test_research_memory import _explore

    authority, prior, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    _finish(prior, worker, receipt)
    directory = prior.directory.parent / "research-cycles"
    prior.directory.rename(directory)
    fresh = add_idea(authority, "Fresh cross-family hypothesis", family="fresh-family")
    database = authority.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setenv("ALGUA_DB_PATH", database)
    monkeypatch.setenv("ALGUA_DATA_DIR", str(prior.directory.parent))
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", archive.tracking_uri)
    result, response = invoke("cycle-start", "--run", "fresh-with-negative-context", "--limit", "1",
        "--category", fresh.category, "--choose", "--choice-dir", str(tmp_path / "choice"),
        "--public-memory-context")
    assert result.exit_code == 0, result.output
    menu = response["campaign"]["menu"]
    assert menu["choices"][0]["prior_evidence_ids"] == [f"ideas:{fresh.id}"]
    assert response["campaign"]["selection"]["choices"][0]["prior_evidence_ids"] == [
        f"ideas:{fresh.id}"]
    snapshot = menu["request"]["context"]["public_research_memory"]
    assert snapshot["observations"][0]["metrics"]["total_return_is"] == -0.3
    assert snapshot["receipts"][0]["attempt_evidence_ids"] == ["idea_attempts:1"]
    assert snapshot["selection_protocol"] == "recent_completed_attempts_desc/v1"
    assert snapshot["authority"] == "none" and snapshot["association"] == "cycle_only"
    checkpoint = json.loads((directory / "fresh-with-negative-context.json").read_text())
    assert checkpoint["request"]["context"]["public_research_memory"] == snapshot
    wrapper = decode_admitted_memory(canonical(response), cycle_id="fresh-with-negative-context",
                                     database=database)
    goal = render_research_goal("Fixture primary task", wrapper)
    assert canonical(wrapper).decode() in goal
    assert wrapper["snapshot"] == snapshot and "author/interpret" in goal
    assert menu["scorecard"]["totals"]["economic_rejected"] == 1


@pytest.fixture
def public_pool(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    data = tmp_path / "authority-data"
    data.mkdir()
    database = data / "algua.db"
    tracking = tmp_path / "public-memory.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(database))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{tracking}")
    conn = connect(database)
    migrate(conn)
    for title, family in [("Opening auction pressure", "auction"),
                          ("Dividend calendar rotation", "calendar"),
                          ("Liquidity replenishment", "liquidity")]:
        add_idea(conn, title, family=family)
    yield conn, data, tracking
    conn.close()


def invoke(*args):
    result = runner.invoke(app, ["research", "idea", *args])
    return result, json.loads(result.stdout)


def menu(run="manual"):
    return invoke("cycle-start", "--run", run, "--limit", "3", "--menu-only",
                  "--public-memory-context")


def test_existing_controller_empty_campaign_already_returns_clean_idle(public_pool):
    from algua.operator.research_cycle import CycleLimits, ResearchCycle

    conn, data, _ = public_pool
    cycle = ResearchCycle(conn, data / "research-cycles", "existing-empty-selection")
    args = {"limits": CycleLimits(max_hypotheses=1), "context": {}, "ttl_minutes": 1440,
            "category": "empty-category"}
    captured = cycle.campaign_menu(**args)
    assert captured["choices"] == []
    campaign = {"menu": captured, "selection": {"menu_id": captured["menu_id"], "choices": []}}
    claimed, result = cycle.start(**args, campaign=campaign)
    assert claimed == [] and result["ok"] is True and result["phase"] == "pool_empty"
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0


def test_empty_campaign_cli_admits_idle_without_chooser_or_new_attempts(
    public_pool, fake_runtime, tmp_path,
):
    conn, data, tracking = public_pool
    directory = tmp_path / "empty-choice"
    result, payload = invoke("cycle-start", "--run", "empty-campaign", "--limit", "1",
        "--category", "empty-category", "--choose", "--choice-dir", str(directory),
        "--public-memory-context")
    assert result.exit_code == 0, result.output
    assert payload["ok"] is True and payload["phase"] == "pool_empty" and payload["claimed"] == []
    assert payload["campaign"]["selection"]["choices"] == []
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0
    assert not directory.exists() and not fake_runtime.exists() and not tracking.exists()
    assert (data / "research-cycles/empty-campaign.json").exists()


def write_campaign(tmp_path, captured):
    campaign = {"menu": captured, "selection": {"menu_id": captured["menu_id"],
                "choices": [{**captured["choices"][0],
                             "reason": "SYNTHETIC_FIXTURE captured choice"}]}}
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(campaign))
    return path


def test_memory_activation_refuses_legacy_before_registry_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    database = tmp_path / "must-not-create.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(database))
    result, payload = invoke("cycle-start", "--run", "invalid", "--limit", "3",
                             "--public-memory-context")
    assert result.exit_code == 1
    assert payload["code"] == "invalid_input"
    assert payload["error"] == "public_memory_context:activation_invalid"
    assert not database.exists()


def test_empty_enabled_menu_is_explicit_without_creating_mlflow(public_pool):
    conn, data, tracking = public_pool
    before = list(conn.iterdump())
    result, payload = menu()
    assert result.exit_code == 0, result.output
    memory = payload["menu"]["request"]["context"]["public_research_memory"]
    assert memory["schema_version"] == "campaign-public-memory/v1"
    assert memory["status"] == "unavailable"
    assert memory["evidence_mode"] == "UNVERIFIED_WORKER"
    assert memory["authority"] == "none" and memory["association"] == "cycle_only"
    assert memory["observations"] == [] and memory["receipts"] == []
    assert memory["coverage"]["unrecorded_variant_failures"] == "UNKNOWN"
    assert memory["coverage"]["evaluated_worktree_verified"] is False
    assert list(conn.iterdump()) == before
    assert not tracking.exists() and not (data / "research-cycles/manual.json").exists()


def test_default_menu_never_opens_public_store(public_pool, monkeypatch):
    conn, _, tracking = public_pool
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "noop")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", "unsupported://must-not-open")
    before = list(conn.iterdump())
    result, payload = invoke("cycle-start", "--run", "legacy", "--limit", "3", "--menu-only")
    assert result.exit_code == 0, result.output
    assert "public_research_memory" not in payload["menu"]["request"]["context"]
    assert list(conn.iterdump()) == before and not tracking.exists()


def test_manual_memory_context_survives_actual_cycle_check(public_pool, tmp_path):
    conn, data, tracking = public_pool
    result, captured = menu()
    assert result.exit_code == 0, result.output
    path = write_campaign(tmp_path, captured["menu"])
    result, adopted = invoke("cycle-start", "--run", "manual", "--limit", "3",
                              "--campaign", str(path), "--public-memory-context")
    assert result.exit_code == 0, result.output
    assert len(adopted["claimed"]) == 1
    checkpoint = json.loads((data / "research-cycles/manual.json").read_text())
    assert checkpoint["request"]["context"] == captured["menu"]["request"]["context"]
    result, checked = invoke("cycle-check", "--run", "manual", "--scratch-data", str(data),
                              "--worker-root", str(ROOT))
    assert result.exit_code == 0, result.output
    assert checked["context_verified"] is True
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1
    assert not tracking.exists()


def test_flag_off_manual_file_cannot_supply_memory_context(public_pool, tmp_path):
    conn, data, _ = public_pool
    result, captured = menu()
    assert result.exit_code == 0, result.output
    path = write_campaign(tmp_path, captured["menu"])
    before = list(conn.iterdump())
    result, rejected = invoke("cycle-start", "--run", "manual", "--limit", "3",
                               "--campaign", str(path))
    assert result.exit_code == 1 and rejected["ok"] is False
    assert list(conn.iterdump()) == before
    assert not (data / "research-cycles/manual.json").exists()


def test_enabled_chooser_prompt_and_admission_bind_the_same_context(
        public_pool, fake_runtime, tmp_path):
    _, data, tracking = public_pool
    directory = tmp_path / "choice"
    result, adopted = invoke("cycle-start", "--run", "chosen", "--limit", "3", "--choose",
                              "--choice-dir", str(directory), "--public-memory-context")
    assert result.exit_code == 0, result.output
    prompt = (directory / "prompt.txt").read_text()
    assert "untrusted" in prompt.lower() and "cycle_only" in prompt
    captured = json.loads(prompt.split("MENU_JSON\n", 1)[1])
    assert captured == adopted["campaign"]["menu"]
    checkpoint = json.loads((data / "research-cycles/chosen.json").read_text())
    assert checkpoint["request"]["context"] == captured["request"]["context"]
    calls = [json.loads(line) for line in fake_runtime.read_text().splitlines()]
    assert len([call for call in calls if call[0] == "run"]) == 1
    assert not tracking.exists()


@pytest.mark.parametrize("drift", ["authority", "worker", "unknown_context", "manifest"])
def test_memory_setup_still_checks_all_base_source_data_fields(
        public_pool, tmp_path, monkeypatch, drift):
    from algua.cli import idea_ops_cmd

    _, data, _ = public_pool
    result, captured = menu()
    assert result.exit_code == 0, result.output
    path = write_campaign(tmp_path, captured["menu"])
    result, _ = invoke("cycle-start", "--run", "manual", "--limit", "3",
                        "--campaign", str(path), "--public-memory-context")
    assert result.exit_code == 0, result.output
    original = idea_ops_cmd._cycle_context

    def changed(*args, **kwargs):
        context = original(*args, **kwargs)
        if (drift == "authority" and kwargs.get("root") is None
                or drift == "worker" and kwargs.get("root") is not None):
            context["source_baseline_sha256"] = "SYNTHETIC_FIXTURE changed source"
        return context

    monkeypatch.setattr(idea_ops_cmd, "_cycle_context", changed)
    if drift == "unknown_context":
        checkpoint = data / "research-cycles/manual.json"
        altered = json.loads(checkpoint.read_text())
        altered["request"]["context"]["unsupported_context_key"] = True
        checkpoint.write_text(json.dumps(altered))
    elif drift == "manifest":
        (data / "manifest.jsonl").write_text('{"fixture":"changed after admission"}\n')
    result, payload = invoke("cycle-check", "--run", "manual", "--scratch-data", str(data),
                              "--worker-root", str(ROOT))
    assert result.exit_code == 1 and payload["ok"] is False


def test_enabled_manual_restart_reuses_original_snapshot_without_reading_again(
        public_pool, tmp_path, monkeypatch):
    from algua.operator import campaign_memory

    conn, data, _ = public_pool
    result, captured = menu()
    assert result.exit_code == 0, result.output
    path = write_campaign(tmp_path, captured["menu"])
    arguments = ("cycle-start", "--run", "manual", "--limit", "3", "--campaign", str(path),
                 "--public-memory-context")
    result, _ = invoke(*arguments)
    assert result.exit_code == 0, result.output
    before = json.loads((data / "research-cycles/manual.json").read_text())
    rows = [tuple(row) for row in conn.execute("SELECT id,idea_id,claim_token FROM idea_attempts")]

    def no_new_snapshot(*args, **kwargs):
        pytest.fail("recovery must not launch an archive batch or replace decision context")

    monkeypatch.setattr(campaign_memory, "capture_public_memory", no_new_snapshot)
    result, reconciled = invoke(*arguments)
    assert result.exit_code == 1  # unfinished work is honestly recorded as controller_restart
    assert reconciled["phase"] == "controller_restart"
    assert reconciled["unfinished_count"] == 0 and reconciled["attempts_total"] == 1
    assert [tuple(row) for row in conn.execute(
        "SELECT id,idea_id,claim_token FROM idea_attempts")] == rows
    assert json.loads((data / "research-cycles/manual.json").read_text()) == before


@pytest.mark.parametrize("failure_phase", ["capture", "revalidate"])
def test_memory_batch_failure_never_falls_back_retries_or_claims(
        public_pool, fake_runtime, tmp_path, monkeypatch, failure_phase):
    from algua.operator import campaign_memory

    conn, data, _ = public_pool
    original = campaign_memory.capture_public_memory
    phases = []

    def fail_once(*args, **kwargs):
        phase = kwargs.get("phase", "capture")
        phases.append(phase)
        assert not conn.in_transaction
        if phase == failure_phase:
            raise ValueError("public_memory_context:artifact_integrity_mismatch")
        return original(*args, **kwargs)

    monkeypatch.setattr(campaign_memory, "capture_public_memory", fail_once)
    before = list(conn.iterdump())
    result, payload = invoke(
        "cycle-start", "--run", "batch-failure", "--limit", "3", "--choose", "--choice-dir",
        str(tmp_path / "failed-choice"), "--public-memory-context")
    assert result.exit_code == 1
    assert payload["code"] == "invalid_input"
    assert payload["error"] == "public_memory_context:artifact_integrity_mismatch"
    assert phases == (["capture"] if failure_phase == "capture" else ["capture", "revalidate"])
    calls = ([json.loads(line) for line in fake_runtime.read_text().splitlines()]
             if fake_runtime.exists() else [])
    assert len([call for call in calls if call[0] == "run"]) == int(failure_phase == "revalidate")
    assert list(conn.iterdump()) == before
    assert not (data / "research-cycles/batch-failure.json").exists()


def test_feedback_change_during_read_refuses_before_chooser_or_claims(
        public_pool, fake_runtime, tmp_path, monkeypatch):
    from algua.operator import campaign_memory

    conn, data, _ = public_pool
    original = campaign_memory.capture_public_memory

    def concurrent_feedback(*args, **kwargs):
        assert not conn.in_transaction
        snapshot = original(*args, **kwargs)
        add_idea(conn, "SYNTHETIC_FIXTURE concurrent evidence", family="concurrent")
        return snapshot

    monkeypatch.setattr(campaign_memory, "capture_public_memory", concurrent_feedback)
    result, payload = invoke(
        "cycle-start", "--run", "feedback-drift", "--limit", "3", "--choose", "--choice-dir",
        str(tmp_path / "feedback-choice"), "--public-memory-context")
    assert result.exit_code == 1 and payload["ok"] is False
    assert not fake_runtime.exists()
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0
    assert not (data / "research-cycles/feedback-drift.json").exists()


def test_started_memory_chooser_never_reads_or_calls_again(
        public_pool, fake_runtime, tmp_path, monkeypatch):
    from algua.operator import campaign_memory

    conn, _, _ = public_pool
    arguments = ("cycle-start", "--run", "already-chosen", "--limit", "3", "--choose",
                 "--choice-dir", str(tmp_path / "once"), "--public-memory-context")
    result, _ = invoke(*arguments)
    assert result.exit_code == 0, result.output
    before = list(conn.iterdump())
    calls = fake_runtime.read_text()

    def forbidden(*args, **kwargs):
        pytest.fail("started chooser must refuse before another archive/model call")

    monkeypatch.setattr(campaign_memory, "capture_public_memory", forbidden)
    result, payload = invoke(*arguments)
    assert result.exit_code == 1 and payload["ok"] is False
    assert list(conn.iterdump()) == before and fake_runtime.read_text() == calls


def test_changed_post_choice_snapshot_refuses_before_admission(
        public_pool, fake_runtime, tmp_path, monkeypatch):
    from algua.operator import campaign_memory

    conn, data, _ = public_pool
    original = campaign_memory.capture_public_memory

    def changed_snapshot(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        if kwargs.get("phase") == "revalidate":
            snapshot["scorecard_attempt_cutoff"] += 1
        return snapshot

    monkeypatch.setattr(campaign_memory, "capture_public_memory", changed_snapshot)
    before = list(conn.iterdump())
    result, payload = invoke(
        "cycle-start", "--run", "snapshot-drift", "--limit", "3", "--choose", "--choice-dir",
        str(tmp_path / "snapshot-choice"), "--public-memory-context")
    assert result.exit_code == 1 and payload["error"] == "public_memory_context:artifact_changed"
    calls = [json.loads(line) for line in fake_runtime.read_text().splitlines()]
    assert len([call for call in calls if call[0] == "run"]) == 1
    assert list(conn.iterdump()) == before
    assert not (data / "research-cycles/snapshot-drift.json").exists()


@pytest.mark.parametrize("failure", ["runtime", "revalidate"])
def test_failed_chooser_directory_blocks_archive_work_on_replay(
        public_pool, fake_runtime, tmp_path, monkeypatch, failure):
    from algua.operator import campaign_memory

    conn, data, _ = public_pool
    original = campaign_memory.capture_public_memory
    phases = []

    def capture(*args, **kwargs):
        phase = kwargs.get("phase", "capture")
        phases.append(phase)
        if failure == "revalidate" and phase == "revalidate":
            raise ValueError("public_memory_context:artifact_changed")
        return original(*args, **kwargs)

    monkeypatch.setattr(campaign_memory, "capture_public_memory", capture)
    if failure == "runtime":
        monkeypatch.setenv("FIXTURE_CASE", "provider")
    directory = tmp_path / "failed-but-retained"
    arguments = ("cycle-start", "--run", "failed-once", "--limit", "3", "--choose",
                 "--choice-dir", str(directory), "--public-memory-context")
    result, failed = invoke(*arguments)
    assert result.exit_code == 1 and failed["ok"] is False
    assert directory.is_dir() and not (data / "research-cycles/failed-once.json").exists()
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0
    before = list(conn.iterdump())
    before_phases = list(phases)
    before_calls = fake_runtime.read_text()

    def forbidden(*args, **kwargs):
        phases.append("FORBIDDEN_REPLAY")
        raise AssertionError("must refuse before another archive batch")

    monkeypatch.setattr(campaign_memory, "capture_public_memory", forbidden)
    result, rejected = invoke(*arguments)
    assert result.exit_code == 1 and rejected["code"] == "invalid_input"
    assert "already started" in rejected["error"]
    assert phases == before_phases
    assert list(conn.iterdump()) == before and fake_runtime.read_text() == before_calls
