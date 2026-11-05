# Algua 2.0 — Task 10 acceptance record

Evidence cut: **2026-11-05**, main [`242d853`](https://github.com/its-nix/algua/commit/242d8538769b2b30acfe2c74beffa14a29b67f61).
This records the owner's mission and design-bundle Task 10 items 1–7 against actual evidence.
The owner reduced ten unattended cycles to **three**; every other requirement remains.
**Overall status: PARTIAL, not accepted as the complete Algua 2.0 machine.**
This cut supersedes older UNKNOWN count statements only; other unmet requirements remain.
PASS below applies only to the stated scope; PARTIAL means some implementation/evidence exists,
UNKNOWN means unproved, and BLOCKED identifies an authorization or operating prerequisite.
This documentation-only update uses separately scoped evidence; it performs no new runtime,
production, browser, model or brokerage assessment.

## Task 10 requirements

| Item | Status | Evidence and exact limit |
|---|---|---|
| 1. Fixed real data and identities | PASS for research | Pinned yfinance snapshot, source/config/dependency/model identities and observed research deployment commits are retained in the [benchmark](real-sweep-benchmark.md) and [cycle record](research-vps-cycles.md). Paper environment/release identity is not established. |
| 2. Unattended cycles and recorded breadth | PASS for counts | **4 completed empirical cycles / 12 attempts / 8 excluded**, exceeding the amended target of 3. Separately, **100 unique parameter configurations across four mechanisms**, 100 trial rows plus 4 parents = **104 records**. Neither denominator means 100 independent hypotheses/alphas; excluded numerical work is not a completed cycle. [Cycles](research-vps-cycles.md), [audited benchmark](real-sweep-benchmark.json). |
| 3. Independent reproduction and visible failures | PARTIAL | One fourth-cycle backtest from retained commit `ee0265c` reproduced all **7 archived IS scalars bit-for-bit**, including return −13.5579% and Sharpe −0.2579. Snapshot/config/dependencies/null seed matched; this is not another cycle, WF/sweep reproduction or proof of the original evaluated worktree. Benchmark lineage/negative/flat results and its original final-wrapper failure remain visible. [Replay scope](research-vps-cycles.md#durable-evidence-and-outcome), [benchmark audit](real-sweep-benchmark.md#original-collector-failure). |
| 4. Multimodal, portfolio and visible strategy evidence | PARTIAL | Real learned-linear and trained-dense fit→pin→canonical evaluations, synthetic all-input CLI fixtures, and real two-sleeve portfolio replay are demonstrated below. Genuine news/fundamentals inputs, economic utility and complete comparable leaderboard/detail acceptance remain open. |
| 5. Failure injection and bounded recovery | PARTIAL | Actual worker failures/timeouts were retained; [#771](https://github.com/its-nix/algua/pull/771) proves kill/reap before fixed **120-second trusted cleanup**, with 12 focused controls. [#776](https://github.com/its-nix/algua/pull/776) separates worker execution from qualification; 342 focused tests and a deployed retained fixture preserve failure exits/history. Failed-refresh, CI-failure and failed-paper-release drills are **UNKNOWN**, not replaced by worker tests. |
| 6. Scheduled paper and separately labelled replay | PARTIAL / BLOCKED | Actual persistent **research** scheduling and historical replay are demonstrated; scheduled **paper-session** ticks, venue/account reconciliation and verified paper release/recovery are not. Replay contributes zero elapsed forward sessions. The merged paper-release wrapper is not installed or activated; account, eligible-cohort and recovery evidence remain missing. [Research profile](../../deploy/systemd/research-vps.md), [paper story](../development/stories/2-10-run-the-72-hour-unattended-acceptance.md). |
| 7. Independent quant/engineering sign-off | PARTIAL | Quant evidence includes independently audited breadth and the selected scalar replay; engineering evidence includes scoped peer-reviewed implementations/tests. Those approvals certify their own scopes, not the unverified rows here. Integrated Task 10 sign-off is **not given**. |

## Mission scope: demonstrated versus remaining

| Area | Status | Recorded result and remaining boundary |
|---|---|---|
| Architecture | PARTIAL | OpenCode operates research through its single runtime seam; Algua performs deterministic CLI computation; engineering owns changes. Existing registry/tracking/schedulers are reused. Complete independent factory/authoritative execution isolation, release/repair and all-target operation remain unaccepted. [Architecture](../architecture.md). |
| Research | PASS for finite throughput; PARTIAL overall | Four completed cycles include authoring, interpretation, real backtest/WF/sweep, terminal ledger and public archive; first three are declared bootstrap replications. The fourth arose from forage/leap and an actual persistent timer. Broad diverse multi-model autonomous search remains partial; completion implies neither novelty nor investment success. [Cycle identities and exclusions](research-vps-cycles.md). |
| Strategies | PARTIAL | One genuine learned pooled-linear model used **36,600 fit observations**, an immutable pin and 251 chronological out-of-fit sessions. Return **0.8893% / Sharpe 0.1335** underperformed the predeclared rule baseline **11.7139% / 0.6010**; construction/warmup differed as declared. No tuning/retry or qualification. [Recorded real case](https://github.com/its-nix/algua/pull/756), [producer semantics](../agent/model-training.md). |
| Multimodal / DL | PASS for bounded training/inference; PARTIAL overall | [#774](https://github.com/its-nix/algua/pull/774) proves synthetic combined-input contracts; [#775](https://github.com/its-nix/algua/pull/775) supplies the initially **untrained** two-hidden-layer inference reference. A separate reviewed **2→8→8→1** dense model genuinely fitted **36,600 rows**, then completed one canonical **251-session** evaluation: return **1.205681% / Sharpe 0.156157**, below the reused rule result **11.7139% / 0.6010**. Actual training/creation occurred in November 2026; the 2025 event cutoff is an explicit historical-proxy **ASSUMPTION**, not model availability. The preserved initial setup failure performed zero fits/evaluations; no tuning or baseline rerun followed. This adds no unattended cycle, qualification, genuine sidecar feeds or demonstrated economic utility. [Public evidence and exact identities](trained-dense-proxy.json). |
| Portfolio | PASS for bounded research replay; PARTIAL daily operation | One actual repeat of an existing **5-symbol / 2-sleeve / 501-session** configuration used canonical lag/costs, seed 0, explicit budgets/caps and unverified research risk assumptions. Net IS return **−10.2309%**, Sharpe **−0.3596**; whole inputs/11 limitations survived capture/prune/readback. Turnover cap was null; no SL/TP overlay was required. This is not a 150-symbol risk-adjusted book, qualified strategy set or scheduled daily paper rebalance. [Recorded proof](https://github.com/its-nix/algua/pull/745), [supported bounds](portfolio-replay-cli.md). |
| Data | PASS for pilot; PARTIAL architecture/data quality | 150 current selected names, **75,150 rows / 501 sessions**, 2024-11-01 through 2026-11-02. No premium purchase. Genuine historical membership, delistings, event knowledge times and other modalities remain unavailable; historical source availability is UNKNOWN. |
| Memory / learning | PARTIAL | Public lineage/negative results survive verified cleanup, including 104 benchmark records and the complete portfolio input. The earlier chooser explanation had one offered option and **zero numerical archive observations**; the later leap's **2 critic rejections / 0 imports / 0 critic errors** remain prior-history evidence. Deployed [#780](https://github.com/its-nix/algua/pull/780) now carries bounded recent cross-family numerical context: an isolated menu-only read returned **0 choices / 6 observations / 2 receipts**, including **2 negative IS** observations; **12 retained**, with **2 input-size + 4 context-size omissions**. It made no claim/model call; existing migration changed DB bytes. Neither this transport nor instruction-level primary/author/interpret forwarding proves subagent use, causal learning or economic improvement. Model archives retain refs, not bytes. [Memory contract](../agent/research-memory.md), [history limits](research-vps-cycles.md#operational-handoff-and-remaining-limits). |
| Dashboard | PARTIAL; scoped browser PASS | Owner-approved [#739](https://github.com/its-nix/algua/pull/739), retained research detail [#778](https://github.com/its-nix/algua/pull/778) and automated browser checks [#783](https://github.com/its-nix/algua/pull/783) are merged. Seven settled synthetic-fixture screenshots cover the stated layout/selection controls below. The actual VPS retained list/detail also passed exact archive readback and overflow checks at 390/1440 px after the scoped [#784 CSS fix](https://github.com/its-nix/algua/pull/784), without registering worker strategies. Production comparability, whole-source health and complete UI acceptance remain unproved. [Ordering implementation](../../web/frontend/src/components/StrategyBoard.tsx), [ordering tests](../../web/frontend/src/components/BoardOrdering.test.tsx). |
| Operations / monitoring | PARTIAL | All three research/forage/leap timers remain enabled; the fourth empirical cycle was timer-launched. The later research firing `20261105-174703-e6b11958f24f` exited 0 with `pool_empty`, **0 attempts / 0 unfinished / 0 selected**, no write errors, and recent-protocol context with **6 observations / 2 receipts**. Separately, `20261105-183226-e6c8982cbac4` ended `setup_failed`, exit **1**, worker exit **null**, **0 attempts** and no primary worker or claims; generic `invalid_input` and an absent choice directory leave the cause **UNKNOWN**. Deployed [#786](https://github.com/its-nix/algua/pull/786) retains future private diagnostics; it does not recover that historical cause. Both operational firings are excluded from **4/12/8**. The obsolete reload-rearmed startup drop-in was backed up/removed without changing calendar/persistence; the failed service state remains, with no subsequent research-success claim. Deployed [#776](https://github.com/its-nix/algua/pull/776) still distinguishes execution from qualification; historical incidents were not cleared. Research scheduling is not paper/live or full recovery acceptance. |
| Immutable paper release / recovery | PARTIAL implementation; UNKNOWN integrated proof | [`deployment prepare/verify`](../../algua/cli/deployment_cmd.py), gated frozen paper intake/runtime and the merged [#779 release wrapper](https://github.com/its-nix/algua/pull/779) exist; **23 focused wrapper fixtures** passed. The wrapper is **not installed or activated**. This operator-invoked wrapper does not build/install trusted artifacts or replace direct-main merge-back with verified-PR admission; those integrations and actual account/cohort/release/recovery evidence remain unproved. Related [#787](https://github.com/its-nix/algua/pull/787) (`934cf698643a2d32a2ff4bc38f0755caa1a2ca09`) and [#788](https://github.com/its-nix/algua/pull/788) (`aa8ec9702cc24ae49566d50a37ab17e28e18929d`) remain **DRAFT**, with source-only owner approval pending; they are not adopted deployment/assessment proof. [Release/recovery instructions](../../deploy/systemd/README.md#schema-v48-story-13d-is-forward-only). |

Separate portfolio engineering controls preserve the original cap-null proof above. Case 01
legitimately refused turnover cap **0.1**. Case 02 passed **501 sessions** with risk assumptions
**0.2 / 0.4**: maximum target gross/turnover **0.7125**, symbol **0.2375**, below cap **0.9**
(nonbinding); recovered risk **1 / 0.5** on **404** full-rank rows, IS return **−0.160596** /
Sharpe **−0.34052**. Case 03 passed **501 sessions**: cap **0.60** bound once, on **2025-01-31**,
scaling unrestricted buys **0.7125 → 0.60** by **0.8421052631578948** to three **0.20** weights.
Lag/target reconstruction errors were zero; recovered risk **1 / 0.5** on **403** full-rank
unrestricted rows, IS return **−0.161695** / Sharpe **−0.34389**. These assumptions remain
**UNVERIFIED**; target turnover does not prove venue/fill turnover. These three configurations
add **zero OpenCode cycles**, qualification or daily paper acceptance.

## Immutable evidence and data limits

Snapshot: `61a2bda1e636d017`; logical content SHA256:
`e63c513cf2b5820d0ef468de7c22e8ab53552a07c1f81a1b625c7849ac1dc550`.
Tier: **pilot_real_proxy**, current-constituent S&P400 sorted-first-150 selection, not historical PIT.
All seven limitations remain: vendor-revisable adjusted prices; unverified corporate actions;
absent delisted names; unavailable event knowledge times; unavailable historical market cap;
unavailable PIT universe membership; survivorship-biased selection. Previously examined windows
are not a globally untouched holdout. Adjusted prices and retrieval clocks do not invent known-at times.

The linked public records retain commits, archive digests, run IDs, config/seed and cost scopes.
Private receipts remain outside Git: `offline-linear-real-proxy-v1/acceptance-receipt.json`
(SHA256 `447b14eaccc88478c6235e83a371eee9cf8edeb453912f3f8d38ae084bd666e9`),
portfolio archive `mlflow:8974d8c526a04146ae1fb7c1d96feba5/public-evidence.json`
(`2f9c73748af201c643c56e24601455e94390c313955e526615d8a7cbb7c88e8d`), and
the cycle archives listed in [research-vps-cycles.md](research-vps-cycles.md).
The private critic readback `2026-11-05/learning-refutations/receipt.json` records leap
`20261105-114040`, trusted log IDs 2/3; SHA256
`d4fb538467709d4e84eb78f5d87f369dd391e47dbc0c9a2591e1f564fcb9d8de`.
Original stopped/failed invocations are retained; no failure was rerun into a fabricated pass.
Private integration receipts are `2026-11-05/task8-browser-renewal/current-result.json`,
`research-numerical-memory/{checks,root-review,vps-readback}.json`, and
`portfolio-cap-risk-03/independent-audit.json`; source approval and runtime evidence remain distinct.
`2026-11-05/web-localhost-deployment/receipt.json` records nine successful health/static/API
checks, 73 exact production assets without fixtures, and seven actual retained **attempt refs**.
The fourth archive's seven evaluations were verified (`9ce5b959…`); these are not seven cycles.
Scoped real-UI receipts are `live-monitor-retained-qa-green/validation-summary.json` and
`live-monitor-research-fetch-triage/summary.json`; the 73-file asset rollout needed no service restart.
Timer removal and the unresolved setup failure are recorded separately in
`research-bootstrap-removal/receipt.json` and `research-183226-diagnosis/conclusion.json`.

## Explicit unresolved inputs and review boundaries

- **BLOCKED:** protected authoritative-isolation [#730](https://github.com/its-nix/algua/pull/730)
  remains open/draft. Its independent provider returned `content_policy_blocked` and the exact
  requested tool is unavailable; this is not an outstanding user-permission request. Source
  approval cannot establish that assessment, and this record does not retry it.
- **PASS for scoped automated browser checks; PARTIAL overall:** [#783](https://github.com/its-nix/algua/pull/783)
  ran the existing Playwright command against a local production build with a truthful synthetic
  fixture: board at 360/390/1440 px, detail and Research at 390/1440 px. Explicit cohort selection
  reordered IDs 2/1; native Enter preserved ID 2. Only unknown-family toggling and empty retained
  state were covered; no qualification or production claim follows. Root visually reviewed selected mobile and desktop screenshots.
  Native CUA still has a technical `timeoutMs` TypeError/IAB limitation. Separate GET/HEAD-only
  real-VPS UI readback listed seven attempt refs and matched the selected fourth-cycle metrics/provenance/
  whole inputs/model refs unchanged before/after the CSS fix, with no page overflow at 390/1440 px.
  The first 390 px capture had transient `Failed to fetch` for three other sources; its cause is
  untraced. At 1440 px it recovered; one bounded diagnostic returned all seven APIs 200 with no
  request/console/page errors (cold reads 10–33 seconds). This does not establish whole-source health.
- **PARTIAL / UNKNOWN:** complete immutable paper supervisor release, smoke, failed-release and
  schema-compatible recovery integration, genuine scheduled paper ticks and the separate
  72-hour safe-operation exercise remain unproved or unimplemented in part.
- **BLOCKED operating inputs:** owner-selected paper venue/account configuration and test/paper
  credentials are needed for venue evidence. The mission already authorizes paper verification;
  account and protected gate/signature/isolation feasibility remain unproved. Credentials alone cannot qualify
  a losing or non-PIT proxy strategy; strict data, qualification and human-signature walls remain.
- **UNKNOWN:** real missing modalities, broader ML/DL research operation, causal cumulative
  improvement, full comparable leaderboard/drilldowns and risk-bound scheduled portfolio behavior.
  No protected financial/auth/capital control may be weakened to close those rows.

The owner expressly waived **full-suite reruns and CI waiting** for this delivery; focused checks
and scoped independent review are reported, with no blanket full-suite/CI-green claim. This waiver
does not prove CI-failure recovery, authorize protected merges or waive paper/live prerequisites.
This documentation change receives link/diff checks only. No paper/live activation, capital
increase, premium-data purchase or overall completion is asserted.
