"""HTTP -> actual root CLI -> synthetic ledger, using separate Python projects.

Run from the repository root after ``uv sync --locked`` and
``uv sync --project web --locked``:
``uv run --project web pytest web/integration -q``.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
from contextlib import closing

import httpx
import pytest
from backend import algua_cli
from backend.main import create_app


@pytest.fixture(autouse=True)
def isolated_http_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "synthetic.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("ALGUA_WEB_STATE", str(tmp_path / "push-state"))
    algua_cli._cache.clear()
    algua_cli._locks.clear()
    algua_cli._semaphore = asyncio.Semaphore(algua_cli._MAX_CONCURRENT_SUBPROCESSES)
    assert algua_cli._cli_command(("runs", "list"))[0] == str(
        algua_cli.REPO / ".venv/bin/algua")
    yield
    algua_cli._cache.clear()
    algua_cli._locks.clear()


def prepare_fixture(case, *args):
    result = subprocess.run(
        [str(algua_cli.REPO / ".venv/bin/python"), "-m", "tests._wf_http_fixture",
         case, "--", *args],
        cwd=algua_cli.REPO, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.asyncio
async def test_actual_http_reads_redact_legacy_wf_without_burning(tmp_path, monkeypatch):
    fixture = prepare_fixture("legacy")
    PRIVATE = fixture["PRIVATE"]
    PARAMS = fixture["PARAMS"]
    fresh = fixture["fresh"]
    old = fixture["old"]
    with closing(sqlite3.connect(os.environ["ALGUA_DB_PATH"])) as conn:
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
    fixture = prepare_fixture("review_fixes")
    PRIVATE = fixture["PRIVATE"]
    PARAMS = fixture["PARAMS"]
    bars = fixture["bars"]
    valid_id = fixture["valid_id"]
    invalid_id = fixture["invalid_id"]
    numeric_id = fixture["numeric_id"]
    with closing(sqlite3.connect(os.environ["ALGUA_DB_PATH"])) as conn:
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
    fixture = prepare_fixture("closed_input")
    PRIVATE = fixture["PRIVATE"]
    PARAMS = fixture["PARAMS"]
    bars = fixture["bars"]
    fresh = fixture["fresh"]
    historical = fixture["historical"]
    with closing(sqlite3.connect(os.environ["ALGUA_DB_PATH"])) as conn:
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
    fixture = prepare_fixture("overflow", field, exponent)
    bars = fixture["bars"]
    healthy = fixture["healthy"]
    malformed = fixture["malformed"]
    with closing(sqlite3.connect(os.environ["ALGUA_DB_PATH"])) as conn:
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
