"""Data-only nested validation for the current canonical portfolio replay producer."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any

from algua.contracts.strategy_identity import strategy_config_hash
from algua.contracts.types import CapacityLimit, ExecutionContract

EXECUTION = {"rebalance_frequency", "decision_lag_bars", "allow_fractional", "max_gross_exposure",
    "max_weight_per_symbol", "allow_short", "warmup_bars", "fees", "slippage", "capacity",
    "fill_price", "target_gross_utilization"}
CONFIG = {"name", "universe", "execution", "params", "construction", "construction_params",
    "overlays", "needs_fundamentals", "needs_news", "needs_model", "model_ref", "feature_lookback"}
BOOK = ("strategies", "budgets", "constraints", "execution", "initial_cash", "symbols",
        "risk_estimates")
PROVENANCE = {"data_source", "seed", "snapshot_id", "bars_provenance", "execution_costs",
    "code_hash", "dependency_hash", *BOOK, "config_hash", "bars_digest", "period", "replay",
    "sleeve_identities", "sleeve_configs", "risk_estimate_authority", "effective_replay_execution"}
LIMITS = {"sessions": 512, "symbols": 8, "sleeves": 8, "work_units": 2_000_000}


def require(condition: Any) -> None:
    if not condition:
        raise ValueError("invalid portfolio evidence")


def encoded(value: Any) -> bytes:
    """The producer's digest/numeric rendering; do not replace with compact archive JSON."""
    return json.dumps(value, sort_keys=True, allow_nan=False).encode()


def same(left: Any, right: Any) -> bool:
    return encoded(left) == encoded(right)


def exact(value: Any, fields: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == fields


def digest(value: Any, length: int, *, nullable: bool = False) -> bool:
    return value is None and nullable or (isinstance(value, str)
        and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None)


def number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def count(value: Any, maximum: int, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _execution(value: dict) -> ExecutionContract:
    require(exact(value, EXECUTION))
    fields = dict(value)
    if fields["capacity"] is not None:
        require(exact(fields["capacity"], {
            "reference_aum", "max_participation_rate", "adv_window_bars"}))
        fields["capacity"] = CapacityLimit(**fields["capacity"])
    execution = ExecutionContract(**fields)
    require(same(asdict(execution), value))
    return execution


@dataclass(frozen=True)
class _Overlay:
    """Only the dumped declaration consumed by the unchanged pure identity helper."""

    policy: str
    params: dict

    def model_dump(self) -> dict:
        return {"policy": self.policy, "params": self.params}


def _config(raw: dict, name: str) -> SimpleNamespace:
    require(exact(raw, CONFIG) and raw["name"] == name)
    require(isinstance(raw["universe"], list)
            and all(isinstance(symbol, str) for symbol in raw["universe"]))
    require(isinstance(raw["params"], dict) and isinstance(raw["construction"], str)
            and isinstance(raw["construction_params"], dict))
    lookback = raw["feature_lookback"]
    require(lookback is None or type(lookback) is int and lookback >= 0)
    require(all(raw[k] is False for k in ("needs_fundamentals", "needs_news", "needs_model"))
            and raw["model_ref"] is None)
    require(isinstance(raw["overlays"], list) and all(exact(o, {"policy", "params"})
        and isinstance(o["policy"], str) and isinstance(o["params"], dict)
        for o in raw["overlays"]))
    return SimpleNamespace(**(raw | {"execution": _execution(raw["execution"]),
        "overlays": [_Overlay(**o) for o in raw["overlays"]]}))


def _sleeves(manifest: dict, provenance: dict) -> int:
    names = {s["strategy"] for s in manifest["sleeves"]}
    for key in ("strategies", "budgets", "sleeve_configs", "sleeve_identities"):
        require(isinstance(provenance[key], dict) and set(provenance[key]) == names)
    sleeve_symbols = 0
    for name in names:
        raw = provenance["sleeve_configs"][name]
        config = _config(raw, name)
        execution = config.execution
        # These are the producer's supported timing checks, not stricter account limits.
        require(execution.decision_lag_bars == 1 and execution.fill_price ==
                manifest["execution"]["fill_price"]
                and execution.rebalance_frequency.lower() == "1d")
        require(set(config.universe) <= set(manifest["symbols"]))
        identity = provenance["sleeve_identities"][name]
        require(exact(identity, {"code_hash", "config_hash", "dependency_hash"})
                and digest(identity["code_hash"], 32) and digest(identity["config_hash"], 32)
                and digest(identity["dependency_hash"], 64, nullable=True))
        require(identity["config_hash"] == provenance["strategies"][name]
                == strategy_config_hash(config))
        sleeve_symbols += len(config.universe)
    return sleeve_symbols


def _replay(value: dict, manifest: dict, sleeve_symbols: int) -> None:
    require(exact(value, {"method", "scope", "sessions", "symbols", "sleeves", "work_units",
        "requested_sessions", "requested_work_units", "limits"}))
    require(value["method"] == "canonical_engine_prefix" and value["scope"] == "research_only"
            and same(value["limits"], LIMITS))
    for key in ("sessions", "requested_sessions"):
        require(count(value[key], 512, 1))
    require(count(value["symbols"], 8, 1) and value["symbols"] == len(manifest["symbols"])
            and count(value["sleeves"], 8) and value["sleeves"] == len(manifest["sleeves"])
            and value["sessions"] <= value["requested_sessions"])
    for sessions, work in (("sessions", "work_units"),
                           ("requested_sessions", "requested_work_units")):
        n, symbols = value[sessions], value["symbols"]
        expected = (symbols + sleeve_symbols) * n * (n + 1) // 2 + symbols * n
        require(count(value[work], 2_000_000, 1) and value[work] == expected)


def validate_provenance(manifest: dict, value: dict) -> None:
    require(exact(value, PROVENANCE))
    require(value["data_source"] == "StoreBackedProvider"
            and same(value["seed"], manifest["seed"])
            and value["snapshot_id"] == manifest["snapshot_id"])
    require(value["code_hash"] is None or isinstance(value["code_hash"], str)
            and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})(?:-dirty-[0-9a-f]{16})?",
                             value["code_hash"]) is not None)
    require(digest(value["dependency_hash"], 64, nullable=True)
            and digest(value["bars_digest"], 64) and digest(value["config_hash"], 64))
    for key in ("constraints", "execution", "initial_cash", "symbols"):
        require(same(value[key], manifest[key]))
    require(same(value["period"], {k: manifest[k] for k in ("start", "end")}))
    require(same(value["budgets"], {s["strategy"]: s["budget"] for s in manifest["sleeves"]}))
    risk = {name: sorted(rows, key=lambda r: (r["as_of"], r["volatility"], r["source"]))
            for name, rows in manifest["risk_estimates"].items()}
    require(same(value["risk_estimates"], risk)
            and value["risk_estimate_authority"] == "unverified_research_assumptions")
    require(same(value["effective_replay_execution"], manifest["execution"] | {
        "warmup_bars": 0, "target_gross_utilization": 1.0, "capacity": None}))
    require(same(value["execution_costs"], {
        "schema_version": "execution-costs/v1", "model": "vectorbt.from_orders",
        "fees": manifest["execution"]["fees"],
        "fees_unit": "fraction_of_trade_notional_per_side",
        "slippage": manifest["execution"]["slippage"],
        "slippage_unit": "adverse_fill_price_fraction_per_side"}))
    _replay(value["replay"], manifest, _sleeves(manifest, value))


def validate_metrics(value: dict, manifest: dict, provenance: dict) -> None:
    ratios = {"sharpe", "sortino", "calmar"}
    fields = {"total_return", "cagr", "ann_volatility", *ratios, "max_drawdown", "hit_rate",
        "tail_ratio", "turnover", "avg_gross_exposure", "n_rebalances",
        "cost_fees", "cost_slippage"}
    require(exact(value, fields))
    require(all(number(v) or k in ratios and v is None for k, v in value.items()
                if k != "n_rebalances"))
    require(count(value["n_rebalances"], provenance["replay"]["sessions"]))
    require(same(value["cost_fees"], manifest["execution"]["fees"])
            and same(value["cost_slippage"], manifest["execution"]["slippage"]))
    if value["ann_volatility"] == 0:
        require(value["sharpe"] is None and value["sortino"] is None)
    else:
        require(value["sharpe"] is not None)
    if value["max_drawdown"] == 0:
        require(value["calmar"] is None)
    else:
        require(value["calmar"] is not None)
