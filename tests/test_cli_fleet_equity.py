"""`fleet equity` — P&L-indexed portfolio curve (hermetic CLI tests)."""

import json
from contextlib import closing

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.config.settings import get_settings
from algua.execution.order_state import record_tick_snapshot
from algua.registry.allocation_history import allocation_capitals_at
from algua.registry.db import connect, migrate
from algua.registry.store import SqliteStrategyRepository
from tests._deployment_helpers import force_legacy_strategy

runner = CliRunner()


@pytest.fixture
def equity_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "p.db"))
    with closing(connect(get_settings().db_path)) as conn:
        migrate(conn)
        rec = SqliteStrategyRepository(conn).add("tenant")
        force_legacy_strategy(conn, rec.id, stage="paper")
        yield conn, rec


def _allocation(conn, rec, capital, effective, revoked=None):
    # Historical fixture: production allocation timestamps come from the writer's wall clock.
    conn.execute(
        "INSERT INTO strategy_allocations(strategy_id, capital, effective_ts, revoked_ts, actor) "
        "VALUES (?,?,?,?,?)", (rec.id, capital, effective, revoked, "agent"))
    conn.commit()


def _tick(conn, rec, timestamp, equity, lane="paper"):
    force_legacy_strategy(conn, rec.id, stage="live" if lane == "live" else "paper")
    record_tick_snapshot(
        conn, rec.name, tick_ts=timestamp, decision_ts=timestamp, equity=equity,
        peak_equity=equity, positions={}, n_submitted=0, reconcile_ok=True, lane=lane,
        strategy_id=rec.id, code_hash="c", config_hash="cfg", dependency_hash="d",
        account_id="acct", cash=equity, clock_source="broker")


def test_cli_fleet_equity_empty_db_returns_empty_points(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "p.db"))
    result = runner.invoke(app, ["fleet", "equity"])
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["ok"] is True
    assert body["lane_filter"] is None
    assert body["points"] == []
    assert body["current_equity"] == 0.0
    assert body["change_today"] == 0.0
    assert body["last_session"] is None
    assert body["truncated"] is False


def test_cli_fleet_equity_rejects_bad_lane(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "p.db"))
    result = runner.invoke(app, ["fleet", "equity", "--lane", "nope"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["ok"] is False


def test_cli_resizes_exclude_cash_flows_preserve_profit_and_since_baseline(equity_db):
    conn, rec = equity_db
    _allocation(conn, rec, 1000, "2026-11-01", "2026-11-02T15:00:00Z")
    _allocation(conn, rec, 1500, "2026-11-02T15:00:00Z", "2026-11-03T15:00:00Z")
    _allocation(conn, rec, 700, "2026-11-03T15:00:00Z")
    _tick(conn, rec, "2026-11-01T20:00:00Z", 1010)
    _tick(conn, rec, "2026-11-02T14:00:00Z", 1015)
    _tick(conn, rec, "2026-11-02T20:00:00Z", 1520)
    _tick(conn, rec, "2026-11-03T20:00:00Z", 690)
    result = runner.invoke(app, ["fleet", "equity"])
    assert result.exit_code == 0, result.stdout
    body = json.loads(result.stdout)
    assert [p["pnl"] for p in body["points"]] == [0.0, 10.0, -20.0]
    assert [p["equity"] for p in body["points"]] == [1010.0, 1520.0, 690.0]
    assert body["current_equity"] == 690
    assert body["truncated"] is False
    result = runner.invoke(app, ["fleet", "equity", "--since", "2026-11-02T19:00:00Z"])
    assert result.exit_code == 0, result.stdout
    assert [p["pnl"] for p in json.loads(result.stdout)["points"]] == [0.0, -30.0]


def test_history_utc_boundaries_and_latest_id_for_equal_effective_times(equity_db):
    conn, rec = equity_db
    _allocation(conn, rec, 1000, "2026-11-01", "2026-11-02T10:00:00Z")
    _allocation(conn, rec, 1500, "2026-11-02T12:00:00+02:00", "2026-11-02T10:00:00Z")
    _allocation(conn, rec, 700, "2026-11-02T10:00:00Z")
    assert allocation_capitals_at(conn, rec.id, [
        "2026-11-02T12:00:00+02:00", "2026-11-02T09:59:59Z",
    ]) == [700.0, 1000.0]


def test_lane_switch_keeps_independent_capital_and_profit_baselines(equity_db):
    conn, rec = equity_db
    _allocation(conn, rec, 1000, "2026-11-01", "2026-11-03")
    _allocation(conn, rec, 500, "2026-11-03")
    _tick(conn, rec, "2026-11-01T20:00:00Z", 1000)
    _tick(conn, rec, "2026-11-02T20:00:00Z", 1010)
    _tick(conn, rec, "2026-11-03T20:00:00Z", 500, "live")
    _tick(conn, rec, "2026-11-04T20:00:00Z", 495, "live")
    result = runner.invoke(app, ["fleet", "equity"])
    assert result.exit_code == 0, result.stdout
    points = json.loads(result.stdout)["points"]
    assert [p["pnl"] for p in points] == [0.0, 10.0, 10.0, 5.0]
    assert [p["equity"] for p in points] == [1000.0, 1010.0, 500.0, 495.0]
    result = runner.invoke(app, ["fleet", "equity", "--lane", "live"])
    assert result.exit_code == 0, result.stdout
    assert [p["pnl"] for p in json.loads(result.stdout)["points"]] == [0.0, -5.0]


def test_no_allocation_history_retains_legacy_raw_equity_changes(equity_db):
    conn, rec = equity_db
    _tick(conn, rec, "2026-11-01T20:00:00Z", 1000)
    _tick(conn, rec, "2026-11-02T20:00:00Z", 1010)
    result = runner.invoke(app, ["fleet", "equity"])
    assert result.exit_code == 0, result.stdout
    assert [p["pnl"] for p in json.loads(result.stdout)["points"]] == [0.0, 10.0]
    _allocation(conn, rec, 500, "2026-11-03")
    # An entirely pre-allocation interval remains legacy, even when later history exists.
    assert allocation_capitals_at(conn, rec.id, ["2026-11-01", "2026-11-02"]) is None


@pytest.mark.parametrize("first_effective,revoked", [
    ("2026-11-02", None),  # legacy and allocated ticks cannot share a known P&L basis
    ("2026-11-01", "2026-11-02T20:00:00Z"),  # revocation is exclusive
])
def test_partial_allocation_history_returns_json_error(equity_db, first_effective, revoked):
    conn, rec = equity_db
    _allocation(conn, rec, 1000, first_effective, revoked)
    _tick(conn, rec, "2026-11-01T20:00:00Z", 1000)
    _tick(conn, rec, "2026-11-02T20:00:00Z", 1010)
    result = runner.invoke(app, ["fleet", "equity"])
    assert result.exit_code != 0
    body = json.loads(result.stdout)
    assert body["ok"] is False
    assert "incomplete allocation history" in body["error"]
    assert body["code"] == "invalid_input"
    if revoked is None:
        _tick(conn, rec, "2026-11-03T20:00:00Z", 1020)
        result = runner.invoke(app, ["fleet", "equity", "--since", first_effective])
        assert result.exit_code == 0, result.stdout
        assert [p["pnl"] for p in json.loads(result.stdout)["points"]] == [0.0, 10.0]
