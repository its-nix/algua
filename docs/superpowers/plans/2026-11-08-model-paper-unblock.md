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
- Unchanged strict research/forward criteria remain binding. The owner selected current historical criteria plus five real scheduled paper sessions for a separate experimental qualification; no strict-certificate substitution or live authority. Layered drawdown is being discussed, not activated here.
- Use focused regressions. Do not repeat the 17-minute full suite after small fixes; classify its existing failures against the already captured baseline.

## Review focus

1. Malformed v2 resolved config must raise WireError, including null/list/scalar/bool.
2. Updating stale merge-back test wiring must not remove the public verified-PR fence.
3. Recovery must preserve terminal run_error history and bounded cross-family memory without reoffering an already attempted campaign hypothesis.
4. Owner waiver must not be represented as sandboxing or a Task4 isolation attestation.
5. A pin after evaluation start, unsupported model profile or changed model identity must fail before evaluation/holdout use.

### Task 1: Repair error handling and stale regressions

Files: `algua/live/frozen_wire.py`, `tests/test_frozen_model_wire.py`, `tests/test_cli_merge_back.py`, `tests/test_chooser_recovery_order.py`, `tests/test_research_campaign.py`.

- [x] Reproduce malformed v2 config with null/list/scalar/bool and exact WireError assertion.
- [x] Validate resolved_config before model-specific dispatch; preserve v1 golden bytes.
- [x] Reproduce the known baseline failures; align legacy saga-wiring fixtures explicitly with their private seam and add a public missing-PR proof refusal test. Keep existing real PR-admission tests.
- [x] Update recovery tests to exercise current bounded cross-family history and retryable run_error semantics, retaining empty-menu coverage for an actually exhausted pool.
- [x] Supply the real driver block's required REPO_ROOT in its extracted-shell fixture.
- [x] Run focused wire, CLI merge-back, PR-admission, chooser/recovery and research-driver checks; commit logical fixes separately.

### Task 2: Apply owner-approved model-paper waiver

Files: `algua/registry/intake.py`, `algua/registry/frozen_runtime.py`, remove `algua/registry/frozen_model_policy.py`; update model-paper fixture/tests, architecture/model docs and exact protection entries.

- [x] Remove the fixture policy bypass so actual default intake goes RED under the existing hold.
- [x] Remove the unconditional policy and test-only bypass. Real profile/config/bundle verification remains.
- [x] Confirm default model-paper CLI uses frozen bytes without a model store, refuses corrupt bundles and unsupported profiles, preserves order identity and still refuses live.
- [x] Document unsandboxed reviewed-code execution, including import-time preparation and escaped-descendant exposure. Do not modify PR-admission attestation semantics.
- [x] Run frozen-model/paper/intake/live-refusal checks; commit.

### Task 3: Permit fixed pre-period model research

Files: new `algua/backtest/model_policy.py`; `walkforward.py`, `sweep.py`; new `tests/test_fixed_model_research.py`, existing model/walk-forward/sweep tests and protection entries.

Interface: `require_fixed_model_period(strategy: LoadedStrategy, start: datetime) -> None`, no I/O or model acquisition. Legacy bars strategies return unchanged. Model strategies require context_v1, bars only, a validated price-linear handle matching the pin, and finite training_as_of <= start.

- [x] Add real trained-fixture walk-forward and sweep success tests; assert identical fixed model and no fitting/model-store reload during evaluation.
- [x] Add future cutoff and unsupported profile refusals before provider access or holdout callback.
- [x] Replace blanket model refusals with this narrow guard; canonical engine retains its first-actual-bar guard. Sweep still has no model-ref grid and holdout remains hidden/burned only through promotion.
- [x] Run focused research/model/PIT/holdout regressions, lint/type/import boundaries; commit.

### Task 4: Record the approved five-session experimental qualification

Files: `registry/db/experimental.py` (schema v50), `registry/experimental_sessions.py`,
`registry/experimental_qualification.py`, `cli/paper_experimental.py`,
`operator/paper_observations.py`, existing session runner and CLI registration.

- Count five contiguous completed exchange sessions, not five returns or historical replay.
- Only the non-overridden real paper operator attaches observations, using a pre-run tick watermark.
  Bind each tenant to its active frozen epoch, successful Phase B invocation, exact identities,
  account, snapshot, broker clock and clean reconciliation. Observe per-tenant outcomes even when
  a sibling makes the aggregate job fail; completion markers retain their existing rules.
- Reuse current passed PIT historical criteria (sealed non-reused committed holdout, >=63 bars,
  positive holdout Sharpe); bind canonical gate/run/series/burn rows without requiring optional
  comparison-board metadata. Delisting-aware evaluation remains eligible.
- Append immutable observations and a distinct qualification. Agent preview cannot record it;
  authenticated human signature binds the full profile/evidence/epoch and is single use. Recheck
  under the write lock. Do not advance stages or mint strict forward/live certificates.
- Preserve model input identities through WF/sweep output and ledger, using a closed five-field
  projection. Keep holdout diagnostics and vectors private.
- Test missing/gapped/stale/mixed-account sessions, failing siblings, bad historical lineage,
  delisting-aware lineage, signed challenges/replay, old-schema migration and disclosure fences.

## Remaining live/risk work

The owner asks about configurable layered drawdown. Recommended starting policy: 10% reduces the
approved normal exposure budget to 50%, 20% halts/cancels then reconciles before controlled exit.
The proposal requires cash-flow-aware account/book tracking, durable severity, authenticated
restoration/configuration changes, aggregate resizing including existing holdings and bounded
risk-reduction orders with healthy venue state. Current raw-equity/market-liquidation controls
must be reconciled explicitly before activation. This change does not implement that controller,
a capped frozen-live consumer, funding, deployment or activation. Preserve the generic frozen-live
refusal and signed live gate.

## Delivery notes — 2026-11-08

Findings fixed:

- Minor: `algua/live/frozen_wire.py:250` — validate malformed resolved config before v2 dispatch
  (`4efa9a9`); wire regressions: 123 passed.
- Important: `algua/backtest/walkforward.py:166` — retain the exact fixed model pin in public
  result and ledger without exposing holdout payloads (`142328e`).
- Important: `algua/registry/experimental_qualification.py:19` — bind canonical gate/series/burn
  lineage, including valid delisting-aware runs, rather than optional comparison-board metadata
  (`07b8d63`).
- Important: `algua/operator/session_runner.py:176` — capture per-tenant outcomes before aggregate
  completion routing so a sibling failure cannot erase another tenant's observation (`07b8d63`).
- Existing stale fixtures: merge-back tests now explicitly exercise their legacy private saga
  and separately prove the public PR wall; recovery/driver fixtures follow current protocols
  (`1f503a4`). The unconditional model-only hold was removed under the owner waiver (`eaa52e0`).

Verification: 443 focused Linux tests passed across model research, paper integration, five-session
qualification, actual SSH signing/replay, migration, disclosure, tracking, owned comparison lineage,
repo hygiene and size limits. A final pure-projection boundary correction was checked with 198
focused tests, Ruff, mypy (453 source files), and all 31 import contracts (0 broken). The preceding
combined 367-test run passed 361 and exposed six schema
version/fingerprint assertions; these were deliberately updated with the new v50 migration and
passed in the final scope. Full-suite/CI repetition was intentionally omitted under the fast
policy. Native macOS cannot run the existing Linux-only process containment tests (`os.waitid`);
Linux validation used the lockfile-matching image with network disabled. No live account, service,
timer or funding was activated. The proposed layered drawdown controller and capped frozen-live
consumer remain explicit follow-up implementation work, not shipped controls.
