import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from algua.backtest._sample import SyntheticProvider
from algua.cli import replay_cmd
from algua.cli.main import app
from algua.contracts.types import ExecutionContract
from algua.data.store import DataStore
from algua.strategies.loader import load_strategy


@pytest.fixture
def replay_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "must-not-exist.db"))
    name = "cross_sectional_momentum"
    start, end = datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 8, 1, tzinfo=UTC)
    symbols = load_strategy(name).universe
    frame = SyntheticProvider().get_bars(symbols, start, end, "1d").reset_index()
    record = DataStore(tmp_path / "data").ingest_bars(
        provider="synthetic_fixture",
        symbols=symbols,
        start="2023-01-01",
        end="2023-08-01",
        as_of="2023-08-02T00:00:00Z",
        source="test fixture",
        frame=frame,
    )
    args = [
        "backtest",
        "replay",
        name,
        "--snapshot",
        record.snapshot_id,
        "--start",
        "2023-01-01",
        "--end",
        "2023-08-01",
    ]
    return args


def test_sequential_replay_has_orders_next_bar_fills_and_no_authority_writes(
    replay_inputs, tmp_path
):
    output = tmp_path / "trace.json"
    runner = CliRunner()
    result = runner.invoke(app, [*replay_inputs, "--output", str(output)])
    assert result.exit_code == 0, result.stdout
    summary, trace = json.loads(result.stdout), json.loads(output.read_text())
    assert summary["mode"] == "historical_replay"
    assert summary["orders"] > 0 and summary["fills"] > 0
    assert summary["next_session_fills_verified"] and summary["reconcile_ok"]
    assert summary["live_authority"] is summary["investment_evidence"] is False
    assert summary["forward_sessions_created"] == 0 and summary["code_hash"]
    assert "runtime_code_hash" in summary
    assert summary["seed"] is None
    assert all(f["fill_ts"] > f["decision_ts"] for f in trace["fill_records"])
    assert not (tmp_path / "must-not-exist.db").exists()
    again = runner.invoke(app, replay_inputs)
    assert again.exit_code == 0
    assert json.loads(again.stdout) == {k: v for k, v in summary.items() if k != "artifact"}
    refusal = runner.invoke(app, [*replay_inputs, "--output", str(output)])
    assert refusal.exit_code == 1 and json.loads(refusal.stdout)["ok"] is False
    assert json.loads(output.read_text()) == trace


@pytest.mark.parametrize("extra", [["--cash", "nan"], ["--cash", "0"], ["--max-drawdown", "0"]])
def test_invalid_cash_or_risk_refuses_json_without_registry(replay_inputs, tmp_path, extra):
    result = CliRunner().invoke(app, [*replay_inputs, *extra])
    assert result.exit_code == 1 and json.loads(result.stdout)["ok"] is False
    assert not (tmp_path / "must-not-exist.db").exists()


def test_unsupported_execution_lag_is_not_silently_replayed(replay_inputs, monkeypatch, tmp_path):
    strategy = load_strategy("cross_sectional_momentum")
    cfg = strategy.config.model_copy(
        update={"execution": ExecutionContract(rebalance_frequency="1d", decision_lag_bars=2)}
    )
    monkeypatch.setattr(replay_cmd, "load_strategy", lambda name: replace(strategy, config=cfg))
    result = CliRunner().invoke(app, replay_inputs)
    assert result.exit_code == 1 and "one-bar" in json.loads(result.stdout)["error"]
    assert not (tmp_path / "must-not-exist.db").exists()
