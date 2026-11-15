"""Standalone HTTP process -> genuine root CLI -> actual failed, synthetic gate writer."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing

import httpx
from backend import algua_cli


def test_standalone_http_failed_gate_cohort_is_read_only(tmp_path, monkeypatch):
    for key, path in (
        ("DB_PATH", "registry.db"),
        ("DATA_DIR", "data"),
        ("KNOWLEDGE_DIR", "kb"),
        ("WEB_STATE", "web-state"),
    ):
        monkeypatch.setenv(f"ALGUA_{key}", str(tmp_path / path))
    assert sys.executable != str(algua_cli.REPO / ".venv/bin/python")
    fixture = subprocess.run(
        [str(algua_cli.REPO / ".venv/bin/python"), "-m", "tests._gate_comparison_fixture"],
        cwd=algua_cli.REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert fixture.returncode == 0, fixture.stderr
    identities = json.loads(fixture.stdout)
    (tmp_path / "generator.json").write_text(fixture.stdout)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--lifespan",
                "off",
            ],
            cwd=algua_cli.REPO / "web",
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=40) as client:
                for _ in range(200):
                    assert server.poll() is None, (tmp_path / "server.log").read_text()
                    try:
                        if client.get("/api/strategy-board").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.1)
                else:
                    raise AssertionError("standalone HTTP server did not become ready")
                with closing(sqlite3.connect(os.environ["ALGUA_DB_PATH"])) as conn:

                    def digest():
                        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()

                    before = digest()
                    for _ in range(2):
                        default = client.get("/api/strategy-board").json()["data"]
                        assert default["schema_version"] == "strategy-board/v1"
                        assert "evidence_schema_version" not in default
                        response = client.get("/api/strategy-board?include_evidence=true")
                        assert response.status_code == 200, response.text
                        (tmp_path / "board-http.json").write_text(response.text)
                        board = response.json()["data"]
                        assert board["evidence_schema_version"] == "strategy-board-evidence/v2"
                        rows = board["rows"]
                        assert {r["strategy_id"] for r in rows} == set(identities["strategies"])
                        assert len({r["evidence"]["comparison"]["cohort_id"] for r in rows}) == 1
                        for row in rows:
                            assert row["stage"] == "backtested"
                            assert row["latest_gate"]["passed"] is False
                            comparison = row["evidence"]["comparison"]
                            assert comparison["status"] == "COMPARABLE"
                            assert comparison["context"]["data_tier"] == "synthetic_fixture"
                            gate_id = row["latest_gate"]["run_id"]
                            detail = client.get(f"/api/runs/{gate_id}").json()["data"]
                            assert detail["strategy_id"] == row["strategy_id"]
                            assert detail["kind"] == "gate" and detail["passed"] == 0
                            wf_id = detail["derived_from"][0]
                            sibling = client.get(f"/api/runs/{wf_id}").json()["data"]
                            assert sibling["sharpe_oos"] is None
                            assert sibling["ann_vol_oos"] is None
                            assert "comparison_context" not in sibling["config_json"]
                            series = client.get(f"/api/runs/series?ids={wf_id},{gate_id}")
                            assert "returns_blob" not in series.text
                            assert "bar_dates_blob" not in series.text
                            assert series.json()["data"]["series"][str(wf_id)] is None
                            assert client.get(f"/api/strategy/{row['name']}").status_code == 200
                        assert digest() == before
                    assert (
                        conn.execute("SELECT count(*) FROM holdout_evaluations").fetchone()[0] == 2
                    )
                    assert conn.execute("SELECT count(*) FROM holdout_returns").fetchone()[0] == 2
        finally:
            server.terminate()
            server.wait(timeout=15)
