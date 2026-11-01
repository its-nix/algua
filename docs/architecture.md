# Algua architecture — implementation map and target design

**Product authority:** [Vision of Record](PRD.md). This document maps current implementation;
the [reconciliation record](vision-reconciliation.md) tracks the gap to the target architecture
and the PRD §25 development sequence. Earlier specs do not override that sequence.

**Evidence baseline:** source, tests and merged changes through `a062a66` (PRs #719–#726).
The October 2026 approved product direction is incorporated here and in the PRD; target design is
explicitly separated from implemented behavior. Source inspection establishes capabilities and
refusals, not deployment or unattended acceptance. The September reconciliation is dated context;
its older artifact, capital-policy and CODEOWNERS observations must be read against current source.
This map grants no operating, deployment, capital or activation permission.

**Read this before adding anything.** It tells you which package owns what, and where the
extension points are. If you find yourself editing a core file to add a provider, broker, calendar,
tracker or command, stop — there is almost certainly a registration seam for it below.

The boundaries here are **enforced, not advisory**: 29 import-linter contracts
(`uv run lint-imports`) and a per-module size ratchet (`tests/test_module_size_ratchet.py`). If your
change fights a boundary, the boundary is usually right.

---

## The shape

The target is a **modular monolith + isolated live runtime + background workers** (PRD §6).
The existing package boundaries support that direction. Isolated immutable deployment execution
is still partial: the [artifact-freeze design](superpowers/specs/2026-09-22-artifact-freeze-design.md)
separates a frozen decision planner from the current supervisor. The initial pure planner seam and
explicit deployment epochs are shipped: new paper intake prepares, verifies offline and binds a
frozen Story 1.3b descriptor (earlier working-tree deployments keep theirs), ticks and forward
evaluations carry its append-only deployment ID, and certificates cannot cross epochs. A frozen
paper tenant's planner runs each dispatched phase in a fresh child process launched from its verified
bundle and environment (`algua/live/frozen_dispatch.py`); the current supervisor re-derives every
strategy-free risk wall and owns all effects. Working-tree deployments still import the mutable
working tree and refuse a deployment-aware tick when that tree or environment drifts. Every frozen
planner attempt the supervisor decides to run a child for is recorded append-only (phases it
settles itself are not) and each frozen tick links its final invocation; forward evidence for a
frozen deployment counts only linked ticks, and `paper promote` qualifies it from its
recorded descriptor and freshly verified content, never the checkout (the raw `registry transition`
edge refuses it). The live lane and go-live refuse frozen deployments (`frozen_live_unsupported`).
The shipped frozen-paper slice includes the two-phase planner boundary, verified immutable
content/environments, child execution and deployment-bound operational evidence/qualification
(Stories 1.3a–d). Existing migration-time tenants remain an explicit unmigrated cohort. The supervisor retains broker access, reconciliation and account-wide
risk controls. Development and deployed artifacts belong to one product/repository; no production
fork is required.

Algua is a lifecycle: an idea becomes a backtest, a backtest becomes a gated candidate, a candidate
paper-trades, and only a human with a signed challenge puts it live. The packages follow that arc.

```
                 contracts ── the vocabulary (Protocols, lifecycle stages). Imports NOTHING.
                     │
    ┌────────────────┼──────────────────┬───────────────────┐
    │                │                  │                   │
  data          features/portfolio   backtest            calendar
  (bars,        (signals,            (simulate + score)  (sessions)
   universes,    construction)          │
   snapshots)         │                 │
    └────────────────┴─────────────────┘
                     │
                 research ── the statistical gate (does this edge survive scrutiny?)
                     │
                 registry ── the lifecycle authority: stages, gates, allocations, approvals
                     │
    ┌────────────────┴──────────────────┐
    │                                   │
  execution                          operator
  (brokers, orders, ledgers)         (the autonomous loop: schedule, merge-back)
    │                                   │
   live ── the tick engine both paper and live lanes run on
    │
   cli ── the ONLY way in. Every command emits JSON on stdout.
```

**The one-way rule:** `cli` composes everything; nothing composes `cli`. Domain packages never
import `algua.cli`. There is exactly one exception in the tree — `registry/human_actor.py` prints a
signing challenge — and it is tracked as debt in **#592**, deliberately left uncontracted so it
stays visible rather than being blessed by an exemption.

### Three harnesses, one product

| Owner | Owns | Boundary |
|---|---|---|
| **Hermes / Nix OS** | Company/project engineering, engine/data/security/UI development, CI/CD maintenance, aggregate health and incident repair | Engineering changes and releases retain applicable review and enforcement; runtime evidence cannot grant authority. |
| **OpenCode** | Independent research campaigns, ideation, strategy authorship, interpretation, quant review and learning | Bounded JSON CLI jobs and approved strategy/metadata authorship; no trusted engine/gate edits or brokerage access. Research must work while Hermes is offline. |
| **Algua** | Deterministic data, simulation, score validation, gates, registry, portfolio/risk, execution and reconciliation | Numerical results and effects come from validated domain code, never an agent's claimed verdict. Trading does not depend on an agent session remaining available. |

Hermes Kanban owns engineering work; GitHub holds code/evidence; Todoist holds human commitments.
Research attempts remain in the existing registry/tracking/KB surfaces. This is the approved product
responsibility map, not a rewrite of agent operating policy. It requires no second orchestrator,
research database, MLflow instance, execution fork or speculative service split.

---

## What each package owns

| package | owns | do NOT put here |
|---|---|---|
| `contracts` | Protocols, lifecycle stages/transitions, the bar schema. Imports nothing from algua. | anything with I/O or a dependency |
| `primitives` | stdlib-only leaves: `flock`, `atomic_io`, `retry`, `timeparse`. Anything may import it. | anything importing algua |
| `config` | `Settings` (env-driven) and `get_settings()` | reading settings at import time — see the calendar seam |
| `data` | providers, importers, snapshots, PIT universes, the immutable store | decision logic; `data` is the **hindsight lane** and is walled off from decision lanes |
| `features` / `portfolio` | signal computation; weight construction | I/O, registry, cli |
| `backtest` | `simulate`/`run`, PIT masking (`pit_view`), the fast/canonical dual path + parity guard (`decision_path`), windowing (`walkforward`) | registry access, tracking, live/execution |
| `calendar` | `MarketCalendar` + the settings-honouring `get_calendar()` factory | cli or registry imports |
| `research` | the statistical gate: DSR, breadth deflation, regime robustness, forward gates | registry imports (`research` never imports `registry`) |
| `registry` | **the lifecycle authority**: stages, transitions, gate tokens, allocations, approvals, families, the SQLite schema | live-lane imports |
| `execution` | broker adapters, order state, ledgers, sizing, flatten/drain | cli imports |
| `live` | the shared tick engine (`run_tick`), book exposure | cli imports |
| `risk` | limits, breaches, kill-switch, global halt, peaks, book breaker | cli or live-lane imports |
| `operator` | the autonomous loop: session gating, merge-back saga, loop health | cli imports |
| `evaluation` | shared task bodies (`backtest_run`, `sweep_run`) + input resolution, importable by BOTH cli and registry | cli imports |
| `knowledge` | the Obsidian vault sync; inspirations domain (`kb/inspirations/`) | imports of cli/registry/backtest/live/execution |
| `tracking` | experiment provenance and artifacts; the default MLflow SQLite backend | treating recorded results as promotion authority |
| `audit` / `observability` | operational events and structured telemetry | granting permissions from runtime evidence |
| `cli` | typer commands, the JSON envelope, flag resolution | domain logic — extract it |

---

## Real free data, complete system semantics

The first tier is approximately two years of real daily yfinance OHLCV for 150–300 selected
symbols. Keep the complete intended research, multimodal, portfolio, learning, monitor, release
and recovery architecture; data limitations constrain claims and gate eligibility rather than
reducing the system to a synthetic demonstration. Hourly operation remains part of the first
complete architecture; the pilot starts with end-of-day decisions and next-session execution.

`data/research_provenance.py` defines `pilot_real_proxy`, `synthetic_fixture` and the reserved
`verified_pit` tier vocabulary. The canonical `pilot-provenance/v1` envelope records provider,
coverage, universe method and limitations. Declared bars bind observed symbols/coverage and
metadata into snapshot identity through `data/provenance_binding.py` and the existing store and
manifest; legacy unlabeled snapshots remain unknown rather than silently relabeled. Writes
claiming verified PIT are refused because no verifier exists. Metadata validation is not proof
of market truth or payload integrity.

`scripts/pilot_proxy.py`, `pilot_proxy_source.py` and `pilot_proxy_audit.py` provide the bounded
acquisition recipe: preserve source bytes/time/digest and full selection accounting, probe first,
limit requests/retries, keep failed symbols visible, use the bars CLI in an isolated environment,
and audit exact-ID readback, logical/physical hashes and coverage/gaps. The merged
[recipe evidence](development/stories/real-proxy-dataset-recipe.md) records snapshot
`baaa116a36acee68`, 150 selected symbols, 75,150 rows and 501 XNYS sessions from 2024-10-31 through
2026-10-30. That is a current S&P 400 proxy, not historical small/mid-cap eligibility. Fresh vendor
downloads have shown adjustment differences; reproduce the pinned payload instead of assuming
reacquisition gives identical data. These are recorded acquisition results, not a new payload audit.

The target common-equity universe uses historical $0.5–10B market cap, price >= $5, trailing
60-session median dollar volume >= $5M and 90-session listing age, all PIT. The pilot cannot verify
those screens, historical membership, delistings or event knowledge times. Preserve all seven
pilot limitations, including revisable adjusted closes and unverified corporate actions. Retrieval
time is not historical knowledge time. Genuine source data is required for economic experiments;
synthetic news/model fixtures exercise interfaces only.

Target propagation carries the exact tier, snapshot, coverage, method and limitations through every
experiment, campaign and UI result. Currently bars ingestion and opt-in board metadata disclosure
are delivered; full downstream propagation is partial. Keep campaign inputs fixed and operational
refreshes separate. A later approved provider adds PIT/security/delisting/event depth through the
same seams, without rewriting the research/portfolio engine or changing the
[frozen bars contract](contracts/bar-schema.md). `get_bars` still lacks historical revision-as-of
selection; a pinned vendor-restated history must not be called historically PIT-correct.

## Unified context and finite scores

The target is one authored prediction interface for rules, statistics, ML/DL, fundamentals,
news/filings and combinations: declared as-of inputs and model pins → finite per-symbol scores →
deterministic construction → portfolio/risk → permitted execution. No inference-time training or
implicit vendor/network fetch belongs in a strategy. Add modalities through explicit typed data
adapters/declarations rather than permanent mutually exclusive strategy APIs.

**Implemented research boundary (PRs #725–#726):**

- `contracts/strategy_context.py` supplies `AsOfView`, `AsOfContext`, `ResearchStrategy` and shared
  score validation. Context includes aware `decision_ts`/`first_decision_ts`, eligible universe,
  immutable snapshot identities, defensive feature/model copies and verified model bytes/provenance.
  News/fundamentals use existing PIT masks; models must be trained no later than the first decision.
  `as_of` is the decision cutoff. Daily UTC-midnight bar labels are not fabricated availability times.
- `strategies/context_loader.py` binds `STRATEGY_INTERFACE = "context_v1"` and `score(context)`;
  a context module cannot also expose `signal` or `signal_panel`. `contracts/strategy_identity.py`
  binds the interface while preserving legacy config hashes. `StrategyConfig` remains compatible;
  context scorers can combine bars, fundamentals, news and the existing pinned-model lane.
- `backtest/run_inputs.py` captures each required source once per top-level run, checks snapshot
  identity drift and freezes input bytes. Decisions, windows, combinations and benchmarks consume
  separate copies of the same captured data. `backtest/context.py` builds masked contexts for the
  canonical decision loop; the existing construction, overlays, capacity and gross-utilization
  controls still produce weights. The engine retains `t → t+1`; context scoring does not license
  an unverified vectorized shortcut.
- Outputs are a real numeric Series with unique symbol strings, finite values and no out-of-universe
  symbol. Missing required modalities/pins, future-known inputs, model tampering and identity drift
  fail closed. The composer in `research/multimodal_context.py` and the actual backtest share these
  score rules. Tests cover combined inputs, future masks, defensive copies, first-fill timing,
  captured-source drift and input reuse across windows/combinations.

**Still partial:** legacy strategies retain their exclusive signal branches and a transitional
`LegacyStrategyAdapter`. Remove them only after every supported strategy has score/weight/decision
and identity parity on pinned inputs. General modality registration, filings/alternative inputs
and complete family migration are targets. The authored loader currently maps the existing
`needs_*` flags and single `model_ref`, not an unrestricted modality/model registry.

Context **signal parameter overrides are refused**, including shared grid validation and CLI
paths, before evaluation/trial/holdout/evidence effects: `score(context)` has no reviewed signal
parameter binding. Construction and overlay grids keep their explicit supported channels; legacy
signal tuning remains. Model-backed sweep/walk-forward stays unsupported. Do not report these as
delivered context signal/ML grids. `strategies/tradable.py` refuses context paper/live/frozen
execution, and retains legacy sidecar/model trading refusals. The frozen wire, deployment identity
and temporal/lane-parity migration remain target work. The real-bars exercise with synthetic
news/model inputs demonstrates controls, not genuine combined-market-data returns or forward evidence.

## Portfolio, factory and cumulative learning targets

Two deterministic portfolio levels stay separate. Within-strategy construction converts scores
into weights using declared policies, optional exits/overlays, cash and conservative sizing.
Across-strategy allocation budgets independently qualified edges, initially with simple capped,
volatility-aware weights and overlap controls. Aggregate to one account target, net shared
holdings, and enforce concentration, liquidity, turnover, available cash and gross/net constraints
before order sizing. A zero-candidate or infeasible case can yield all cash. Daily reevaluation does
not require daily trading; holding periods, hysteresis and cost thresholds are explicit. SL/TP is
optional research, not the organizing contract. Backtest/paper decisions must agree; allocation
estimates cannot use future observations.

Current `portfolio/construction.py`, overlays, `registry/allocations.py`, planner and account book
controls are foundations, not proof of this integrated allocator. The inspected base does not
establish capped volatility/overlap allocation and aggregated account-target parity as complete.

The target OpenCode factory runs observe prior evidence → choose bounded campaign → hypothesize
with mechanism/falsifier/family/trial budget → author in isolation → cheap deterministic screening
→ rigorous evaluation → independent quant review → persist outcome/lineage → choose next work.
Use a broad menu of families with a novelty reserve; allocate CPU/GPU, storage, wall time and model
spend from measured yield and learning. Use agent sessions for reasoning, batch programs for
numerics. Trial and family/search-breadth accounting survives unsuccessful screening and retries.

Existing `registry/idea_attempts.py` has fenced claims, attempt outcomes, reaping and retry caps;
`idea_scorecard.py`, tracking and knowledge provide feedback foundations. They do not establish
complete durable recording of every variant or causal learning across autonomous cycles. Keep
errors, exclusions, duplicates, abandoned/unfinished work and negative economics separate. A next
campaign must cite prior evidence and explain its changed choice; measure diversity, repeatability,
valid/attempted throughput and cost, stage yield, failures/recovery and reused learning together.

Target one durable systemd research initiator with role-scoped bounded workers, idempotent cycle
IDs/checkpoints and bounded retries. Existing `deploy/systemd/algua-{research,leap,forage}.timer`
and `.opencode/scripts/run_agent.sh` are shipped machinery. The runtime/model seam stays in that
script and `.opencode/opencode.json`; this is not evidence of a completed single-initiator cutover
or live service configuration. Market-session operation and necessary trusted queues keep separate
clocks/locks. Hermes monitors aggregate health and owns engineering incidents, not each trial.

## Strategy-first monitor: delivered and target

The private monitor home is now the strategy-first view (PR #722), with secondary diagnostics
and operational warnings and no bottom four-tab navigation. `registry/strategy_board.py` and
`/api/strategy-board` project one row per stable strategy ID, joined to its **latest** gate run
by identity/time, never the best past metric or a reusable name. Stage/family filtering and stable-ID
drilldown are delivered. Missing/non-finite metrics stay unavailable; an observed zero remains zero.

PRs #723–#724 add opt-in `runs board --include-evidence` /
`/api/strategy-board?include_evidence=true`, consumed by `StrategyBoard.tsx`. The extension shows
requested evaluation/timeframe/schema, lineage-checked OOS interval/count and exact-snapshot
provenance/coverage/all limitations. Atomic VALID/INVALID/UNAVAILABLE wrappers fail closed on
malformed, conflicting or missing metadata. `data/board_provenance.py` reads manifest metadata,
not payloads; metadata-bound validity is neither a payload audit nor PIT certification. Missing
legacy evidence is never inferred from a newer snapshot or provider name.

**Comparison remains UNKNOWN and metric sorting is disabled**: historical cost and homogeneous
comparison context are unavailable, even on metadata-valid rows. Server lifecycle order remains.
The approved target permits exploratory sorting by observed OOS Sharpe/return/drawdown only within
comparable cohorts, with data-tier/timeframe filters, unranked unknowns and distinct backtest,
paper and live evidence. Full lineage/run/search-breadth, portfolio-contribution, deployment/CI
and risk drilldowns remain integration targets. UI ordering must never feed promotion, family
classification or an expected-profit claim. Keyboard, loading/error/stale/unknown, identity and
390/860/1440 viewport scenarios have source tests/scripts; this inspection does not certify a
running deployment or the complete operational UX target.

## Isolation, release and recovery acceptance

Frozen-paper child execution already provides pinned bundles/environments, a replacement
environment, validated wire results, supervisor-owned risk/effects, bounded output/deadlines and
recorded invocations. `live/frozen_invocation.py` launches through `primitives/contained_process.py`;
that process-group containment is **not** a no-network/no-filesystem-authority sandbox. Legacy
working-tree execution and the research authoring sandbox are distinct boundaries.

Before broader automatic trusted execution of generated strategy Python, prove an enforced
credential-free, network-denied, broker/registry-write-denied boundary around every authoritative
strategy load/evaluation, with typed validated output. Hostile-code tests must reach the actual
boundary, not just an authoring worktree. Missing kernel isolation must fail closed. This is an
acceptance blocker; source hashes, prompts, allowlists and fresh processes do not satisfy it.

Root and standalone web CI are implemented in `.github/workflows/ci.yml` (including PR #720).
The target release chain additionally needs independent review and CI bound to the exact reviewed
and integrated source, immutable artifact digests, isolated untrusted PR execution, serialized safe
paper release, smoke/health verification and known-good recovery. A green CI run or an ordinary
software auto-merge does not demonstrate immutable paper CI/CD. Paper releases must not silently
change live artifacts. Rollback is conditional on schema compatibility; forward-only migration
requires safe halt/forward repair rather than an unsafe downgrade. These are release properties,
not new operating permissions or instructions.

Hermes closes engineering incidents only after reproduction, a regression test, bounded repair,
independent verification and observed authorized-release recovery. Aggregate telemetry/evidence IDs
connect the incident to the result without altering experiment rows. Inject worker crash, refresh
failure, CI failure and paper-release failure; verify bounded retries, idempotency, no duplicate
orders, durable failure reasons and recovery/safe state. Historical accelerated replay and actual
scheduled paper ticks require separate evidence; only genuine elapsed broker-clock observations
can qualify forward operation.

## Implementation and acceptance boundary

| Area | Implemented at `a062a66` | Remaining target / evidence limit |
|---|---|---|
| Data (PRs #719, #721) | Typed bars provenance/identity and bounded real-proxy recipe with recorded acquisition/audit | Full experiment/cycle propagation and deeper PIT/event data remain partial; no verified-PIT verifier. |
| Context (PRs #725–#726) | Composer, actual loader/scorer/canonical backtest, immutable shared inputs and refusal controls | Legacy/family migration, signal parameter binding and frozen/paper/live migration incomplete; model sweeps refused. |
| Board (PRs #722–#724) | Strategy-first UI, stable identity, latest evidence, opt-in provenance/OOS disclosure | Honest non-comparability; sorting and broader integrated target not accepted. |
| Portfolio / memory / factory | Construction, allocations, risk, attempts, scorecards, tracking/KB and operator primitives | Integrated allocator, comprehensive learning and one independent factory require system evidence. |
| Execution / release / repair | Frozen-paper reproducibility/evidence, current supervisor, CI and operational controls | Authoritative strategy sandbox, safe immutable paper release/recovery and closed repair loop not accepted. |
| Capital / live | Authenticated promotion/live gates and existing book guards | ₪2,000 envelope and inclusive cash-flow-adjusted 10% pause differ from current defaults; frozen live unsupported. |
| Unattended machine | Components and fixtures exist | **10 unattended cycles / >=100 real-data attempts: UNKNOWN.** Integrated scheduled operation and fault-recovery acceptance not established. |

The architecture dependency order is data/provenance and canonical direction → context and
portfolio → authoritative strategy isolation → independent factory/learning → paper release,
monitor and incident feedback → integrated acceptance. It sits within PRD §25's eight phases.
Machine acceptance (PRD §23) can succeed on limited real data with honest refusals and isolated
integration mechanics; it does not establish investment acceptance. Investment needs adequate PIT,
OOS/multiple-testing and actual forward evidence, reproducible immutable live identity, signer
protection, capital/risk enforcement and reconciled broker state plus authenticated human activation.
The 72-hour safe-operation objective remains separate from component counts. No data purchase,
capital change, runtime change or trading activation follows from this architecture.

The implementation claims above are grounded in the files named in each section and
`tests/test_{pilot_proxy,research_provenance,provenance_edges,multimodal_context,score_context_backtest,board_snapshot_provenance}.py`,
`tests/registry/test_strategy_board_evidence.py`, and the board/leaderboard UI tests. Historical
acceptance notes retain their original scope; merged source/refusal tests determine current status.

---

## How to add things

### A data provider
`algua/data/providers/` — implement the provider, then register it:
```python
register_provider("myvendor", lambda settings: MyProvider(...))
```
`get_provider(name, settings)` resolves it. The built-ins register themselves the same way, so
your factory is not a second-class citizen — see the tracker section below for the one
unavoidable two-line cost (an import so your registration actually runs).

### A bulk importer
`algua/data/importers/` — same shape: `register_importer("myvendor", factory)`.

### A broker
`algua/execution/broker_factory.py` — add a `BrokerKind` member and register a `BrokerSpec`:
```python
register_broker(BrokerKind.MY_VENUE, BrokerSpec(
    key_field="my_api_key", secret_field="my_api_secret", url_field="my_url",
    construct=MyBroker, missing_credentials="...",
))
```
The registry is **closed and enum-keyed on purpose**: a config flag able to swap paper for live at
runtime would be a hazard, not a feature. Declare the host allowlist (`_ALLOWED_HOSTS`) on the
adapter — the base class enforces https + allowlisted host.

### An experiment tracker
`algua/tracking/` — implement the `ExperimentTracker` Protocol in **its own module**, then
`register_tracker("mybackend", MyTracker)`. `tracking_backend` in settings selects it.
Return `TRACKING_SKIPPED` from a no-op backend so the JSON reports "skipped", not a null run id.

**Two lines land in `tracking/factory.py`** — an import and the `register_tracker` call. That is the
whole core-file cost, and it is a *declaration that the backend exists*, not a change to any logic:
Python needs something to import your module before its registration can run. (Entry points would
remove even that, and would be over-engineering while every backend ships in-tree.) The same shape
applies to providers, importers and brokers.

**Expect the size ratchet to push you into a new file.** `tests/test_module_size_ratchet.py` pins
every module ≥300 lines at its current size, and several are pinned at *exactly* their length — so
appending a class to an existing module often fails the gate. That is the ratchet working: the new
thing belongs in its own module. Check `wc -l` before you plan to extend a large file.

### A trading calendar
There is one implementation and one selector (`ALGUA_EXCHANGE`), so there is **no registry** — just
`get_calendar()`, which reads settings **per call, never at import**. An import-time read binds the
value before a test's `monkeypatch.setenv` can take effect; that is how a go-live guard was once
silently disarmed.

### A strategy
`algua/strategies/<category>/<name>.py` — see the `author-a-strategy` skill. A strategy declares
`CONFIG` and a named construction policy. Legacy modules expose `signal()`; research context
modules declare `STRATEGY_INTERFACE = "context_v1"` and expose `score(context)` through the bounded
integration described above. Context modules are not paper/live eligible. Strategy code never
touches `algua.data` directly.

### An overlay policy
The seam is three files: `algua/portfolio/overlays.py` (types, invariants, the `_OVERLAYS`
registry, `resolve_overlays`), `algua/portfolio/overlay_policies.py` (the two bundled policies —
`trailing_stop`, `regime_gate` — plus their validators and lookbacks), and
`algua/portfolio/overlay_validation.py` (`OverlayError` + the shared param-domain helpers). An
overlay is `(weights, view, params) -> weights`, applied in declared order inside
`LoadedStrategy.construct()` AFTER the construction policy and BEFORE the capacity cap. To add one,
implement the policy function, its param validator and its `lookback(params)` in
`overlay_policies.py`, then register it in `_OVERLAYS` in `overlays.py` (static dict, no runtime
registration: the module source is hashed into strategy identity — all three files are
CODEOWNERS-protected). It must be **tighten-only** — never add a symbol, scale up, flip a side or
emit NaN — and `apply_overlays` enforces that after every policy. A strategy opts in with
`overlays=[OverlaySpec(policy=..., params=...)]`; sweeps tune it as `overlay.<i>.<key>`.

### A CLI command
`algua/cli/<area>_cmd.py`. **Command modules may not import each other** — that contract is real and
has zero escapes. If two commands need the same body, the body belongs in a domain package
(`evaluation/`, `registry/`, `operator/`) and both import it from there. That is what
`evaluation/sweep_run.py` and `registry/promote_run.py` are.

### An ideation category
One line in `.opencode/categories.txt` and at least one venue covering it in
`kb/inspirations/_sources.yaml`; the research launcher's claim round-robin and the forage rotation
both key on the slug.

---

## The walls (why a change might be refused)

- **Vision versus authority** — PRD §§18–19 describe intended autonomy. Today's authenticated
  live gate and merge allowlists remain binding. The research worker stops at `candidate`;
  gated operational commands may reach `forward_tested`. Broader repair/deployment permission
  needs explicit implementation and review.
- **PIT / anti-look-ahead** — `backtest/pit_view.py` masks universe, fundamentals and news as-of each
  decision instant; `backtest/engine.py` shifts decisions `t → t+1`. `decision_path.py`'s parity
  guard is what licenses the fast vectorised path: it proves the fast path agrees with the canonical
  loop, so weakening it silently licenses wrong numbers.
- **Overlays are tighten-only** — `portfolio/overlays.py::apply_overlays` rejects any policy output
  that adds a symbol, increases `|weight|`, flips a sign or is non-finite. That is what lets the
  #135 risk rails run once, inside construction, and stay valid after any overlay chain.
- **Single-use holdout (#192)** — `backtest/grid.py`'s index is the date-index truth that
  `holdout_window` reproduces; a holdout is burned on peek and cannot be re-read.
- **The paper→live wall** — an agent may drive the lifecycle up to `forward_tested` and **never**
  put a strategy live. `forward_tested → live` needs a verified human signature plus a fresh forward
  certificate.
- **Lane parity** — paper is the rehearsal for live, so both lanes must enforce the same invariants.
  `tests/test_lane_parity.py` asserts it structurally, because a fix reaching one lane and not the
  other is silent (that is exactly what happened in #559/#601). Every book exit of either lane
  drains the strategy's own resting orders before it sheds its allocation:
  `transition_strategy` selects the source lane's guard itself through
  `execution/lane_exit.select_exit_guard` (`paper_exit_drain.PaperExitGuard` or `LiveExitGuard`),
  so no caller can forget it (#685).
- **CODEOWNERS is executable** — `operator/diff_policy.py` derives the autonomous merge-back's
  denylist from it, so a module missing from CODEOWNERS is one an agent can merge unreviewed.
  `tests/test_repo_hygiene.py` pins the integrity-critical set. The root `CODEOWNERS` is the ONLY
  CODEOWNERS file (GitHub reads one file, `.github/` first, so a second would shadow it);
  `tests/test_codeowners_parity.py` fails if GitHub's file and the runtime denylist diverge (#648).
  GitHub code-owner review is still only advisory for the sole owner/admin (see branch protection:
  `required_approving_review_count: 0`, `enforce_admins: false`).

---

## Before you commit

```
uv run pytest -q && uv run ruff check . && uv run mypy algua && uv run lint-imports
```

Touching `web/`? Also `uv run --project web pytest web/backend/tests -q` and
`cd web/frontend && npm run check && npm run build`. The root `uv.lock` is `dependency_hash`
identity — never add web deps to it.
