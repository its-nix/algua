"""`algua runs list`/`show`/`series` — the CLI seam over `algua.registry.run_views`."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.store import DataStore
from algua.registry.db import registry_conn
from algua.registry.gate_history import GATE_DECISION_ALLOWLIST
from algua.registry.store import SqliteStrategyRepository
from tests.test_research_provenance import _ingest

runner = CliRunner()


@pytest.fixture(autouse=True)
def _tmp_db(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "r.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))


def _json(result):
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _record(kind: str, strategy: str, **metrics: float | None) -> int:
    with registry_conn() as conn:
        return SqliteStrategyRepository(conn).record_run(kind, strategy, metrics=metrics)


def test_empty_ledger_is_ok_with_zero_rows():
    payload = _json(runner.invoke(app, ["runs", "list"]))
    assert payload["ok"] is True
    assert payload["runs"] == []
    assert payload["count"] == 0


def test_kind_filters():
    _record("backtest", "alpha")
    _record("walk_forward", "alpha")
    payload = _json(runner.invoke(app, ["runs", "list", "--kind", "backtest"]))
    assert payload["count"] == 1
    assert payload["runs"][0]["kind"] == "backtest"


def test_sort_orders_best_first_with_nulls_last():
    _record("walk_forward", "alpha", sharpe_oos=None)
    _record("walk_forward", "beta", sharpe_oos=0.5)
    _record("walk_forward", "gamma", sharpe_oos=1.5)
    payload = _json(runner.invoke(app, ["runs", "list", "--sort", "sharpe_oos"]))
    names = [row["strategy_name"] for row in payload["runs"]]
    assert names == ["gamma", "beta", "alpha"]


def test_limit_caps():
    for i in range(5):
        _record("backtest", f"strat{i}")
    payload = _json(runner.invoke(app, ["runs", "list", "--limit", "2"]))
    assert payload["count"] == 2
    assert len(payload["runs"]) == 2


def test_bad_sort_exits_nonzero_with_json_error_envelope():
    result = runner.invoke(app, ["runs", "list", "--sort", "1; DROP TABLE runs"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert "error" in out
    assert "code" in out


def test_strategy_filters():
    _record("backtest", "alpha")
    _record("backtest", "beta")
    payload = _json(runner.invoke(app, ["runs", "list", "--strategy", "alpha"]))
    assert payload["count"] == 1
    assert payload["runs"][0]["strategy_name"] == "alpha"


def test_family_filters():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        repo.add("alpha", family="momentum")
        repo.add("beta", family="mean_reversion")
        repo.record_run("backtest", "alpha")
        repo.record_run("backtest", "beta")
    payload = _json(runner.invoke(app, ["runs", "list", "--family", "momentum"]))
    assert payload["count"] == 1
    assert payload["runs"][0]["strategy_name"] == "alpha"


def test_list_output_contains_no_series():
    """The two commands share a module — guard against widening `runs list`'s payload to carry a
    series (that is `runs series`'s job alone, see #349)."""
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        returns = pd.Series(
            [0.01, -0.02], index=pd.to_datetime(["2024-01-02", "2024-01-03"]), dtype=float)
        returns_id = repo.persist_backtest_returns("alpha", "2024-01-01", "2024-01-05", returns)
        repo.record_run("backtest", "alpha", series_backtest_id=returns_id)
    payload = _json(runner.invoke(app, ["runs", "list"]))
    (row,) = payload["runs"]
    assert "returns" not in row
    assert "returns_json" not in row
    assert row["series_backtest_id"] == returns_id


# -- runs show --------------------------------------------------------------------------------


def _record_gate(repo: SqliteStrategyRepository, decision_json: str) -> int:
    rec = repo.add("alpha")
    gate_id = repo.record_gate_evaluation(
        rec.id, passed=True, n_funnel=1, own_lifetime_combos=1, windowed_total_combos=1,
        funnel_window_days=90, breadth_provenance="measured", pit_ok=True, pit_override=False,
        holdout_n_bars=63, min_holdout_observations=63, code_hash="c", config_hash="cfg",
        dependency_hash="d", data_source="SyntheticProvider", snapshot_id=None,
        period_start="2024-01-01", period_end="2024-06-01", holdout_frac=0.2, actor="agent",
        decision_json=decision_json,
    )
    return repo.record_run("gate", "alpha", strategy_id=rec.id, gate_id=gate_id)


def test_show_returns_one_run():
    run_id = _record("backtest", "alpha", sharpe_is=1.0)
    payload = _json(runner.invoke(app, ["runs", "show", str(run_id)]))
    assert payload["ok"] is True
    assert payload["id"] == run_id
    assert payload["strategy_name"] == "alpha"


def test_show_missing_run_id_is_json_error_envelope():
    result = runner.invoke(app, ["runs", "show", "9999"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert "error" in out
    assert "code" in out


def test_show_gate_run_includes_checks_and_stays_inside_allowlist():
    decision_json = json.dumps({
        "passed": True,
        "checks": [{
            "name": "holdout_sharpe", "op": ">", "threshold": 0.0, "value": 1.2,
            "passed": True, "advisory": False,
        }],
        # Deliberately outside GATE_DECISION_ALLOWLIST — must never survive projection.
        "per_regime_sharpes": [0.1, 0.2, 0.3],
        "not_a_real_field": "smuggled",
    })
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        run_id = _record_gate(repo, decision_json)
    payload = _json(runner.invoke(app, ["runs", "show", str(run_id)]))
    decision = payload["gate_decision"]
    assert decision["checks"][0]["name"] == "holdout_sharpe"
    # The test that matters most: assert against the REAL allowlist constant, not a hand-copied
    # list — a hand-copied list silently rots the moment the allowlist changes.
    assert set(decision) <= GATE_DECISION_ALLOWLIST
    assert "per_regime_sharpes" not in decision
    assert "not_a_real_field" not in decision


# -- runs series --------------------------------------------------------------------------------


def test_series_single_run_returns_its_series():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        returns = pd.Series(
            [0.01, -0.02], index=pd.to_datetime(["2024-01-02", "2024-01-03"]), dtype=float)
        series_id = repo.persist_backtest_returns("alpha", "2024-01-01", "2024-01-05", returns)
        run_id = repo.record_run("backtest", "alpha", series_backtest_id=series_id)
    payload = _json(runner.invoke(app, ["runs", "series", str(run_id)]))
    entry = payload["series"][str(run_id)]
    assert entry["kind"] == "backtest"
    assert len(entry["returns"]) == 2


def test_series_several_runs_returns_several():
    id_a = _record("backtest", "alpha")
    id_b = _record("backtest", "beta")
    payload = _json(
        runner.invoke(app, ["runs", "series", str(id_a), "--run-id", str(id_b)]))
    assert set(payload["series"]) == {str(id_a), str(id_b)}


def test_series_run_with_no_pointer_is_null_not_omitted():
    run_id = _record("backtest", "alpha")
    payload = _json(runner.invoke(app, ["runs", "series", str(run_id)]))
    assert str(run_id) in payload["series"]
    assert payload["series"][str(run_id)] is None


def test_series_dedupes_repeated_ids():
    run_id = _record("backtest", "alpha")
    payload = _json(
        runner.invoke(app, ["runs", "series", str(run_id), "--run-id", str(run_id)]))
    assert list(payload["series"]) == [str(run_id)]


def test_series_caps_at_16_ids():
    ids = [_record("backtest", f"strat{i}") for i in range(17)]
    args = ["runs", "series", str(ids[0])]
    for run_id in ids[1:]:
        args += ["--run-id", str(run_id)]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert "16" in out["error"]


def test_series_at_16_ids_succeeds():
    ids = [_record("backtest", f"strat{i}") for i in range(16)]
    args = ["runs", "series", str(ids[0])]
    for run_id in ids[1:]:
        args += ["--run-id", str(run_id)]
    payload = _json(runner.invoke(app, args))
    assert len(payload["series"]) == 16


def test_series_missing_run_id_is_json_error_envelope():
    result = runner.invoke(app, ["runs", "series", "9999"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert "error" in out
    assert "code" in out


# -- runs board ---------------------------------------------------------------------------------


def test_board_empty_registry_is_ok_with_zero_rows():
    payload = _json(runner.invoke(app, ["runs", "board"]))
    assert payload["ok"] is True
    assert payload["schema_version"] == "strategy-board/v1"
    assert payload["count"] == 0
    assert payload["rows"] == []


def test_board_lists_every_strategy_with_its_latest_gate_only():
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        gated = repo.add("gated")
        repo.add("bare")
        repo.record_run("gate", "gated", strategy_id=gated.id, metrics={"sharpe_oos": 1.0})
        latest = repo.record_run(
            "gate", "gated", strategy_id=gated.id, passed=True, metrics={"sharpe_oos": 0.2})
        repo.record_run("gate", "bare", metrics={"sharpe_oos": 9.0})  # legacy name-only run
    payload = _json(runner.invoke(app, ["runs", "board"]))
    assert payload["ok"] is True
    assert payload["count"] == 2
    rows = {row["name"]: row for row in payload["rows"]}
    assert rows["gated"]["latest_gate"]["run_id"] == latest
    assert rows["gated"]["latest_gate"]["passed"] is True
    assert rows["bare"]["latest_gate"] is None


def test_board_read_failure_is_a_json_error_not_an_empty_board(monkeypatch):
    import sqlite3

    def _boom(repo):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("algua.cli.runs_cmd.strategy_board_payload", _boom)
    result = runner.invoke(app, ["runs", "board"])
    assert result.exit_code != 0
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert "error" in out


def test_board_include_evidence_composes_exact_manifest_read(tmp_path, monkeypatch):
    from algua.backtest.walkforward import walk_forward
    from algua.data.serve import StoreBackedProvider
    from algua.primitives.timeparse import utc
    from algua.registry.runs import provenance_of, record_walk_forward_run
    from algua.strategies.loader import load_strategy
    from tests.test_run_provenance import COSTS, END, NAME, START, snapshot

    # Synthetic engineering bars, trusted existing strategy, and a display-only gate row.
    store, captured = snapshot(tmp_path, monkeypatch)
    wf = walk_forward(load_strategy(NAME), StoreBackedProvider(store, captured.snapshot_id),
                      utc(START), utc(END), windows=2)
    assert wf.bars_provenance == captured.to_dict()
    assert wf.execution_costs == COSTS
    assert wf.config_hash and wf.dependency_hash
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy = repo.add(NAME)
        sibling = record_walk_forward_run(repo, NAME, wf, strategy_id=strategy.id)
        repo.record_run("gate", NAME, strategy_id=strategy.id,
                        derived_from=[sibling], provenance=provenance_of(wf))

    saved = _json(runner.invoke(app, ["runs", "show", str(sibling)]))
    assert saved["config_json"]["run_provenance"] == {
        "bars": captured.to_dict(), "execution_costs": COSTS,
    }
    assert saved["config_hash"] == wf.config_hash
    assert saved["dependency_hash"] == wf.dependency_hash

    def no_current_manifest(*_):
        pytest.fail("board evidence must read the persisted capture, not the current manifest")

    monkeypatch.setattr("algua.cli.runs_cmd.SnapshotProvenanceReader.resolve", no_current_manifest)
    payload = _json(runner.invoke(app, ["runs", "board", "--include-evidence"]))

    assert payload["evidence_schema_version"] == "strategy-board-evidence/v1"
    row, = payload["rows"]
    assert row["evidence"]["snapshot_provenance"] == {
        "status": "VALID", "reason": None,
        "value": json.loads(captured.metadata.source_metadata["research_provenance"]),
    }
    assert row["recorded_provenance"] == {
        "status": "VALID", "reason": None,
        "value": {"bars_snapshot_id": captured.snapshot_id,
                  "bars_content_hash": captured.content_hash, "execution_costs": COSTS},
    }
    assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
    assert row["evidence"]["comparison"]["observed_metric_sort_enabled"] is False
    assert captured.snapshot_id not in json.dumps(row["evidence"]["snapshot_provenance"])


@pytest.mark.parametrize("linked_legacy_sibling", [False, True])
def test_board_include_evidence_legacy_context_is_unknown(tmp_path, linked_legacy_sibling):
    # A current declared manifest cannot fill a historical run's absent captured context.
    snapshot = _ingest(DataStore(tmp_path / "data"))
    provenance = {
        "snapshot_id": snapshot.snapshot_id,
        "timeframe": "1d",
        "period_start": "2026-01-01",
        "period_end": "2026-01-06",
        "config_hash": "legacy-canonical-config",
        "dependency_hash": "legacy-canonical-dependencies",
    }
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy = repo.add("alpha")
        lineage = []
        if linked_legacy_sibling:
            lineage = [repo.record_run("walk_forward", "alpha", strategy_id=strategy.id,
                                       provenance=provenance)]
        repo.record_run(
            "gate",
            "alpha",
            strategy_id=strategy.id,
            derived_from=lineage,
            provenance=provenance,
        )

    payload = _json(runner.invoke(app, ["runs", "board", "--include-evidence"]))

    assert payload["evidence_schema_version"] == "strategy-board-evidence/v1"
    row, = payload["rows"]
    assert row["evidence"]["snapshot_provenance"] == {
        "status": "UNAVAILABLE", "reason": "provenance_absent", "value": None,
    }
    assert row["recorded_provenance"] == {
        "status": "UNAVAILABLE", "reason": "run_provenance_absent", "value": None,
    }
    assert row["evidence"]["comparison"]["status"] == "UNKNOWN"
    assert row["evidence"]["comparison"]["observed_metric_sort_enabled"] is False
    assert snapshot.snapshot_id not in json.dumps(payload)
