"""Bounded review regressions; registry fixtures never evaluate or promote a gate."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from algua.registry.db import registry_conn
from algua.registry.store import SqliteStrategyRepository
from algua.registry.strategy_board import strategy_board_payload
from tests.test_run_provenance import COSTS, END, NAME, START, snapshot


def board_pair(tmp_path, monkeypatch, *, sibling_update=None, gate_update=None, legacy=False,
               no_lineage=False, malformed_cost=False):
    _store, rec = snapshot(tmp_path, monkeypatch)
    common = {"snapshot_id": rec.snapshot_id, "period_start": START, "period_end": END,
              "timeframe": "1d", "config_hash": "canonical-config",
              "dependency_hash": "canonical-dependencies", "news_snapshot": "news-independent",
              "fundamentals_snapshot": "fundamentals-independent",
              "delisting_snapshot": "delistings-independent",
              "universe_name": "universe-independent"}
    with registry_conn() as conn:
        repo = SqliteStrategyRepository(conn)
        strategy = repo.add(NAME)
        sibling = repo.record_run(
            "walk_forward", NAME, strategy_id=strategy.id,
            provenance=common | {"code_hash": "runtime-stamp"} | (sibling_update or {}),
            config={} if legacy else {"run_provenance": {
                "bars": rec.to_dict(), "execution_costs": COSTS | {"fees": True}
                if malformed_cost else COSTS,
            }},
        )
        repo.record_run("gate", NAME, strategy_id=strategy.id,
                        derived_from=[] if no_lineage else [sibling],
                        provenance=common | {"code_hash": "artifact-closure"} | (gate_update or {}))
        default = strategy_board_payload(repo)
        def no_manifest(_):
            pytest.fail("historical run evidence must never query a current manifest")
        result = strategy_board_payload(repo, snapshot_evidence=no_manifest)
        assert strategy_board_payload(repo) == default
    row, = result["rows"]
    assert set(row["evidence"]) == {
        "run_id", "evaluation", "oos_interval", "snapshot_provenance", "comparison",
    }
    assert row["evidence"]["comparison"] == {
        "status": "UNKNOWN", "observed_metric_sort_enabled": False,
        "reasons": ["lineage_or_source_unavailable"
                    if row["recorded_provenance"]["status"] == "VALID"
                    else "recorded_inputs_unavailable"], "cohort_id": None, "context": None,
    }
    return row


@pytest.mark.parametrize("field", ["config_hash", "dependency_hash", "news_snapshot",
                                   "fundamentals_snapshot", "delisting_snapshot", "universe_name"])
def test_conflicting_canonical_or_modal_identity_is_invalid(tmp_path, monkeypatch, field):
    row = board_pair(tmp_path, monkeypatch, gate_update={field: "different"})
    assert row["recorded_provenance"]["status"] == "INVALID"
    assert row["evidence"]["snapshot_provenance"] == {
        "status": "INVALID", "reason": "snapshot_binding_mismatch", "value": None,
    }


@pytest.mark.parametrize("field", ["config_hash", "dependency_hash"])
@pytest.mark.parametrize("source", ["gate", "sibling", "both"])
def test_missing_legacy_identity_is_unavailable(tmp_path, monkeypatch, field, source):
    row = board_pair(tmp_path, monkeypatch,
                     gate_update={field: None} if source in {"gate", "both"} else {},
                     sibling_update={field: None} if source in {"sibling", "both"} else {})
    assert row["recorded_provenance"]["status"] == "UNAVAILABLE"
    assert row["evidence"]["snapshot_provenance"] == {
        "status": "UNAVAILABLE", "reason": "missing_fields", "value": None,
    }


def test_legitimate_distinct_code_hash_schemes_are_accepted(tmp_path, monkeypatch):
    row = board_pair(tmp_path, monkeypatch)
    assert row["recorded_provenance"]["status"] == "VALID"
    assert row["evidence"]["snapshot_provenance"]["status"] == "VALID"


@pytest.mark.parametrize("field", ["config_hash", "dependency_hash"])
def test_matching_nontext_canonical_identity_is_invalid(tmp_path, monkeypatch, field):
    row = board_pair(tmp_path, monkeypatch, sibling_update={field: b"not-a-text-hash"},
                     gate_update={field: b"not-a-text-hash"})
    assert row["recorded_provenance"]["status"] == "INVALID"


@pytest.mark.parametrize("no_lineage", [False, True])
def test_legacy_missing_recorded_context_never_falls_back(tmp_path, monkeypatch, no_lineage):
    row = board_pair(tmp_path, monkeypatch, legacy=True, no_lineage=no_lineage)
    assert row["recorded_provenance"]["status"] == "UNAVAILABLE"
    assert row["evidence"]["snapshot_provenance"] == {
        "status": "UNAVAILABLE", "reason": "provenance_absent", "value": None,
    }


def test_snapshot_failure_reasons_match_the_actual_frontend_vocabulary(tmp_path, monkeypatch):
    row = board_pair(tmp_path, monkeypatch, malformed_cost=True)
    snapshot_error = row["evidence"]["snapshot_provenance"]
    frontend = (Path(__file__).resolve().parents[2] /
                "web/frontend/src/components/StrategyBoard.tsx").read_text()
    block = frontend.split("const INVALID_REASONS = new Set([", 1)[1].split("])", 1)[0]
    reasons = set(re.findall(r"'([^']+)'", block))
    assert snapshot_error["status"] == "INVALID"
    assert snapshot_error["value"] is None
    assert snapshot_error["reason"] in reasons
