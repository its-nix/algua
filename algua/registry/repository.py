from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol

from algua.contracts.lifecycle import Actor, Stage
from algua.contracts.registry_metadata import Author, HypothesisStatus
from algua.contracts.types import ExitLaneGuard, PendingLiveAuthorization


class GateOutcome(NamedTuple):
    """Return value of ``record_gate_and_maybe_promote``: the gate row id, the committed
    ``final_passed`` verdict, and the updated ``StrategyRecord`` if the strategy was promoted
    (None otherwise)."""

    gate_id: int
    final_passed: bool
    updated_rec: StrategyRecord | None


class FunnelFloor(NamedTuple):
    """Funnel-wide cross-strategy trial-Sharpe dispersion floor (#221 Slice 0). ``var_ann`` is the
    MEAN of per-strategy pooled trial-Sharpe variances (annualized) across strategies active in the
    rolling window, or ``None`` when fewer than ``MIN_FUNNEL_FLOOR_STRATEGIES`` finite per-strategy
    variances exist (fail-open -> Phase-1 behavior). ``n_strategies`` is the count of strategies
    that contributed a FINITE per-strategy pooled variance (strategies with NULL or non-finite
    pooled variance are excluded entirely and do not count toward this total). ``n_total_rows`` is
    the total search_trials rows across THOSE strategies (including their out-of-window/stale rows,
    since the window selects strategies by their most-recent trial date, then pools ALL of each
    selected strategy's rows)."""

    var_ann: float | None
    n_strategies: int
    n_total_rows: int


class FunnelSnapshot(NamedTuple):
    """The funnel-wide, MUTABLE state that a (lock-free) promotion decision was computed against,
    captured so ``record_gate_and_maybe_promote`` can CAS-verify it is unchanged at
    commit time (#339). Every field below feeds the recorded decision (the breadth ``n_funnel``
    and the DSR evidence via the trial count and SR* floor), so a change to ANY of
    them between the lock-free compute and the commit would make the committed decision reflect a
    DIFFERENT funnel snapshot than the one it was computed against — a non-serializable
    mixed-snapshot outcome. The commit re-reads each value under the write lock and aborts
    (``FunnelDriftError``) on any mismatch, so a committed promotion is provably a pure function of
    ONE funnel snapshot.

    Fields:
    - ``strategy_name`` / ``funnel_window_days`` / ``dsr_binding``: identify what to re-read.
    - ``own_lifetime_combos`` = ``total_search_combos(strategy_name)``.
    - ``windowed_total_combos`` = ``windowed_search_combos(funnel_window_days)``.
    - ``dsr_trial_var_ann`` = ``pooled_trial_sharpe_var(strategy_name)`` (None unless dsr_binding).
    - ``funnel_floor_var_ann`` / ``funnel_floor_n_strategies`` / ``funnel_floor_n_total_rows`` =
      the ``FunnelFloor`` fields from ``funnel_trial_sharpe_var(funnel_window_days)`` (var_ann
      None / counts 0 unless dsr_binding).
    - ``search_trials_count`` / ``search_trials_max_id``: the append-only ``search_trials``
      fingerprint ``(COUNT(*), COALESCE(MAX(id), 0))``. Because ``search_trials`` is INSERT-only,
      this pins the ENTIRE row set — it closes the (astronomically unlikely) "different rows yield a
      bit-identical pooled/funnel variance" collision that value-equality alone could not.
    """

    strategy_name: str
    funnel_window_days: int
    dsr_binding: bool
    own_lifetime_combos: int
    windowed_total_combos: int
    dsr_trial_var_ann: float | None
    funnel_floor_var_ann: float | None
    funnel_floor_n_strategies: int
    funnel_floor_n_total_rows: int
    search_trials_count: int
    search_trials_max_id: int


class ArtifactIdentity(NamedTuple):
    """The full identity a human approval binds to and the live gate recomputes.

    A ``NamedTuple`` so callers can either unpack ``(code_hash, config_hash, dependency_hash)``
    or read fields by name. ``dependency_hash`` is ``None`` only when the lockfile is absent;
    such an identity can never match a stored approval (see ``has_valid_approval``)."""

    code_hash: str
    config_hash: str
    dependency_hash: str | None


class FunnelDriftError(ValueError):
    """Raised (fail-closed) when the funnel-wide state a promotion decision was computed against
    changed before the commit could serialize it (#339). Conservative: it can only PREVENT a
    commit, never produce a false pass. The caller re-runs the promotion against fresh funnel
    state. A ``ValueError`` so the CLI's ``@json_errors`` surfaces it as a clean JSON error."""

    pass


class StrategyExists(ValueError):
    pass


class StrategyNotFound(LookupError):
    pass


@dataclass
class StrategyRecord:
    id: int
    name: str
    stage: Stage
    created_at: str
    updated_at: str
    family: str | None = None
    tags: list[str] = field(default_factory=list)
    author: Author = Author.AGENT
    hypothesis_status: HypothesisStatus = HypothesisStatus.UNTESTED
    derived_from: str | None = None
    description: str | None = None


def kb_metadata(rec: StrategyRecord) -> dict:
    """Return the registry-owned frontmatter fields for kb sync (no id/name/stage).

    Lives beside ``StrategyRecord`` so both ``registry_cmd`` and ``strategy_cmd`` import it from the
    registry layer rather than from each other.
    """
    return {
        "family": rec.family, "tags": rec.tags, "author": rec.author.value,
        "hypothesis_status": rec.hypothesis_status.value,
        "derived_from": rec.derived_from, "description": rec.description,
    }


# =============================================================================
# Narrow role protocols (#334, ISP).
#
# The single 46-method ``StrategyRepository`` Protocol below is composed from these
# cohesive, bounded-context slices so a caller can depend on ONLY the role it uses
# (e.g. a read-only consumer takes ``StrategyReader``, not the whole persistence seam).
# ``StrategyRepository`` remains the exact structural superset, so broad cross-context
# consumers keep depending on it unchanged. The sqlite implementation in
# ``algua.registry.store`` is the only place that knows SQL and structurally satisfies
# every slice below; swapping the backing store means writing another implementation,
# not touching policy code.
# =============================================================================


class StrategyReader(Protocol):
    """Read a single strategy record — the cross-context read capability."""

    def get(self, name: str) -> StrategyRecord:
        """Return the strategy by name, or raise ``StrategyNotFound``."""
        ...


class StrategyLister(Protocol):
    """List strategy records with optional filters."""

    def list_strategies(
        self,
        stage: Stage | None = None,
        *,
        family: str | None = None,
        tags: list[str] | None = None,
        author: Author | None = None,
        hypothesis_status: HypothesisStatus | None = None,
    ) -> list[StrategyRecord]:
        """List strategies, optionally filtered. Filters AND together; repeated ``tags`` means
        all-of. ``author``/``hypothesis_status`` use COALESCE so NULL legacy rows match the
        default. Ordered by insertion."""
        ...


class StrategyStore(StrategyReader, StrategyLister, Protocol):
    """Strategy CRUD + organizational metadata + stage transitions."""

    def add(
        self,
        name: str,
        *,
        family: str | None = None,
        tags: list[str] | None = None,
        author: Author = Author.AGENT,
        hypothesis_status: HypothesisStatus = HypothesisStatus.UNTESTED,
        derived_from: str | None = None,
        description: str | None = None,
    ) -> StrategyRecord:
        """Insert a new strategy at stage ``idea`` with its initial transition row and the given
        organizational metadata. ``derived_from``, if set, must name an existing strategy and may
        not be the strategy itself.
        Raises ``StrategyExists`` / ``StrategyNotFound`` / ``ValueError``.
        """
        ...

    def update_metadata(
        self,
        name: str,
        *,
        family: str | None = None,
        author: Author | None = None,
        hypothesis_status: HypothesisStatus | None = None,
        derived_from: str | None = None,
        description: str | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
    ) -> StrategyRecord:
        """Update only the supplied organizational-metadata fields (never the stage).
        ``add_tags``/``remove_tags`` mutate the tag set. Returns the updated record.
        """
        ...

    def backfill_metadata(
        self,
        name: str,
        *,
        family: str | None = None,
        tags: list[str] | None = None,
        author: str | None = None,
        hypothesis_status: str | None = None,
        derived_from: str | None = None,
        description: str | None = None,
    ) -> StrategyRecord:
        """Fill only currently-NULL metadata columns from the given values (one-shot recovery).
        A column already holding a value is left untouched. ``author``/``hypothesis_status`` are
        raw validated strings (the caller maps/validates against the enums). Idempotent: re-running
        is a no-op once columns are non-NULL.
        """
        ...

    def default_fill_metadata_nulls(self) -> None:
        """Fill every strategy row's author/hypothesis_status/tags column from its default when
        still NULL. Terminal step of the ``backfill-from-kb`` command. Idempotent."""
        ...

    def delete(self, name: str) -> None:
        """Remove a strategy row and its transition rows. ONLY for rolling back a failed
        ``strategy new`` that just created it — there is no general deletion workflow."""
        ...

    def list_transitions(self, name: str) -> list[dict]:
        """Return the strategy's ordered stage-transition history."""
        ...

    def apply_transition(
        self,
        rec: StrategyRecord,
        to: Stage,
        actor: Actor,
        reason: str | None = None,
        code_hash: str | None = None,
        config_hash: str | None = None,
        dependency_hash: str | None = None,
        consume_gate_id: int | None = None,
        consume_forward_gate_id: int | None = None,
        revoke_allocation: bool = False,
        live_authorization: PendingLiveAuthorization | None = None,
        exit_guard: ExitLaneGuard | None = None,
    ) -> StrategyRecord:
        """Atomically advance ``rec`` to ``to``, append a transition row, return the new state.

        The stage write is a compare-and-swap on ``rec.stage``: if another session moved the
        stage since the caller read ``rec``, raise ``TransitionError`` (the whole transaction —
        including any token consume — rolls back). At most one of ``consume_gate_id`` /
        ``consume_forward_gate_id`` may be set (``ValueError`` otherwise); the forward consume
        re-checks the full token predicate (identity, actor, passed, unconsumed, TTL) against the
        caller-supplied ``code_hash``/``config_hash``/``dependency_hash`` at consume time.

        When ``revoke_allocation`` is set (the live -> dormant bench edge), the implementation MUST,
        in ONE atomic write transaction (write lock taken up front): re-assert the strategy is flat
        (no open live positions), revoke its active live allocation, and apply the stage CAS. Doing
        the flatness check outside that transaction reopens the #247 TOCTOU (a fill landing between
        the check and the CAS orphans a position on a now-dormant strategy).

        ``exit_guard`` (only valid when ``revoke_allocation`` is set, #497 F2/H1) is the
        broker-backed source-lane drain: its ``cancel_and_ingest`` runs BEFORE the write lock
        (cancel the strategy's resting orders + ingest the venue feed), and its
        ``owned_open_order_ids`` is re-listed UNDER the lock so a resting order that survived the
        cancel blocks the revoke+CAS rather than orphaning a position after it leaves its book."""
        ...


class ApprovalLedger(Protocol):
    """Human-approval records that pin an artifact identity for the live gate."""

    def record_approval(
        self,
        strategy_id: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
        approved_by: str,
    ) -> int:
        """Persist a human approval pinning ``code_hash``/``config_hash``/``dependency_hash``;
        return its row id."""
        ...

    def has_valid_approval(
        self,
        strategy_id: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
    ) -> bool:
        """True iff a non-revoked approval pins exactly this strategy + code + config +
        dependency set. A ``None`` ``dependency_hash`` (no lockfile) never matches, and a stored
        row with a NULL ``dependency_hash`` never matches a concrete hash — both fail closed."""
        ...


class SearchBreadthLedger(Protocol):
    """Search-trial breadth + trial-Sharpe dispersion (the #211/#221 multiple-testing inputs)."""

    def record_search_trial(
        self, strategy_name: str, n_combos: int, grid_json: str,
        *, trial_sharpe_count: int | None = None,
        trial_sharpe_mean: float | None = None,
        trial_sharpe_var_ann: float | None = None,
    ) -> int:
        """Persist one measured search-breadth row (size + grid + the sweep's trial-Sharpe
        (count, mean, annualized var) for the #211 DSR dispersion); return its row id. Keyed by
        strategy NAME so a sweep run BEFORE the strategy is registered still counts toward promotion
        breadth. Stats default to None for callers that record only breadth."""
        ...

    def pooled_trial_sharpe_var(self, strategy_name: str) -> float | None:
        """Exact pooled SAMPLE variance (ddof=1) of the strategy's trial Sharpes across all its
        search_trials rows, via the law of total variance over the per-row (count, mean, var)
        triples. Returns None (fail closed) if there are no rows OR any contributing row has a
        NULL/NaN/inf count/mean/var. ANNUALIZED units (caller converts)."""
        ...

    def funnel_trial_sharpe_var(self, window_days: int) -> FunnelFloor:
        """Per-strategy pooling FIRST, then mean across strategies active in the trailing
        ``window_days`` (anti-gaming: one vote per strategy regardless of combo count)."""
        ...

    def total_search_combos(self, strategy_name: str) -> int:
        """Sum of ``n_combos`` across every recorded ``search_trials`` row for the strategy NAME —
        the cumulative count of parameter combinations searched for this strategy (0 if none)."""
        ...

    def windowed_search_combos(self, window_days: int) -> int:
        """Sum of ``n_combos`` across ALL strategies' ``search_trials`` recorded within the trailing
        ``window_days`` — funnel-wide search effort for the breadth wall (0 if none)."""
        ...

    def search_trials_fingerprint(self) -> tuple[int, int]:
        """``(COUNT(*), COALESCE(MAX(id), 0))`` over ALL ``search_trials`` rows. Because that table
        is append-only (INSERT-only, AUTOINCREMENT PK), this pair strictly increases on every
        insert and so uniquely fingerprints the entire row set — the row-identity half of the #339
        funnel CAS."""
        ...


class HoldoutLedger(Protocol):
    """Single-use holdout-window reservations/burns + OOS return-vector persistence."""

    def reserve_holdout(
        self,
        strategy_id: int,
        *,
        data_source: str,
        snapshot_id: str | None,
        period_start: str,
        period_end: str,
        holdout_frac: float,
        holdout_start: str,
        holdout_end: str,
    ) -> int:
        """Atomically claim the holdout window; return the reservation id.

        Under ``BEGIN IMMEDIATE`` (write lock held): re-check overlap against ALL rows (pending
        reservation OR committed burn) for this strategy, matching on the OOS INTERVAL
        ``[holdout_start, holdout_end]`` — the exact bars ``walk_forward`` burns (#192). The match
        is PROVENANCE-INDEPENDENT (#205): ``data_source``/``snapshot_id`` are stored as evidence
        only, never matched on, so the same OOS window is burn-once regardless of how the bars were
        reached (snapshot S, snapshot S2, or provider P). Then INSERT a pending row
        (``committed_at=NULL``, placeholder ``config_hash=''``). Match is on the INTERVAL, never
        config: a different ``holdout_frac`` landing on overlapping OOS bars does NOT escape the
        guard. A stored row with a NULL interval (legacy/old-code reservation) matches
        UNCONDITIONALLY — fail closed. An
        inverted incoming interval (start > end) is rejected (fail closed). ``period_*``/
        ``holdout_frac`` are evidence only.

        Raises ``ValueError`` (fail closed) if an overlapping row exists: the holdout is single-use
        for every actor (no reuse override; spec 2026-11-13). The ``reused`` column is written 0.

        TOP-LEVEL ONLY: must not be called inside an open transaction / ``with self._conn:`` block
        (raises ``RuntimeError`` if ``self._conn.in_transaction``)."""
        ...

    def finalize_holdout_reservation(
        self, reservation_id: int, *, config_hash: str, strategy_id: int
    ) -> None:
        """Commit a reservation into a burn: set ``committed_at`` + the real evidentiary
        ``config_hash``. Raises if the row is missing, already committed, or strategy_id mismatches
        (guards double-finalize and caller-bug cross-strategy writes).
        """
        ...

    def release_holdout_reservation(self, reservation_id: int) -> None:
        """Free a still-pending reservation (clean walk_forward failure). Never touches a committed
        burn; a release after finalize/crash is a harmless no-op."""
        ...

    def record_holdout_returns(
        self, holdout_evaluation_id: int, strategy_id: int, *,
        holdout_start: str, holdout_end: str,
        returns: list[float], bar_dates: list[str],
    ) -> int:
        """Persist ONE OOS return vector for a committed holdout burn (#221 Slice 1). Separate
        transaction from the burn (the burn committed at on_peek). UNIQUE(holdout_evaluation_id)
        makes a re-run reconciliation safe. Validation is fail-closed and happens before the write.
        Returns the new holdout_returns row id."""
        ...

    def overlapping_holdout_return_streams(
        self, strategy_id: int, holdout_start: str, holdout_end: str, window_days: int
    ) -> list[tuple[list[float], list[str]]]:
        """SIBLING-ONLY cross-strategy read (#221 Slice 1 access control): returns OTHER strategies'
        OOS return vectors (date-aligned ``(returns, bar_dates)`` pairs) whose holdout interval
        overlaps ``[holdout_start, holdout_end]``, burned within the trailing ``window_days``.
        NEVER returns the requesting strategy's own vector (``hr.strategy_id != strategy_id``).
        This is the ONLY method that reads ``returns_blob``.

        Window filter is on ``holdout_evaluations.created_at`` (burn time), NOT
        ``holdout_returns.created_at`` (write time). Interval overlap is the standard test:
        ``hr.holdout_start <= holdout_end AND holdout_start <= hr.holdout_end``.

        Raises ``ValueError`` if a returned blob is corrupt (length ≠ n_bars).

        NOTE: ``holdout_returns`` keys by ``strategy_id`` (FK to ``strategies.id``) while
        ``search_trials`` keys by ``strategy_name`` — the asymmetry is intentional.
        """
        ...


class GateLedger(Protocol):
    """Research/shortlist gate evaluations + the atomic record-gate-and-maybe-promote."""

    def record_gate_evaluation(
        self,
        strategy_id: int,
        *,
        passed: bool,
        n_funnel: int,
        own_lifetime_combos: int,
        windowed_total_combos: int,
        funnel_window_days: int,
        breadth_provenance: str,
        pit_ok: bool,
        pit_override: bool,
        holdout_n_bars: int,
        min_holdout_observations: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
        data_source: str,
        snapshot_id: str | None,
        period_start: str,
        period_end: str,
        holdout_frac: float,
        actor: str,
        decision_json: str,
        fundamentals_snapshot: str | None = None,
        news_snapshot: str | None = None,
        universe_name: str | None = None,
    ) -> int:
        """Persist one gate evaluation (pass or fail) and return its row id. A passing AGENT row is
        the single-use token the shortlist transition consumes. ``universe_name`` is the
        gated-universe identity (#559), optional with default None. The historical ``family_id``/
        ``family_lifetime_effective`` columns are left NULL (lean trim step 7)."""
        ...

    def find_consumable_gate_evaluation(
        self,
        strategy_id: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
    ) -> int | None:
        """Return the id of the most-recent AGENT passing unconsumed gate row whose identity matches
        the recomputed (code, config, dependency), or None. A human row and a NULL
        ``dependency_hash`` are never consumable tokens — fail-closed."""
        ...

    def record_gate_and_maybe_promote(
        self,
        rec: StrategyRecord,
        *,
        gate_row: dict[str, Any],
        funnel: FunnelSnapshot,
        actor: Actor,
        reason: str | None = None,
        run_row: dict[str, Any] | None = None,
    ) -> GateOutcome:
        """Record a gate evaluation and optionally promote to ``candidate`` — all under a single
        **BEGIN IMMEDIATE** transaction (write lock held from the funnel-snapshot CAS through the
        INSERT + stage CAS).

        ``gate_row`` carries ``record_gate_evaluation``'s keyword arguments (including the
        provisional ``passed`` flag). ``final_passed`` is the provisional integrity-floor verdict.
        The ``fdr_*`` columns are historical (lean trim step 7): new rows write them NULL.

        ``funnel`` is the funnel-wide snapshot the (lock-free) decision was computed against
        (#339). Under the write lock every mutable field is RE-READ and CAS-verified; on any drift
        the whole transaction rolls back and raises ``FunnelDriftError``, so a committed decision
        is provably a pure function of ONE funnel snapshot (serializable).

        TOP-LEVEL ONLY: raises ``RuntimeError`` if called inside an open transaction (mirrors
        ``reserve_holdout``). Crash semantics: a process crash before commit rolls back both
        the gate row and the stage CAS — no half-promoted strategy.

        ``run_row`` (Task 7, spec 2026-08-23 §4.1) is the economic-layer ``runs`` payload for THIS
        decision, when the caller wants one recorded — inserted inside this same transaction
        (immediately after the ``gate_evaluations`` INSERT) so it shares the gate row's commit/
        rollback fate. Its ``passed`` is overwritten with this call's own ``final_passed`` so the
        run row can never disagree with the gate row it derives from.
        """
        ...


class ForwardGateLedger(Protocol):
    """Forward-test gate evaluations + the paper -> forward_tested atomic promotion + live-wall
    certificate selection (#124)."""

    def record_forward_gate_evaluation(
        self,
        strategy_id: int,
        *,
        passed: bool,
        n_forward_observations: int,
        min_forward_observations: int,
        session_coverage: float | None,
        realized_sharpe: float | None,
        holdout_sharpe: float | None,
        degradation_factor: float,
        sharpe_floor: float,
        realized_vol: float | None,
        min_forward_vol: float,
        realized_max_drawdown: float | None,
        max_forward_drawdown: float,
        first_tick_id: int | None,
        last_tick_id: int | None,
        first_tick_ts: str | None,
        last_tick_ts: str | None,
        max_staleness_sessions: int,
        n_reconcile_failures: int,
        n_concurrent_forward: int,
        account_id: str | None,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
        actor: str,
        decision_json: str,
        consumable: bool,
        deployment_id: int | None = None,
    ) -> int:
        """Persist one forward-test gate evaluation (pass or fail) and return its row id. A
        passing AGENT row written ``consumable=True`` is the single-use token the paper ->
        forward_tested transition consumes; ``consumable=False`` writes the row already consumed
        — a CERTIFICATE for the live wall, never a re-entry token (#124 GATE-2)."""
        ...

    def record_forward_pass_and_promote(
        self,
        rec: StrategyRecord,
        *,
        gate_row: dict[str, Any],
        actor: Actor,
        reason: str | None = None,
    ) -> tuple[int, StrategyRecord]:
        """Record a PASSING forward-gate evaluation AND advance ``rec`` paper -> forward_tested
        ATOMICALLY — the row insert, the compare-and-swap stage change, and the transition row
        commit together or not at all (#124 GATE-2). ``gate_row`` carries
        ``record_forward_gate_evaluation``'s row kwargs minus ``actor``/``consumable``.

        The row is born consumed regardless of actor (born-and-spent in the one transaction): it
        is the live wall's certificate, never a re-entry token a later demotion could bank. If
        another session moved the stage since ``rec`` was read, ``TransitionError`` — and the
        loser leaves NO row at all (its decision is lost; re-run the gate). Raises ``ValueError``
        on a non-passing ``gate_row``."""
        ...

    def find_consumable_forward_gate_evaluation(
        self,
        strategy_id: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
        *,
        now: str,
        ttl_days: int,
    ) -> int | None:
        """Return the id of the most-recent AGENT passing unconsumed forward-gate row whose
        identity matches the recomputed (code, config, dependency) and whose ``created_at`` is
        within ``ttl_days`` of ``now`` (a stale token can never be banked), or None. A human row
        and a NULL ``dependency_hash`` are never consumable tokens — fail-closed."""
        ...

    def latest_forward_gate_row(
        self,
        strategy_id: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
    ) -> dict | None:
        """Return the newest forward-gate row (all columns, as a dict) for this strategy+identity
        regardless of passed/consumed, or None. The live wall's certificate selection —
        pass-or-fail on purpose: a newer failed re-evaluation must invalidate an older pass
        (#124). A NULL ``dependency_hash`` matches nothing — fail-closed."""
        ...

class BacktestReturnsLedger(Protocol):
    """Backtest return-series persistence (#222, Task 7)."""

    def persist_backtest_returns(
        self,
        strategy_name: str,
        period_start: str,
        period_end: str,
        returns: Any,
    ) -> int:
        """Persist a backtest return series as JSON [[date_str, float], ...]. Returns row id.
        ``returns`` is a ``pd.Series`` (typed ``Any`` here to avoid the pandas import in the
        Protocol module)."""
        ...

    def load_backtest_returns(self, strategy_name: str) -> Any:
        """Load the most recent return series for a strategy, or None.
        Returns a ``pd.Series | None`` (typed ``Any`` here to avoid the pandas import)."""
        ...


class RunLedger(Protocol):
    """The economic-layer evaluation ledger (``runs`` + ``run_metrics``; Task 7, spec
    2026-08-23). Narrow on purpose: only ``record_run`` is exposed through this Protocol slice —
    every other ``RunLedgerMixin`` entry point (``record_sweep_trials``, ``list_runs``, ...) is
    called through the concrete ``SqliteStrategyRepository``, the established pattern from Tasks
    2-6. This slice exists so a Protocol-typed caller (``promotion.py``'s ``run_gate``) can record
    the walk-forward run without depending on the concrete class."""

    def record_run(  # noqa: PLR0913 — mirrors RunLedgerMixin.record_run exactly
        self,
        kind: str,
        strategy_name: str,
        *,
        strategy_id: int | None = None,
        derived_from: list[int] | None = None,
        components: list[dict[str, Any]] | None = None,
        provenance: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        metrics: dict[str, float | int | None] | None = None,
        extra_metrics: dict[str, float | None] | None = None,
        passed: bool | None = None,
        trials_truncated_at: int | None = None,
        gate_id: int | None = None,
        series_backtest_id: int | None = None,
        series_holdout_id: int | None = None,
    ) -> int:
        """Insert one run row (and its overflow metrics), in its own transaction, and return its
        id. ``metrics`` keys MUST come from the fixed vocabulary (``METRIC_COLUMNS`` in
        ``algua/registry/store/runs.py``); anything else raises. ``gate_id`` is the
        ``gate_evaluations.id`` a `gate` run derives from — NULL for every other kind.
        ``series_backtest_id``/``series_holdout_id`` point at the return-series row this run's
        series was persisted to — NULL when none exists."""
        ...


class StrategyRepository(
    StrategyStore,
    ApprovalLedger,
    SearchBreadthLedger,
    HoldoutLedger,
    GateLedger,
    ForwardGateLedger,
    BacktestReturnsLedger,
    RunLedger,
    Protocol,
):
    """Persistence seam for the registry — the structural union of all role protocols above.

    The lifecycle policy (transitions, approvals) depends on this Protocol or on one of its narrow
    slices, never on a concrete database driver. The sqlite implementation lives in
    ``algua.registry.store`` and is the only place that knows SQL; swapping the backing store means
    writing another implementation, not touching policy code. Cross-context consumers depend on this
    full seam; single-context consumers depend on the narrow role protocol they use (ISP, #334).
    """


class ApprovalRepository(StrategyReader, ApprovalLedger, Protocol):
    """The slice the approval workflow depends on: read a strategy + record/verify approvals."""
