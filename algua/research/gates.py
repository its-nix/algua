"""Promotion gate (backtested -> candidate) composer (#335 extraction).

GATE PHILOSOPHY — this gate is an INTEGRITY FLOOR, not a statistical exam. Only the correctness
checks BIND: ``min_holdout_observations`` (the 63-bar power floor), ``pit_required`` (Wall B) and
``holdout_sharpe_floor`` (raw holdout Sharpe > 0). Everything statistical is RECORDED on its check
(``"advisory": true``) and never vetoes ``passed``: ``holdout_sharpe`` (against the base
``min_holdout_sharpe``), ``holdout_return``, and the one trial-aware quality signal, DSR
(``dsr_evidence``) plus its serial-dependence bootstrap (``dsr_bootstrap``), whose trial count is
``max(own lifetime combos, funnel-wide windowed combos)`` (spec 2026-11-12 §4.7). Making DSR
binding is a separate owner decision. Lean trim step 7 removed the breadth haircut, window
stability, regime robustness, the idiosyncratic-alpha screen and the FDR ledger.

The recorded holdout Sharpe (the ``holdout_sharpe`` check's VALUE) parameterizes the strict
forward bar (``paper promote``: Sharpe >= max(0.5x holdout, 0.3) over 63 broker-clocked
observations), so an overfit-inflated holdout self-punishes there.

The pure maths ``evaluate_gate`` composes lives in sibling modules:

- ``algua.research.dsr``        — DSR SR*/confidence, dispersion floor, the trial count.
- ``algua.research._constants`` — the shared holdout-power floor (MIN_HOLDOUT_OBSERVATIONS).

This module keeps the gate-orchestration surface: ``GateCriteria``, ``GateDecision``, the
declarative ``GateSpec``/``GATE_SPECS``, the orchestration-level constants, and ``evaluate_gate``.
``GateDecision.to_dict()`` delegates to ``algua.research.gate_serialization.gate_decision_to_dict``.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from algua.backtest._constants import ANN
from algua.backtest.walkforward import WalkForwardResult
from algua.research._constants import MIN_HOLDOUT_OBSERVATIONS
from algua.research.dsr import DSR_ALPHA, dsr_confidence
from algua.research.gate_serialization import gate_decision_to_dict

__all__ = [
    "FUNNEL_WINDOW_DAYS",
    "GATE_SPECS",
    "GateCriteria",
    "GateDecision",
    "GateSpec",
    "evaluate_gate",
]

# Funnel-level multiple-testing window (Wall A). Protected constant, not an agent-tunable knob
# (relaxing it would weaken the gate). Rolling window keeps the bar bounded; the wait-out-the-window
# trade-off is accepted and auditable via search_trials.created_at.
FUNNEL_WINDOW_DAYS = 90

@dataclass
class GateCriteria:
    """Thresholds for promoting backtested -> candidate. Holdout checks are the search-breadth
    defense (the holdout was never used during selection)."""

    min_holdout_sharpe: float = 0.5
    min_holdout_return: float = 0.0       # strict > 0
    min_holdout_observations: int = MIN_HOLDOUT_OBSERVATIONS  # Wall C: power floor, fails closed


@dataclass
class GateDecision:
    passed: bool
    checks: list[dict[str, Any]]
    n_combos: int | None = None
    breadth_provenance: str | None = None
    base_min_holdout_sharpe: float | None = None
    own_lifetime_combos: int | None = None
    windowed_total_combos: int | None = None
    funnel_window_days: int | None = None
    pit_ok: bool | None = None
    pit_override: bool = False
    dsr_binding: bool = False
    dsr_confidence: float | None = None
    dsr_skip_reason: str | None = None
    dsr_n_trials: int | None = None
    dsr_trial_sr_var_ann: float | None = None
    dsr_t: int | None = None
    dsr_skew: float | None = None
    dsr_raw_kurtosis: float | None = None
    # Funnel-wide dispersion floor audit (#221, Phase 3 Slice 0). Populated when dsr_binding.
    dsr_funnel_floor_var_ann: float | None = None
    dsr_funnel_floor_n_strategies: int | None = None
    dsr_funnel_floor_n_total_rows: int | None = None
    # Returns-persistence audit (#221 Slice 1). Non-binding: True iff run_gate wrote a
    # holdout_returns row for this evaluation. False for pre-Slice-1 promotions (omit-not-fail).
    returns_available: bool = False
    # Serial-dependence bootstrap audit (#221 Slice 2). ARMED/EVALUATED (the check is computed +
    # appended, advisory — veto power removed) only when dsr_binding AND bootstrap_binding are both
    # True (gates computes effective_bootstrap_binding = dsr_binding AND bootstrap_binding). The
    # caller (promotion.py) sets bootstrap_binding only when measured breadth AND the OOS vector is
    # present. Not armed: all dsr_bootstrap_* fields remain False/None (omit-not-fail).
    dsr_bootstrap_binding: bool = False
    dsr_bootstrap_lower: float | None = None
    dsr_bootstrap_seed: int | None = None
    dsr_bootstrap_b: int | None = None
    dsr_bootstrap_block_len: int | None = None
    # Effective independent trials audit (#221 Slice 3). SHADOW-ONLY: recorded, never fed into the
    # binding dsr_confidence (which keeps n_trials = raw N). Populated by promotion.run_gate.
    dsr_n_eff: int | None = None
    dsr_rho_bar: float | None = None
    dsr_n_siblings: int | None = None
    def to_dict(self) -> dict[str, Any]:
        return gate_decision_to_dict(self)


_OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": lambda v, t: v >= t,
    ">": lambda v, t: v > t,
}


@dataclass(frozen=True)
class GateSpec:
    """Declarative description of one gate check (#40).

    Adding a gate is appending a spec here — no edits to the evaluation loop. `source` and
    `metric_key` locate the value on the WalkForwardResult; `threshold_attr` names the
    GateCriteria field; `op` is the comparison operator. `advisory` checks are computed and
    recorded exactly like binding ones but carry ``"advisory": true`` and never veto ``passed``
    (the factory soft gate — only the integrity floor binds).
    """

    name: str
    source: str  # "holdout" -> wf.holdout_metrics
    metric_key: str
    threshold_attr: str
    op: str
    advisory: bool = False


GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec("holdout_sharpe", "holdout", "sharpe", "min_holdout_sharpe", ">=", advisory=True),
    GateSpec("holdout_return", "holdout", "total_return", "min_holdout_return", ">",
             advisory=True),
    GateSpec("min_holdout_observations", "holdout", "n_bars", "min_holdout_observations", ">="),
)


def evaluate_gate(
    wf: WalkForwardResult,
    criteria: GateCriteria,
    *,
    n_combos: int | None = None,
    breadth_provenance: str | None = None,
    pit_ok: bool,
    own_lifetime_combos: int | None = None,
    windowed_total_combos: int | None = None,
    funnel_window_days: int | None = None,
    dsr_binding: bool = False,
    dsr_trial_var_ann: float | None = None,
    dsr_funnel_floor_var_ann: float | None = None,
    dsr_funnel_floor_n_strategies: int | None = None,
    dsr_funnel_floor_n_total_rows: int | None = None,
    bootstrap_binding: bool = False,
    bootstrap_lower_confidence: float | None = None,
    bootstrap_seed: int | None = None,
    bootstrap_b: int | None = None,
    bootstrap_block_len: int | None = None,
) -> GateDecision:
    """Judge a walk-forward result against the gate criteria. Pure; no side effects.

    Driven by GATE_SPECS so the metric dict and the gate stay in sync without hand editing.

    Factory soft gate: ``passed`` composes ONLY the binding integrity-floor checks
    (``min_holdout_observations``, ``holdout_sharpe_floor``, ``pit_required``). Every statistical
    check is computed and recorded, marked ``"advisory": true``, and never vetoes. The
    (advisory) ``holdout_sharpe`` check's threshold is the base ``criteria.min_holdout_sharpe``;
    the trial-aware multiple-testing signal is DSR (``dsr_evidence`` + ``dsr_bootstrap``), whose
    trial count is ``n_combos`` (lean trim step 7 removed the breadth haircut on this bar).
    ``breadth_provenance`` ("measured"/"declared") is carried into
    the decision for the audit trail; it does not change the math. The ``holdout_sharpe`` check's
    VALUE is read by name by the forward gate (``qualified_holdout_sharpe``) to parameterize the
    forward bar — its name/value/threshold semantics are a stable contract.
    """
    sources = {"holdout": wf.holdout_metrics}
    base_holdout_sharpe = float(criteria.min_holdout_sharpe)

    checks: list[dict[str, Any]] = []
    for spec in GATE_SPECS:
        value = float(sources[spec.source][spec.metric_key])
        threshold = float(getattr(criteria, spec.threshold_attr))
        # A non-finite metric (inf trivially clears >=/>, NaN is never a real result) is a
        # gate failure, never a pass — and is never recorded as a NaN/inf in the payload.
        if not math.isfinite(value):
            check: dict[str, Any] = {"name": spec.name, "value": None, "threshold": threshold,
                                     "op": spec.op, "passed": False}
        else:
            check = {"name": spec.name, "value": value, "threshold": threshold,
                     "op": spec.op, "passed": bool(_OPS[spec.op](value, threshold))}
        if spec.advisory:
            check["advisory"] = True
        checks.append(check)
    # Integrity floor (factory soft gate): the RAW holdout Sharpe must be strictly positive — a
    # correctness screen (a strategy that lost money out-of-sample has no business in the paper
    # book), NOT a statistical bar (the holdout_sharpe check above is advisory).
    # Same value the holdout_sharpe check scores; fixed threshold 0.0, no criteria knob, no actor
    # split. A non-finite value FAILS CLOSED and is nulled out of the payload (same convention as
    # the spec loop above).
    raw_holdout_sharpe = float(wf.holdout_metrics["sharpe"])
    if not math.isfinite(raw_holdout_sharpe):
        checks.append({"name": "holdout_sharpe_floor", "value": None, "threshold": 0.0,
                       "op": ">", "passed": False})
    else:
        checks.append({"name": "holdout_sharpe_floor", "value": raw_holdout_sharpe,
                       "threshold": 0.0, "op": ">",
                       "passed": bool(raw_holdout_sharpe > 0.0)})
    # PIT precondition (Wall B): boolean, not a metric comparison. pit_ok is computed by the
    # protected promotion orchestrator (presence + coverage). Non-PIT fails closed for every actor:
    # there is no override (spec 2026-11-13). `pit_override` stays in the decision as False so the
    # recorded schema is unchanged.
    pit_passed = bool(pit_ok)
    pit_override = False
    checks.append({"name": "pit_required", "passed": pit_passed,
                   "pit_ok": bool(pit_ok), "override": None})
    # DSR evidence (#211): an ADVISORY check, appended ONLY when armed (measured trial dispersion
    # is available). When not armed it is omitted entirely (omit-not-fail).
    # Unit conversion lives here: holdout Sharpe and trial variance are ANNUALIZED; DSR per-period.
    dsr_conf: float | None = None
    dsr_skip_reason: str | None = None
    n_for_dsr = n_combos if n_combos is not None else 1
    t_hold = int(wf.holdout_metrics["n_bars"])
    skew = float(wf.holdout_metrics.get("skewness", 0.0))
    raw_kurt = float(wf.holdout_metrics.get("kurtosis", 3.0))
    sr_obs_ann = float(wf.holdout_metrics["sharpe"])
    # The bootstrap check is only armed when BOTH dsr_binding AND bootstrap_binding are True.
    # The caller (promotion.py) sets bootstrap_binding only when measured breadth AND the OOS
    # vector is present; gates binds on dsr_binding AND bootstrap_binding.
    # Using effective_bootstrap_binding throughout keeps the audit state self-consistent: if
    # dsr_binding=False the bootstrap check is never appended and all bootstrap audit fields
    # remain None/False, regardless of what the caller passed for bootstrap_binding.
    effective_bootstrap_binding = bool(dsr_binding and bootstrap_binding)
    if dsr_binding:
        var_pp = (dsr_trial_var_ann / ANN) if dsr_trial_var_ann is not None else None
        floor_pp = (
            dsr_funnel_floor_var_ann / ANN
            if dsr_funnel_floor_var_ann is not None and math.isfinite(dsr_funnel_floor_var_ann)
            else None
        )
        if var_pp is not None and math.isfinite(var_pp):
            dsr_conf = dsr_confidence(
                sr_obs_ann / math.sqrt(ANN), t_hold, skew, raw_kurt, n_for_dsr, var_pp,
                funnel_floor_var_per_period=floor_pp)
        passed_dsr = dsr_conf is not None and dsr_conf >= (1.0 - DSR_ALPHA)
        dsr_value = dsr_conf if (dsr_conf is not None and math.isfinite(dsr_conf)) else None
        checks.append({"name": "dsr_evidence", "value": dsr_value,
                       "threshold": 1.0 - DSR_ALPHA, "op": ">=", "passed": bool(passed_dsr),
                       "advisory": True})
        if dsr_conf is None:
            # measured sweep exists but stats missing -> recorded as a failed advisory check
            dsr_skip_reason = "no_dispersion"
        if effective_bootstrap_binding:
            boot_pass = (bootstrap_lower_confidence is not None
                         and bootstrap_lower_confidence >= (1.0 - DSR_ALPHA))
            boot_value = (bootstrap_lower_confidence
                          if (bootstrap_lower_confidence is not None
                              and math.isfinite(bootstrap_lower_confidence)) else None)
            checks.append({"name": "dsr_bootstrap", "value": boot_value,
                           "threshold": 1.0 - DSR_ALPHA, "op": ">=", "passed": bool(boot_pass),
                           "advisory": True})
    else:
        dsr_skip_reason = "no_measured_dispersion"

    return GateDecision(
        # Factory soft gate: only BINDING checks (no "advisory" marker — the integrity floor:
        # min_holdout_observations, holdout_sharpe_floor, pit_required) compose `passed`.
        # Advisory checks are recorded verbatim but never veto.
        passed=all(c["passed"] for c in checks if not c.get("advisory")),
        checks=checks,
        n_combos=n_combos,
        breadth_provenance=breadth_provenance,
        base_min_holdout_sharpe=base_holdout_sharpe,
        own_lifetime_combos=own_lifetime_combos,
        windowed_total_combos=windowed_total_combos,
        funnel_window_days=funnel_window_days,
        pit_ok=bool(pit_ok),
        pit_override=pit_override,
        dsr_binding=bool(dsr_binding),
        dsr_confidence=dsr_conf,
        dsr_skip_reason=dsr_skip_reason,
        dsr_n_trials=(n_for_dsr if dsr_binding else None),
        dsr_trial_sr_var_ann=(dsr_trial_var_ann if dsr_binding else None),
        dsr_t=(t_hold if dsr_binding else None),
        dsr_skew=(skew if dsr_binding else None),
        dsr_raw_kurtosis=(raw_kurt if dsr_binding else None),
        dsr_funnel_floor_var_ann=(dsr_funnel_floor_var_ann if dsr_binding else None),
        dsr_funnel_floor_n_strategies=(dsr_funnel_floor_n_strategies if dsr_binding else None),
        dsr_funnel_floor_n_total_rows=(dsr_funnel_floor_n_total_rows if dsr_binding else None),
        dsr_bootstrap_binding=effective_bootstrap_binding,
        dsr_bootstrap_lower=(bootstrap_lower_confidence if effective_bootstrap_binding else None),
        dsr_bootstrap_seed=(bootstrap_seed if effective_bootstrap_binding else None),
        dsr_bootstrap_b=(bootstrap_b if effective_bootstrap_binding else None),
        dsr_bootstrap_block_len=(bootstrap_block_len if effective_bootstrap_binding else None),
    )
