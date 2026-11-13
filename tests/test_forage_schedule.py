"""Refill demand, resource reservations, crash/retry accounting and UTC boundaries."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from algua.operator.forage_schedule import forage_due

NOW = datetime(2026, 11, 13, 10, tzinfo=UTC)


def test_eligible_queue_idle_but_three_utc_refresh_runs(tmp_path):
    assert not forage_due(tmp_path, eligible=True, now=NOW)["ready"]
    refresh = NOW.replace(hour=3)
    assert forage_due(tmp_path, eligible=True, now=refresh)["reason"] == "daily_refresh"
    assert not (tmp_path / "forage-budget.json").exists()


def test_empty_queue_reservations_survive_failed_launch_and_cap_retries(tmp_path):
    first = forage_due(tmp_path, eligible=False, reserve="20261113-100000", now=NOW)
    assert first["reserved"] and first["remaining_daily_cycles"] == 1
    assert forage_due(tmp_path, eligible=False, now=NOW)["reason"] == "cooldown"
    later = NOW + timedelta(hours=2)
    assert forage_due(tmp_path, eligible=False, reserve="20261113-120000", now=later)["reserved"]
    assert forage_due(tmp_path, eligible=False, now=later + timedelta(hours=2)
                      )["reason"] == "daily_budget_exhausted"
    assert forage_due(tmp_path, eligible=False, now=NOW + timedelta(days=1)
                      )["remaining_daily_cycles"] == 2


def test_existing_daily_forage_digest_counts_after_deploy(tmp_path):
    (tmp_path / "forage-runs.jsonl").write_text(json.dumps({"stamp": "20261113-030000"}) + "\n")
    assert forage_due(tmp_path, eligible=False, now=NOW)["remaining_daily_cycles"] == 1
    forage_due(tmp_path, eligible=False, now=NOW, reserve="20261113-100000")
    assert forage_due(tmp_path, eligible=False, now=NOW + timedelta(hours=2)
                      )["reason"] == "daily_budget_exhausted"


@pytest.mark.parametrize("payload", ["{}", '{"day":"2026-11-14","launches":{}}', "not json"])
def test_corrupt_budget_fails_closed(tmp_path, payload):
    (tmp_path / "forage-budget.json").write_text(payload)
    with pytest.raises(ValueError):
        forage_due(tmp_path, eligible=False, now=NOW)


def test_invalid_request_does_not_spend_budget(tmp_path):
    with pytest.raises(ValueError):
        forage_due(tmp_path, eligible=False, reserve="invalid", now=NOW)
    assert not (tmp_path / "forage-budget.json").exists()


def test_concurrent_refill_reservations_launch_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    def reserve(second):
        return forage_due(tmp_path, eligible=False, now=NOW,
                          reserve=f"20261113-1000{second:02d}")["reserved"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(reserve, range(4))) == 1


def test_cli_refill_uses_eligible_menu_not_raw_open_depth(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli.main import app
    from algua.registry.db import connect, migrate
    from algua.registry.negative_results import record_negative_result
    from tests.campaign_fixtures import add_idea

    db = tmp_path / "registry.db"
    monkeypatch.setenv("ALGUA_DB_PATH", str(db))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    conn = connect(db)
    migrate(conn)
    idea = add_idea(conn, "SYNTHETIC_FIXTURE measured refutation")
    record_negative_result(conn, kind="gate_fail", verdict="FAIL", actor="system",
                           source="auto:research_promote", hypothesis=idea.hypothesis,
                           reason="measured failure")
    conn.close()
    result = CliRunner().invoke(app, ["research", "sources", "refill"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["reason"] == "no_eligible_ideas"
    assert not (tmp_path / "data" / "forage-budget.json").exists()


def test_large_or_torn_digest_does_not_disable_refill(tmp_path):
    digest = tmp_path / "forage-runs.jsonl"
    digest.write_bytes(b"old\n" * 300000 + b'{"stamp":"20261113-030000"}\n' + b'{"stamp":')
    result = forage_due(tmp_path, eligible=False, now=NOW)
    assert result["ready"] and result["remaining_daily_cycles"] == 1


def test_legacy_local_time_future_stamp_counts_without_clock_failure(tmp_path):
    (tmp_path / "forage-runs.jsonl").write_text('{"stamp":"20261113-110000"}\n')
    assert forage_due(tmp_path, eligible=False, now=NOW)["reason"] == "cooldown"
