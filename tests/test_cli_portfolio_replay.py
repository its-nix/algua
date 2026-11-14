"""The real snapshot -> canonical book replay -> existing run-ledger CLI path."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from algua.backtest._sample import SyntheticProvider
from algua.cli.main import app
from algua.contracts.types import ExecutionContract
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore

runner = CliRunner()
SYMBOLS = ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"]


@pytest.fixture
def constant_strategy(tmp_path, monkeypatch):
    import algua.strategies as package
    from algua.strategies import loader

    family = tmp_path / "portfolio_cache_fixture"
    family.mkdir()
    (family / "__init__.py").write_text("")
    name = "portfolio_constant_score"
    source = family / f"{name}.py"
    source.write_text(
        "import pandas as pd\n"
        "from algua.contracts.types import ExecutionContract\n"
        "from algua.strategies.base import StrategyConfig\n"
        f"CONFIG = StrategyConfig(name={name!r}, universe=['AAPL', 'MSFT'], "
        "execution=ExecutionContract('1d', fill_price='close', target_gross_utilization=1.0), "
        "construction='equal_weight_positive')\n"
        "def signal(view, params):\n"
        "    return pd.Series({'AAPL': 1.0})\n"
    )
    original_dirs = loader._family_dirs
    monkeypatch.setattr(package, "__path__", list(package.__path__) + [str(tmp_path)])
    monkeypatch.setattr(loader, "_family_dirs", lambda: original_dirs() + [family])
    yield name, source
    for key in list(sys.modules):
        if key.startswith("algua.strategies.portfolio_cache_fixture"):
            sys.modules.pop(key)


@pytest.fixture
def replay(tmp_path, monkeypatch):
    data = tmp_path / "data"
    db = tmp_path / "replay.db"
    monkeypatch.setenv("ALGUA_DATA_DIR", str(data))
    monkeypatch.setenv("ALGUA_DB_PATH", str(db))
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 4, 23, tzinfo=UTC)
    bars = SyntheticProvider(seed=19).get_bars(SYMBOLS, start, end, "1d")
    bars = bars.loc[bars.index < end]
    record = DataStore(data).ingest_bars(
        provider="synthetic", symbols=SYMBOLS, start=start.date().isoformat(),
        end=end.date().isoformat(),
        as_of="2024-04-24T00:00:00+00:00", source="portfolio-cli-fixture",
        frame=bars.reset_index().rename(columns={"timestamp": "ts"}),
        timeframe="1d", adjustment="none",
        provenance=ProvenanceDeclaration(data_tier=DataTier.SYNTHETIC_FIXTURE,
                                         universe_method="portfolio-cli-fixture/v1",
                                         limitations=("synthetic_not_market_data",)),
    )
    manifest = {
        "schema_version": "portfolio-replay/v1", "snapshot_id": record.snapshot_id,
        "start": start.isoformat(), "end": end.isoformat(), "symbols": SYMBOLS,
        "sleeves": [{"strategy": "cross_sectional_momentum", "budget": 0.5},
                    {"strategy": "high52_proximity", "budget": 0.5}],
        "execution": asdict(ExecutionContract("1d", fees=0.001, slippage=0.002)),
        "constraints": {"max_gross": 0.9, "max_weight_per_symbol": 0.5,
                        "max_turnover": None},
        "initial_cash": 17.5, "seed": 19, "risk_estimates": {},
    }
    return manifest, tmp_path / "manifest.json", db


def invoke(manifest, path):
    path.write_text(json.dumps(manifest))
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout, parse_constant=lambda v: pytest.fail(f"nonfinite: {v}"))


def test_real_snapshot_replay_records_one_distinct_composite_and_repeats(replay):
    manifest, path, db = replay
    first = invoke(manifest, path)
    second = invoke(manifest, path)
    assert first["ok"] is True
    assert first["schema_version"] == "portfolio-replay-result/v1"
    assert first["evidence_class"] == "in_sample_research_replay"
    assert first["is_forward_test"] is False
    assert first["data_tier"] == "synthetic_fixture"
    assert "synthetic_not_market_data" in first["limitations"]
    assert first["portfolio_name"].startswith("portfolio-replay:")
    assert first["portfolio_name"] == second["portfolio_name"]
    for key in ("metrics", "path", "provenance", "manifest"):
        assert first[key] == second[key]
    assert first["provenance"]["snapshot_id"] == manifest["snapshot_id"]
    costs = first["provenance"]["execution_costs"]
    assert costs["fees"] == 0.001 and costs["slippage"] == 0.002
    assert first["provenance"]["effective_replay_execution"]["target_gross_utilization"] == 1.0
    assert first["provenance"]["bars_provenance"]["source_metadata"]["research_provenance"]
    assert set(first["provenance"]["sleeve_identities"]) == {
        "cross_sectional_momentum", "high52_proximity",
    }
    for identity in first["provenance"]["sleeve_identities"].values():
        assert all(identity[k] for k in ("code_hash", "config_hash", "dependency_hash"))
    assert any(row["executed_weights"] for row in first["path"])
    assert all(sum(row["decision_weights"].values()) <= 0.9 for row in first["path"])
    assert first["path"][0]["executed_weights"] == {}
    assert first["metrics"]["cost_fees"] == 0.001
    shown = runner.invoke(app, ["runs", "show", str(first["recorded_run"]["run_id"])])
    assert shown.exit_code == 0, shown.stdout
    readback = json.loads(shown.stdout)["config_json"]["portfolio_replay"]
    assert readback["data_tier"] == first["data_tier"]
    assert readback["data_provenance"] == first["data_provenance"]
    assert readback["limitations"] == first["limitations"]
    assert "path" not in readback
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
        assert len(rows) == 2
        assert {row["strategy_name"] for row in rows} == {first["portfolio_name"]}
        assert all(row["kind"] == "backtest" and row["strategy_id"] is None for row in rows)
        assert all(row["sharpe_oos"] is None and row["passed"] is None for row in rows)
        stored = json.loads(rows[0]["config_json"])
        assert stored["portfolio_replay"]["manifest"] == first["manifest"]
        assert stored["portfolio_replay"]["provenance"] == first["provenance"]
        assert stored["portfolio_replay"]["data_tier"] == "synthetic_fixture"
        assert "path" not in stored["portfolio_replay"]
        for table in ("strategies", "stage_transitions", "approvals", "gate_evaluations",
                      "holdout_evaluations", "strategy_allocations", "paper_orders", "live_orders",
                      "tick_snapshots", "live_authorizations"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_all_cash_uses_real_snapshot_and_reports_undefined_ratios_as_null(replay):
    manifest, path, db = replay
    manifest["sleeves"] = []
    result = invoke(manifest, path)
    assert result["metrics"]["total_return"] == 0
    assert result["metrics"]["sharpe"] is None
    assert result["metrics"]["calmar"] is None
    assert result["provenance"]["sleeve_identities"] == {}
    for row in result["path"]:
        assert row["cash"] == 17.5 and row["equity"] == 17.5
        assert row["executed_weights"] == row["decision_weights"] == {}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT sharpe_is, sortino_is, calmar_is FROM runs").fetchone() == (
            None, None, None,
        )


def test_aware_offsets_are_converted_without_changing_the_requested_instant(replay):
    manifest, path, _ = replay
    manifest["sleeves"] = []
    manifest["start"] = "2024-01-02T02:00:00+02:00"
    result = invoke(manifest, path)
    assert result["manifest"]["start"] == "2024-01-02T00:00:00+00:00"
    assert result["path"][0]["date"] == "2024-01-02T00:00:00+00:00"


@pytest.mark.parametrize("change", [
    {"schema_version": "portfolio-replay/v2"}, {"unknown": True}, {"seed": True},
    {"initial_cash": True}, {"initial_cash": float("nan")}, {"start": "2024-01-02"},
    {"symbols": SYMBOLS + ["AAPL"]}, {"symbols": []},
    {"sleeves": [{"strategy": "cross_sectional_momentum", "budget": 1.1}]},
    {"sleeves": [{"strategy": "cross_sectional_momentum", "budget": 0.5}] * 2},
    {"risk_estimates": {"unknown": []}},
])
def test_malformed_manifest_refuses_before_evaluation_or_registry(replay, monkeypatch, change):
    manifest, path, db = replay
    manifest.update(change)
    import algua.evaluation.portfolio_run as module

    def forbidden(*args, **kwargs):
        pytest.fail("malformed input reached evaluation")

    monkeypatch.setattr(module, "simulate_portfolio", forbidden)
    path.write_text(json.dumps(manifest))
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not db.exists()


@pytest.mark.parametrize("execution", [
    {"allow_short": True}, {"allow_fractional": False}, {"decision_lag_bars": 0},
    {"decision_lag_bars": True}, {"rebalance_frequency": "1h"}, {"fees": True},
    {"slippage": -0.1}, {"capacity": {}}, {"max_gross_exposure": 2},
])
def test_unsupported_execution_refuses_without_creating_registry(replay, execution):
    manifest, path, db = replay
    manifest["execution"].update(execution)
    path.write_text(json.dumps(manifest))
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not db.exists()


@pytest.mark.parametrize("raw", ['{"schema_version":"a","schema_version":"b"}',
                                  "[]", "{", " " * 65537],
                         ids=["duplicate_keys", "array", "malformed", "oversized"])
def test_json_shape_duplicate_keys_and_size_refuse(replay, raw):
    _, path, db = replay
    path.write_text(raw)
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
    assert not db.exists()


def test_incompatible_declared_universe_is_not_silently_pruned(replay):
    manifest, path, db = replay
    manifest["symbols"] = ["AAPL"]
    path.write_text(json.dumps(manifest))
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    assert "universe" in json.loads(result.stdout)["error"]
    assert not db.exists()


def test_post_replay_identity_drift_does_not_record_a_result(replay, monkeypatch):
    import algua.evaluation.portfolio_run as module

    manifest, path, db = replay
    original = module.compute_artifact_hashes
    calls = 0

    def changing(name):
        nonlocal calls
        calls += 1
        identity = original(name)
        return identity if calls <= 4 else identity._replace(config_hash="changed")

    monkeypatch.setattr(module, "compute_artifact_hashes", changing)
    path.write_text(json.dumps(manifest))
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    assert "changed during replay" in json.loads(result.stdout)["error"]
    assert not db.exists()


def test_unexpected_identity_change_on_refresh_refuses_before_evaluation(replay, monkeypatch):
    import algua.evaluation.portfolio_run as module

    manifest, path, db = replay
    original = module.compute_artifact_hashes
    calls = 0

    def changing(name):
        nonlocal calls
        calls += 1
        identity = original(name)
        return identity if calls <= 2 else identity._replace(code_hash="unexpected-refresh-drift")

    def forbidden(*args, **kwargs):
        pytest.fail("unexpected refresh drift reached evaluation")

    monkeypatch.setattr(module, "compute_artifact_hashes", changing)
    monkeypatch.setattr(module, "simulate_portfolio", forbidden)
    path.write_text(json.dumps(manifest))
    result = runner.invoke(app, ["backtest", "portfolio", "--manifest", str(path)])
    assert result.exit_code == 1
    assert "changed during loading" in json.loads(result.stdout)["error"]
    assert not db.exists()


@pytest.mark.slow
def test_cold_process_mixed_family_book_captures_all_imports_before_identities(replay, tmp_path):
    """A later feature import must not retroactively change an earlier sleeve's captured closure."""
    import algua

    manifest, path, db = replay
    project = tmp_path / "cold-source"
    package = Path(algua.__file__).resolve().parent
    shutil.copytree(package, project / "algua", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(package.parent / "uv.lock", project / "uv.lock")
    family = project / "algua/strategies/mixed_import_fixture"
    family.mkdir()
    (family / "__init__.py").write_text("")
    shared = (
        "import pandas as pd\n"
        "from algua.contracts.types import ExecutionContract\n"
        "from algua.strategies.base import StrategyConfig\n"
    )
    for name, feature in (("a_pure_import_score", False), ("z_feature_import_score", True)):
        (family / f"{name}.py").write_text(
            shared + ("from algua.features.alphas import xs_trailing_return\n" if feature else "")
            + f"CONFIG = StrategyConfig(name={name!r}, universe=['AAPL', 'MSFT'], "
            "execution=ExecutionContract('1d'), params={'lookback': 2}, "
            "construction='equal_weight_positive', feature_lookback=2)\n"
            "def signal(view, params):\n"
            + ("    return xs_trailing_return(view, params)\n" if feature
               else "    return pd.Series({'AAPL': 1.0})\n")
        )
    manifest["sleeves"] = [{"strategy": "a_pure_import_score", "budget": 0.5},
                           {"strategy": "z_feature_import_score", "budget": 0.5}]
    path.write_text(json.dumps(manifest))
    script = (
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\nimport algua\n"
        "assert Path(algua.__file__).resolve().parent == Path(sys.argv[1]) / 'algua'\n"
        "from algua.cli.main import main\n"
        "main(['backtest', 'portfolio', '--manifest', sys.argv[2]])\n"
    )
    environment = {
        "PATH": os.environ["PATH"], "ALGUA_DATA_DIR": str(path.parent / "data"),
        "ALGUA_DB_PATH": str(db), "ALGUA_KNOWLEDGE_DIR": str(tmp_path / "kb"),
        "NUMBA_CACHE_DIR": str(tmp_path / "numba"), "MPLCONFIGDIR": str(tmp_path / "mpl"),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "NUMBA_NUM_THREADS": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", script, str(project), str(path)], cwd=project, env=environment,
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert set(result["provenance"]["sleeve_identities"]) == {
        "a_pure_import_score", "z_feature_import_score",
    }
    assert any(row["executed_weights"] for row in result["path"])


def test_same_config_source_change_executes_fresh_callable(replay, constant_strategy):
    from algua.registry.approvals import compute_artifact_hashes
    from algua.strategies.loader import load_strategy

    name, source = constant_strategy
    cached = load_strategy(name)
    previous = compute_artifact_hashes(name)
    assert cached.signal(pd.DataFrame()).index.tolist() == ["AAPL"]
    source.write_text(source.read_text().replace("{'AAPL': 1.0}", "{'MSFT': 1.0}"))
    manifest, path, _ = replay
    manifest["sleeves"] = [{"strategy": name, "budget": 1.0}]
    manifest["execution"]["fill_price"] = "close"
    manifest["constraints"]["max_weight_per_symbol"] = 0.9
    result = invoke(manifest, path)
    captured = result["provenance"]["sleeve_identities"][name]
    assert captured["config_hash"] == previous.config_hash
    assert captured["code_hash"] != previous.code_hash
    assert result["path"][0]["decision_weights"] == {"MSFT": 0.5}
    assert all("AAPL" not in row["decision_weights"] for row in result["path"])


@pytest.mark.parametrize("prices,undefined", [([100.0, 100.0, 102.0, 104.0], True),
                                             ([100.0, 100.0, 102.0, 99.96], False)])
def test_sortino_nulls_only_undefined_downside_in_output_and_ledger(
    replay, constant_strategy, prices, undefined,
):
    name, _ = constant_strategy
    manifest, path, db = replay
    dates = pd.date_range("2024-01-02", periods=4, tz="UTC")
    frame = pd.DataFrame([{
        "ts": date, "symbol": symbol, "open": price, "high": price + 1,
        "low": price - 1, "close": price, "adj_close": price, "volume": 1_000_000.0,
    } for date, price in zip(dates, prices, strict=True) for symbol in SYMBOLS])
    snapshot = DataStore(path.parent / "data").ingest_bars(
        provider="synthetic", symbols=SYMBOLS, start=dates[0].date().isoformat(),
        end="2024-01-06", as_of="2024-01-07T00:00:00+00:00",
        source="sortino-adapter-fixture", frame=frame, timeframe="1d", adjustment="none",
        provenance=ProvenanceDeclaration(data_tier=DataTier.SYNTHETIC_FIXTURE,
                                         universe_method="sortino-adapter-fixture/v1",
                                         limitations=("synthetic_not_market_data",)),
    )
    manifest.update(snapshot_id=snapshot.snapshot_id, start=dates[0].isoformat(),
                    end="2024-01-06T00:00:00+00:00", initial_cash=100.0,
                    sleeves=[{"strategy": name, "budget": 1.0}])
    manifest["execution"].update(fill_price="close", fees=0.0, slippage=0.0,
                                 target_gross_utilization=1.0)
    manifest["constraints"]["max_weight_per_symbol"] = 0.9
    result = invoke(manifest, path)
    assert result["metrics"]["ann_volatility"] > 0
    if undefined:
        assert all(row["return"] >= 0 for row in result["path"])
        assert result["metrics"]["sortino"] is None
    else:
        assert any(row["return"] < 0 for row in result["path"])
        assert result["metrics"]["sortino"] == pytest.approx(0.0, abs=1e-10)
    with sqlite3.connect(db) as conn:
        scalar, config = conn.execute("SELECT sortino_is, config_json FROM runs").fetchone()
        stored = json.loads(config)["portfolio_replay"]["metrics"]["sortino"]
        if undefined:
            assert scalar is stored is None
        else:
            assert scalar == stored == pytest.approx(0.0, abs=1e-10)
