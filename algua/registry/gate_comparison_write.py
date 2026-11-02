"""Seal only the newly inserted comparison record inside the existing atomic gate write."""

from __future__ import annotations

import json
import sqlite3


def seal_gate_comparison(conn: sqlite3.Connection, run_id: int) -> None:
    if not conn.in_transaction:
        raise RuntimeError("comparison capture requires the open gate transaction")
    from algua.provenance.json_record import decode_json
    from algua.registry.gate_comparison_context import decode_context
    from algua.registry.gate_comparison_validation import validate_gate_record
    from algua.registry.store import SqliteStrategyRepository

    repo = SqliteStrategyRepository(conn)
    gate = repo.get_run(run_id)
    if gate is None or gate["kind"] != "gate":
        return
    try:
        config = decode_json(gate["config_json"])
    except (ValueError, TypeError, OverflowError, RecursionError):
        return  # Invalid metadata stays UNKNOWN and cannot change the financial transaction.
    record = config.get("gate_comparison_record")
    if record is None or not isinstance(record, dict) or "gate_run_id" in record:
        return  # No reconstruction, resealing or backfill of existing/legacy records.
    record.update(gate_run_id=run_id, gate_evaluation_id=gate["gate_id"])
    try:
        sibling = repo.get_run(record["wf_run_id"])
        valid = (
            sibling is not None
            and decode_context(record.get("context")) is not None
            and validate_gate_record(repo, record, gate, sibling)
        )
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        valid = False
    if not valid:
        del config["gate_comparison_record"]
    conn.execute(
        "UPDATE runs SET config_json=? WHERE id=?",
        (json.dumps(config, sort_keys=True, allow_nan=False), run_id),
    )
