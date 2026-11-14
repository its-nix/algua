from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime

from algua.backtest.bootstrap import stable_bootstrap_seed, stationary_bootstrap_dsr
from algua.backtest.decision_path import verify_signal_panel_parity
from algua.backtest.neff import estimate_n_eff
from algua.backtest.walkforward import WalkForwardResult
from algua.contracts.lifecycle import Actor, Stage, TransitionError, validate_transition
from algua.contracts.types import DataProvider, assert_gated_costs
from algua.registry.approvals import compute_artifact_hashes
from algua.registry.gate_comparison_record import capture_gate_comparison
from algua.registry.repository import FunnelSnapshot, StrategyRepository
from algua.registry.runs import provenance_of, record_walk_forward_run, walk_forward_metrics
from algua.research.dsr import (
    DSR_ALPHA,
    DSR_BOOTSTRAP_LOWER_QUANTILE,
    DSR_BOOTSTRAP_RESAMPLES,
    MIN_CORR_OVERLAP_BARS,
    MIN_N_EFF_SIBLINGS,
    RHO_BAR_SHRINKAGE_K,
    dsr_sr_star_annualized,
    effective_funnel_breadth,
)
from algua.research.gates import FUNNEL_WINDOW_DAYS, GateCriteria, GateDecision, evaluate_gate
from algua.strategies.loader import StrategyNotFound, load_strategy


def resolve_pit_ok(
    universe_name: str | None,
    universe_snapshots: list[dict[str, str]] | None,
    period_start: date,
) -> bool:
    """Wall B: PIT-valid iff a universe was used AND its earliest membership snapshot is effective
    on or before the backtest start (coverage, not mere presence)."""
    if universe_name is None or not universe_snapshots:
        return False
    # Fail closed: a malformed/missing effective_date means we CANNOT prove PIT coverage, so treat
    # it as non-PIT (not promotable) rather than raising after the holdout has been recorded.
    try:
        earliest = min(date.fromisoformat(s["effective_date"]) for s in universe_snapshots)
    except (KeyError, ValueError, TypeError):
        return False
    return earliest <= period_start


@dataclass
class BreadthContext:
    n_funnel: int
    own: int
    windowed_total: int
    provenance: str


def promotion_preflight(
    repo: StrategyRepository,
    name: str,
    *,
    actor: Actor,
    provider: DataProvider,
    start: datetime,
    end: datetime,
    universe_name: str | None = None,
    universe_by_date: Mapping[date, Collection[str]] | None = None,
) -> BreadthContext:
    """Pre-peek phase — runs BEFORE walk_forward, so every hard refusal happens before the holdout
    is touched and before any gate row is minted: (1) actor legality; (2) reproducible source;
    (3) stage legality (BACKTESTED -> CANDIDATE must be legal — never mint a passing token for an
    illegal source stage); (4) cost floor; (5) exhaustive signal_panel parity gate (raises
    BacktestError on divergence, no-op when no signal_panel); (6) declared feature_lookback;
    (7) breadth resolution (refuse "no measured breadth" here); (8) gated-universe subset.

    ``actor`` is an audit label: every wall applies to every actor. There is no human override
    (spec 2026-11-13 — the signed go-live is the only approval)."""
    # FIRST check, before any holdout-affecting work: only an agent or a human may promote. SYSTEM
    # is not a valid promote actor — it would burn the holdout and mint a gate_evaluations row it
    # can NEVER consume (consumable rows are filtered actor='agent'), leaving an orphaned token.
    if actor not in (Actor.AGENT, Actor.HUMAN):
        raise ValueError(
            f"research promote requires --actor agent or human, got {actor.value}")
    # Reproducible-source guard (#205): a holdout burn must be over reproducible bars — an
    # immutable snapshot (snapshot_id set) or a deterministic provider (reproducible marker) — so
    # the OOS truth it spends is identical on a re-run. Refuse a non-snapshot, non-reproducible
    # provider BEFORE any provider read (verify_signal_panel_parity below reads bars).
    # select_provider exposes only demo/snapshot today; this fail-closes a future mutable/live
    # provider. Duck-typed getattr avoids a registry->data import-boundary violation; `is not True`
    # (not just falsy) so a future provider with a truthy-but-not-True `reproducible` cannot slip
    # the guard (fail closed).
    if (getattr(provider, "snapshot_id", None) is None
            and getattr(provider, "reproducible", False) is not True):
        raise ValueError(
            "research promote requires a reproducible data source: an ingested snapshot "
            "(--snapshot) or a deterministic provider. A non-reproducible/live provider's bars may "
            "revise between runs.")
    rec = repo.get(name)
    # Source stage MUST be exactly BACKTESTED. validate_transition alone is too permissive here:
    # PAPER -> CANDIDATE is a legal back-step, so promoting from `paper` would otherwise pass
    # preflight, burn the holdout, and mint a token. Require backtested explicitly, then validate.
    if rec.stage is not Stage.BACKTESTED:
        raise TransitionError(
            f"research promote requires stage backtested, got {rec.stage.value}")
    validate_transition(rec.stage, Stage.CANDIDATE)  # TransitionError (a ValueError) if illegal
    # Load the strategy module for parity-check and breadth resolution below.
    # Silently skip if the strategy is not a bundled module (e.g. tests using synthetic names).
    try:
        _loaded = load_strategy(name)
    except StrategyNotFound:
        _loaded = None
    # Transaction-cost floor (#325): a promote may only gate a backtest evaluated at a realistic
    # transaction cost. The whole statistical stack (Sharpe/DSR/bootstrap) is calibrated
    # on the return stream this promote will peek; if that stream were (near-)cost-free, a strategy
    # whose only edge is a cost illusion could clear every gate. assert_gated_costs fails closed on
    # a sub-floor fees+slippage BEFORE the holdout is touched, so a frictionless config can't mint
    # a gate token. Applies to every actor.
    if _loaded is not None:
        assert_gated_costs(_loaded.execution)
    # Exhaustive signal_panel parity gate (#178): a panel that diverges from its per-bar signal on
    # ANY bar cannot pass promotion. Runs on the already-loaded strategy, in static mode over the
    # promotion window, BEFORE the holdout is touched. No-op when the strategy has no signal_panel.
    # Raises BacktestError on divergence (caught by the `promote` CLI's @json_errors).
    if _loaded is not None:
        verify_signal_panel_parity(_loaded, provider, start, end)
    # Walk-forward embargo declaration (#345): the holdout is gated on a purge gap sized by
    # the strategy's declared feature lookback. An UNDECLARED lookback (feature_lookback is None)
    # resolves the embargo to 0 (legacy zero-gap, see _resolve_embargo), leaving a real
    # ~60-bar-lookback signal with NO purge and re-opening the leak on the gate-bearing path. Fail
    # closed:
    # the strategy must declare feature_lookback (it may declare 0 for a strategy with no rolling
    # feature window). Only enforceable for a bundled module (load_strategy resolved);
    # synthetic-name test strategies are left as-is, matching the parity gate above.
    if _loaded is not None and _loaded.config.feature_lookback is None:
        raise ValueError(
            f"research promote requires {name!r} to declare feature_lookback (the bars of "
            f"trailing history its signal reads) so the walk-forward embargo can purge the "
            f"in-sample/holdout boundary (#345). Declare it on the strategy CONFIG (0 if the "
            f"signal has no rolling feature window).")
    windowed_total = repo.windowed_search_combos(FUNNEL_WINDOW_DAYS)
    measured = repo.total_search_combos(name)
    if measured <= 0:
        raise ValueError(
            f"no recorded search breadth for {name!r}; run `algua backtest sweep {name} ...` "
            f"(records breadth). Breadth is always measured; it cannot be declared."
        )
    own, provenance = measured, "measured"
    # Gated-universe subset guard (#559): a promote on a PIT universe fails closed — still
    # BEFORE the holdout is touched and before any gate row is minted — when the loaded strategy's
    # CONFIG.universe contains a symbol that was NEVER a member of the gated universe's membership
    # timeline (the union over the same universe_by_date map the PIT walk-forward consumes). The
    # module's universe is agent-authored and can silently diverge from the universe the evidence
    # was produced on (e.g. a 5-symbol template incl. NVDA gated on liquid10); at deployment the
    # tick binds to the GATE universe, so a config symbol outside it was never validated at all.
    # Applies to every actor. Placed AFTER the structural refusals above so the established refusal
    # precedence (stage, costs, parity, lookback, breadth) is unchanged.
    if _loaded is not None and universe_by_date:
        gated_members: set[str] = set().union(*universe_by_date.values())
        offending = sorted(set(_loaded.config.universe) - gated_members)
        if offending:
            raise ValueError(
                f"strategy {name!r} CONFIG.universe contains symbols that were never members of "
                f"the gated universe {universe_name!r}: {offending}. The paper deployment is "
                f"bound to the gated universe (#559) — fix CONFIG.universe or gate on a universe "
                f"that covers it."
            )
    return BreadthContext(effective_funnel_breadth(own, windowed_total), own, windowed_total,
                          provenance)


@dataclass
class PromotionOutcome:
    decision: GateDecision
    promoted: bool


def run_gate(
    repo: StrategyRepository,
    wf: WalkForwardResult,
    *,
    name: str,
    actor: Actor,
    criteria: GateCriteria,
    breadth: BreadthContext,
    universe_name: str | None,
    universe_snapshots: list[dict[str, str]] | None,
    period_start: date,
    period_end: date,
    holdout_frac: float,
    data_source: str,
    snapshot_id: str | None,
    holdout_evaluation_id: int | None = None,
    attempt_token: str | None = None,
    comparison_inputs: dict[str, bool | None] | None = None,
) -> PromotionOutcome:
    """Post-walk phase: resolve PIT, evaluate, record the gate_evaluations row (pass AND fail), and
    on pass transition BACKTESTED->CANDIDATE (which consumes the just-minted agent token).
    Identity is recomputed via compute_artifact_hashes(name) — the SAME function the shortlist gate
    matches against (NOT wf.code_hash, which is git-HEAD-based and would never match)."""
    pit_ok = resolve_pit_ok(universe_name, universe_snapshots, period_start)
    holdout_n_bars = int(wf.holdout_metrics["n_bars"])
    # The DSR trial count (spec 2026-11-12 §4.7): max(own lifetime combos, funnel-wide windowed
    # combos), both exactly as preflight read them. The #339 funnel CAS below re-verifies them
    # under the write lock.
    n_funnel = effective_funnel_breadth(breadth.own, breadth.windowed_total)
    # DSR evidence (#211): armed/evaluated iff breadth is MEASURED (the advisory dsr_evidence
    # check is appended only then). Declared breadth (human, no sweep) omits DSR entirely.
    dsr_binding = breadth.provenance == "measured"
    dsr_trial_var_ann = repo.pooled_trial_sharpe_var(name) if dsr_binding else None
    funnel_floor = repo.funnel_trial_sharpe_var(FUNNEL_WINDOW_DAYS) if dsr_binding else None
    # Serial-dependence bootstrap (#221 Slice 2): bind iff measured AND the in-process OOS vector
    # is present. Recompute DSR confidence against the SAME floored SR* the closed form uses;
    # gates.py gets only the pre-computed scalar (it does no resampling).
    # NOTE: pre-existing measured promotion tests that supply holdout_returns also exercise this
    # bootstrap path — a future reviewer adding a `checks` assertion for dsr_bootstrap should
    # account for that.
    holdout_rets = wf.holdout_returns  # local binding so mypy can narrow the tuple type below
    bootstrap_binding = dsr_binding and holdout_rets is not None
    boot_lower = boot_seed = boot_b = boot_block = None
    if bootstrap_binding and holdout_rets is not None:  # second guard narrows tuple type for mypy
        sr_star_pp = dsr_sr_star_annualized(
            n_funnel, dsr_trial_var_ann, funnel_floor.var_ann if funnel_floor else None)
        boot_seed = stable_bootstrap_seed(
            name, wf.holdout_metrics["start"], wf.holdout_metrics["end"], wf.config_hash)
        boot = stationary_bootstrap_dsr(
            holdout_rets[0], holdout_rets[1], sr_star_pp, DSR_ALPHA,
            DSR_BOOTSTRAP_RESAMPLES, boot_seed, lower_quantile=DSR_BOOTSTRAP_LOWER_QUANTILE)
        boot_lower, boot_b, boot_block = boot.lower_confidence, boot.b_used, boot.block_len
    decision = evaluate_gate(
        wf, criteria, n_combos=n_funnel, breadth_provenance=breadth.provenance,
        pit_ok=pit_ok, own_lifetime_combos=breadth.own,
        windowed_total_combos=breadth.windowed_total, funnel_window_days=FUNNEL_WINDOW_DAYS,
        dsr_binding=dsr_binding, dsr_trial_var_ann=dsr_trial_var_ann,
        dsr_funnel_floor_var_ann=(funnel_floor.var_ann if funnel_floor else None),
        dsr_funnel_floor_n_strategies=(funnel_floor.n_strategies if funnel_floor else None),
        dsr_funnel_floor_n_total_rows=(funnel_floor.n_total_rows if funnel_floor else None),
        bootstrap_binding=bootstrap_binding, bootstrap_lower_confidence=boot_lower,
        bootstrap_seed=boot_seed, bootstrap_b=boot_b, bootstrap_block_len=boot_block,
    )
    identity = compute_artifact_hashes(name)
    rec = repo.get(name)

    # Effective independent trials N_eff (#221 Slice 3) — SHADOW-ONLY: recorded for the audit trail,
    # NEVER passed as the binding DSR trial count (a lower N_eff would loosen the gate; it goes
    # binding only at Slice 5 with haircut retirement). Sibling-only read (excludes own vector).
    # Guarded on holdout_metrics["start"/"end"] presence (omit-not-fail for legacy fixtures
    # that pre-date Slice 1 and don't carry the OOS interval in the WalkForwardResult).
    h_start_neff = wf.holdout_metrics.get("start")
    h_end_neff = wf.holdout_metrics.get("end")
    if dsr_binding and h_start_neff is not None and h_end_neff is not None:
        siblings = repo.overlapping_holdout_return_streams(
            rec.id, h_start_neff, h_end_neff, FUNNEL_WINDOW_DAYS)
        neff = estimate_n_eff(
            n_funnel, siblings, min_siblings=MIN_N_EFF_SIBLINGS,
            min_overlap_bars=MIN_CORR_OVERLAP_BARS, shrinkage_k=RHO_BAR_SHRINKAGE_K)
        decision.dsr_n_eff = neff.n_eff
        decision.dsr_rho_bar = neff.rho_bar
        decision.dsr_n_siblings = neff.n_siblings

    # Persist the OOS return vector for this burn (#221 Slice 1) — separate tx from the burn
    # (which committed at on_peek). Written on EVERY burn (pass or fail): the holdout was
    # revealed, so the vector exists and funnel siblings may use it. gates.py never sees the
    # vector; promotion is the sole writer. A missing row for a committed burn is a recoverable
    # inconsistency (UNIQUE guards a re-run). returns_available feeds Slices 2-4
    # (omit-not-fail for pre-Slice-1 promotions).
    returns_available = False
    holdout_returns_id: int | None = None
    if holdout_evaluation_id is not None and wf.holdout_returns is not None:
        rets, bar_dates = wf.holdout_returns
        if not (len(rets) == len(bar_dates) == holdout_n_bars):
            raise ValueError(
                f"holdout_returns length {len(rets)}/{len(bar_dates)}"
                f" != holdout n_bars {holdout_n_bars}")
        holdout_returns_id = repo.record_holdout_returns(
            holdout_evaluation_id, rec.id,
            holdout_start=wf.holdout_metrics["start"], holdout_end=wf.holdout_metrics["end"],
            returns=rets, bar_dates=bar_dates)
        returns_available = True
    decision.returns_available = returns_available

    # Public-only WF sibling; tail scalars belong to the post-burn gate row.
    from algua.registry.runs import _sample

    wf_run_id = record_walk_forward_run(repo, rec.name, wf, strategy_id=rec.id,
                                        research_inputs=comparison_inputs)

    # Build gate_row (all record_gate_evaluation kwargs, including provisional passed flag).
    gate_row = {
        "passed": decision.passed,
        "n_funnel": n_funnel,
        "own_lifetime_combos": breadth.own,
        "windowed_total_combos": breadth.windowed_total,
        "funnel_window_days": FUNNEL_WINDOW_DAYS,
        "breadth_provenance": breadth.provenance,
        "pit_ok": bool(decision.pit_ok),
        "pit_override": bool(decision.pit_override),
        "holdout_n_bars": holdout_n_bars,
        "min_holdout_observations": criteria.min_holdout_observations,
        "code_hash": identity.code_hash,
        "config_hash": identity.config_hash,
        "dependency_hash": identity.dependency_hash,
        "data_source": data_source,
        "snapshot_id": snapshot_id,
        # #559: the gated-universe identity, stamped on every row (pass AND fail) so a deployment
        # can be bound to the universe its gate evidence was produced on. NULL for non-universe
        # runs (the tick binding treats NULL as config_legacy).
        "universe_name": universe_name,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "holdout_frac": holdout_frac,
        "decision_json": json.dumps(decision.to_dict(), sort_keys=True),
        # PIT sidecar provenance (#132): the snapshot ids the walk-forward/holdout consumed, so the
        # gate audit row records exactly which fundamentals/news snapshot fed a needs_* promotion.
        "fundamentals_snapshot": wf.fundamentals_snapshot,
        "news_snapshot": wf.news_snapshot,
        # #485: opaque per-attempt idempotency key from the autonomous merge-back driver (NULL for
        # every ordinary caller), stamped on the gate row so promote-outcome attribution binds to
        # the branch identity, not the ambient stage.
        "attempt_token": attempt_token,
    }

    # Atomic gate-record-and-maybe-promote always uses BEGIN IMMEDIATE.
    # #339 — capture the funnel-wide MUTABLE snapshot this decision was computed against, so the
    # commit can CAS-verify it under the write lock and refuse to serialize a mixed-snapshot
    # (stale-breadth / stale-variance) outcome. own/windowed are the exact values evaluate_gate
    # used (from preflight); the variances are the run_gate reads above; the search_trials
    # fingerprint (captured here) is the append-only row-identity guard. Any drift by commit -> the
    # store rolls back and raises FunnelDriftError, and the operator re-runs against fresh state.
    st_count, st_max = repo.search_trials_fingerprint()
    funnel = FunnelSnapshot(
        strategy_name=name,
        funnel_window_days=FUNNEL_WINDOW_DAYS,
        dsr_binding=dsr_binding,
        own_lifetime_combos=breadth.own,
        windowed_total_combos=breadth.windowed_total,
        dsr_trial_var_ann=dsr_trial_var_ann,
        funnel_floor_var_ann=(funnel_floor.var_ann if funnel_floor else None),
        funnel_floor_n_strategies=(funnel_floor.n_strategies if funnel_floor else 0),
        funnel_floor_n_total_rows=(funnel_floor.n_total_rows if funnel_floor else 0),
        search_trials_count=st_count,
        search_trials_max_id=st_max,
    )
    outcome = repo.record_gate_and_maybe_promote(
        rec, gate_row=gate_row, funnel=funnel, actor=actor,
        reason=_gate_reason(decision) if decision.passed else None,
        # The same decision as an economic-layer run row. PASS AND FAIL — the rejections are the
        # dataset the IS-vs-OOS scatter is mostly made of.
        run_row={
            "strategy_id": rec.id, "derived_from": [wf_run_id],
            "components": [wf.model_ref] if wf.model_ref is not None else [],
            "config": capture_gate_comparison(wf, rec.id, wf_run_id, holdout_evaluation_id,
                                               holdout_returns_id, comparison_inputs),
            # The atomic writer supplies final_passed and the gate evaluation identity.
            # Base provenance off the SIBLING walk-forward run's own provenance_of(wf), not a
            # hand-copied field list: the two rows describe the SAME evaluation and must not drift
            # (a hand-copy here had already dropped seed/timeframe, silently). Override only the
            # fields that are GENUINELY different for the gate: code_hash/config_hash/
            # dependency_hash come from `identity`, recomputed via compute_artifact_hashes(name) —
            # deliberately NOT wf's own git-HEAD-based hashes (see run_gate's docstring); the
            # gate's data_source/snapshot_id/universe_name/period_start/period_end are read from
            # the SAME local variables that were passed into walk_forward(), so they are already
            # identical to wf's — provenance_of(wf) carries them without an override.
            "provenance": provenance_of(wf) | {
                "code_hash": identity.code_hash,
                "config_hash": identity.config_hash,
                "dependency_hash": identity.dependency_hash,
            },
            "metrics": walk_forward_metrics(wf) | _sample(wf.holdout_metrics, "_oos")
                       | {"n_obs_oos": holdout_n_bars},
            # The DSR / bootstrap diagnostics: queryable, but deliberately outside the fixed
            # vocabulary. Finite scalars only — decision.to_dict() also carries strings, lists and
            # bools, and `bool` is an `int` subclass so it must be excluded explicitly.
            "extra_metrics": {
                k: float(v) for k, v in decision.to_dict().items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            },
            # v44: the holdout_returns row this burn's OOS vector was written to above (NULL for a
            # pre-Slice-1 promotion with no returns_available) — resolves `runs series` to it.
            "series_holdout_id": holdout_returns_id,
        },
    )

    # final_passed == provisional_passed (the integrity floor). Kept as an assignment (not an
    # assert) so the decision always mirrors what the store committed.
    decision.passed = outcome.final_passed

    return PromotionOutcome(decision=decision, promoted=outcome.final_passed)


def _gate_reason(decision: GateDecision) -> str:
    """Human-readable gate summary. Metric checks render value/op/threshold; boolean checks (e.g.
    pit_required) render name=pass|fail."""
    parts: list[str] = []
    for c in decision.checks:
        if "value" in c and c.get("value") is not None and c.get("threshold") is not None:
            parts.append(f"{c['name']}={c['value']:.4g}{c['op']}{c['threshold']:.4g}")
        else:
            parts.append(f"{c['name']}={'pass' if c['passed'] else 'fail'}")
    breadth = (
        f"; funnel_breadth={decision.n_combos}({decision.breadth_provenance}"
        f"; own={decision.own_lifetime_combos}, windowed={decision.windowed_total_combos}"
        f", window={decision.funnel_window_days}d)"
        f"; min_holdout_sharpe={decision.base_min_holdout_sharpe:.4g}"
        f"->{decision.effective_min_holdout_sharpe:.4g}"
        if decision.n_combos is not None else ""
    )
    return "gate pass: " + ", ".join(parts) + breadth
