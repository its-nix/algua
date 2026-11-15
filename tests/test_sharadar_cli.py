import json

import pandas as pd
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.store import DataStore


def test_typed_fundamentals_ingestion(tmp_path, monkeypatch):
    from algua.data.providers.sharadar_client import SharadarClient
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_SHARADAR_API_KEY", "test-api-key")
    raw = pd.DataFrame([dict(ticker="AAPL", date="2025-02-01", dimension="ARQ",
                             reportperiod="2024-12-31", eps=2.)])
    monkeypatch.setattr(SharadarClient, "fetch", lambda *a, **kw: (raw.copy(), {}))
    args = ["data", "sharadar", "ingest-fundamentals", "--symbols", "AAPL", "--start",
            "2025-01-01", "--end", "2025-03-01", "--metric", "eps"]
    runner = CliRunner()
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout
    snapshot = json.loads(first.stdout)["snapshot"]
    assert snapshot["kind"] == "fundamentals"
    assert snapshot["source_metadata"]["pit_status"] == "unverified_vendor_history"
    frame = DataStore(tmp_path / "data").read_fundamentals(snapshot["snapshot_id"])
    assert frame.value.tolist() == [2.]
    assert frame.knowable_at.min() == pd.Timestamp("2025-02-04", tz="UTC")
    verified = runner.invoke(app, ["data", "verify", "--snapshot-id", snapshot["snapshot_id"]])
    assert verified.exit_code == 0, verified.stdout


def test_failed_fundamentals_ingestion_is_json_and_leaves_no_snapshot(tmp_path, monkeypatch):
    from algua.data.providers.sharadar_client import SharadarClient
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_SHARADAR_API_KEY", "test-api-key")
    monkeypatch.setattr(SharadarClient, "fetch", lambda *a, **kw: (pd.DataFrame(), {}))
    runner = CliRunner()
    result = runner.invoke(app, ["data", "sharadar", "ingest-fundamentals", "--symbols",
                                "AAPL", "--start", "2025-01-01", "--end", "2025-03-01",
                                "--metric", "eps"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not DataStore(tmp_path / "data").list_snapshots()


def test_second_symbol_failure_is_atomic(tmp_path, monkeypatch):
    from algua.data.providers.sharadar_client import SharadarClient
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_SHARADAR_API_KEY", "test-api-key")
    raw = pd.DataFrame([dict(ticker="AAPL", date="2025-02-01", dimension="ARQ",
                             reportperiod="2024-12-31", eps=2.)])
    def fetch(self, table, ticker, *args, **kwargs):
        return (raw.copy() if ticker == "AAPL" else pd.DataFrame()), {}
    monkeypatch.setattr(SharadarClient, "fetch", fetch)
    result = CliRunner().invoke(app, ["data", "sharadar", "ingest-fundamentals",
        "--symbols", "AAPL,MSFT", "--start", "2025-01-01", "--end", "2025-03-01",
        "--metric", "eps"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["ok"] is False
    assert not DataStore(tmp_path / "data").list_snapshots()
