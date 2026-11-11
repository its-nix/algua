"""Historical checkout mechanics without operational admission or evidence writes."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

import typer

from algua.backtest.stamps import runtime_stamps
from algua.cli.app import emit
from algua.cli.errors import json_errors
from algua.config.settings import get_settings
from algua.data.serve import StoreBackedProvider
from algua.data.store import DataStore
from algua.execution.sim_broker import SimBroker
from algua.live.paper_loop import run_paper
from algua.primitives.timeparse import utc
from algua.registry.approvals import compute_artifact_hashes
from algua.strategies.loader import load_strategy

replay_app = typer.Typer(no_args_is_help=True)


@replay_app.command("replay")
@json_errors
def replay(
    name: str,
    snapshot: str = typer.Option(..., "--snapshot"),
    start: str = typer.Option(..., "--start"),
    end: str = typer.Option(..., "--end"),
    cash: float = typer.Option(50_000.0, "--cash"),
    max_drawdown: float = typer.Option(0.2, "--max-drawdown"),
    output: Path | None = typer.Option(None, "--output"),
) -> None:
    """Replay bars through SimBroker without broker API, stage, ledger or evidence writes."""
    if not math.isfinite(cash) or cash <= 0 or not 0 < max_drawdown <= 1:
        raise ValueError("cash must be finite/positive and drawdown in (0,1]")
    first, last = utc(start), utc(end)
    if first >= last:
        raise ValueError("replay start must precede end")
    if output is not None and output.exists():
        raise ValueError("replay output must be a new file")
    strategy = load_strategy(name)
    if strategy.execution.decision_lag_bars != 1 or strategy.execution.rebalance_frequency != "1d":
        raise ValueError("sequential replay supports daily decisions with a one-bar fill lag")
    store = DataStore(get_settings().data_dir)
    record = store.get_snapshot(snapshot)
    store.verify_snapshot(record)
    identity = compute_artifact_hashes(name)
    stamps = runtime_stamps()
    result = run_paper(
        strategy,
        SimBroker(cash=cash),
        StoreBackedProvider(store, snapshot),
        first,
        last,
        max_drawdown=max_drawdown,
    )
    lag_ok = all(f.fill_ts > f.decision_ts for f in result.fills)
    if not all(
        math.isfinite(v)
        for v in (result.final_cash, result.final_equity, *result.final_positions.values())
    ):
        raise ValueError("historical replay ended with unusable cash, equity or positions")
    if not lag_ok or not result.reconcile_ok:
        raise ValueError("historical replay fill timing or reconciliation failed")
    payload = {
        "ok": True,
        "mode": "historical_replay",
        "execution_source": "working_tree",
        "strategy": name,
        "snapshot_id": snapshot,
        "content_hash": record.content_hash,
        **identity._asdict(),
        "seed": None,  # The sequential simulator does not initialize an RNG.
        "start": start,
        "end": end,
        "source_metadata": record.to_dict()["source_metadata"],
        "max_drawdown": max_drawdown,
        "orders": len(result.orders),
        "fills": len(result.fills),
        "filled": sum(f.status == "filled" for f in result.fills),
        "partial": sum(f.status == "partial" for f in result.fills),
        "rejected": sum(f.status == "rejected" for f in result.fills),
        "next_session_fills_verified": lag_ok,
        "reconcile_ok": result.reconcile_ok,
        "initial_cash": cash,
        "final_cash": result.final_cash,
        "final_equity": result.final_equity,
        "return_pct": (result.final_equity / cash - 1) * 100,
        "final_positions": result.final_positions,
        "friction_model": "SimBroker reference fills; fees/slippage not charged",
        "valuation_model": (
            "Raw reference fills and vendor adjusted marks; corporate actions unverified"
        ),
        "identity_kind": "approval_first_party_closure",
        "runtime_code_hash": stamps["code_hash"],
        "investment_evidence": False,
        "forward_sessions_created": 0,
        "live_authority": False,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive create also refuses a file that appeared while the replay was running.
        with output.open("x") as target:
            json.dump(
                payload
                | {
                    "order_records": [asdict(o) for o in result.orders],
                    "fill_records": [asdict(f) for f in result.fills],
                },
                target,
                indent=2,
                default=str,
                allow_nan=False,
            )
            target.write("\n")
        payload["artifact"] = str(output)
    emit(payload)
