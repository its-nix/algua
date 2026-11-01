"""Campaign feedback through the persisted registry and the research CLI."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.contracts.idea import AttemptOutcome
from algua.registry.campaign_read import read_campaign_scorecard
from algua.registry.db import connect, migrate
from tests.campaign_fixtures import add_idea, attempt


def test_persisted_example_reconsiders_duplicate_only_after_its_outcome(tmp_path):
    directory = tmp_path / "example"
    untouched = tmp_path / "MUST_NOT_CREATE.db"
    result = subprocess.run([sys.executable, "scripts/examples/campaign_feedback.py",
                             "--output-dir", str(directory)],
        env={**os.environ, "ALGUA_DB_PATH": str(untouched)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert not untouched.exists()
    assert payload["registry_sha256"] == hashlib.sha256(
        Path(payload["registry"]).read_bytes()).hexdigest()
    before = json.loads((directory / "menu-before.json").read_text())
    after = json.loads((directory / "menu-after.json").read_text())
    assert [c["hypothesis_id"] for c in before["choices"]] == [1, 2, 3, 4]
    assert [c["hypothesis_id"] for c in after["choices"]] == [9, 4, 2, 11]
    changed = after["scorecard"]["hypotheses"][-1]
    original = before["scorecard"]["hypotheses"][0]
    assert changed["created_at"] > after["scorecard"]["attempts"][0]["outcome_at"]
    assert changed["source_ref"] != original["source_ref"]
    assert changed["falsification"] != original["falsification"]
    assert "idea_attempts:1" in after["choices"][-1]["prior_evidence_ids"]
    assert set(after["exclusions"]["10"]["prior_evidence_ids"]) == {
        "ideas:1", "ideas:10", "idea_attempts:1"}


def test_campaign_menu_reads_empty_persisted_history(tmp_path, monkeypatch):
    path = tmp_path / "registry.db"
    conn = connect(path)
    migrate(conn)
    conn.close()
    monkeypatch.setenv("ALGUA_DB_PATH", str(path))
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    result = CliRunner().invoke(app, ["research", "campaign-menu", "--budget", "2"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["choices"] == []
    assert payload["scorecard"]["totals"]["attempted"] == 0
    assert payload["unallocated_budget"] == 2
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_campaign_cli_exclusions_include_reason_and_exact_causal_ids(tmp_path, monkeypatch):
    path = tmp_path / "registry.db"
    conn = connect(path)
    try:
        migrate(conn)
        old = add_idea(conn, "opening imbalance persistence", family="a")
        attempt(conn, old, AttemptOutcome.HOLDOUT_NEGATIVE)
        duplicate = add_idea(conn, old.title, family="a")
    finally:
        conn.close()
    monkeypatch.setenv("ALGUA_DB_PATH", str(path))
    result = CliRunner().invoke(app, ["research", "campaign-menu", "--budget", "2"])
    assert result.exit_code == 0, result.output
    exclusions = json.loads(result.stdout)["exclusions"]
    assert set(exclusions[str(old.id)]["prior_evidence_ids"]) == {"ideas:1", "idea_attempts:1"}
    assert "duplicate" in exclusions[str(duplicate.id)]["reason"]
    assert set(exclusions[str(duplicate.id)]["prior_evidence_ids"]) == {
        "ideas:1", "ideas:2", "idea_attempts:1"}


def test_lifetime_denominators_preserve_all_attempts_and_wal(tmp_path):
    path = tmp_path / "history.db"
    conn = connect(path)
    try:
        migrate(conn)
        for index, outcome in enumerate([*AttemptOutcome, None]):
            idea = add_idea(conn, f"fixture {index}", family=f"family-{index}")
            attempt(conn, idea, outcome)
        # The writer stays open: these commits live in WAL, not just the base DB file.
        before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
        sc = read_campaign_scorecard(path)
        assert sc["totals"] == {
            "attempted": 9, "completed": 8, "unfinished": 1, "invalid": 1,
            "run_error": 1, "abandoned": 1, "economic_rejected": 3,
            "economic_evaluated": 5, "preview_pass": 1, "promoted_candidate": 1,
        }
        assert len(sc["attempts"]) == 9
        assert {a["evidence_id"] for a in sc["attempts"]} == {
            f"idea_attempts:{n}" for n in range(1, 10)}
        assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before
    finally:
        conn.close()


@pytest.mark.parametrize("schema", ["missing_db", "empty", "partial"])
def test_missing_registry_or_schema_refuses_json_without_creating_files(tmp_path, monkeypatch,
                                                                      schema):
    path = tmp_path / "registry.db"
    if schema != "missing_db":
        with sqlite3.connect(path) as conn:
            if schema == "partial":
                conn.execute("CREATE TABLE ideas(id INTEGER)")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    monkeypatch.setenv("ALGUA_DB_PATH", str(path))
    result = CliRunner().invoke(app, ["research", "campaign-menu", "--budget", "2"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["code"] in {"file_not_found", "invalid_input"}
    assert payload["retryable"] is False
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == before


def test_source_changing_during_capture_refuses_without_opening_it(tmp_path, monkeypatch):
    import shutil

    path = tmp_path / "registry.db"
    conn = connect(path)
    migrate(conn)
    conn.close()
    copy = shutil.copyfile

    def changed_source(src, dst):
        result = copy(src, dst)
        # Simulate a writer committing while the reader copies the source file.
        if src == path:
            writer = connect(path)
            try:
                add_idea(writer, "SYNTHETIC_FIXTURE capture drift")
            finally:
                writer.close()
        return result

    monkeypatch.setattr(shutil, "copyfile", changed_source)
    monkeypatch.setenv("ALGUA_DB_PATH", str(path))
    result = CliRunner().invoke(app, ["research", "campaign-menu", "--budget", "1"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["code"] == "db_unavailable"
    assert payload["retryable"] is True
    assert "changed during capture" in payload["error"]


def test_schema_missing_campaign_columns_refuses_instead_of_silently_using_legacy(tmp_path,
                                                                               monkeypatch):
    path = tmp_path / "registry.db"
    conn = connect(path)
    migrate(conn)
    conn.execute("ALTER TABLE ideas RENAME COLUMN category TO absent_category")
    conn.commit()
    conn.close()
    monkeypatch.setenv("ALGUA_DB_PATH", str(path))
    result = CliRunner().invoke(app, ["research", "campaign-menu", "--budget", "1"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["code"] == "invalid_input"
    assert "schema" in payload["error"]


def test_auto_negative_log_without_hypothesis_links_through_existing_strategy_fk(tmp_path):
    from algua.contracts.idea import IdeaStatus
    from algua.registry.ideas import IdeaRepository
    from algua.registry.negative_results import record_negative_result
    from algua.registry.store import SqliteStrategyRepository
    from algua.research.campaign_policy import campaign_exclusions, campaign_menu

    path = tmp_path / "r.db"
    conn = connect(path)
    try:
        migrate(conn)
        old = add_idea(conn, "opening imbalance persistence", family="a")
        strategy = SqliteStrategyRepository(conn).add("synthetic_fixture")
        IdeaRepository(conn).set_status(old.id, to=IdeaStatus.AUTHORED,
                                        authored_strategy_id=strategy.id)
        record_negative_result(conn, strategy_name=strategy.name, kind="gate_fail", verdict="FAIL",
            actor="system", reason="SYNTHETIC_FIXTURE invalid data", source="auto:research_promote")
        add_idea(conn, "weekly dividend seasonality", family="a")
        (choice,) = campaign_menu(read_campaign_scorecard(path), budget=1)
        assert "negative_results:1" in choice.prior_evidence_ids
        assert "economic_rejected=0/0" in choice.reason
        exclusion = campaign_exclusions(read_campaign_scorecard(path))[old.id]
        assert set(exclusion["prior_evidence_ids"]) == {"ideas:1", "negative_results:1"}
    finally:
        conn.close()
