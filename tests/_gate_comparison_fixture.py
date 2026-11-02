"""Owned synthetic acceptance inputs; the gate, burn, vector and lineage use the real CLI.

Run with this tree's Python and explicit ALGUA_{DB_PATH,DATA_DIR,KNOWLEDGE_DIR}.
Family assignments alone are fixture scaffolding, never qualification evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from algua.backtest._sample import SyntheticProvider
from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore
from algua.primitives.timeparse import utc
from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository

REPO = Path(__file__).resolve().parents[1]
START, END = "2021-01-01", "2025-01-01"
NAMES = ("high52_proximity", "path_efficiency_quality_momentum")
SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]


def cli(*args: str) -> dict:
    result = subprocess.run(
        [str(REPO / ".venv/bin/algua"), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    log = os.environ.get("GATE_FIXTURE_COMMAND_LOG")
    if log:
        with Path(log).open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "argv": result.args,
                        "cwd": str(REPO),
                        "exit": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                + "\n"
            )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload


def fixture_family(name: str) -> None:
    """Explicit fixture-only family scaffolding; no gate/holdout/run writes here."""
    now = datetime.now(UTC).isoformat()
    with registry_conn() as conn, conn:
        family = conn.execute(
            "INSERT INTO families(name,created_at,created_by_actor,created_by_strategy) "
            "VALUES (?,?,?,?)",
            (f"synthetic_fixture_{name}", now, "agent", name),
        ).lastrowid
        conn.execute(
            "INSERT INTO family_events(event_type,family_id,actor,created_at) VALUES (?,?,?,?)",
            ("family_created", family, "agent", now),
        )
        conn.execute(
            "INSERT INTO family_members(family_id,strategy_name,joined_at,joined_by_actor) "
            "VALUES (?,?,?,?)",
            (family, name, now, "agent"),
        )
        conn.execute(
            "INSERT INTO family_events(event_type,family_id,strategy_name,actor,clustering_verdict,"
            "similarity_score,clustering_version,clustering_config_json,axis_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "strategy_assigned",
                family,
                name,
                "agent",
                "NOVEL",
                0.0,
                "fixture-only",
                "{}",
                "{}",
                now,
            ),
        )


def generate(
    *,
    names: tuple[str, ...] = NAMES,
    seed: int = 21,
    start: str = START,
    end: str = END,
    invoke: Callable[..., dict] = cli,
) -> dict:
    for key in ("ALGUA_DB_PATH", "ALGUA_DATA_DIR", "ALGUA_KNOWLEDGE_DIR"):
        assert Path(os.environ[key]).is_absolute(), key
    assert not Path(os.environ["ALGUA_DB_PATH"]).exists(), "requires a fresh owned registry"
    store = DataStore(Path(os.environ["ALGUA_DATA_DIR"]))
    frame = SyntheticProvider(seed=seed).get_bars(SYMBOLS, utc(start), utc(end), "1d")
    frame = frame[frame.index < utc(end)].reset_index().rename(columns={"timestamp": "ts"})
    snapshot = store.ingest_bars(
        provider="fixture",
        symbols=SYMBOLS,
        start=start,
        end=end,
        as_of="2025-01-02T00:00:00+00:00",
        source="synthetic-gate-interface-fixture",
        frame=frame,
        provenance=ProvenanceDeclaration(
            DataTier.SYNTHETIC_FIXTURE, "synthetic-gate-fixture/v1", ("synthetic_not_market_data",)
        ),
    )
    outputs = {}
    for name in names:
        common = [name, "--snapshot", snapshot.snapshot_id, "--start", start, "--end", end]
        invoke("backtest", "run", *common, "--register")
        fixture_family(name)
        invoke("backtest", "sweep", *common, "--param", "construction.top_k=1,3")
        decision = invoke("research", "promote", *common)
        assert decision["passed"] is False and decision["promoted"] is False, decision
        assert any(
            c["name"] == "pit_required" and c["passed"] is False for c in decision["checks"]
        ), decision
        outputs[name] = decision
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategies = [repo.get(name).id for name in names]
        assert all(repo.get(name).stage.value == "backtested" for name in names)
        runs = [dict(row) for row in repo.list_runs(kind="gate")]
        assert len(runs) == len(names)
    return {
        "data_tier": "synthetic_fixture",
        "qualification": False,
        "snapshot_id": snapshot.snapshot_id,
        "strategies": strategies,
        "gate_runs": [r["id"] for r in runs],
        "decisions": outputs,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=21)
    parser.add_argument("--end", default=END)
    args = parser.parse_args()
    print(json.dumps(generate(seed=args.seed, end=args.end), sort_keys=True))
