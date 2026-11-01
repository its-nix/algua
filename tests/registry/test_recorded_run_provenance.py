"""Read-only disclosure must not upgrade broken lineage or fabricate historical costs."""
from __future__ import annotations

import json

import pytest

from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests.test_run_provenance import COSTS, NAME, snapshot


@pytest.mark.parametrize("corruption", [
    "none", "bars_hash", "bars_id", "cost_bool", "cost_nan", "cost_missing_unit",
    "wrong_snapshot", "wrong_strategy", "wrong_modality", "wrong_period",
    "two_siblings", "dangling", "wrong_kind", "legacy", "unknown_bars", "unknown_costs",
])
def test_board_requires_exact_recorded_context(tmp_path, monkeypatch, corruption):
    _store, rec = snapshot(tmp_path, monkeypatch)
    bars = rec.to_dict()
    costs = dict(COSTS)
    provenance = {"snapshot_id": rec.snapshot_id, "timeframe": "1d",
                  "config_hash": "canonical-config", "dependency_hash": "canonical-dependencies",
                  "period_start": "2024-01-01", "period_end": "2024-12-31"}
    if corruption == "bars_hash":
        bars["content_hash"] = "corrupt"
    elif corruption == "bars_id":
        bars["snapshot_id"] = "another"
    elif corruption == "cost_bool":
        costs["fees"] = False
    elif corruption == "cost_nan":
        costs["slippage"] = float("nan")
    elif corruption == "cost_missing_unit":
        del costs["fees_unit"]
    recorded = {"bars": None if corruption == "unknown_bars" else bars,
                "execution_costs": None if corruption == "unknown_costs" else costs}
    config = {} if corruption == "legacy" else {"run_provenance": recorded}
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy = repo.add(NAME)
        sibling = repo.record_run(
            "backtest" if corruption == "wrong_kind" else "walk_forward", NAME,
            strategy_id=repo.add("other").id if corruption == "wrong_strategy" else strategy.id,
            provenance=provenance, config=config,
        )
        gate_prov = dict(provenance)
        for corrupt, key, value in [
            ("wrong_snapshot", "snapshot_id", "another"),
            ("wrong_modality", "news_snapshot", "news-independent"),
            ("wrong_period", "period_start", "2024-02-01"),
        ]:
            if corruption == corrupt:
                gate_prov[key] = value
        lineage = [sibling, sibling] if corruption == "two_siblings" else [sibling]
        if corruption == "dangling":
            lineage = [9999]
        repo.record_run("gate", NAME, strategy_id=strategy.id,
                        derived_from=lineage, provenance=gate_prov)
        row = next(r for r in strategy_board_payload(repo, snapshot_evidence=lambda _: {
            "status": "UNAVAILABLE", "reason": "provenance_absent", "value": None,
        })["rows"] if r["name"] == NAME)
    evidence = row["evidence"]
    recorded_evidence = row["recorded_provenance"]
    if corruption in {"none", "unknown_bars"}:
        assert recorded_evidence["status"] == "VALID"
        assert recorded_evidence["value"]["execution_costs"] == COSTS
        if corruption == "unknown_bars":
            assert evidence["snapshot_provenance"]["value"] is None
            assert recorded_evidence["value"]["bars_content_hash"] is None
    elif corruption in {"legacy", "unknown_costs"}:
        assert recorded_evidence["status"] == "UNAVAILABLE"
        assert "recorded_inputs_unavailable" in evidence["comparison"]["reasons"]
    else:
        assert recorded_evidence["status"] == "INVALID"
        assert recorded_evidence["value"] is None
        assert evidence["snapshot_provenance"]["status"] == "INVALID"
    assert evidence["comparison"]["observed_metric_sort_enabled"] is False
    assert json.loads(json.dumps(evidence)) == evidence
