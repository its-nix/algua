# Vision reconciliation — 2026-09-24

> **Historical record, last updated 2026-10-30.** The analysis below is dated 2026-09-24 unless a
> passage says otherwise. For the current state use the
> [observed-target report](development/observed-target-report-2026-10-30-three-harness.md). Passages
> overtaken since then are marked in place.

**Purpose:** translate the [Vision of Record](PRD.md) into consistent repository guidance and
backlog direction. This is an implementation-gap record, not another product vision or a grant
of operating authority. Evidence below was inspected at base commit
`d9ed65455a626d3120559eca30fc0ed0818f9084`; it is not an inspection of funded accounts or deployed services.

**Authority routing (2026-10-30).** Hermes Kanban owns delegated engineering work, GitHub owns code
and evidence, and Todoist holds only Lior's human commitments; no trial or experiment gets a task
card. Every merge, deployment, credential change, destructive or external-sharing action and
protected-authority change requires Lior's approval. Auto-merge and paper CI/CD are TARGET BLOCKED,
not permissions.

## Authority and document roles

| Document | Authority / use |
|---|---|
| [PRD](PRD.md) | Canonical product objectives, constraints and eight-phase development sequence; the owner's 30 sections are retained, with requested sections amended on 2026-10-30. |
| [Three-harness design](superpowers/specs/2026-10-30-algua-three-harness-design.md) and [plan](superpowers/plans/2026-10-30-algua-three-harness-implementation.md) | Approved target direction. Their new controls are not implemented and they are not operating permission. |
| [Architecture](architecture.md) | Current packages, extension seams and implementation boundaries. |
| [AGENTS.md](../AGENTS.md), [CLAUDE.md](../CLAUDE.md), [operating guide](agent/operating.md) | Current review and operating rules; narrower worker permissions remain binding. |
| [Contracts](contracts/bar-schema.md), code, tests and enforced policies | Current interface and safety behavior. A conflict with the vision requires an explicit implementation change through existing review. |
| [Dated specs and plans](superpowers/README.md) | Design history and scoped technical rationale; old roadmap and product assumptions do not override the current PRD. |
| [Decision log](.decision-log.md) | Owner decisions and reconciliation audit, including superseded policy. |

The vision's priority order is a product tradeoff order within its capital, integrity and human
authority constraints. It does not permit trading away an approval wall for expected profit.
Its conceptual journey through shadow/paper/experimental/scaled live is not a change to the
current `Stage` enum. Research workers stop at `candidate`; gated operational commands can
reach `forward_tested`; real-money activation still requires the signed human ceremony.

## Current capability versus target

| Area | Verified current state | Target / next work |
|---|---|---|
| Operating kernel | Data snapshots, backtests, gates, execution, paper/live tick engines, risk and operator packages exist. | Demonstrate one strategy's safe end-to-end lifecycle; package presence is not acceptance evidence. Phase 1. |
| Artifact reproducibility | The pure planner seam and explicit append-only deployment epochs are shipped. **Updated 2026-10-30:** Stories 1.3b, 1.3c and 1.3d have also shipped, so paper intake binds frozen descriptors, frozen planners run from verified bundles in child processes, and forward evidence binds to linked ticks. Earlier working-tree deployments keep theirs. | The live lane and go-live still refuse frozen deployments (`frozen_live_unsupported`). Bind signed live authorization to the exact deployment and hand it to live under Stories 2.3 and 2.4 and [#661](https://github.com/Lior-Nis/algua/issues/661). Phase 1, PRD §§5, 7, 10. |
| Experiment memory | `tracking/`, `knowledge/`, idea outcomes and strategy/family notes exist. `Settings.tracking_backend` defaults to `mlflow-sqlite`. | Complete the durable experiment graph, failed-result coverage, prior-search requirement and knowledge synthesis. Phase 2, PRD §9. |
| Data and hourly operation | Bars, PIT universes and fundamentals/news storage exist. `data/capabilities.py` admits US equities and daily-family research horizons; supported storage is not proof of usable live feeds. | Deep PIT OHLCV, fundamentals, timestamped news/filings and complete hourly operation. Phase 3; [#625](https://github.com/Lior-Nis/algua/issues/625), [#630](https://github.com/Lior-Nis/algua/issues/630), and live alternative-data gap [#472](https://github.com/Lior-Nis/algua/issues/472). |
| Autonomous engineering | Telemetry, operator machinery and research merge-back exist. `operator/diff_policy.py` permits strategy Python files and `kb/` under its deny rules. | Full incident → reproduction → test → fix → independent review → permitted release → verification loop. General core-repair merges/deployments are not enabled by PRD adoption. Phase 4. |
| Portfolio | Construction, allocations, exposures, overlays and account risk controls exist. | Validate weak correlation and incremental contribution, then allocate within approved limits. Phase 5. |
| ML / LLM strategies | Model-related contracts and research paths exist; provider/inference support must be evaluated per feature. | Broader evaluated model capabilities, simpler baselines and reproducible prompt/input/output provenance. Phase 6; [#627](https://github.com/Lior-Nis/algua/issues/627). |
| Capital and market breadth | Initial vision scope is personal capital in long-only stocks and unleveraged ETFs. | Evidence-led compatible external capital in Phase 7; economically justified additional markets in Phase 8. No automatic purchases, funding or broker activation. |
| Unattended operation | Docker research runs, systemd workers, health commands and safety controls exist. | Demonstrate the PRD §20 72-hour target with predefined safe states and auditable recovery. This review did not run that acceptance exercise. |

Hourly research and execution are part of the first complete architecture. A daily strategy may
prove the first lifecycle slice before hourly completion. More bars alone do not establish more
independent evidence, justify a lower gate, or promise a fixed forward-validation duration.

## Important gaps requiring separate implementation review

These findings were **flag-only** in the 2026-09-24 documentation change. Current controls remain
binding.

1. **Experimental-account loss policy — Important. Owner decision made 2026-10-04.**
   `algua/config/settings.py:79` defaults `book_max_drawdown` to **0.15**; this is not the new
   **10%** intervention rule. `algua/risk/book_breaker.py:79` uses a strict below-threshold
   comparison. `algua/cli/live_cmd.py:506` halts the book and attempts account-wide closing.
   Lior decided the policy on 2026-10-04 in [#624](https://github.com/Lior-Nis/algua/issues/624):
   drawdown from the live equity high-water mark with cash flows moving the peak equally, triggering
   at 10% or more inclusive, engaging the halt and cancelling resting orders while keeping positions,
   and resuming only by signed human command. [Story 2.6](development/stories/2-6-pause-live-trading-at-ten-percent-drawdown.md)
   owns that unimplemented work. Do not silently change runtime settings.
   Update (#647): `paper run-all` now runs the same breaker body as live
   (`algua/execution/book_breaker_halt.py`), against its own per-lane high-water mark
   (`paper_book_equity_peak`, schema v49). Thresholds are unchanged.
2. **Immutable execution — Important. Partly overtaken 2026-10-30.**
   As of 2026-09-24 a deployment descriptor was evidence, not recoverable executable content.
   Stories 1.3b, 1.3c and 1.3d have since shipped materialization, verified paper execution and
   evidence binding. Preserve the frozen decision/current supervisor split. Signed deployment
   identity and any narrowing of the approved code closure still require the existing protected
   review. Owner: #661 and Stories 2.3 and 2.4; the frozen child process is process separation, not
   an authority sandbox.
3. **Legacy signed relaxations — Important. Owner decision made 2026-10-04.**
   The old PRD tied signed research/forward relaxations to dollar capital rungs. Those rungs
   are superseded. Lior decided in [#624](https://github.com/Lior-Nis/algua/issues/624) that signed
   relaxations stay available for exploration and can never authorize go-live, with no agent waiver.
   [Story 2.1](development/stories/2-1-refuse-live-qualification-on-relaxed-gates.md) owns this. The
   raw-edge refusal is in the tree; the implementation state of its remaining parts is recorded in the
   [observed-target report](development/observed-target-report-2026-10-30-three-harness.md).
4. **Authority and deployment protection — Important. Partly overtaken 2026-10-30.**
   The autonomous diff gate reads root `CODEOWNERS`. The 2026-09-24 finding of two CODEOWNERS files
   was resolved by #648; root is now the only one. Effective branch protection was read on
   2026-10-30 and does not enforce exact-head or independent review; deployed filesystem ownership
   is still unverified. Verify owner-review coverage and an immutable installed signing anchor before
   relying on them for autonomous releases. Owner: Lior/deployment implementer, before Phase 1 live
   acceptance or Phase 4 permission expansion. Preserve existing controls; do not edit protection
   files here.
5. **Initial capital and instrument constraints — Important.**
   `algua/config/settings.py:65` defaults `book_max_gross` to **2.0** (`book_max_net` is 1.0).
   Existing generic exposure limits do not establish PRD §21's long-only, unleveraged ETF,
   no-borrowing, no-derivatives policy or the approved ₪2,000 experimental capital ceiling.
   Verify eligible instruments, account funding/buying-power semantics and enforced sizing
   limits before experimental live acceptance. Owner:
   [Story 2.5](development/stories/2-5-enforce-the-experimental-capital-envelope.md), unimplemented;
   activation needs Lior's USD ceiling and instrument list. Separate safety review, no
   runtime-default changes in this documentation pass.
6. **Inherited calendar-purity wording — Important.**
   `AGENTS.md` §3 retains the supplied rule that calendar imports no other Algua modules.
   The shipped import-linter rule instead keeps calendar independent of CLI and registry;
   `calendar.get_calendar()` uses settings, as the current architecture describes. This is an
   existing specification/enforcement mismatch, not a new permission. Owner: Lior, before
   work changes calendar boundaries, must reconcile the intended invariant with the shipped
   contract. This pass neither weakens the supplied invariant nor changes code/import policy.

The 90-day target measures an end-to-end operating machine. It does not waive research evidence,
forward qualification or human live approval if a strategy cannot qualify within that time.

## Strategy leaderboard supersession (2026-10-30)

The owner-approved target strategy leaderboard supersedes the default lifecycle order and the no-leaderboard intent of [spec-strategy-board](development/stories/spec-strategy-board.md) and of the [dashboard decision layer](development/stories/spec-dashboard-decision-layer.md), for the future home UI only. Sorting stays exploratory, and this supersession grants no promotion authority: the display-only condition in the [run-tracking design](superpowers/specs/2026-08-23-strategy-run-tracking-design.md) still binds, so no ordering may feed `research promote`, family classification or any other selection path.

The frozen blocks of those stories are unchanged historical owner intent. Both carry a notice in their change logs.

- **Current until a separately admitted UI contract:** the [strategy-board contract](development/specs/spec-strategy-board/strategy-board-contract.md) stays authoritative, covering `strategy-board/v1`, lifecycle row order, latest gate by identity, scalar-only metrics, nullable evidence and holdout secrecy. The docstring in `algua/registry/strategy_board.py` that says the board "never ranks" describes this current behavior and is deliberately left in place until that contract lands.
- **Approved target:** default order by comparable OOS Sharpe, one row per strategy identity, latest gate never best, UNKNOWN or non-comparable rows visually separate and unranked, no bottom tab bar, as set out in [design §8](superpowers/specs/2026-10-30-algua-three-harness-design.md).
- **Still never:** a composite score, a winner label, a recommendation, best-run selection, zero substituted for missing evidence, a per-bar holdout vector, or a mutating action.

Admission work is [plan Task 8](superpowers/plans/2026-10-30-algua-three-harness-implementation.md), which also has to reconcile the [monitor redesign](superpowers/specs/2026-08-27-monitor-human-facing-redesign-design.md).

## Backlog migration

Issue numbers are retained so links, discussions and design history survive. The phase mapping
below changes product priority and scope, not issue completion state or deployed configuration.

| Existing issue | Reconciled scope | Admission / dependency |
|---|---|---|
| [#624](https://github.com/Lior-Nis/algua/issues/624) | Phase 1 operating kernel and experimental personal live acceptance | Replace dollar rungs and stale account assertions; require actual readiness, #661, the 10% policy review and authenticated human activation. |
| [#625](https://github.com/Lior-Nis/algua/issues/625) | Phase 3 deep PIT US-equity/ETF data, daily/hourly | OHLCV, fundamentals, timestamped news/filings; no vendor purchase commitment. Shared expense ceiling is up to ₪2,000. |
| [#627](https://github.com/Lior-Nis/algua/issues/627) | Phase 6 evaluated ML/DL/LLM strategy capabilities | Phase 1 artifact/environment provenance remains foundational. SQLite tracking already exists; avoid reviving its resolved file-store question. |
| [#628](https://github.com/Lior-Nis/algua/issues/628) | Phase 8 optional additional market data | A specific economic hypothesis and justified data cost precede adapters/calendars/instrument work. Four mandatory lanes are superseded. |
| [#629](https://github.com/Lior-Nis/algua/issues/629) | Phase 8 conditional crypto execution | Deferred beyond initial stocks/ETF scope; requires compatible evidence, risk/capital policy and human live authorization. |
| [#630](https://github.com/Lior-Nis/algua/issues/630) | Phase 3 hourly operation, anticipated by Phase 1 interfaces | Closed-bar timing, costs, reconciliation, staleness and evidence must be cadence-correct. No bar-count-to-calendar validation promise. |
| [#661](https://github.com/Lior-Nis/algua/issues/661) | Phase 1 immutable deployed decision artifacts | Planner extraction, working-tree epochs and frozen paper execution are implemented (updated 2026-10-30). Signed deployment binding and live hand-off remain, under separate protected review. |

Phases 2, 4, 5 and 7 also require scoped acceptance work; this mapping does not claim that seven
legacy issues exhaust the new roadmap. Each future issue must state its contribution under
PRD §28 and distinguish implemented behavior from proposed work.

## Historical reference map

The [September 6 PRD](https://github.com/Lior-Nis/algua/blob/d9ed65455a626d3120559eca30fc0ed0818f9084/docs/PRD.md)
remains in Git history. Its old section numbers must not be interpreted as current anchors.

| Historical source | How to read it now |
|---|---|
| May 29 architecture and foundation plan | Original rationale and build history; old TOTP, lifecycle, absent-module and six-project statements are historical. Use current architecture and operating guides. |
| September 8 ideation design/plan | Technical history; new product anchors are PRD §§3, 8–10, 25. Volume is supporting evidence; retained learning and validated profit are outcomes. |
| September 10 overlays design | Tighten-only contract remains; anchors move to PRD §§7, 10, 13–15. |
| September 12 holistic verdict | Dated diagnosis. Its roadmap override and quarter-versus-years validation projections are superseded; observations are not current account state. |
| September 22 artifact-freeze design | Aligned Phase 1 direction, PRD §§5, 7, 10, 24–25; retain explicit partial status. |

## Completion evidence (2026-09-24 pass)

This section records that pass only. Results for the 2026-10-30 work are in the
[observed-target report](development/observed-target-report-2026-10-30-three-harness.md).

- All 30 canonical sections preserved; an independent manual comparison found no textual
  divergence from the supplied vision. Conversational introduction and citation placeholders
  are excluded. The file also matches the source text used for the replacement exactly.
- Current entry points, research guidance, categories and inline source-documentation citations
  reconciled. Python changes are comments/docstrings only, verified by comparing syntax trees
  with docstrings removed; no executable behavior changed.
- Local Markdown destinations checked. Historical source notices and the design-history index
  point to the current vision; old PRD numbers remain explicitly historical.
- Issue bodies updated and read back successfully: #624, #625, #627, #628, #629, #630, #661.
  Historical reference wording corrected in #633–#639, preserving their technical findings.
  All 14 issues remain open. Roadmap issues retain their prior bodies as historical context;
  #661 retains its technical slices. Updates identify this branch as pending merge.
- `uv run pytest -q`: **3,985 passed**, 171 warnings, 492.72 seconds.
- `uv run ruff check .`: passed. `uv run mypy algua`: passed, 292 source files.
  `uv run lint-imports`: **28 kept, 0 broken**. These checks were run after pytest completed;
  running lint during pytest briefly encountered a test-created temporary strategy module.
- Whitespace checked with Markdown hard-break trailing spaces allowed, preserving the owner's
  exact two-space line breaks in the PRD metadata.
- [Review](review-vision-reconciliation.md): the capital-policy omission was added above;
  completion bookkeeping is recorded here. Current safety and authority controls remain binding.

This pass does not certify live readiness or execute trading operations.
