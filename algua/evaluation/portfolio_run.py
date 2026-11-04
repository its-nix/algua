"""Strict, research-only CLI composition of the bounded canonical account replay.

Composite results use the existing economic run ledger under a reserved, content-derived name.
They never acquire a strategy ID, lifecycle state, gate verdict or trading permission.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pandas as pd

from algua.backtest.metrics import portfolio_metrics
from algua.backtest.portfolio import PortfolioSimulation, simulate_portfolio
from algua.backtest.result import BacktestResult
from algua.config.settings import get_settings
from algua.contracts.types import ExecutionContract
from algua.data.serve import StoreBackedProvider
from algua.data.store import DataStore
from algua.evaluation.portfolio_manifest import MAX_MANIFEST_BYTES as MAX_MANIFEST_BYTES
from algua.evaluation.portfolio_manifest import (
    _aware,
    _constant,
    _Manifest,
    _pairs,
)
from algua.portfolio.allocator import PortfolioConstraints, RiskEstimate
from algua.provenance.snapshot_evidence import project_snapshot_record
from algua.registry.approvals import compute_artifact_hashes
from algua.registry.db import registry_conn
from algua.registry.runs import backtest_metrics
from algua.registry.store import SqliteStrategyRepository
from algua.strategies.base import config_hash
from algua.strategies.loader import load_strategy


def read_manifest(path: Path) -> _Manifest:
    with path.open("rb") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError(f"portfolio manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    return _Manifest.model_validate(json.loads(
        raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant,
    ))


def _weights(row: pd.Series) -> dict[str, float]:
    return {str(symbol): float(value) for symbol, value in row.items() if value != 0}


def _path(simulation: PortfolioSimulation) -> list[dict[str, Any]]:
    returns = simulation.portfolio.returns()
    equity, cash = simulation.portfolio.value(), simulation.portfolio.cash()
    return [{
        "date": timestamp.isoformat(), "return": float(returns.loc[timestamp]),
        "equity": float(equity.loc[timestamp]), "cash": float(cash.loc[timestamp]),
        "decision_weights": _weights(simulation.decision_weights.loc[timestamp]),
        "current_weights": _weights(simulation.current_weights.loc[timestamp]),
        "executed_weights": _weights(simulation.executed_weights.loc[timestamp]),
    } for timestamp in simulation.decision_weights.index]


def run_portfolio_replay(manifest_path: Path) -> dict[str, Any]:
    """Validate first, replay pinned inputs, then record one in-sample composite evaluation."""
    request = read_manifest(manifest_path)
    execution = ExecutionContract(**request.execution.model_dump())
    constraints = PortfolioConstraints(**request.constraints.model_dump())
    # Imports can expand a shared package's discovered closure. Finish the declared request's
    # ordinary imports before capturing identities; fresh loading must still preserve them.
    for sleeve in request.sleeves:
        load_strategy(sleeve.strategy)
    identities = {s.strategy: compute_artifact_hashes(s.strategy) for s in request.sleeves}
    strategies = {s.strategy: load_strategy(s.strategy, reload=True) for s in request.sleeves}
    for name, strategy in strategies.items():
        if identities[name].config_hash != config_hash(strategy):
            raise ValueError(f"{name}: loaded strategy config differs from captured identity")
    if any(compute_artifact_hashes(name) != identity for name, identity in identities.items()):
        raise ValueError("portfolio sleeve identity changed during loading; result not evaluated")
    configs = {name: strategy.config.model_dump(mode="json")
               for name, strategy in strategies.items()}
    risk = {name: tuple(RiskEstimate(_aware(r.as_of), r.volatility, r.source) for r in estimates)
            for name, estimates in request.risk_estimates.items()}
    simulation = simulate_portfolio(
        strategies, {s.strategy: s.budget for s in request.sleeves}, constraints,
        StoreBackedProvider(DataStore(get_settings().data_dir), request.snapshot_id),
        _aware(request.start), _aware(request.end), execution=execution,
        initial_cash=request.initial_cash, symbols=request.symbols,
        risk_estimates=risk, seed=request.seed,
    )
    if any(compute_artifact_hashes(name) != identity for name, identity in identities.items()):
        raise ValueError("portfolio sleeve identity changed during replay; result not recorded")
    provenance = simulation.provenance | {
        "sleeve_identities": {name: identity._asdict() for name, identity in identities.items()},
        "sleeve_configs": configs, "risk_estimate_authority": "unverified_research_assumptions",
        "effective_replay_execution": asdict(replace(
            execution, warmup_bars=0, target_gross_utilization=1.0, capacity=None,
        )),
    }
    manifest = request.model_dump()
    identity_bytes = json.dumps({"manifest": manifest, "provenance": provenance},
                               sort_keys=True, allow_nan=False).encode()
    name = "portfolio-replay:" + hashlib.sha256(identity_bytes).hexdigest()
    metrics = portfolio_metrics(simulation.portfolio, simulation.executed_weights,
                                fees=execution.fees, slippage=execution.slippage)
    result = BacktestResult(
        strategy=name, metrics=metrics, config_hash=provenance["config_hash"],
        data_source=provenance["data_source"], timeframe="1d", period=provenance["period"],
        returns=simulation.portfolio.returns(),
    )
    display: dict[str, float | None] = dict(metrics)
    if metrics["ann_volatility"] == 0:
        display.update(sharpe=None, sortino=None)
    if metrics["max_drawdown"] == 0:
        display["calmar"] = None
    downside_moment = float(simulation.portfolio.returns().dropna().clip(upper=0).pow(2).mean())
    if not downside_moment > 0:
        display["sortino"] = None
    ledger_metrics = backtest_metrics(result)
    ledger_metrics["sortino_is"] = display["sortino"]
    source = provenance["bars_provenance"]
    evidence: dict[str, Any] = (
        project_snapshot_record(request.snapshot_id, source) if source is not None
        else {"status": "UNAVAILABLE", "reason": "provenance_absent", "value": None})
    source_value: dict[str, Any] | None = evidence["value"]
    payload = {
        "schema_version": "portfolio-replay-result/v1", "portfolio_name": name,
        "evidence_class": "in_sample_research_replay", "is_forward_test": False,
        "data_tier": source_value["data_tier"] if source_value is not None else "unknown",
        "data_provenance": evidence,
        "limitations": ["static_universe_not_verified_pit", "no_delisting_records",
                        "no_promotion_or_trading_authority", "replay_not_elapsed_forward_test"]
                        + (source_value["limitations"] if source_value is not None
                           else ["data_provenance_unavailable"]),
        "manifest": manifest, "provenance": provenance, "metrics": display,
        "path": _path(simulation),
    }
    json.dumps(payload, allow_nan=False)  # Refuse non-finite output before opening the registry.
    with registry_conn() as conn:
        run_id = SqliteStrategyRepository(conn).record_run(
            "backtest", name, strategy_id=None,
            provenance={k: provenance[k] for k in (
                "code_hash", "config_hash", "dependency_hash", "data_source", "snapshot_id", "seed",
            )} | {"timeframe": "1d", "period_start": request.start, "period_end": request.end},
            config={"portfolio_replay": {k: v for k, v in payload.items() if k != "path"}},
            metrics=ledger_metrics,
        )
    return payload | {"recorded_run": {"run_id": run_id, "kind": "backtest", "strategy_id": None}}
