"""Real controller/CLI recovery; only the executable chooser output is a fixture."""
from __future__ import annotations

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.registry.db import connect, migrate
from algua.registry.idea_attempts import IdeaAttemptsRepository
from tests.campaign_fixtures import add_idea
from tests.test_campaign_choice_producer import fake_runtime as fake_runtime

runner = CliRunner()


def invoke(*args):
    result = runner.invoke(app, ["research", "idea", "cycle-start", *args])
    return result, json.loads(result.stdout)


@pytest.fixture
def interrupted(tmp_path, monkeypatch):
    data = tmp_path / "authority-data"
    data.mkdir()
    database = data / "algua.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(database))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "mlflow-sqlite")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'absent-tracking.db'}")
    conn = connect(database)
    migrate(conn)
    add_idea(conn, "SYNTHETIC_FIXTURE opening auction pressure", family="auction")
    result, started = invoke("--run", "interrupted", "--limit", "1")
    assert result.exit_code == 0 and len(started["claimed"]) == 1
    original = dict(conn.execute("SELECT * FROM idea_attempts").fetchone())
    yield conn, data, original
    conn.close()


def fresh(conn):
    return add_idea(conn, "SYNTHETIC_FIXTURE dividend calendar rotation", family="calendar")


def calls(path):
    return ([json.loads(line) for line in path.read_text().splitlines()]
            if path.exists() else [])


@pytest.mark.parametrize("memory", [False, True])
def test_prior_recovery_precedes_real_chooser_and_memory_admission(
        interrupted, fake_runtime, tmp_path, monkeypatch, memory):
    from algua.operator import campaign_memory

    conn, data, original = interrupted
    idea = fresh(conn)
    directory = tmp_path / "choice"
    flags = ["--public-memory-context"] if memory else []
    observed = []
    capture = campaign_memory.capture_public_memory

    def observe(menu, **kwargs):
        observed.append(json.loads(json.dumps(menu["scorecard"]["attempts"])))
        return capture(menu, **kwargs)

    if memory:
        monkeypatch.setattr(campaign_memory, "capture_public_memory", observe)
    result, adopted = invoke("--run", "following", "--limit", "1", "--choose",
                             "--choice-dir", str(directory), *flags)
    assert result.exit_code == 0, result.stdout + "\n".join(
        f"{p.name}: {p.read_text()[:4000]}" for p in directory.glob("*.stderr"))
    assert [i["id"] for i in adopted["claimed"]] == [idea.id]
    menu = json.loads((directory / "menu.json").read_text())
    assert menu == adopted["campaign"]["menu"]
    prior, = menu["scorecard"]["attempts"]
    assert prior["id"] == original["id"] and prior["outcome"] == "run_error"
    assert prior["reason"] == "controller_restart:1"
    saved = dict(conn.execute("SELECT * FROM idea_attempts WHERE id=?",
                             (original["id"],)).fetchone())
    assert saved["claim_token"] == original["claim_token"]
    assert saved["outcome"] == "run_error"
    assert len([c for c in calls(fake_runtime) if c[0] == "run"]) == 1
    checkpoint = json.loads((data / "research-cycles/following.json").read_text())
    assert checkpoint["request"]["campaign"] == adopted["campaign"]
    if memory:
        context = menu["request"]["context"]["public_research_memory"]
        assert len(observed) == 2 and all(rows[0]["outcome"] == "run_error" for rows in observed)
        # Current memory protocol considers bounded terminal history across families, including
        # infrastructure failures. The old relevance-only protocol is no longer the default.
        assert context["coverage"]["candidate_attempts_considered"] == 1
        assert context["coverage"]["cycles_without_receipt"] == 1
        assert context["evidence_mode"] == "UNVERIFIED_WORKER" and context["authority"] == "none"
        assert checkpoint["request"]["context"]["public_research_memory"] == context
    assert not (tmp_path / "absent-tracking.db").exists()


def test_recovered_attempt_is_not_reoffered_and_empty_pool_is_a_safe_noop(
        interrupted, fake_runtime, tmp_path):
    conn, data, original = interrupted
    result, started = invoke("--run", "following", "--limit", "1", "--choose",
                             "--choice-dir", str(tmp_path / "choice"))
    assert result.exit_code == 0, result.stdout
    assert started['claimed'] == [] and started['phase'] == 'pool_empty'
    prior = conn.execute("SELECT * FROM idea_attempts WHERE id=?", (original["id"],)).fetchone()
    assert prior["outcome"] == "run_error" and prior["reason"] == "controller_restart:1"
    assert prior["claim_token"] == original["claim_token"]
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1
    assert not calls(fake_runtime)


def test_empty_menu_finishes_prior_checkpoint_without_spending(interrupted, fake_runtime, tmp_path):
    from algua.contracts.idea import AttemptOutcome

    conn, data, original = interrupted
    # Model a crash after a terminal outcome committed but before the cycle checkpoint finished.
    IdeaAttemptsRepository(conn).record_outcome(original['idea_id'], token=original['claim_token'],
        outcome=AttemptOutcome.WALKFORWARD_REFUTED, reason='SYNTHETIC_FIXTURE terminal result')
    result, refused = invoke("--run", "following", "--limit", "1", "--choose",
                             "--choice-dir", str(tmp_path / "choice"))
    assert result.exit_code == 0 and refused['claimed'] == []
    assert refused['phase'] == 'pool_empty'
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1
    prior = conn.execute('SELECT outcome, reason FROM idea_attempts WHERE id=?',
                         (original['id'],)).fetchone()
    assert tuple(prior) == ('walkforward_refuted', 'SYNTHETIC_FIXTURE terminal result')
    assert not calls(fake_runtime)
    assert (data / 'research-cycles/following.json').is_file()


@pytest.mark.parametrize("fault", ["cycle", "rows", "checkpoint-object", "checkpoint-symlink",
    "directory", "file", "symlink", "dangling-symlink", "invalid-id"])
def test_used_or_invalid_identity_refuses_before_recovery_archive_or_model(
        interrupted, fake_runtime, tmp_path, monkeypatch, fault):
    from algua.operator import campaign_memory

    conn, data, _ = interrupted
    fresh(conn)
    run, directory = "following", tmp_path / "choice"
    if fault == "cycle":
        run = "interrupted"
    elif fault == "rows":
        IdeaAttemptsRepository(conn).claim(run_stamp=run, limit=1, ttl_minutes=180)
    elif fault.startswith("checkpoint"):
        checkpoint = data / "research-cycles/following.json"
        if fault == "checkpoint-object":
            checkpoint.mkdir()
        else:
            checkpoint.symlink_to(tmp_path / "missing-checkpoint")
    elif fault in {"directory", "file"}:
        directory.mkdir() if fault == "directory" else directory.write_text("used")
    elif fault in {"symlink", "dangling-symlink"}:
        target = tmp_path / "target"
        if fault == "symlink":
            target.mkdir()
        directory.symlink_to(target, target_is_directory=True)
    else:
        run = "invalid/id"
    before = list(conn.iterdump())
    archive_calls = []

    def forbidden(*args, **kwargs):
        archive_calls.append(True)
        raise AssertionError("archive must not precede identity refusal")

    monkeypatch.setattr(campaign_memory, "capture_public_memory", forbidden)
    result, refused = invoke("--run", run, "--limit", "1", "--choose",
                             "--choice-dir", str(directory), "--public-memory-context")
    assert result.exit_code == 1 and refused["ok"] is False
    assert list(conn.iterdump()) == before
    assert not archive_calls and not calls(fake_runtime)


@pytest.mark.parametrize("fault", ["ttl", "limits", "context"])
def test_invalid_complete_request_precedes_recovery(
        interrupted, fake_runtime, tmp_path, monkeypatch, fault):
    from algua.cli import idea_ops_cmd

    conn, _, _ = interrupted
    fresh(conn)
    extra = []
    if fault == "ttl":
        monkeypatch.setenv("ALGUA_IDEA_CLAIM_TTL_MINUTES", "1")
    elif fault == "limits":
        extra = ["--workers", "2"]
    else:
        monkeypatch.setattr(idea_ops_cmd, "_cycle_context", lambda *args: {"invalid": float("nan")})
    before = list(conn.iterdump())
    result, refused = invoke("--run", "following", "--limit", "1", "--choose",
                             "--choice-dir", str(tmp_path / "choice"), *extra)
    assert result.exit_code == 1 and refused["ok"] is False
    assert list(conn.iterdump()) == before and not calls(fake_runtime)
    assert not (tmp_path / "choice").exists()


def test_failed_prior_recovery_refuses_before_archive_or_model(
        interrupted, fake_runtime, tmp_path, monkeypatch):
    from algua.operator import campaign_memory

    conn, data, _ = interrupted
    fresh(conn)
    before = list(conn.iterdump())

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("SYNTHETIC_FIXTURE outcome write unavailable")

    def forbidden(*args, **kwargs):
        pytest.fail("archive must not run after incomplete prior recovery")

    monkeypatch.setattr(IdeaAttemptsRepository, "record_outcome", fail)
    monkeypatch.setattr(campaign_memory, "capture_public_memory", forbidden)
    result, refused = invoke("--run", "following", "--limit", "1", "--choose",
                             "--choice-dir", str(tmp_path / "choice"), "--public-memory-context")
    assert result.exit_code == 1 and refused["ok"] is False
    assert "prior cycle recovery unfinished" in refused["error"]
    assert list(conn.iterdump()) == before and not calls(fake_runtime)
    assert not (tmp_path / "choice").exists()
    assert not (data / "research-cycles/following.json").exists()


def test_menu_only_keeps_prior_attempts_unchanged(interrupted):
    conn, _, _ = interrupted
    fresh(conn)
    before = list(conn.iterdump())
    result, payload = invoke("--run", "following", "--limit", "1", "--menu-only")
    assert result.exit_code == 0 and payload["ok"] is True
    assert payload["menu"]["scorecard"]["attempts"][0]["outcome"] is None
    assert list(conn.iterdump()) == before


def test_manual_campaign_still_refuses_feedback_changed_by_start_recovery(
        interrupted, fake_runtime, tmp_path):
    conn, _, _ = interrupted
    fresh(conn)
    result, payload = invoke("--run", "following", "--limit", "1", "--menu-only")
    assert result.exit_code == 0
    menu = payload["menu"]
    campaign = {"menu": menu, "selection": {"menu_id": menu["menu_id"], "choices": [
        {**menu["choices"][0], "reason": "SYNTHETIC_FIXTURE supplied before recovery"}]}}
    path = tmp_path / "manual.json"
    original = json.dumps(campaign)
    path.write_text(original)
    result, refused = invoke("--run", "following", "--limit", "1", "--campaign", str(path))
    assert result.exit_code == 1 and "stale" in refused["error"]
    assert path.read_text() == original and not calls(fake_runtime)
    assert conn.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 1
    assert conn.execute("SELECT outcome FROM idea_attempts").fetchone()[0] == "run_error"


def test_existing_directory_lock_excludes_early_recovery(interrupted, fake_runtime, tmp_path):
    import fcntl

    conn, data, _ = interrupted
    fresh(conn)
    before = list(conn.iterdump())
    with (data / "research-cycles/.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, refused = invoke("--run", "following", "--limit", "1", "--choose",
                                 "--choice-dir", str(tmp_path / "choice"))
    assert result.exit_code == 1 and refused["ok"] is False
    assert list(conn.iterdump()) == before and not calls(fake_runtime)
    assert not (tmp_path / "choice").exists()
