"""Actual HTTP -> standalone web -> root CLI -> synthetic public producer, no fake gates."""
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


@pytest.mark.asyncio
async def test_public_windows_http_is_identity_bound_private_free_and_read_only(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "public.db"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("ALGUA_WEB_STATE", str(tmp_path / "web-state"))
    fixture = subprocess.run(
        [str(algua_cli.REPO / ".venv/bin/python"), "-m", "tests._public_window_fixture"],
        cwd=algua_cli.REPO, capture_output=True, text=True, timeout=60, check=False)
    assert fixture.returncode == 0, fixture.stderr
    ids = json.loads(fixture.stdout)
    first, second, legacy = ids["strategies"]
    first_run, second_run, legacy_run = ids["runs"]
    algua_cli._cache.clear()
    algua_cli._locks.clear()
    algua_cli._semaphore = asyncio.Semaphore(algua_cli._MAX_CONCURRENT_SUBPROCESSES)
    with closing(sqlite3.connect(os.environ["ALGUA_DB_PATH"])) as conn:
        before = [tuple(r) for r in conn.execute("SELECT * FROM runs")]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test",
        ) as client:
            for _ in range(2):
                algua_cli._cache.clear()
                for path in [
                    "/api/strategy-board", "/api/strategy-board?include_evidence=true",
                    "/api/strategy-board?research=true", "/api/runs",
                    f"/api/runs/{first_run}", f"/api/runs/{legacy_run}",
                    f"/api/strategy/{first}/research?run_id={first_run}",
                    f"/api/strategy/{legacy}/research?run_id={legacy_run}",
                    f"/api/runs/series?ids={first_run},{legacy_run}",
                ]:
                    response = await client.get(path)
                    assert response.status_code == 200, response.text
                    assert str(ids["PRIVATE"]) not in response.text
                board = (await client.get("/api/strategy-board?research=true")).json()["data"]
                assert board["evidence_schema_version"] == "strategy-board-research/v2"
                a, b, old = sorted(board["rows"], key=lambda r: r["strategy_id"])
                assert a["evidence"]["comparison"]["status"] == "COMPARABLE"
                cohort = a["evidence"]["comparison"]["cohort_id"]
                assert cohort == b["evidence"]["comparison"]["cohort_id"]
                assert a["latest_research"]["mean_window_sharpe"] == 0.0
                assert a["latest_research"]["min_window_sharpe"] == -1.0
                assert old["evidence"]["comparison"]["status"] == "UNKNOWN"
                assert old["latest_research"]["mean_window_sharpe"] is None
                mismatch = await client.get(f"/api/strategy/{second}/research?run_id={first_run}")
                assert mismatch.status_code >= 400
                detail = (await client.get(f"/api/runs/{first_run}")).json()["data"]
                assert detail["config_json"]["params"] == ids["PARAMS"]
                assert detail["config_json"]["public_window_record"]["strategy_id"] == first
                assert second_run != first_run
            assert [tuple(r) for r in conn.execute("SELECT * FROM runs")] == before
            assert conn.execute("SELECT count(*) FROM gate_evaluations").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 0
    algua_cli._cache.clear()
    algua_cli._locks.clear()
