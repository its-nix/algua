"""Closed, data-only replay input evidence; these fixtures assert no numerical execution."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from algua.contracts.types import CapacityLimit, ExecutionContract
from algua.provenance.research import (
    DataTier,
    ProvenanceDeclaration,
    build_envelope,
    encode_envelope,
)
from algua.provenance.snapshot import SnapshotMetadata, SnapshotRecord, compute_snapshot_id
from algua.provenance.snapshot_evidence import project_snapshot_record
from algua.strategies.base import StrategyConfig, strategy_config_hash

BOOK = ("strategies", "budgets", "constraints", "execution", "initial_cash", "symbols",
        "risk_estimates")
LIMITATIONS = ["static_universe_not_verified_pit", "no_delisting_records",
               "no_promotion_or_trading_authority", "replay_not_elapsed_forward_test"]


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def seal(config):
    payload = config["portfolio_replay"]
    provenance = payload["provenance"]
    provenance["config_hash"] = hashlib.sha256(encoded(
        {k: provenance[k] for k in BOOK})).hexdigest()
    payload["portfolio_name"] = "portfolio-replay:" + hashlib.sha256(encoded({
        "manifest": payload["manifest"], "provenance": provenance})).hexdigest()
    return config


@pytest.fixture
def portfolio_input():
    envelope = build_envelope(ProvenanceDeclaration(
        DataTier.SYNTHETIC_FIXTURE, "portfolio-memory-fixture/v1",
        ("synthetic_not_market_data",)), provider="synthetic",
        coverage_start="2024-01-02", coverage_end="2024-01-04")
    metadata = SnapshotMetadata(
        dataset="bars", provider="synthetic", symbols=("AAA",), start="2024-01-02",
        end="2024-01-05", as_of="2024-01-06T00:00:00+00:00", source="fixture",
        kind="bars", timeframe="1d", adjustment="none",
        source_metadata={"research_provenance": encode_envelope(envelope)})
    snapshot = SnapshotRecord(compute_snapshot_id(metadata, "b" * 64), metadata, 3,
        "b" * 64, Path("bars.parquet"), "2024-01-06T00:00:00+00:00",
        storage_format="parquet_dataset").to_dict()
    execution = asdict(ExecutionContract("1d", fees=0.001, slippage=0.002))
    config = StrategyConfig(name="fixture_rule", universe=["AAA"],
        execution=ExecutionContract("1d"), construction="equal_weight_positive")
    manifest = {"schema_version": "portfolio-replay/v1", "snapshot_id": snapshot["snapshot_id"],
        "start": "2024-01-02T00:00:00+00:00", "end": "2024-01-05T00:00:00+00:00",
        "symbols": ["AAA"], "sleeves": [{"strategy": "fixture_rule", "budget": 0.5}],
        "execution": execution, "constraints": {"max_gross": 0.9,
            "max_weight_per_symbol": 0.8, "max_turnover": None},
        "initial_cash": 17.5, "seed": None, "risk_estimates": {}}
    provenance = {
        "data_source": "StoreBackedProvider", "seed": None,
        "snapshot_id": snapshot["snapshot_id"], "bars_provenance": snapshot,
        "execution_costs": {"schema_version": "execution-costs/v1",
            "model": "vectorbt.from_orders", "fees": 0.001,
            "fees_unit": "fraction_of_trade_notional_per_side", "slippage": 0.002,
            "slippage_unit": "adverse_fill_price_fraction_per_side"},
        "code_hash": None, "dependency_hash": None,
        "strategies": {"fixture_rule": strategy_config_hash(config)},
        "budgets": {"fixture_rule": 0.5}, "constraints": manifest["constraints"],
        "execution": execution, "initial_cash": 17.5, "symbols": ["AAA"],
        "risk_estimates": {}, "bars_digest": "c" * 64,
        "period": {"start": manifest["start"], "end": manifest["end"]},
        "replay": {"method": "canonical_engine_prefix", "scope": "research_only",
            "sessions": 3, "symbols": 1, "sleeves": 1, "work_units": 15,
            "requested_sessions": 3, "requested_work_units": 15,
            "limits": {"sessions": 512, "symbols": 8, "sleeves": 8, "work_units": 2_000_000}},
        "sleeve_identities": {"fixture_rule": {"code_hash": "d" * 32,
            "config_hash": strategy_config_hash(config), "dependency_hash": None}},
        "sleeve_configs": {"fixture_rule": config.model_dump(mode="json")},
        "risk_estimate_authority": "unverified_research_assumptions",
        "effective_replay_execution": execution | {"warmup_bars": 0,
            "target_gross_utilization": 1.0, "capacity": None}}
    evidence = project_snapshot_record(snapshot["snapshot_id"], snapshot)
    return seal({"portfolio_replay": {
        "schema_version": "portfolio-replay-result/v1", "portfolio_name": "",
        "evidence_class": "in_sample_research_replay", "is_forward_test": False,
        "data_tier": evidence["value"]["data_tier"], "data_provenance": evidence,
        "limitations": LIMITATIONS + evidence["value"]["limitations"],
        "manifest": manifest, "provenance": provenance,
        "metrics": {"total_return": -0.1, "cagr": -0.2, "ann_volatility": 0.3,
            "sharpe": -0.5, "sortino": -0.7, "calmar": -1.0, "max_drawdown": -0.2,
            "hit_rate": 0.0, "tail_ratio": 0.0, "turnover": 1.0,
            "avg_gross_exposure": 0.5, "n_rebalances": 2,
            "cost_fees": 0.001, "cost_slippage": 0.002}}})


def validate(config):
    from algua.operator.portfolio_memory_inputs import public_portfolio_inputs

    return public_portfolio_inputs(config)


def test_whole_valid_input_is_detached_lossless_and_pure(portfolio_input, monkeypatch):
    from algua.config.settings import Settings
    from algua.operator.portfolio_memory_inputs import public_portfolio_inputs
    from algua.strategies import loader

    def forbidden(*args, **kwargs):
        raise AssertionError("pure validation performed runtime/configuration/store work")

    monkeypatch.setattr(Settings, "__init__", forbidden)
    monkeypatch.setattr(loader, "load_strategy", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    before = copy.deepcopy(portfolio_input)
    result = public_portfolio_inputs(portfolio_input)
    assert result == before and result is not portfolio_input
    assert result["portfolio_replay"]["manifest"]["seed"] is None
    assert result["portfolio_replay"]["provenance"]["code_hash"] is None
    assert result["portfolio_replay"]["metrics"]["total_return"] == -0.1
    result["portfolio_replay"]["manifest"]["symbols"].append("DETACHED")
    assert portfolio_input == before


def test_fresh_api_import_and_call_stay_off_runtime_packages(portfolio_input, tmp_path):
    bootstrap = """import importlib.abc, json, sys
forbidden = ('algua.strategies', 'algua.config', 'algua.models')
class RefuseRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + '.') for prefix in forbidden):
            raise AssertionError('pure portfolio API imported a forbidden runtime package')
sys.meta_path.insert(0, RefuseRuntime())
from algua.operator.portfolio_memory_inputs import public_portfolio_inputs
value = json.loads(sys.stdin.read())
result = public_portfolio_inputs(value)
assert result == value and result is not value
assert not any(name == prefix or name.startswith(prefix + '.')
               for name in sys.modules for prefix in forbidden)
print('pure import and validation passed')
"""
    home = tmp_path / "private-home"
    home.mkdir()
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap],
        input=encoded(portfolio_input), capture_output=True, timeout=20,
        env={"HOME": str(home), "TMPDIR": str(tmp_path), "PATH": "/usr/local/bin:/usr/bin:/bin"})
    assert completed.returncode == 0, completed.stderr.decode()
    assert completed.stdout == b"pure import and validation passed\n"


@pytest.mark.parametrize("seed", [None, 0, 2**32 - 1])
def test_seed_and_optional_runtime_stamps_preserve_producer_values(portfolio_input, seed):
    payload = portfolio_input["portfolio_replay"]
    payload["manifest"]["seed"] = payload["provenance"]["seed"] = seed
    payload["provenance"]["code_hash"] = "a" * 40 + "-dirty-" + "e" * 16
    payload["provenance"]["dependency_hash"] = "f" * 64
    assert validate(seal(portfolio_input)) == portfolio_input


def test_all_cash_unknown_source_and_undefined_ratios_remain_explicit(portfolio_input):
    payload = portfolio_input["portfolio_replay"]
    manifest, provenance = payload["manifest"], payload["provenance"]
    manifest["sleeves"] = []
    for key in ("strategies", "budgets", "sleeve_configs", "sleeve_identities"):
        provenance[key] = {}
    provenance["replay"].update(sleeves=0, work_units=9, requested_work_units=9)
    provenance["bars_provenance"] = None
    payload.update(data_tier="unknown", data_provenance={"status": "UNAVAILABLE",
        "reason": "provenance_absent", "value": None},
        limitations=LIMITATIONS + ["data_provenance_unavailable"])
    payload["metrics"].update(sharpe=None, sortino=None, calmar=None, ann_volatility=0.0,
                              max_drawdown=0.0, total_return=0.0)
    assert validate(seal(portfolio_input)) == portfolio_input


def test_sleeve_capacity_overlays_and_opaque_inputs_keep_general_contract(portfolio_input):
    payload = portfolio_input["portfolio_replay"]
    execution = ExecutionContract("1d", max_gross_exposure=1.5, warmup_bars=900,
        capacity=CapacityLimit(1000.0, 0.1, 20))
    config = StrategyConfig(name="fixture_rule", universe=["AAA"], execution=execution,
        construction="equal_weight_positive", params={"holdout_key_is_input": "雪\nopaque"},
        construction_params={"opaque": {"nested": [1, 2]}},
        overlays=[{"policy": "trailing_stop", "params": {"opaque": "declared"}}])
    provenance = payload["provenance"]
    provenance["sleeve_configs"]["fixture_rule"] = config.model_dump(mode="json")
    digest = strategy_config_hash(config)
    provenance["strategies"]["fixture_rule"] = digest
    provenance["sleeve_identities"]["fixture_rule"]["config_hash"] = digest
    result = validate(seal(portfolio_input))
    assert result == portfolio_input
    assert result["portfolio_replay"]["provenance"][
        "sleeve_identities"]["fixture_rule"]["config_hash"] == strategy_config_hash(config)


@pytest.mark.parametrize("opaque", [(1, 2), {1: "non-string-key"}])
def test_non_json_input_is_not_silently_normalized(portfolio_input, opaque):
    provenance = portfolio_input["portfolio_replay"]["provenance"]
    raw = provenance["sleeve_configs"]["fixture_rule"]
    raw["params"]["opaque"] = opaque
    config = StrategyConfig(**(raw | {"execution": ExecutionContract(**raw["execution"])}))
    digest = strategy_config_hash(config)
    provenance["strategies"]["fixture_rule"] = digest
    provenance["sleeve_identities"]["fixture_rule"]["config_hash"] = digest
    seal(portfolio_input)
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(portfolio_input)


def test_risk_timeline_original_order_and_sorted_provenance_are_preserved(portfolio_input):
    payload = portfolio_input["portfolio_replay"]
    rows = [{"as_of": f"2024-01-0{day}T00:00:00+00:00", "volatility": 0.2,
             "source": "declared:unverified"} for day in (2, 1)]
    payload["manifest"]["risk_estimates"] = {"fixture_rule": rows}
    payload["provenance"]["risk_estimates"] = {"fixture_rule": list(reversed(rows))}
    assert validate(seal(portfolio_input)) == portfolio_input


@pytest.mark.parametrize("sortino", [None, 0.0])
def test_undefined_and_measured_zero_ratios_are_not_conflated(portfolio_input, sortino):
    metrics = portfolio_input["portfolio_replay"]["metrics"]
    metrics.update(sharpe=0.0, sortino=sortino, max_drawdown=0.0, calmar=None)
    assert validate(seal(portfolio_input)) == portfolio_input


@pytest.mark.parametrize("location", ["config", "payload", "manifest", "provenance", "metrics",
    "costs", "replay", "limits", "sleeve", "identity", "bars", "source-metadata"])
def test_unknown_private_namespaces_refuse_even_with_matching_composite_hash(
    portfolio_input, location,
):
    payload = portfolio_input["portfolio_replay"]
    provenance = payload["provenance"]
    targets = {"config": portfolio_input, "payload": payload, "manifest": payload["manifest"],
        "provenance": provenance, "metrics": payload["metrics"],
        "costs": provenance["execution_costs"], "replay": provenance["replay"],
        "limits": provenance["replay"]["limits"],
        "sleeve": provenance["sleeve_configs"]["fixture_rule"],
        "identity": provenance["sleeve_identities"]["fixture_rule"],
        "bars": provenance["bars_provenance"],
        "source-metadata": provenance["bars_provenance"]["source_metadata"]}
    targets[location]["PRIVATE_DIAGNOSTIC"] = "DO_NOT_ECHO"
    seal(portfolio_input)
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(portfolio_input)


@pytest.mark.parametrize("field", ["path", "ok", "recorded_run", "sharpe_oos", "holdout",
                                  "window_metrics", "gate_verdict"])
def test_result_and_non_is_namespaces_are_never_admitted(portfolio_input, field):
    portfolio_input["portfolio_replay"][field] = {"DO_NOT_ECHO": 7}
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(seal(portfolio_input))


@pytest.mark.parametrize("fault", ["class", "forward", "seed", "snapshot", "period", "budgets",
    "execution", "constraints", "costs", "effective", "risk-authority", "strategies",
    "sleeve-config-hash", "runtime-code", "bars-digest", "work", "requested-work", "sessions",
    "method", "data-tier", "data-evidence", "limitations", "model", "metric-bool",
    "metric-infinite", "rebalance-bool", "sortino-infinite", "manifest-noncanonical"])
def test_inconsistent_or_unsupported_evidence_refuses_after_resealing(portfolio_input, fault):
    payload = portfolio_input["portfolio_replay"]
    provenance, manifest = payload["provenance"], payload["manifest"]
    if fault == "class":
        payload["evidence_class"] = "forward_test"
    elif fault == "forward":
        payload["is_forward_test"] = 0
    elif fault == "seed":
        provenance["seed"] = 0
    elif fault == "snapshot":
        provenance["snapshot_id"] = "e" * 16
    elif fault == "period":
        provenance["period"]["start"] = "2024-01-03T00:00:00+00:00"
    elif fault in ("budgets", "strategies"):
        provenance[fault]["fixture_rule"] = 0.6 if fault == "budgets" else "a" * 32
    elif fault in ("execution", "effective", "costs"):
        key = {"effective": "effective_replay_execution", "costs": "execution_costs"}.get(
            fault, fault)
        provenance[key]["fees"] = 0.02
    elif fault == "constraints":
        provenance["constraints"] = {**provenance["constraints"], "max_gross": 0.8}
    elif fault == "risk-authority":
        provenance["risk_estimate_authority"] = "verified"
    elif fault == "sleeve-config-hash":
        provenance["sleeve_configs"]["fixture_rule"]["params"]["changed"] = 1
    elif fault in ("runtime-code", "bars-digest"):
        provenance[{"runtime-code": "code_hash", "bars-digest": "bars_digest"}[fault]] = "bad"
    elif fault in ("work", "requested-work", "sessions", "method"):
        key = {"work": "work_units", "requested-work": "requested_work_units"}.get(fault, fault)
        provenance["replay"][key] = (
            True if fault == "sessions" else "bad" if fault == "method" else 1)
    elif fault == "data-tier":
        payload["data_tier"] = "verified_pit"
    elif fault == "data-evidence":
        payload["data_provenance"]["value"]["limitations"] = []
    elif fault == "limitations":
        payload["limitations"] = []
    elif fault == "model":
        provenance["sleeve_configs"]["fixture_rule"]["needs_model"] = True
    elif fault == "metric-bool":
        payload["metrics"]["total_return"] = True
    elif fault in ("metric-infinite", "sortino-infinite"):
        payload["metrics"]["sharpe" if fault == "metric-infinite" else "sortino"] = float("inf")
    elif fault == "rebalance-bool":
        payload["metrics"]["n_rebalances"] = True
    else:
        manifest["start"] = "2024-01-02T02:00:00+02:00"
    if fault not in ("metric-infinite", "sortino-infinite"):
        seal(portfolio_input)
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(portfolio_input)


@pytest.mark.parametrize("value", [None, [], {}, {"portfolio_replay": {}},
                                  {"portfolio_replay": "DO_NOT_ECHO"}])
def test_malformed_input_has_only_fixed_error(value):
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(value)


def test_declared_digest_mismatch_is_not_repaired(portfolio_input):
    payload = portfolio_input["portfolio_replay"]
    payload["portfolio_name"] = "portfolio-replay:" + "a" * 64
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(portfolio_input)
    seal(portfolio_input)
    payload["provenance"]["config_hash"] = "a" * 64
    with pytest.raises(ValueError, match="^portfolio_memory:invalid_input$"):
        validate(portfolio_input)
