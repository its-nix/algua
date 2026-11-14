"""CLI integration tests for --delistings / --assume-terminal-last-close flags.

Task 9 of issue #212: survivorship-free CLI wiring.

* backtest run/walk-forward/sweep accept --delistings NAME
* research promote accepts --delistings; --assume-terminal-last-close is not a promote option
  (removed with the human gate overrides, spec 2026-11-13)
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.store import DataStore

runner = CliRunner()

STRATEGY = "cross_sectional_momentum"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "r.db"))


def _seed_delistings(tmp_path):
    """Import a minimal delistings CSV into the DataStore (as-of well before backtest end dates)."""
    csv = tmp_path / "d.csv"
    csv.write_text("symbol,delisting_date,delisting_value\nB,2020-01-02,5.0\n")
    r = runner.invoke(app, [
        "data", "import-delistings", "--file", str(csv), "--source", "v",
        "--as-of", "2019-12-31T00:00:00+00:00",
    ])
    assert r.exit_code == 0, r.output


def test_backtest_run_accepts_delistings_flag(tmp_path):
    _seed_delistings(tmp_path)
    res = runner.invoke(app, [
        "backtest", "run", STRATEGY, "--demo",
        "--start", "2020-01-01", "--end", "2020-03-01", "--delistings", "vendor",
    ])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["ok"] is True


def test_backtest_run_delisting_snapshot_is_actual_snapshot_id(tmp_path):
    """delisting_snapshot in the result JSON must be the real snapshot_id, not the user label."""
    _seed_delistings(tmp_path)
    # Discover the actual snapshot_id from the store
    store = DataStore(tmp_path)
    real_snapshot_id = store.latest_delistings_snapshot_id()
    assert real_snapshot_id is not None, "seed should have written a delistings snapshot"

    res = runner.invoke(app, [
        "backtest", "run", STRATEGY, "--demo",
        "--start", "2020-01-01", "--end", "2020-03-01", "--delistings", "ANY",
    ])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    # Must be the actual snapshot_id, not the user-supplied label "ANY"
    assert payload.get("delisting_snapshot") == real_snapshot_id
    assert payload.get("delisting_snapshot") != "ANY"


def test_backtest_run_accepts_assume_terminal_last_close(tmp_path):
    _seed_delistings(tmp_path)
    res = runner.invoke(app, [
        "backtest", "run", STRATEGY, "--demo",
        "--start", "2020-01-01", "--end", "2020-03-01",
        "--delistings", "vendor", "--assume-terminal-last-close",
    ])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["ok"] is True


def test_backtest_walk_forward_accepts_delistings_flag(tmp_path):
    _seed_delistings(tmp_path)
    res = runner.invoke(app, [
        "backtest", "walk-forward", STRATEGY, "--demo",
        "--start", "2020-01-01", "--end", "2022-01-01", "--delistings", "vendor",
    ])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["ok"] is True


def test_backtest_sweep_accepts_delistings_flag(tmp_path):
    _seed_delistings(tmp_path)
    res = runner.invoke(app, [
        "backtest", "sweep", STRATEGY, "--demo",
        "--start", "2020-01-01", "--end", "2022-01-01",
        "--delistings", "vendor",
        "--param", "lookback=20,40",
    ])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["ok"] is True


def test_backtest_run_no_delistings_snapshot_is_json_error(tmp_path):
    """--delistings with no ingested snapshot fails closed (ValueError -> JSON error)."""
    # no seed — nothing in the store
    res = runner.invoke(app, [
        "backtest", "run", STRATEGY, "--demo",
        "--start", "2020-01-01", "--end", "2020-03-01", "--delistings", "vendor",
    ])
    assert res.exit_code == 1
    assert json.loads(res.output)["ok"] is False


@pytest.mark.parametrize("actor_args", [[], ["--actor", "human"]])
def test_research_promote_refuses_assume_terminal_last_close(actor_args):
    """--assume-terminal-last-close is no longer a promote option for ANY actor: an unknown
    option (usage error), never silently ignored. A held-into-gap name without a delisting record
    fails closed on the promote path."""
    res = runner.invoke(app, [
        "research", "promote", STRATEGY,
        "--universe", "U",
        "--start", "2020-01-01", "--end", "2020-12-31",
        "--assume-terminal-last-close",
        *actor_args,
    ])
    assert res.exit_code == 2
    assert "no such option" in res.output.lower()


def test_research_promote_fdr_throttle_override_flag_removed():
    """Factory soft gate: --fdr-throttle-override was REMOVED with the FDR freeze — the CLI must
    reject it as an UNKNOWN option (usage error), for every actor, not route it anywhere."""
    for actor_args in ([], ["--actor", "human"]):
        res = runner.invoke(app, [
            "research", "promote", STRATEGY,
            "--universe", "U",
            "--start", "2020-01-01", "--end", "2020-12-31",
            "--fdr-throttle-override",
            *actor_args,
        ])
        assert res.exit_code == 2  # usage error: unknown option
        assert "no such option" in res.output.lower() or "unexpected" in res.output.lower()
