---
title: "Task 2 context scoring in the canonical backtest"
type: feature
created: "2026-11-01"
status: fixes-applied-pending-verification
baseline_commit: ab70c3d5947cb7398dbdb5be93b9fe3cfe0f69ca
context:
  - docs/PRD.md
  - docs/architecture.md
---

<frozen-after-approval reason="owner-approved Task 2 integration scope">

## Intent

**Problem:** The delivered multimodal `score(context)` slice is research-only. The real loader and
canonical backtest still expose mutually exclusive legacy signal lanes, so bars, PIT news and a
pinned model cannot be evaluated together by the engine whose results feed research.

**Approach:** Bind a versioned context scorer through the existing `StrategyConfig`,
`LoadedStrategy`, loader, artifact identity and canonical backtest loop. Preserve legacy behavior,
hashes and fast-path parity; keep paper/live/frozen use explicitly unsupported and fail closed.

## Boundaries & Constraints

**Always:** Preserve `t→t+1`, point-in-time masks, model byte/pin/provenance/training cutoffs,
finite in-universe scores, existing construction/risk rails, config identity and authored-source
closure semantics. Keep frozen `DataProvider` and runtime contracts unchanged.

**Ask First:** Any change to live/paper/frozen execution, registry/DB, promotion gates, capital,
authentication/signers, CODEOWNERS, or a legacy config hash.

**Never:** Add an identity wrapper, implicit data fetch, alternate backtest engine, fabricated
timestamp, paid acquisition, deployment, merge, trade, or authority-state write.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Combined context | bars + PIT news + exact pinned model | canonical backtest scores and constructs weights | `t` decision fills no earlier than `t+1` |
| Missing/tampered input | absent news, wrong pin/bytes/provenance, future-trained model | no backtest result | fail closed before scoring |
| Invalid score | duplicate, out-of-universe, non-real or non-finite values | no weights | typed backtest refusal |
| Legacy strategy | current signal or parity-guarded panel | unchanged result and config hash | existing guards unchanged |
| Unsupported lane | context strategy loaded for paper/live/frozen | no planner execution | explicit tradability refusal |

</frozen-after-approval>

## Code Map

- `algua/strategies/base.py` and `algua/contracts/strategy_{scoring,identity,interface}.py` --
  context binding, config identity and the closed discriminator vocabulary in the pure contracts
  layer, so the planner closure gains no new strategy-layer authority.
- `algua/strategies/loader.py`, `context_loader.py` -- authored score loading and verified model
  binding without crossing the module-size floor.
- `algua/backtest/run_inputs.py`, `benchmark.py`, `context.py` -- fetched-once immutable frame-byte
  authority, verified source identities, no-refetch benchmark projection and canonical contexts.
- `algua/backtest/decision_path.py` -- canonical invocation and unchanged fast-path licensing.
- `algua/backtest/engine.py` -- provider provenance and `t→t+1` execution boundary.
- `algua/backtest/sweep.py`, `walkforward.py` -- complete loaded-state reconstruction and pinned
  result provenance; the model-sweep refusal remains unchanged.
- `tests/test_score_context_backtest.py` -- focused integration and guard acceptance.
- `scripts/multimodal_context_exercise.py` -- repeatable real-bars pilot evidence.

## Tasks & Acceptance

**Execution:**

- [x] Add focused red tests for loader/identity, combined canonical execution, guards and refusal.
- [x] Implement the smallest loader/base/context/engine integration with legacy compatibility.
- [x] Extend the read-only real-bars pilot and record honest fixture/proxy limitations.
- [x] Run only the focused Task 2 and directly adjacent tests requested for this writer phase.
- [x] Apply the first bounded review's fixes with focused red/green regressions.
- [x] Replace the reviewed multi-fetch provenance guard with the owner-approved immutable
  fetched-once run-input bundle shared by decisions, benchmark, walk-forward and every sweep combo.
- [x] Tighten root CODEOWNERS and repository hygiene for every exact moved/extracted integrity
  module; HUMAN protected review remains required before merge.

**Acceptance Criteria:**

- Given exact bars/news/model identities, when the canonical engine evaluates a context strategy,
  then only as-of inputs reach one finite `score(context)` call per decision and fills remain lagged.
- Given any required input or identity/temporal guard failure, when evaluation starts, then it fails
  closed without weights or lane admission.
- Given a legacy strategy, when loaded and backtested, then its hash and canonical/fast behavior are
  unchanged.
- Given a context provider, when a run starts, then each required source is independently pinned,
  fetched, immediately serialized and rechecked before the next source callback; identities are
  rechecked after later sidecars so cross-source drift still fails closed. All contexts, benchmark
  projection, result provenance and sweep combos consume that byte authority.
- Given provider-owned frames, consumer-returned frames or nested mutable object cells, when any
  alias is mutated after capture, then later decisions and sibling consumers still see the exact
  captured values; a frozen dataclass facade alone is not treated as immutability.
- Given a legacy protocol-only provider, when `simulate` runs, then it does not inspect optional
  snapshot metadata outside the frozen `DataProvider` interface.
- Given a bars-only or bars+news context strategy, when a sweep override is built, then the complete
  loaded state is preserved; model-backed sweep/walk-forward remains refused.

## Spec Change Log

- 2026-11-01: implementation kept the discriminator on the loaded strategy/module rather than
  extending strict frozen `StrategyConfig`; legacy hashes remain byte-identical and context hashes
  conditionally include `context_v1`.
- 2026-11-01: independent-review fix pass eagerly pins and verifies context provider identities,
  threads the verified values privately into run/walk-forward results, preserves the full loaded
  dataclass during sweep reconstruction, centralizes interface predicates, and adds exact-file
  CODEOWNERS/hygiene coverage. No frozen contract, runtime lane, parity guard or execution lag was
  relaxed.
- 2026-11-01: owner approved enforce-by-construction capture. `RunInputBundle` now stores immutable
  serialized bars/required sidecars and verified identities once at the top-level boundary.
  Simulation, decisions, benchmark, walk-forward and all sweep combinations materialize isolated
  frames from the same bytes. Pure helpers moved under `contracts` to restore the planner closure
  without an allowlist expansion; the pre-burn provenance seam and cleanup ordering remain intact.
- 2026-11-01: independent review found that serialization still occurred after all provider
  callbacks and that untracked `strategies/context_loader.py` escaped the placement test. The
  bounded author fix now performs per-source pin/fetch/serialize/verify capture, re-verifies prior
  required identities after later sidecars, and declares `context_loader.py` exact top-level
  infrastructure with a tracking-independent nonoffender assertion.

## Design Notes

The context discriminator is identity-bearing for context strategies but absent from the frozen
serialized config. Existing frozen descriptors therefore decode exactly as before, while a context
strategy cannot be represented as eligible frozen content and is refused at the tradable loader.

Context strategies are canonical-loop only: declaring `signal` or `signal_panel` alongside
`score(context)` is refused. Existing legacy `signal_panel` strategies retain the bounded runtime
and exhaustive promotion parity guards unchanged.

## Delivered and remaining

Delivered here: simultaneous bars/PIT-news/pinned-model scoring in the actual canonical engine;
exact snapshot/model identities in each immutable context; finite, unique, in-universe score
validation; first-decision model temporal checks; unchanged construction/risk rails and execution
lag; legacy config-hash and fast-path compatibility; explicit research-only tradability refusal.

The independent-review findings are fixed in the working tree. Fixes-only verification and the
coordinator's full root gate remain pending; this story is not merge-ready or delivered.

Still outside this increment: strategy-family migration/removal of legacy signal branches,
timestamped real-news evidence, PIT historical-universe evidence, and any paper/live/frozen wire or
eligibility expansion. No alpha, qualification, forward-evidence or deployment claim is made.

Human protected review targets before merge (required because this branch tightens CODEOWNERS and
touches integrity-critical modules):

1. `algua/strategies/base.py`: legacy exclusivity, model binding, authored source root and hash API.
2. `algua/backtest/decision_path.py`: canonical dispatch, PIT masks and untouched fast-path guard.
3. `algua/backtest/run_inputs.py`, `benchmark.py`, `engine.py`: immutable byte authority, one fetch,
   verified identities and provider-independent benchmark before the unchanged `t→t+1` shift.
4. `algua/strategies/tradable.py`: paper/live/frozen admission remains explicitly closed.
5. The exact Task2 CODEOWNERS additions and matching `INTEGRITY_CRITICAL_MODULES` entries: moved
   pure helpers and extracted benchmark/bundle retain exact protection; no broad ownership rule.

## Verification

**Writer-phase commands:**

- Review-fix red slice -- **2 failed, 1 passed**: immediate alias capture and exact untracked-file
  hygiene classification failed; the retained cross-source identity-drift control already passed.
- Post-fix focused Task 2 + pre-burn/planner/CODEOWNERS/hygiene suite -- **42 passed**.
- External changing-provider acceptance probe -- exit 0 for the correct lineage reason:
  `get_bars_calls=1`, primary snapshot retained, benchmark present.
- Independent-review capture-order probe -- exit 0, preserving the original bars value across a
  later sidecar callback while retaining the stable bars/news identities.
- Mutation checks for delayed serialization, omitted cross-source identity verification and omitted
  `context_loader.py` classification each failed their focused test; both guarded source files were
  restored byte-for-byte by SHA-256 comparison.
- Changed-source Ruff and mypy, plus all 29 import-linter contracts -- exit 0.
- Pilot exercise against snapshot `baaa116a36acee68` -- pass; 1,503 rows, 501 decisions, 500
  executed rows, first fill at `t+1`, future news excluded, all seven proxy/non-PIT limitations
  retained. Output is byte-identical to the author/reviewer evidence (SHA-256
  `6c68312a54028d61ebd39e1f4c9024a2457aa29cfcd9347dc98cb80285873416`).
- Independent adversarial review is complete and its two findings are fixed. A separate fixes-only
  verification and the full repository gate are intentionally pending for the coordinator after
  this sole-writer diff is frozen.

## Approved immutable fetched-run inputs

The owner approved the bounded enforce-by-construction replacement. `capture_run_inputs` captures
each source as pin, fetch, immediate serialization and verification before invoking the next source,
then re-verifies earlier required identities after later sidecars. Those bytes are the authority: every
consumer deserializes a fresh frame, severing provider aliases, pandas block aliases and nested
mutable object-cell aliases. Result stamps come from the captured identity, never a later provider
read. Walk-forward benchmark projection accepts captured bars and cannot refetch; sweep captures in
the parent before dispatch and gives every combination the same bundle bytes.

The historical `_market_return_series(strategy, provider, ...)` direct-call seam remains for its
focused compatibility tests, but production `walk_forward` calls only
`market_return_series_from_bars`. The frozen `DataProvider` protocol and bar schema are unchanged.
No paper/live/frozen lane can load a context strategy, and model-backed sweep/walk-forward remains
refused. No fixture result is alpha or qualification evidence.

## Suggested Review Order

**Identity and admission**

- Start with the loaded interface boundary and unchanged legacy adapter contract.
  [`base.py:107`](../../algua/strategies/base.py#L107)

- Confirm context identity extends, rather than replaces, canonical config hashing.
  [`strategy_identity.py:15`](../../algua/contracts/strategy_identity.py#L15)

- Verify authored score loading retains exact model resolution and source-root semantics.
  [`loader.py:86`](../../algua/strategies/loader.py#L86)

- Confirm paper/live/frozen admission fails closed before planning.
  [`tradable.py:11`](../../algua/strategies/tradable.py#L11)

**Canonical decision path**

- Review immutable capture, PIT masking, and per-run snapshot binding.
  [`run_inputs.py:95`](../../algua/backtest/run_inputs.py#L95)

- Confirm context dispatch does not alter protected fast-path licensing.
  [`decision_path.py:44`](../../algua/backtest/decision_path.py#L44)

- Verify provider identities precede the unchanged execution-lag shift.
  [`engine.py:86`](../../algua/backtest/engine.py#L86)

**Validation and evidence**

- Inspect shared finite, unique, in-universe score validation.
  [`strategy_context.py:202`](../../algua/contracts/strategy_context.py#L202)

- Trace the combined bars/news/model integration and refusal tests.
  [`test_score_context_backtest.py:191`](../../tests/test_score_context_backtest.py#L191)

- Check the honest real-bars, synthetic-news/model pilot evidence generator.
  [`multimodal_context_exercise.py:75`](../../scripts/multimodal_context_exercise.py#L75)
