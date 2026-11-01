---
title: 'Planner input contract: non-finite current weights and symbol labels'
type: 'correctness'
created: '2026-10-22'
status: 'in-review'
baseline_commit: 'a3c71fa'
context:
  - 'docs/development/stories/deferred-work.md'
  - 'docs/development/stories/1-1-extract-in-process-decision-planner.md'
  - 'docs/development/specs/spec-story-1-3c-frozen-paper-execution'
  - 'docs/agent/story-delivery.md'
  - 'AGENTS.md'
todoist:
  - 'https://app.todoist.com/app/task/6hfMw6W8mcVjQ2wp'  # NaN current-holding weight policy
  - 'https://app.todoist.com/app/task/6hfMw6Vvhv8rRgMp'  # symbol-label contract
---

<!--
Id/slug choice: these are two deferred correctness reviews from Story 1.1, not Epic 1/2 stories,
so this follows the repository's quick-spec convention for non-epic work
(`docs/development/stories/spec-<slug>.md`, as `spec-strategy-board.md` and
`spec-dashboard-decision-layer.md` do) and is not added to sprint-status.yaml. One combined spec
because both findings live in the same function and resolve to one shared input contract.
-->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `build_intents` (`algua/live/planner_decision.py:34-45`) is the one function that
turns target weights and current holding weights into order intents. It trusts both inputs:

1. A **non-finite current weight** is silently mishandled. `abs(target - NaN) > WEIGHT_TOL` is
   `False`, so a NaN holding produces **no intent at all**, whatever the target (reproduced on
   `a3c71fa`: target 0.5 → `[]`; target 0.0, i.e. an exit → `[]`). A `+inf` holding produces a
   `SELL` intent toward a positive target. Either way the planner emits a decision that is not a
   function of the true book, without raising.
2. **Symbol labels have no type contract on the strategy side.** `check_finite_weights` rejects null
   and duplicate labels but not non-string ones, and `check_universe_membership` admits any
   zero-weight label. `build_intents` then calls `sorted(set(weights.index) | set(current_weights))`
   with no key, so a strategy returning `{1: 0.0, "AAPL": 0.5}` against string holdings raises a bare
   `TypeError` (reproduced). The same bare `sorted(...)` appears in the risk rails' *error messages*
   (`algua/risk/limits.py:121,135,178,192`): a mixed-label Series that trips the finite, cap or
   long-only rail raises `TypeError` instead of `RiskBreach`, so it escapes the
   breach → kill-switch routing (`paper_cmd` traps `RiskBreach` only) and is reported as a generic
   error instead.

Neither has a known production incident. Both pre-date the Story 1.1 extraction.

**Approach:** Define one **planner input contract**, enforced at the planner boundary and shared
with the risk rails rather than duplicated in the planner:

- every symbol label (strategy target-weight index **and** current-weight keys) is a non-empty
  `str`;
- every current weight is a finite `float`;
- a violation **fails closed** (raises before any intent is built). It never coerces to flat or
  skips the symbol.

All of this is already true for the frozen/operational path, which validates captured state
upstream. The change makes the in-process planner and the shared rails enforce the same contract
instead of relying on every caller to have done it.

## Boundaries & Constraints

**Always:** fail closed; keep `validate_decision_weights` the one weight-validation path for
backtest, paper and live (no planner-only drift); keep `DECISION_BREACH_KINDS` and the frozen
child's closed `RISK_BREACH_KINDS` vocabulary unchanged unless the owner picks option N2 below;
preserve the `t→t+1` rule, the live gate and the JSON command contract; test-first, with a
mutation check on every new guard.

**Ask first:** adding a new `RiskBreach` kind; changing the breach routing (kill-switch vs. account
halt) of any existing kind; any change to backtest results for a registered strategy.

**Never:** treat a NaN holding as 0.0 (that would buy the full target on top of an unknown real
position); silently drop or skip a symbol; widen what a frozen child may report.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Today (`a3c71fa`) | Expected after this spec |
|---|---|---|---|
| NaN holding, nonzero target | `current={"AAPL": nan}`, target 0.5 | `[]`, no error | Fails closed before intents |
| NaN holding, exit | `current={"AAPL": nan}`, target 0.0 | `[]`, the position is never exited | Fails closed before intents |
| +inf / -inf holding | `current={"AAPL": inf}` | `SELL` toward 0.5 | Fails closed before intents |
| Non-str holding key | `current={1: 0.1}` | TypeError in sort, or accepted | Fails closed (contract error) |
| Mixed target labels, zero weight | `{1: 0.0, "AAPL": 0.5}` | Rails pass; `build_intents` raises bare TypeError | `RiskBreach("non_finite_weight")`, "non-string symbol label" |
| Mixed labels that breach a rail | `{1: -0.1, "A": -0.1}`, long-only | Bare TypeError while rendering the message | `RiskBreach` of the right kind; message rendered with `key=str` |
| Empty-string label | `{"": 0.1}` | Accepted | `RiskBreach("non_finite_weight")` |
| Valid inputs | str labels, finite weights | Sorted delta intents | Byte-identical intents (parity) |

</frozen-after-approval>

## Evidence (baseline `a3c71fa`)

**Where the gap is**

- `algua/live/planner_decision.py:34-45`: `build_intents`. There is no finiteness or label-type check
  on `current_weights`, and an unkeyed `sorted(set(weights.index) | set(current_weights))` at
  line 39.
- `algua/live/planner_decision.py:48-54`: `canonical_weights` already sorts with `key=str`, so
  normalization tolerates mixed labels and the failure surfaces only later, in `build_intents`.
- `algua/live/planner_decision.py:57-69`: `plan()` validates target weights (via `canonical_weights`
  and `validate_decision_weights`) but passes `inputs.current_weights` through unchecked.
- `algua/risk/limits.py:107-139`: `check_finite_weights` rejects null labels (line 115), duplicates
  (line 120), bool/non-numeric dtype and non-finite values, but not non-`str` labels. Its own
  messages sort without `key=str` (lines 121, 135).
- `algua/risk/limits.py:142-167`: `check_universe_membership` admits zero-weight labels of any type
  and is the one rail that already renders with `key=str` (line 166).
- `algua/risk/limits.py:178,192`: the per-symbol cap and long-only messages sort without `key=str`.
- `algua/risk/limits.py:72-74`: `DECISION_BREACH_KINDS` already contains `non_finite_weight`, which
  already covers *label* defects (null, duplicate). That is the precedent for reusing it in label
  option L1.

**Callers and where `current_weights` comes from**

- `algua/live/paper_loop.py:96-100` (`run_paper`, the `paper run` sim replay): computes
  `qty * bar_closes.get(s, 0.0) / equity` with no finiteness check. A held symbol whose close is NaN
  at `t` would give a NaN weight. Today the equity guard at `paper_loop.py:88` fires first, because
  `SimBroker.equity` (`algua/execution/sim_broker.py:53-55`) also goes NaN, so the case is caught as
  `non_positive_equity` (fail-closed, but with a misleading kind). A held symbol missing from the
  `closes` columns is valued at `0.0` by both `.get` defaults: the holding becomes invisible rather
  than NaN.
- `algua/live/planner_late.py:84-109` (frozen/operational tick): already enforces the contract.
  `_numeric_mapping` (`:121-135`) requires non-empty `str` keys (NFC-normalized) and finite values
  through `_finite_number` (`:112-118`), then derives `current_weights` at `:96-98`.
- `algua/live/frozen_attempt.py:78-90`: the supervisor re-derives the child's intents with
  `build_intents` from the validated `verdict.current_weights`.
- `algua/live/frozen_wire_json.py:232-242`: wire `decode_pairs` requires `str` symbols, sorted and
  unique, with finite values.
- `algua/live/planner_binding.py:71,95`: bar symbols and planner mapping keys must be non-empty
  strings. `algua/data/schema.py:42-43`: bar symbols must be strings.
- `algua/live/live_loop.py:41`: re-exports `decide`. Live sizing goes through the late planner
  above.

**What follows from the callers:** the NaN-holding path is **latent**. Every operational caller
validates upstream, and the only unvalidated caller (`run_paper`) is shielded by an incidental
guard. The label path is **reachable** from any strategy whose `target_weights` returns a
non-string index label, through `plan()`/`decide()` in-process and through the shared rails in
backtests.

**Existing tests**

- `tests/test_planner.py:56-64` covers NaN *target* weights (`non_finite_weight`) only.
- No test covers NaN or inf *current* weights in `build_intents` or `plan`, mixed or non-string
  target labels, or non-string current-weight keys.
- `tests/test_live_loop.py` covers the late planner's captured-value validation.
- `tests/test_frozen_dispatch.py` pins `DECISION_BREACH_KINDS`. `tests/test_failure_vocabularies.py`
  pins `RISK_BREACH_KINDS`.

## Options

### Non-finite current weight (Todoist 6hfMw6W8mcVjQ2wp)

| Option | Behavior | For | Against |
|---|---|---|---|
| **N1. Fail closed: contract error (recommended)** | `plan()`/`build_intents` raise `ValueError("current_weights[...] must be a finite number")`, mirroring `planner_late._finite_number` | Same contract and error style the frozen path already uses. No vocabulary change. Unreachable from validated callers, so no operational behavior change. | A contract `ValueError` is not a `RiskBreach`, so it does not trip the strategy kill switch. It is reported as a generic error, which is correct for a caller bug. |
| N2. Fail closed: dark-feed breach | Raise `RiskBreach("unvaluable_marks")` (in `DARK_FEED_KINDS`): halt the account, preserve positions | Matches the real-world cause (an unvaluable mark) and routes to halt-and-preserve | Puts a strategy-free wall inside the pure decision step. A frozen child must not report it (`DECISION_BREACH_KINDS`), so the two paths would diverge. Needs routing review. |
| N3. Flatten (NaN → 0.0) | Treat the holding as flat and emit the target delta | Never blocks a tick | **Unsafe:** with an unknown real position it can buy the full target on top of it (over-exposure), or skip the exit of a real holding. Violates "never silently flatten" (`limits.py:108-112`). |
| N4. Skip with alert | Today's omission plus an audit/alert row | Minimal change | Keeps a stale position silently. The decision is still not a function of the book. Alert-only is fail-open. |

Also in scope with N1 or N2: in `run_paper`, check marks for held symbols *before* sizing, so a NaN
or missing close for a held symbol raises `RiskBreach("unvaluable_marks")` instead of the
misleading `non_positive_equity`, and a held symbol absent from `closes` is no longer valued at 0.0.
This uses an existing kind and is the same semantics the live lane applies (`assert_marks_usable`).

### Symbol-label contract (Todoist 6hfMw6Vvhv8rRgMp)

| Option | Behavior | For | Against |
|---|---|---|---|
| **L1. Validate at the shared rail (recommended)** | `check_finite_weights` also rejects any label that is not a non-empty `str`, raising `RiskBreach("non_finite_weight")`. `build_intents` checks `current_weights` keys the same way (`ValueError`). Every rail message sorts with `key=str`. | One rule for backtest, paper and live. Reuses a decision kind that already covers label defects. Matches wire, bars and late-planner rules. | The kind name says "weight", not "label". It can newly reject a backtest that today passes with a zero-weight non-`str` label (readiness must scan registered strategies). |
| L2. Planner-only validation | Check labels in `plan()` only | Smallest diff | The planner-only drift the Todoist card warns against. Backtests and the live rails disagree. |
| L3. New kind `invalid_symbol_label` | As L1 with a new `RiskBreach` kind | Precise name | Changes the frozen child's closed vocabulary and `DECISION_BREACH_KINDS`. A wider contract change and readiness rerun for Story 1.3c §7. |
| L4. Coerce with `key=str` everywhere | Sort with `key=str` and accept any hashable label | Never raises | Hides the bug. `1` and `"1"` collide in messages and broker symbols. A non-`str` symbol can still reach `OrderIntent`. |

Out of scope, noted: strategy-side NFC normalization of labels (the late planner normalizes
captured keys; strategy weights are not normalized). It needs a separate parity check.

## Recommendation

**N1 + L1, with the `run_paper` mark check**, all fail-closed:

- labels on both inputs must be non-empty `str`;
- current weights must be finite;
- target-label defects use the existing `non_finite_weight` decision breach;
- current-weight defects are contract `ValueError`s that mirror `planner_late`.

No new breach kind and no change to the frozen vocabulary. Valid inputs produce byte-identical
intents.

## Owner decision

Lior approved on 2026-10-22:

1. **N1.** Fail closed with a contract `ValueError` for NaN/inf current weights.
2. **L1.** Labels must be non-empty `str`, enforced in `check_finite_weights` as `non_finite_weight`.
3. The `run_paper` held-symbol mark check.

## Code Map (for the implementing story, after approval)

- `algua/risk/limits.py`: label-type rule in `check_finite_weights`; `key=str` in every rail
  message.
- `algua/live/planner_decision.py`: `current_weights` contract check (`str` keys, finite values)
  shared by `plan()` and `build_intents`. Prefer one helper reused from, or moved beside,
  `planner_late._numeric_mapping` over a third copy.
- `algua/live/paper_loop.py`: held-symbol mark check before sizing.
- `tests/test_planner.py`, `tests/test_risk_limits.py`, `tests/test_decision_parity.py`,
  `tests/test_frozen_dispatch.py`: new cases plus parity.

## Tasks & Acceptance

**Execution (after owner approval):**
- [x] Readiness: scan registered strategies and `algua/strategies/` for non-`str` weight labels;
  rerun readiness if any exist.
- [x] Tests first: one failing test per I/O-matrix row.
- [x] Implement N1/L1 (or the chosen options) and the `run_paper` mark check.
- [x] Mutation-check each new guard (break it, confirm a test fails, restore it).
- [x] Independent review round (story-delivery §4); record findings here.

**Acceptance Criteria:**
- Given a NaN, +inf or -inf current weight for any symbol, when `plan()` or `build_intents` runs,
  then it raises before returning any intent and no symbol is silently omitted.
- Given a target-weight Series with any non-`str` or empty-string label, when
  `validate_decision_weights` runs, then it raises `RiskBreach` of kind `non_finite_weight` naming a
  non-string symbol label. This holds identically in the backtest, paper and live paths.
- Given mixed-type labels that also breach the cap, long-only or finite rail, when the breach
  message is rendered, then a `RiskBreach` of that rail's kind is raised, never a bare `TypeError`.
- Given a `current_weights` mapping with a non-`str` key, when `plan()` or `build_intents` runs,
  then it raises a contract error before any intent is built.
- Given a held symbol with a NaN or missing close at decision bar `t` in `run_paper`, when the bar
  is processed, then the loop raises `RiskBreach("unvaluable_marks")` before sizing.
- Given valid inputs, when compared to baseline `a3c71fa`, then intents, the frozen-attempt
  comparison (`frozen_attempt.py:89`) and decision-parity tests are unchanged.
- `DECISION_BREACH_KINDS` and `RISK_BREACH_KINDS` are unchanged (under options N1 and L1).

## Test Plan

- `tests/test_planner.py`: parametrize `build_intents` and `plan` over NaN, +inf and -inf current
  weights, with targets of 0.0 and 0.5. Add non-`str` and empty current keys, and mixed target
  labels.
- `tests/test_risk_limits.py`: each rail (finite, cap, long-only, universe) with mixed labels raises
  `RiskBreach`, not `TypeError`. Non-`str` and empty labels raise `non_finite_weight`.
- `tests/test_paper_loop.py`: held symbol with a NaN close and held symbol
  missing from `closes` both raise `unvaluable_marks`.
- Parity: the existing `tests/test_decision_parity.py` and `tests/test_frozen_dispatch.py` stay
  green unmodified.
- Gate: `uv run pytest -q && uv run ruff check . && uv run mypy algua && uv run lint-imports`.

## Out of Scope

- New `RiskBreach` kinds or breach-routing changes (unless the owner picks N2 or L3).
- NFC normalization of strategy-returned labels.
- Broker or ledger valuation changes outside `run_paper`'s held-symbol mark check.
- Any live-activation, capital or authority-boundary change.

## Implementation record

### Approved implementation retained

The original PR #712 implements owner-approved N1 + L1 and the held-symbol mark check.
`build_intents` validates all current holdings through the shared `numeric_mapping` before
constructing any `OrderIntent`, with `normalize=False` to preserve raw symbol identities.
`planner_late` keeps the shared helpers' default NFC normalization and collision rejection.
Target labels are checked at `check_finite_weights`; no new breach kind is introduced.

The earlier implementation reported a synthetic readiness scan of 26 bundled strategies and an
empty local registry. That is historical evidence, not a fresh scan of this integration tree or
production. This recovery did not open a production registry or repeat registry readiness checks.

### Integration recovery — 2026-11-01

This subsection records the prior author handoff; the bounded independent-review fixes below
supersede its then-open scalar findings.

Lior explicitly authorized Codex authorship for this bounded recovery. The coordinator supplied
the sole integration worktree after merging current main `d6f5d1a25619469e08382ae2139d7a1306354fdd`
into original `8818d32`. Those Git identities are coordinator-provided; the author ran no Git
commands, created no commit and performed no merge/deployment/activation.

Only the original eight paths were permitted. Fresh changes are confined to `paper_loop.py`,
`limits.py`, the three original test files and this nonfrozen execution record. The retained
`planner_decision.py` and `planner_late.py` bytes are unchanged after every mutation is restored.
The aggregate entry in the supplied source is named `plan_portfolio` (there is no
`plan_aggregate` definition). Its complete function source is byte-identical to the verified
current-default copy; `portfolio/allocator.py` and all frozen wrappers remain unchanged.

**Test-first fixes:**

- Important: tuple labels represented by a pandas `MultiIndex` raised `NotImplementedError`
  inside `Index.isnull`, escaping L1. The new two-case shared-rail regression first produced
  one failure and one pass. Skip the unsupported null-index operation for `MultiIndex`; the
  existing label guard then rejects its tuple symbols as `non_finite_weight`.
- Important: after a healthy real fill, an unusable held close could reach drawdown before the
  mark check. The new five-case regression first produced three failures (`-inf`, `0`, `-1`
  reported `drawdown`) and two passes. Post-warm-up held-mark validation now precedes drawdown;
  warm-up keeps its original drawdown check. This completes the already approved held-mark
  `unvaluable_marks` outcome; breach kinds, routing tables, risk thresholds and live gates are
  unchanged. The acceptance reviewer confirmed this specific fix in one verification pass.

**Fresh coverage:**

- Both `plan` and `build_intents`: NaN, +inf and -inf current holdings against targets `0.0`,
  `0.5` and an omitted target (exit). A valid earlier-sorted symbol needs an order, while an
  `OrderIntent` sentinel proves that no intent is constructed before the later invalid holding
  is rejected with an exact `ValueError` rather than `RiskBreach`.
- Shared finite rail: non-string/empty/tuple labels; stable mixed duplicate-label errors.
  Existing direct mixed-label cap, short-policy and universe sibling tests remain intact.
- Unicode: decomposed holding at target, actual buys/sells/exits, and simultaneous raw/NFC
  holdings remain distinct; late's default normalization and collision rejection remain tested.
- Paper: held marks missing, NaN, +inf, -inf, zero and negative reject before decision/sizing
  or order submission, with a positive finite held-mark control that actually submits orders.
  A separate enabled-drawdown test first fills a real position, then corrupts its next close.
- Current portfolio allocation/replay, late planner, frozen dispatch/attempt/runtime/wire,
  decision/lane parity, closed breach vocabularies and the unchanged module ratchet all pass.

**Actual current-default-source RED:** the author copied only
`task3-portfolio/algua/live/planner_decision.py` to the external evidence directory, verified
its builder has the same unguarded contract and its `plan_portfolio` source is identical, then
loaded that copied module without modifying the other worktree. All 18 N1 cases failed because
`ValueError` was not raised. Dependencies were supplied by this integration environment; this
is a source-level reproduction, not a Git/head or deployed-runtime certification.

**Mutations:** 16 sequential mutations each exited 1 on the intended regression assertion or
expected-exception mismatch; each source file was restored byte-for-byte before continuing.
They cover current mapping/finite/key checks, raw Unicode identity, late default NFC/collisions,
label validation/rendering, MultiIndex handling, direct cap/long-only rendering, and held-mark
call/missing/finite/positive/precedence checks. No collecting/import failure was counted as a
killed mutation. Duplicate/value diagnostic `key=str` calls are downstream of the string-label
rail; their historical non-killing mutations are not claimed as fresh killed guards here.

**Source-closure inspection:** both planner/late runtime first-party closures contain the shared
validator and aggregate allocator, with no registry, execution, operator, data or CLI authority.
The sampled `cross_sectional_momentum` identity closure does not include the planner: identity
roots remain signal/construction/overlays, not universal orchestration coverage. Frozen source
export covers `algua/`, but no export/preparation or trust-anchor change was performed.

**Scalar-contract findings at the prior handoff (historical):**

The following were unpatched at that handoff. Both are resolved by the explicitly authorized
bounded disposition below; they are no longer unresolved blockers.

- Important, `planner_decision.py:43`: finite `numpy.float64(0.5)` current holdings are rejected
  by the retained exact built-in numeric check. Native `0.5` passes. The old unguarded builder
  accepted NumPy floats. Decide the supported scalar contract before broadening the shared
  captured-state validator; this recovery does not claim that compatibility is resolved.
- Minor, `planner_decision.py:46`: `10**400` raises `OverflowError` during conversion rather than
  `ValueError`. It still fails closed. Decide whether oversized numeric inputs belong in the
  shared helper's contract before altering late validation.

These observations and the paper finding came from one read-only blind/edge/acceptance review
round. The paper fix alone received a subsequent bounded verification; no further review loop.

### Bounded independent-review disposition — 2026-11-01

The fresh independent reviewer returned **REQUEST CHANGES** for finite `numpy.float64(0.25)`
holdings rejected by `build_intents`, `plan` and `plan_portfolio`, and oversized native integers
escaping as `OverflowError`. Lior explicitly authorized fixing these compatibility and error-type
bugs without another approval wall. This is an author verification of those fixes, not a new
independent approval or a new broad review round. The original reviewer and author evidence
remains unchanged outside the repository.

- **Important — resolved:** the shared `finite_number` / `numeric_mapping` helpers now expose
  `allow_real_scalars=False`. Only current holdings in `build_intents` opt in, accepting finite
  `numbers.Real` scalars including NumPy floats/integers and converting them once to native float.
  Booleans and strings remain rejected. There is no third validator implementation.
- **Minor — resolved:** float-conversion overflow becomes the existing finite-number contract
  `ValueError`, including both signs of `10**400`. Finite native late-state numbers keep their
  prior values.
- **Preserved:** both helpers default to exact native `int`/`float` types; the actual late
  captured-state calls retain those defaults. NumPy scalars, booleans and strings remain invalid
  there. Late NFC normalization/collision rejection, raw current-symbol identity, refusal before
  intent construction, breach vocabularies and risk controls are preserved.
- Only `planner_decision.py`, `tests/test_planner.py` and this nonfrozen record changed during
  this bounded pass. The complete `plan_portfolio` source remains byte-for-byte unchanged.
  No frozen decoder, safety/cap/CI file, DB, trading, deployment or publication operation is part
  of this pass; no Git commands or commits were made.

**Test-first evidence:** before the fix, the new targeted selection exited 1 with **42 failed,
74 passed**: 36 finite NumPy compatibility failures and six leaked overflow exceptions. After
the minimal helper change, the identical selection exited 0 with **116 passed**. Tests cover
native and NumPy real scalars across all three entry points with actual buys/reductions/exits,
native parity controls, current bool/string/non-finite refusal, default helper and actual late
captured-state rejection, native late valid numbers and oversized-integer refusal before intents.

**Mutation evidence:** eight sequential mutations were killed by the intended test assertions,
not collection/import errors: remove the builder opt-in, stop forwarding the mode, loosen either
helper default, accept booleans, accept strings, leak overflow and bypass finiteness. Each was
restored byte-for-byte to the fixed source before proceeding. Exact commands/exits, logs and
restoration records are in `bounded-commands.jsonl` and `bounded-mutations.json` under the evidence
directory. The separate report is `bounded-fix-report.md`.

## Spec Change Log

- 2026-10-22: owner approved N1 + L1 and the held-symbol mark check; original implementation
  and review fixed raw Unicode identity preservation without changing late NFC defaults.
- 2026-11-01: recovered the retained implementation against coordinator-integrated current main;
  added missing matrix/sentinel/Unicode/held-mark coverage, fixed MultiIndex error handling and
  held-mark/drawdown precedence test-first, and replaced stale gate evidence with fresh results.
  Frozen owner intent, breach vocabulary, aggregate function and protected siblings are unchanged.
- 2026-11-01: resolved the independent review's finite-scalar and overflow findings test-first
  using an explicit current-holdings scalar mode and shared conversion error normalization.
  Kept exact late defaults, the complete aggregate function, frozen owner intent and old evidence.

## Verification — prior author handoff

All commands used the explicit interpreter
`/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python`.
The final focused test command was:

```bash
/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python -m pytest -q tests/test_planner.py tests/test_risk_limits.py tests/test_paper_loop.py tests/test_portfolio_allocator.py tests/test_portfolio_risk_estimates.py tests/test_book_portfolio_parity.py tests/test_book_portfolio_controls.py tests/test_live_loop.py tests/test_planner_parity.py tests/test_decision_parity.py tests/test_frozen_dispatch.py tests/test_frozen_attempt.py tests/test_failure_vocabularies.py tests/test_module_size_ratchet.py tests/test_frozen_runtime.py tests/test_frozen_wire_result.py tests/test_frozen_wire.py tests/test_lane_parity.py tests/test_registry_approvals.py::test_code_hash_covers_construction_module -o cache_dir=/home/liornisimov/.hermes/profiles/algua/cache/scratch/pr712-evidence/pytest-cache
```

Exit 0: **672 passed in 30.12s**, including the module ratchet.

Final static commands (each exit 0):

```bash
/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python -m ruff check . --no-cache
/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python -m mypy algua --cache-dir /home/liornisimov/.hermes/profiles/algua/cache/scratch/pr712-evidence/mypy-cache
/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python .venv/bin/lint-imports --no-cache
```

Mypy: 376 source files. Import-linter: 29 kept, 0 broken.

**Full pytest gate was not run**, as explicitly reserved for the coordinator under its frozen
lock. No historical resource-budget waiver is used as acceptance evidence. This is an author
handoff, not merge approval or a claim that the full gate is green. Status remains `in-review`.

Exact argv/exits, RED logs, mutation logs/restoration hashes, source snapshots/closure reports,
review prompts/results and the separate `author-report.md` are outside the repository at
`/home/liornisimov/.hermes/profiles/algua/cache/scratch/pr712-evidence`.

## Verification — bounded independent-review fixes

The same explicit `.venv/bin/python` interpreter ran the new RED/GREEN selection, all eight
mutations and the final focused siblings. Final focused result: **736 passed, 14 deselected**
in 13.56s, exit 0. The selection covers planner/risk/paper, aggregate allocation/replay,
live/late and decision parity, frozen dispatch/attempt/wire/result validation, closed breach
vocabularies and the module ratchet. Four DB-backed test functions and two real-child test
functions (14 parameterized cases total) were explicitly deselected to keep DB operations and
alternate-interpreter launches outside this pass. No tests were changed to disable them.

Targeted static checks also exited 0:

```bash
/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python -m ruff check algua/live/planner_decision.py tests/test_planner.py --no-cache
/home/liornisimov/Projects/algua/.worktrees/pr712-current-integration/.venv/bin/python -m mypy algua/live/planner_decision.py --cache-dir /home/liornisimov/.hermes/profiles/algua/cache/scratch/pr712-evidence/bounded-mypy-cache
```

The exact focused pytest argv, deselections and exits are saved in `bounded-commands.jsonl`;
the runnable selection is `bounded_focused.py`. This pass did **not** run the full pytest,
repository-wide Ruff/mypy or import-linter gates and does not claim those gates are green.
The prior handoff results above remain dated evidence only. The spec remains `in-review`.
The separate `bounded-fix-report.md` records disposition and preservation checks.

## Suggested Review Order

- Check the approved caller contract and unchanged raw identities.
  [planner_decision.py:86](../../../algua/live/planner_decision.py#L86)
- Reject tuple labels through the existing shared label rail.
  [limits.py:122](../../../algua/risk/limits.py#L122)
- Validate held marks before interpreting post-warm-up economic losses.
  [paper_loop.py:111](../../../algua/live/paper_loop.py#L111)
- Verify no intent construction can precede a later invalid holding.
  [test_planner.py:163](../../../tests/test_planner.py#L163)
- Check real-fill bad-mark classification under an enabled drawdown breaker.
  [test_paper_loop.py:163](../../../tests/test_paper_loop.py#L163)
- Check shared-rail tuple and mixed duplicate label diagnostics.
  [test_risk_limits.py:227](../../../tests/test_risk_limits.py#L227)
