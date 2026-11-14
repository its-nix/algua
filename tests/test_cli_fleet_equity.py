"""`fleet equity` — P&L-indexed portfolio curve (hermetic CLI tests)."""

import json

from typer.testing import CliRunner

from algua.cli.main import app

runner = CliRunner()


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


def test_cli_fleet_equity_rejects_bad_lane(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "p.db"))
    result = runner.invoke(app, ["fleet", "equity", "--lane", "nope"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["ok"] is False
