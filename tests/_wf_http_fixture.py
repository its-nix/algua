"""Synthetic HTTP fixtures, executed only by the root interpreter via ``-m``."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from algua.registry.db import registry_conn
from algua.registry.runs import record_walk_forward_run
from algua.registry.store import SqliteStrategyRepository
from tests.test_wf_public_disclosure import PARAMS, PRIVATE, wf_result


def legacy():
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
    return {"fresh": fresh, "old": old}


def review_fixes():
    from copy import deepcopy

    from tests.test_run_provenance import COSTS
    from tests.test_wf_public_disclosure import canonical_bars_record, record_provenance_pair

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
    return {"bars": bars, "valid_id": valid_id, "invalid_id": invalid_id, "numeric_id": numeric_id}


def closed_input():
    from algua.provenance.snapshot_evidence import project_snapshot_record
    from tests.test_run_provenance import COSTS
    from tests.test_wf_public_disclosure import canonical_bars_record, record_provenance_pair

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
    return {"bars": bars, "fresh": fresh, "historical": historical}


def overflow(field, exponent):
    from tests.test_wf_public_disclosure import canonical_bars_record

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
    return {"bars": bars, "healthy": healthy, "malformed": malformed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=["legacy", "review_fixes", "closed_input", "overflow"])
    parser.add_argument("field", nargs="?", choices=["row_count", "schema_version"])
    parser.add_argument("exponent", nargs="?", choices=["1e999", "-1e999"])
    args = parser.parse_args()
    if Path(os.environ["ALGUA_DB_PATH"]).exists():
        parser.error("fixture database must be new")
    if args.case == "overflow":
        if args.field is None or args.exponent is None:
            parser.error("overflow requires field and exponent")
        fixture = overflow(args.field, args.exponent)
    else:
        if args.field is not None or args.exponent is not None:
            parser.error("only overflow accepts field and exponent")
        fixture = {"legacy": legacy, "review_fixes": review_fixes,
                   "closed_input": closed_input}[args.case]()
    print(json.dumps({"PRIVATE": PRIVATE, "PARAMS": PARAMS, **fixture}))


if __name__ == "__main__":
    main()
