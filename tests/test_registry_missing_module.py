import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "r.db"))


def test_registry_show_survives_missing_strategy_module():
    # Registered by name only: there is no algua/strategies/ghost_strategy module.
    added = runner.invoke(app, ["registry", "add", "ghost_strategy"])
    assert added.exit_code == 0, added.stdout

    shown = runner.invoke(app, ["registry", "show", "ghost_strategy"])
    assert shown.exit_code == 0, shown.stdout
    assert "ghost_strategy" in shown.stdout

    listed = runner.invoke(app, ["registry", "list"])
    assert listed.exit_code == 0, listed.stdout
    assert [s["name"] for s in json.loads(listed.stdout)] == ["ghost_strategy"]
