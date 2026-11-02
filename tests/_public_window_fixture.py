"""Synthetic-only subprocess fixture for actual HTTP and production-bundle privacy checks."""
from __future__ import annotations

import json

from algua.config.settings import Settings
from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests.registry.test_public_windows import record
from tests.test_wf_public_disclosure import PARAMS, PRIVATE


def prepare():
    Settings.model_config["env_file"] = None
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        first, first_run, _ = record(repo, "synthetic_alpha")
        second, second_run, _ = record(repo, "synthetic_beta")
        legacy = repo.add("synthetic_legacy")
        old = repo.record_run(
            "walk_forward", legacy.name, strategy_id=legacy.id,
            metrics={"mean_window_sharpe": 999},
            config={"params": PARAMS, "research_record": {
                "schema_version": "recorded-wf-scalars/v1", "context_sha256": "a" * 64}})
        with conn:
            conn.execute("UPDATE runs SET sharpe_oos=?,components=? WHERE id=?",
                         (PRIVATE, json.dumps([{"tail": [PRIVATE]}]), old))
        return {"synthetic_only": True, "PRIVATE": PRIVATE, "PARAMS": PARAMS,
                "strategies": [first.id, second.id, legacy.id],
                "runs": [first_run, second_run, old],
                "board": strategy_board_payload(repo, research=True)}


if __name__ == "__main__":
    print(json.dumps(prepare(), allow_nan=False))
