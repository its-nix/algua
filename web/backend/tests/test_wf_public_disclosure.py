"""HTTP -> actual CLI subprocess -> synthetic ledger, without canned CLI responses."""
from __future__ import annotations

import json

import httpx
import pytest
from backend.main import create_app

from algua.registry.db import registry_conn
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from tests.test_wf_public_disclosure import PARAMS, PRIVATE, wf_result


@pytest.mark.asyncio
async def test_actual_http_reads_redact_legacy_wf_without_burning(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "synthetic.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        repo.add("synthetic")
        fresh = record_walk_forward_run(repo, "synthetic", wf_result())
        old = repo.record_run("walk_forward", "synthetic")
        with conn:
            conn.execute("UPDATE runs SET sharpe_oos=?,config_json=? WHERE id=?", (
                PRIVATE, json.dumps({"params": PARAMS, "result": {
                    "holdout_metrics": {"sharpe": PRIVATE}, "holdout_returns": [PRIVATE]}}), old))
            conn.execute("INSERT INTO run_metrics VALUES (?,?,?)", (old, "alias", PRIVATE))
        before = [tuple(r) for r in conn.execute("SELECT * FROM runs")]
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ["/api/runs", "/api/runs?sort=sharpe_oos", f"/api/runs/{fresh}",
                         f"/api/runs/{old}", f"/api/runs/series?ids={old}",
                         "/api/strategy-board", "/api/strategy-board?include_evidence=true"]:
                response = await client.get(path)
                assert response.status_code == 200, response.text
                assert str(PRIVATE) not in response.text
                assert response.json()["ok"] is True
            detail = (await client.get(f"/api/runs/{old}")).json()["data"]
            assert detail["config_json"]["params"] == PARAMS
            assert detail["sharpe_oos"] is None
        assert [tuple(r) for r in conn.execute("SELECT * FROM runs")] == before
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM holdout_returns").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_review_fixes_preserve_exact_inputs_and_invalidity_over_actual_http(
    tmp_path, monkeypatch,
):
    from copy import deepcopy

    from tests.test_run_provenance import COSTS
    from tests.test_wf_public_disclosure import canonical_bars_record, record_provenance_pair

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "review-fixes.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    bars = canonical_bars_record()
    malformed = deepcopy(bars)
    malformed["source_metadata"]["research_provenance"] = {"tail": PRIVATE}
    numeric = COSTS | {"fees": json.dumps({"holdout_returns": [PRIVATE]})}
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        valid_id, _ = record_provenance_pair(repo, bars, name="canonical")
        invalid_id, _ = record_provenance_pair(repo, malformed, name="malformed")
        numeric_id, _ = record_provenance_pair(repo, bars, costs=numeric, name="numeric")
        # Read the original unsafe legacy shapes, without relying on the write projector.
        with conn:
            for run_id, original, costs in [(invalid_id, malformed, COSTS),
                                             (numeric_id, bars, numeric)]:
                config = {"params": PARAMS, "run_provenance": {"bars": original,
                                                              "execution_costs": costs}}
                conn.execute("UPDATE runs SET config_json=? WHERE id=?",
                             (json.dumps(config), run_id))
            conn.execute("UPDATE runs SET mean_window_sharpe=? WHERE id=?",
                         (json.dumps({"tail": PRIVATE}), numeric_id))
        before = [tuple(r) for r in conn.execute("SELECT * FROM runs")]
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(2):
                for path in ["/api/runs", "/api/runs?sort=mean_window_sharpe",
                             f"/api/runs/{valid_id}",
                             f"/api/runs/{invalid_id}", f"/api/runs/{numeric_id}",
                             "/api/strategy-board?include_evidence=true"]:
                    response = await client.get(path)
                    assert response.status_code == 200, response.text
                    assert str(PRIVATE) not in response.text
                detail = (await client.get(f"/api/runs/{valid_id}")).json()["data"]
                assert detail["config_json"]["run_provenance"]["bars"] == bars
                assert detail["config_json"]["params"] == PARAMS
                response = await client.get("/api/strategy-board?include_evidence=true")
                board = response.json()["data"]
                by_name = {row["name"]: row for row in board["rows"]}
                assert by_name["canonical"]["recorded_provenance"]["status"] == "VALID"
                for name in ["malformed", "numeric"]:
                    assert by_name[name]["recorded_provenance"]["status"] == "INVALID"
                    assert by_name[name]["evidence"]["snapshot_provenance"]["status"] == "INVALID"
        assert [tuple(r) for r in conn.execute("SELECT * FROM runs")] == before
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_actual_http_rejects_new_scalar_input_metadata_with_matching_hash(
    tmp_path, monkeypatch,
):
    from algua.provenance.snapshot_evidence import project_snapshot_record
    from tests.test_run_provenance import COSTS
    from tests.test_wf_public_disclosure import canonical_bars_record, record_provenance_pair

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "closed-input.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    bars = canonical_bars_record({"observation": str(PRIVATE)})
    assert project_snapshot_record(bars["snapshot_id"], bars)["status"] == "VALID"
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        fresh, _ = record_provenance_pair(repo, bars, name="new-scalar")
        historical, _ = record_provenance_pair(repo, bars, name="historical-scalar")
        with conn:
            conn.execute("UPDATE runs SET config_json=? WHERE id=?", (json.dumps({
                "params": PARAMS, "run_provenance": {"bars": bars, "execution_costs": COSTS}}),
                historical))
        before = [tuple(row) for row in conn.execute("SELECT * FROM runs")]
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(2):
                for path in ["/api/runs", "/api/runs?sort=mean_window_sharpe",
                             f"/api/runs/{fresh}", f"/api/runs/{historical}",
                             f"/api/runs/series?ids={fresh},{historical}",
                             "/api/strategy-board", "/api/strategy-board?include_evidence=true"]:
                    response = await client.get(path)
                    assert response.status_code == 200, response.text
                    assert str(PRIVATE) not in response.text
                detail = (await client.get(f"/api/runs/{historical}")).json()["data"]
                assert detail["snapshot_id"] == bars["snapshot_id"]
                assert detail["config_json"]["params"] == PARAMS
                assert detail["config_json"]["run_provenance"]["bars"] == {"invalid_fields": True}
                response = await client.get("/api/strategy-board?include_evidence=true")
                board = response.json()["data"]
                for row in board["rows"]:
                    assert row["recorded_provenance"]["status"] == "INVALID"
                    assert row["evidence"]["snapshot_provenance"]["status"] == "INVALID"
        assert [tuple(row) for row in conn.execute("SELECT * FROM runs")] == before
        assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM holdout_returns").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["row_count", "schema_version"])
@pytest.mark.parametrize("exponent", ["1e999", "-1e999"])
async def test_actual_http_integer_overflow_keeps_healthy_neighbors_and_raw_history(
    tmp_path, monkeypatch, field, exponent,
):
    from backend import algua_cli

    from tests.test_wf_public_disclosure import canonical_bars_record

    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "overflow.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    bars = canonical_bars_record()
    wf = wf_result()
    wf.snapshot_id, wf.bars_provenance = bars["snapshot_id"], bars
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        healthy = record_walk_forward_run(repo, "healthy", wf)
        malformed = repo.record_run("walk_forward", "malformed")
        config = json.dumps({"run_provenance": {"bars": bars | {field: "overflow"}}})
        config = config.replace('"overflow"', exponent)
        with conn:
            conn.execute("UPDATE runs SET config_json=? WHERE id=?", (config, malformed))
        before = [tuple(row) for row in conn.execute("SELECT * FROM runs")]
        outputs = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test",
        ) as client:
            for _ in range(2):
                algua_cli._cache.clear()  # Exercise subprocess reads again, not cached evidence.
                outputs.append({
                    "list": await client.get("/api/runs"),
                    "malformed": await client.get(f"/api/runs/{malformed}"),
                    "healthy": await client.get(f"/api/runs/{healthy}"),
                })
                assert [tuple(row) for row in conn.execute("SELECT * FROM runs")] == before
                assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
                assert conn.execute("SELECT count(*) FROM holdout_returns").fetchone()[0] == 0
        for results in outputs:
            for response in results.values():
                assert response.status_code == 200, response.text
                assert response.json()["ok"] is True
            by_id = {row["id"]: row for row in results["list"].json()["data"]["runs"]}
            assert by_id[healthy]["config_json"]["run_provenance"]["bars"] == bars
            assert by_id[malformed]["config_json"]["run_provenance"]["bars"] == {
                "invalid_fields": True}
            bad = results["malformed"].json()["data"]
            assert bad["config_json"]["run_provenance"]["bars"] == {"invalid_fields": True}
            good = results["healthy"].json()["data"]
            assert good["config_json"]["run_provenance"]["bars"] == bars
            assert good["mean_window_sharpe"] == 0.0
            assert good["min_window_sharpe"] == -2.5
