import json

import pytest
import requests
from typer.testing import CliRunner

from algua.cli.main import app


def test_eodhd_snapshot_backtests_offline_reproducibly(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "registry.db"))
    monkeypatch.setenv("ALGUA_EODHD_API_KEY", "demo")
    import pandas as pd

    days = pd.bdate_range("2025-01-01", "2025-12-31")
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        payload = [] if "/splits/" in url else [
            {"date": day.date().isoformat(), "open": 100 + i, "high": 102 + i,
             "low": 99 + i, "close": 101 + i, "adjusted_close": 101 + i, "volume": 1000}
            for i, day in enumerate(days)]
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr("algua.data.providers.eodhd.requests.get", get)
    runner = CliRunner()
    result = runner.invoke(app, ["data", "ingest-bars", "--provider", "eodhd",
        "--symbols", "AAPL,AMZN", "--start", "2025-01-01", "--end", "2026-01-01",
        "--data-tier", "pilot_real_proxy", "--universe-method", "demo-plumbing-only"])
    assert result.exit_code == 0, result.stdout
    snapshot = json.loads(result.stdout)["snapshot"]
    assert snapshot["timeframe"] == "1d"
    assert len(calls) == 4
    result = runner.invoke(app, ["data", "ingest-universe", "demo-plumbing-only",
        "--symbols", "AAPL,AMZN", "--effective-date", "2025-01-01",
        "--source", "synthetic test selection; not historical index membership"])
    assert result.exit_code == 0, result.stdout

    def offline(*args, **kwargs):
        raise AssertionError("backtests must not download data")
    monkeypatch.setattr("algua.data.providers.eodhd.requests.get", offline)
    args = ["backtest", "run", "cross_sectional_momentum", "--snapshot",
            snapshot["snapshot_id"], "--universe", "demo-plumbing-only",
            "--start", "2025-01-01", "--end", "2026-01-01"]
    outputs = []
    for _ in range(2):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.stdout
        outputs.append(json.loads(result.stdout))
    assert outputs[0]["snapshot_id"] == snapshot["snapshot_id"]
    assert outputs[0]["metrics"] == outputs[1]["metrics"]
    result = runner.invoke(app, ["data", "verify"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["failed"] == 0


@pytest.mark.parametrize("fail_call", [1, 2, 3, 4])
def test_eodhd_failure_is_json_and_publishes_no_snapshot(monkeypatch, tmp_path, fail_call):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_EODHD_API_KEY", "private-token")
    calls = 0
    def get(url, **kwargs):
        nonlocal calls
        calls += 1
        response = requests.Response()
        response.status_code = 403 if calls == fail_call else 200
        if calls == fail_call:
            payload = {"error": "private-token"}
        else:
            payload = [] if "/splits/" in url else [
                {"date": "2025-01-02", "open": 100, "high": 102, "low": 99,
                 "close": 101, "adjusted_close": 101, "volume": 1000}]
        response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr("algua.data.providers.eodhd.requests.get", get)
    runner = CliRunner()
    result = runner.invoke(app, ["data", "ingest-bars", "--provider", "eodhd",
        "--symbols", "AAPL,AMZN", "--start", "2025-01-01", "--end", "2026-01-01"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["ok"] is False
    assert "private-token" not in result.stdout
    result = runner.invoke(app, ["data", "inspect"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
