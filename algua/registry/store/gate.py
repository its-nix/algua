"""``GateLedger`` — research/shortlist gate evaluations, the funnel-snapshot CAS, and the
atomic record-gate-and-maybe-promote transaction."""
from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

from algua.contracts.lifecycle import Actor, Stage, TransitionError
from algua.registry.gate_comparison_write import seal_gate_comparison
from algua.registry.repository import (
    FunnelDriftError,
    FunnelFloor,
    FunnelSnapshot,
    GateOutcome,
    StrategyRecord,
)
from algua.registry.store._util import _now
from algua.registry.store.base import TransitionMixin


class GateLedgerMixin(TransitionMixin):
    _conn: sqlite3.Connection

    if TYPE_CHECKING:
        # Cross-file calls: the real implementations live in SIBLING mixins (search_breadth.py,
        # runs.py) and are composed by the facade. Declared TYPE_CHECKING-only — unlike
        # algua/data/store/bars.py, whose stub points at the FACADE (which always wins the MRO),
        # a runtime stub here would SHADOW a sibling mixin declared later in the facade's base
        # list. Signatures are copied from repository.py's Protocol declarations.
        def search_trials_fingerprint(self) -> tuple[int, int]: ...
        def windowed_search_combos(self, window_days: int) -> int: ...
        def total_search_combos(self, strategy_name: str) -> int: ...
        def pooled_trial_sharpe_var(self, strategy_name: str) -> float | None: ...
        def funnel_trial_sharpe_var(self, window_days: int) -> FunnelFloor: ...
        # runs.py (RunLedgerMixin) — not a repository.py Protocol method (it is store-internal:
        # only the gate's own BEGIN IMMEDIATE calls it, never CLI/research code).
        def _insert_run_locked(self, kind: str, strategy_name: str, **kwargs: Any) -> int: ...

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
        the single-use token the shortlist transition consumes."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO gate_evaluations"
                "(strategy_id, passed, n_funnel, own_lifetime_combos, windowed_total_combos,"
                " funnel_window_days, breadth_provenance, pit_ok, pit_override, holdout_n_bars,"
                " min_holdout_observations, code_hash, config_hash, dependency_hash, data_source,"
                " snapshot_id, period_start, period_end, holdout_frac, actor, decision_json,"
                " fundamentals_snapshot, news_snapshot, consumed, created_at, universe_name)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (strategy_id, int(passed), n_funnel, own_lifetime_combos, windowed_total_combos,
                 funnel_window_days, breadth_provenance, int(pit_ok), int(pit_override),
                 holdout_n_bars, min_holdout_observations, code_hash, config_hash, dependency_hash,
                 data_source, snapshot_id, period_start, period_end, holdout_frac, actor,
                 decision_json, fundamentals_snapshot, news_snapshot, _now(), universe_name),
            )
        rowid = cur.lastrowid
        assert rowid is not None
        return rowid

    def find_consumable_gate_evaluation(
        self,
        strategy_id: int,
        code_hash: str,
        config_hash: str,
        dependency_hash: str | None,
    ) -> int | None:
        """Return the id of the most-recent AGENT passing unconsumed gate row whose identity matches
        the recomputed current (code, config, dependency), or None. The ``actor='agent'`` filter
        means a human/override promote's audit row is never an agent-consumable token. A NULL
        ``dependency_hash`` matches nothing — fail-closed, mirroring has_valid_approval."""
        if dependency_hash is None:
            return None
        row = self._conn.execute(
            "SELECT id FROM gate_evaluations WHERE strategy_id=? AND passed=1 AND consumed=0"
            " AND actor='agent' AND code_hash=? AND config_hash=? AND dependency_hash=?"
            " ORDER BY id DESC LIMIT 1",
            (strategy_id, code_hash, config_hash, dependency_hash),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    @staticmethod
    def _cas_funnel(name: str, expected: object, actual: object) -> None:
        """Fail-closed exact-equality check for one funnel-snapshot field (#339). Float fields are
        compared exactly: they are recomputed from the SAME committed rows by the SAME deterministic
        code, so an unchanged funnel yields a bit-identical value; any real drift changes it."""
        if expected != actual:
            raise FunnelDriftError(
                f"{name} changed between promotion compute and commit "
                f"({expected!r} -> {actual!r}); re-run the promotion against fresh funnel state")

    def _verify_funnel_snapshot(self, funnel: FunnelSnapshot) -> None:
        """#339 serializability CAS — MUST run with the write lock held (inside BEGIN IMMEDIATE).
        Re-reads every mutable funnel-wide input the (lock-free) decision was computed against and
        raises ``FunnelDriftError`` on any drift, which the caller's ``except`` rolls the whole
        transaction back on. Conservative: it can only PREVENT a commit, never cause a false pass.

        Covers the complete decision-input set (the rest of the decision is pinned to immutable
        artifacts — fixed data snapshot, immutable strategy source/config hash, deterministic
        bootstrap seed, and the atomically pre-burned holdout reservation #161):
          * the append-only ``search_trials`` row-identity fingerprint (pins the whole row set, so
            it pins the measured own-combo count AND the pooled/funnel variances against a
            same-value collision);
          * ``windowed_search_combos`` — feeds ``n_funnel`` (the DSR trial count) on EVERY path;
          * on the measured (DSR-armed) path, the own-combo count and the two DSR variances that
            feed the recorded DSR evidence."""
        cur_count, cur_max = self.search_trials_fingerprint()
        self._cas_funnel(
            "search_trials fingerprint",
            (funnel.search_trials_count, funnel.search_trials_max_id), (cur_count, cur_max))
        self._cas_funnel(
            "windowed_search_combos", funnel.windowed_total_combos,
            self.windowed_search_combos(funnel.funnel_window_days))
        if funnel.dsr_binding:
            self._cas_funnel(
                "total_search_combos", funnel.own_lifetime_combos,
                self.total_search_combos(funnel.strategy_name))
            self._cas_funnel(
                "pooled_trial_sharpe_var", funnel.dsr_trial_var_ann,
                self.pooled_trial_sharpe_var(funnel.strategy_name))
            floor = self.funnel_trial_sharpe_var(funnel.funnel_window_days)
            self._cas_funnel(
                "funnel_trial_sharpe_var.var_ann", funnel.funnel_floor_var_ann, floor.var_ann)
            self._cas_funnel(
                "funnel_trial_sharpe_var.n_strategies",
                funnel.funnel_floor_n_strategies, floor.n_strategies)
            self._cas_funnel(
                "funnel_trial_sharpe_var.n_total_rows",
                funnel.funnel_floor_n_total_rows, floor.n_total_rows)

    def record_gate_and_maybe_promote(
        self,
        rec: StrategyRecord,
        *,
        gate_row: dict[str, Any],
        funnel: FunnelSnapshot,
        actor: Actor,
        reason: str | None = None,
        # ``run_row`` is the economic-layer run payload for THIS decision (spec 2026-08-23 §4.1),
        # inserted inside this method's BEGIN IMMEDIATE so it shares the gate row's fate. It cannot
        # be written by the caller: this method refuses to run inside an open transaction, so a
        # caller-side write would either land in a separate transaction (a run row that survives a
        # rolled-back gate — a phantom evaluation) or trip the top-level guard above.
        run_row: dict[str, Any] | None = None,
    ) -> GateOutcome:
        actor = Actor(actor)
        # TOP-LEVEL ONLY — mirrors reserve_holdout's contract. A manual BEGIN IMMEDIATE inside an
        # already-open transaction would raise "cannot start a transaction within a transaction";
        # catching that instead of pre-checking would leave the caller's surrounding tx open in a
        # rolled-back state. Fail loudly so the contract is enforced, not assumed.
        if self._conn.in_transaction:
            raise RuntimeError(
                "record_gate_and_maybe_promote must be called at top level,"
                " not inside an open transaction")

        # #339 — bind the funnel snapshot to the strategy being promoted. The in-lock CAS re-reads
        # the funnel-wide state keyed by funnel.strategy_name; if that name did not match rec (a
        # caller passing the wrong snapshot), the CAS would validate a DIFFERENT strategy's inputs
        # and the promoted strategy's own drift could escape. Fail closed on mismatch — the store
        # method is the safety boundary, not just the run_gate caller.
        if funnel.strategy_name != rec.name:
            raise FunnelDriftError(
                f"funnel snapshot is for {funnel.strategy_name!r} but the promotion is for "
                f"{rec.name!r}; the funnel CAS must verify the strategy being promoted")

        provisional_passed = bool(gate_row.get("passed"))
        final_passed: bool

        # BEGIN IMMEDIATE takes the write lock up front so the gate row INSERT and the optional
        # stage CAS are one atomic critical section.
        # BaseException (not Exception) so KeyboardInterrupt/SystemExit still rolls back.
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            # #339 — serializability CAS: re-read the funnel-wide MUTABLE state the (lock-free)
            # decision was computed against and abort if any of it drifted, so a committed decision
            # is provably a pure function of ONE funnel snapshot. Runs BEFORE the INSERT/stage-CAS,
            # inside this one write-locked critical section.
            self._verify_funnel_snapshot(funnel)
            # final_passed is the provisional integrity-floor verdict (the statistical stack is
            # advisory and never vetoes).
            final_passed = provisional_passed

            # Patch decision_json so the stored audit record reflects final_passed — only known
            # after this transaction's checks run.
            raw_decision = json.loads(gate_row.get("decision_json") or "{}")
            raw_decision["passed"] = final_passed
            decision_json = json.dumps(raw_decision)

            cur = self._conn.execute(
                "INSERT INTO gate_evaluations"
                "(strategy_id, passed, n_funnel, own_lifetime_combos, windowed_total_combos,"
                " funnel_window_days, breadth_provenance, pit_ok, pit_override, holdout_n_bars,"
                " min_holdout_observations, code_hash, config_hash, dependency_hash, data_source,"
                " snapshot_id, period_start, period_end, holdout_frac, actor, decision_json,"
                " consumed, created_at,"
                " fundamentals_snapshot, news_snapshot, attempt_token, universe_name)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                # Agent passing rows are born-consumed: the stage has already advanced inside
                # this transaction, so the token is spent. Leaving consumed=0 would let a
                # future `registry transition --to candidate --actor agent` reuse the old row
                # after a back-step, bypassing the gate re-run requirement.
                (rec.id, int(final_passed),
                 gate_row["n_funnel"], gate_row["own_lifetime_combos"],
                 gate_row["windowed_total_combos"], gate_row["funnel_window_days"],
                 gate_row["breadth_provenance"], int(gate_row["pit_ok"]),
                 int(gate_row.get("pit_override", False)),
                 gate_row["holdout_n_bars"], gate_row["min_holdout_observations"],
                 gate_row["code_hash"], gate_row["config_hash"], gate_row.get("dependency_hash"),
                 gate_row["data_source"], gate_row.get("snapshot_id"),
                 gate_row["period_start"], gate_row["period_end"], gate_row["holdout_frac"],
                 actor.value, decision_json,
                 int(actor is Actor.AGENT and final_passed), _now(),
                 # The fdr_* and family_* columns are historical (lean trim step 7): omitted
                 # here, so new rows leave them NULL. Rows written before keep their values.
                 gate_row.get("fundamentals_snapshot"), gate_row.get("news_snapshot"),
                 gate_row.get("attempt_token"), gate_row.get("universe_name")),
            )
            gate_id = cur.lastrowid
            assert gate_id is not None

            if run_row is not None:
                # The run verdict and evaluation ID belong to this atomic gate transaction.
                row = dict(run_row)
                row["passed"] = final_passed
                # Name the gate_evaluations row THIS run derives from — minted one line above, in
                # the SAME BEGIN IMMEDIATE, so the two ids can never mismatch or drift apart.
                row["gate_id"] = gate_id
                run_id = self._insert_run_locked("gate", rec.name, **row)
                seal_gate_comparison(self._conn, run_id)

            updated_rec: StrategyRecord | None = None
            if final_passed:
                # #246: re-assert the source-stage invariant INSIDE this locked critical section.
                # The CAS below only pins WHERE stage=rec.stage (the caller's post-walk_forward
                # re-read). If a concurrent transition drifted the strategy off BACKTESTED before
                # that re-read — e.g. to a terminal RETIRED — the CAS would happily apply a
                # forbidden RETIRED->CANDIDATE edge (ALLOWED_TRANSITIONS forbids it). Mirror
                # promotion_preflight here, atomic with the CAS, so the gate can never resurrect a
                # drifted/terminal stage. Require exactly BACKTESTED (not validate_transition, which
                # permits the legal PAPER->CANDIDATE back-step) — promotion_preflight's reasoning.
                if rec.stage is not Stage.BACKTESTED:
                    raise TransitionError(
                        f"research promote requires stage backtested at promote time, got "
                        f"{rec.stage.value} (source drifted off backtested under concurrency since "
                        f"preflight); refusing to promote")
                updated_rec = self._apply_transition_locked(
                    rec, Stage.CANDIDATE, actor, reason,
                    code_hash=gate_row["code_hash"], config_hash=gate_row["config_hash"],
                    dependency_hash=gate_row.get("dependency_hash"),
                    consume_gate_id=None, consume_forward_gate_id=None, now=_now())

            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

        return GateOutcome(gate_id=gate_id, final_passed=final_passed, updated_rec=updated_rec)

    def passing_gate_by_token(self, strategy: str, attempt_token: str) -> int | None:
        """The ``gate_evaluations.id`` of the PASSING, STRICT-AGENT row stamped with this exact
        ``attempt_token`` for ``strategy`` — the authoritative read the merge-back driver (#485)
        uses to attribute a promote outcome to THIS attempt, never to the ambient stage nor to "did
        the call raise". Returns None if no such row exists.

        The match is by exact ``attempt_token`` equality AND strict-agent context
        (``actor='agent'``, ``passed=1``): the token is a caller-supplied opaque per-attempt key
        (enforced unique by the partial index on non-null ``(strategy_id, attempt_token)``), so a
        concurrent external ``research promote`` of the same strategy — which supplies a different
        token, or NULL — can never be mistaken for this attempt's own gate row even if it mints a
        higher-id passing row in the same window.
        """
        row = self._conn.execute(
            "SELECT g.id FROM gate_evaluations g JOIN strategies s ON s.id = g.strategy_id"
            " WHERE s.name = ? AND g.attempt_token = ? AND g.passed = 1 AND g.actor = 'agent'"
            " ORDER BY g.id DESC LIMIT 1",
            (strategy, attempt_token),
        ).fetchone()
        return int(row["id"]) if row is not None else None

    def gate_exists_by_token(self, strategy: str, attempt_token: str) -> bool:
        """True iff ANY ``gate_evaluations`` row — PASSING **or** FAILING — is already stamped with
        this exact ``attempt_token`` for ``strategy``. The crash-idempotency read the merge-back
        driver (#485) uses to avoid re-invoking a metered promote whose prior (crashed) attempt
        already inserted a row and burned the holdout: because ``(strategy_id, attempt_token)`` is
        partial-unique, a second promote under the same token would late-fail on the index AFTER its
        side effects, so the driver must detect the existing row and branch on it instead of
        re-invoking. Unlike :meth:`passing_gate_by_token` this ignores ``passed`` (a failing row
        still consumed the token and burned the holdout)."""
        row = self._conn.execute(
            "SELECT 1 FROM gate_evaluations g JOIN strategies s ON s.id = g.strategy_id"
            " WHERE s.name = ? AND g.attempt_token = ? LIMIT 1",
            (strategy, attempt_token),
        ).fetchone()
        return row is not None
