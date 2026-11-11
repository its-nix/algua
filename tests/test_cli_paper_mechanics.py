"""JSON commands with a fixture venue; no broker credentials or network."""
import json

from typer.testing import CliRunner

from algua.cli import paper_mechanics_cmd as cli
from tests.test_paper_mechanics import Venue
from tests.test_paper_mechanics import world as world_fixture

world = world_fixture


def test_read_only_account_discovery_without_paths_or_uuid(monkeypatch):
    venue = Venue()
    monkeypatch.setattr(cli, "_broker", lambda: venue)
    result = CliRunner().invoke(cli.mechanics_app, ["account"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["account"]["id"] == "isolated-paper"
    assert not venue.posts


def test_account_comparison_is_optional_but_enforced(monkeypatch):
    monkeypatch.setattr(cli, "_broker", Venue)
    result = CliRunner().invoke(cli.mechanics_app, ["--expected-account", "wrong", "account"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_mutation_without_expected_account_is_json_refusal():
    result = CliRunner().invoke(cli.mechanics_app, ["step"])
    assert result.exit_code == 1
    assert "expected-account" in json.loads(result.stdout)["error"]


def test_cli_cycle_and_cached_status(world, monkeypatch):
    conn, venue, path = world
    risk_path = conn.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setattr(cli, "_broker", lambda: venue)
    args = ["--state", str(path), "--risk-db", risk_path,
            "--expected-account", "isolated-paper"]
    for command in (["init", "--symbol", "CSL"], ["step"], ["status"], ["close"]):
        result = CliRunner().invoke(cli.mechanics_app, args + command)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["mechanics"]["qualification_credit"] is False
    assert len(venue.posts) == 1


def test_state_cannot_alias_risk_registry(world, monkeypatch):
    conn, venue, _ = world
    risk_path = conn.execute("PRAGMA database_list").fetchone()[2]
    monkeypatch.setattr(cli, "_broker", lambda: venue)
    result = CliRunner().invoke(cli.mechanics_app,
        ["--state", risk_path, "--risk-db", risk_path, "--expected-account", "isolated-paper",
         "init", "--symbol", "CSL"])
    assert result.exit_code == 1
    assert "distinct" in json.loads(result.stdout)["error"]
    assert not venue.posts
