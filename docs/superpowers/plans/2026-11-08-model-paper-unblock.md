# Model-paper unblock and reliability fixes implementation plan

> **For agentic workers:** Use executing-plans inline, with focused RED/GREEN checks and one final bounded review. Continue the owner's existing native execution choice.

**Goal:** Fix the reported defects, permit reviewed frozen model paper execution under the owner's explicit isolation waiver, and enable chronological evaluation of a model fixed before the entire evaluated period.

**Architecture:** Retain the existing frozen child and current supervisor. Remove the newly introduced unconditional model-only isolation refusal rather than claiming an OS sandbox. Reuse canonical backtest, sweep, walk-forward and candidate gates; admit only the supported context price-linear profile whose fixed pin predates the evaluation start.

**Tech stack:** Existing Python 3.12, uv, SQLite, Typer and pytest; no new dependencies.

**Spec:** `../specs/2026-11-07-strategy-cicd-design.md`, amended by the owner's 2026-11-08 instruction explicitly approving removal of the trading blocker. The waiver covers import-time artifact preparation and paper evaluation under the repository's accepted reviewed-code trust model. It supplies no isolation attestation, PR admission, live activation, credential access, funding or timer authorization.

## Global constraints

- Preserve signed human live approval, exact artifact/model/data identities and later-bar execution.
- Preserve verified-PR admission and its separate isolation-attestation requirement.
- Keep unsupported modalities/models refused. No fitting, model grids, `latest` resolution or future model during evaluation.
- Unchanged strict research/forward criteria remain binding. Five-session experimental qualification is a distinct follow-up once the requested economic and drawdown-policy answers arrive; no silent strict-certificate substitution.
- Use focused regressions. Do not repeat the 17-minute full suite after small fixes; classify its existing failures against the already captured baseline.

## Review focus

1. Malformed v2 resolved config must raise WireError, including null/list/scalar/bool.
2. Updating stale merge-back test wiring must not remove the public verified-PR fence.
3. Recovery must preserve retryable infrastructure failures and bounded cross-family memory.
4. Owner waiver must not be represented as sandboxing or a Task4 isolation attestation.
5. A pin after evaluation start, unsupported model profile or changed model identity must fail before evaluation/holdout use.

### Task 1: Repair error handling and stale regressions

Files: `algua/live/frozen_wire.py`, `tests/test_frozen_model_wire.py`, `tests/test_cli_merge_back.py`, `tests/test_chooser_recovery_order.py`, `tests/test_research_campaign.py`.

- [ ] Reproduce malformed v2 config with null/list/scalar/bool and exact WireError assertion.
- [ ] Validate resolved_config before model-specific dispatch; preserve v1 golden bytes.
- [ ] Reproduce the known baseline failures; align legacy saga-wiring fixtures explicitly with their private seam and add a public missing-PR proof refusal test. Keep existing real PR-admission tests.
- [ ] Update recovery tests to exercise current bounded cross-family history and retryable run_error semantics, retaining empty-menu coverage for an actually exhausted pool.
- [ ] Supply the real driver block's required REPO_ROOT in its extracted-shell fixture.
- [ ] Run focused wire, CLI merge-back, PR-admission, chooser/recovery and research-driver checks; commit logical fixes separately.

### Task 2: Apply owner-approved model-paper waiver

Files: `algua/registry/intake.py`, `algua/registry/frozen_runtime.py`, remove `algua/registry/frozen_model_policy.py`; update model-paper fixture/tests, architecture/model docs and exact protection entries.

- [ ] Remove the fixture policy bypass so actual default intake goes RED under the existing hold.
- [ ] Remove the unconditional policy and test-only bypass. Real profile/config/bundle verification remains.
- [ ] Confirm default model-paper CLI uses frozen bytes without a model store, refuses corrupt bundles and unsupported profiles, preserves order identity and still refuses live.
- [ ] Document unsandboxed reviewed-code execution, including import-time preparation and escaped-descendant exposure. Do not modify PR-admission attestation semantics.
- [ ] Run frozen-model/paper/intake/live-refusal checks; commit.

### Task 3: Permit fixed pre-period model research

Files: new `algua/backtest/model_policy.py`; `walkforward.py`, `sweep.py`; new `tests/test_fixed_model_research.py`, existing model/walk-forward/sweep tests and protection entries.

Interface: `require_fixed_model_period(strategy: LoadedStrategy, start: datetime) -> None`, no I/O or model acquisition. Legacy bars strategies return unchanged. Model strategies require context_v1, bars only, a validated price-linear handle matching the pin, and finite training_as_of <= start.

- [ ] Add real trained-fixture walk-forward and sweep success tests; assert identical fixed model and no fitting/model-store reload during evaluation.
- [ ] Add future cutoff and unsupported profile refusals before provider access or holdout callback.
- [ ] Replace blanket model refusals with this narrow guard; canonical engine retains its first-actual-bar guard. Sweep still has no model-ref grid and holdout remains hidden/burned only through promotion.
- [ ] Run focused research/model/PIT/holdout regressions, lint/type/import boundaries; commit.

## Subsequent policy-dependent delivery

The pending owner questions settle whether to reuse current experimental historical criteria and whether 20% drawdown cancels/pauses or liquidates. After answers, specify the separate five-real-session profile, its append-only per-tenant evidence and signed qualification, with explicit generic-live refusal until a capped frozen-live consumer is implemented. Do not describe that future consumer as shipped by this plan.
