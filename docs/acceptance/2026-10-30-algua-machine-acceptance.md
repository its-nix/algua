# Algua 2.0 — Task 10 acceptance record

Evidence cut: **2026-11-05**, main [`4ad3646`](https://github.com/its-nix/algua/commit/4ad3646fdd7d25f842c3577df8a2e71e0fe3e176).
This records the owner's mission and design-bundle Task 10 items 1–7 against actual evidence.
The owner reduced ten unattended cycles to **three**; every other requirement remains.
**Overall status: PARTIAL, not accepted as the complete Algua 2.0 machine.**
This cut supersedes older UNKNOWN count statements only; other unmet requirements remain.
PASS below applies only to the stated scope; PARTIAL means some implementation/evidence exists,
UNKNOWN means unproved, and BLOCKED identifies an authorization or operating prerequisite.
No new runtime, production, browser, model or brokerage assessment was performed for this record.

## Task 10 requirements

| Item | Status | Evidence and exact limit |
|---|---|---|
| 1. Fixed real data and identities | PASS for research | Pinned yfinance snapshot, source/config/dependency/model identities and observed research deployment commits are retained in the [benchmark](real-sweep-benchmark.md) and [cycle record](research-vps-cycles.md). Paper environment/release identity is not established. |
| 2. Unattended cycles and recorded breadth | PASS for counts | **4 completed empirical cycles / 12 attempts / 8 excluded**, exceeding the amended target of 3. Separately, **100 unique parameter configurations across four mechanisms**, 100 trial rows plus 4 parents = **104 records**. Neither denominator means 100 independent hypotheses/alphas; excluded numerical work is not a completed cycle. [Cycles](research-vps-cycles.md), [audited benchmark](real-sweep-benchmark.json). |
| 3. Independent reproduction and visible failures | PARTIAL | One fourth-cycle backtest from retained commit `ee0265c` reproduced all **7 archived IS scalars bit-for-bit**, including return −13.5579% and Sharpe −0.2579. Snapshot/config/dependencies/null seed matched; this is not another cycle, WF/sweep reproduction or proof of the original evaluated worktree. Benchmark lineage/negative/flat results and its original final-wrapper failure remain visible. [Replay scope](research-vps-cycles.md#durable-evidence-and-outcome), [benchmark audit](real-sweep-benchmark.md#original-collector-failure). |
| 4. Multimodal, portfolio and visible strategy evidence | PARTIAL | Real learned-linear fit→pin→canonical evaluation, synthetic DL and all-input CLI fixtures, and real two-sleeve portfolio replay are demonstrated below. Genuine news/fundamentals/DL economics and complete comparable leaderboard/detail acceptance remain open. |
| 5. Failure injection and bounded recovery | PARTIAL | Actual worker failures/timeouts were retained; [#771](https://github.com/its-nix/algua/pull/771) proves kill/reap before fixed **120-second trusted cleanup**, with 12 focused controls. [#776](https://github.com/its-nix/algua/pull/776) separates worker execution from qualification; 342 focused tests and a deployed retained fixture preserve failure exits/history. Failed-refresh, CI-failure and failed-paper-release drills are **UNKNOWN**, not replaced by worker tests. |
| 6. Scheduled paper and separately labelled replay | PARTIAL / BLOCKED | Actual persistent **research** scheduling and historical replay are demonstrated; scheduled **paper-session** ticks, venue/account reconciliation and verified paper release/recovery are not. Replay contributes zero elapsed forward sessions. Missing paper inputs, incomplete release integration and protected review are separate blockers. [Research profile](../../deploy/systemd/research-vps.md), [paper story](../development/stories/2-10-run-the-72-hour-unattended-acceptance.md). |
| 7. Independent quant/engineering sign-off | PARTIAL | Quant evidence includes independently audited breadth and the selected scalar replay; engineering evidence includes scoped peer-reviewed implementations/tests. Those approvals certify their own scopes, not the unverified rows here. Integrated Task 10 sign-off is **not given**. |

## Mission scope: demonstrated versus remaining

| Area | Status | Recorded result and remaining boundary |
|---|---|---|
| Architecture | PARTIAL | OpenCode operates research through its single runtime seam; Algua performs deterministic CLI computation; engineering owns changes. Existing registry/tracking/schedulers are reused. Complete independent factory/authoritative execution isolation, release/repair and all-target operation remain unaccepted. [Architecture](../architecture.md). |
| Research | PASS for finite throughput; PARTIAL overall | Four completed cycles include authoring, interpretation, real backtest/WF/sweep, terminal ledger and public archive; first three are declared bootstrap replications. The fourth arose from forage/leap and an actual persistent timer. Broad diverse multi-model autonomous search remains partial; completion implies neither novelty nor investment success. [Cycle identities and exclusions](research-vps-cycles.md). |
| Strategies | PARTIAL | One genuine learned pooled-linear model used **36,600 fit observations**, an immutable pin and 251 chronological out-of-fit sessions. Return **0.8893% / Sharpe 0.1335** underperformed the predeclared rule baseline **11.7139% / 0.6010**; construction/warmup differed as declared. No tuning/retry or qualification. [Recorded real case](https://github.com/its-nix/algua/pull/756), [producer semantics](../agent/model-training.md). |
| Multimodal / DL | PASS for synthetic contracts; PARTIAL overall | [#774](https://github.com/its-nix/algua/pull/774): 4 CLI tests show bars, schema-valid news/fundamentals and an exact pinned linear model independently change scores/returns, with future exclusion and pin refusal. [#775](https://github.com/its-nix/algua/pull/775): two nonlinear hidden layers with hand-authored **untrained** weights; 122 focused tests. Neither proves real sidecar feeds, trained DL or economic utility. |
| Portfolio | PASS for bounded research replay; PARTIAL daily operation | One actual repeat of an existing **5-symbol / 2-sleeve / 501-session** configuration used canonical lag/costs, seed 0, explicit budgets/caps and unverified research risk assumptions. Net IS return **−10.2309%**, Sharpe **−0.3596**; whole inputs/11 limitations survived capture/prune/readback. Turnover cap was null; no SL/TP overlay was required. This is not a 150-symbol risk-adjusted book, qualified strategy set or scheduled daily paper rebalance. [Recorded proof](https://github.com/its-nix/algua/pull/745), [supported bounds](portfolio-replay-cli.md). |
| Data | PASS for pilot; PARTIAL architecture/data quality | 150 current selected names, **75,150 rows / 501 sessions**, 2024-11-01 through 2026-11-02. No premium purchase. Genuine historical membership, delistings, event knowledge times and other modalities remain unavailable; historical source availability is UNKNOWN. |
| Memory / learning | PARTIAL | Public lineage/negative results survive verified cleanup, including 104 benchmark records and the complete portfolio input. A chooser explanation read structured prior attempt/family/exclusion history, but had one offered option and **zero numerical archive observations**. A later leap recorded **2 critic rejections / 0 imports / 0 critic errors**; one explicitly cites refuted idea 1 and distinguishes its integrity block from empirical momentum rejection. This is limited prior-history/rejection evidence, not numerical-archive causal learning or economic improvement. Model archives retain refs, not bytes; worker retention is not complete cross-cycle transport. [Memory contract](../agent/research-memory.md), [history limits](research-vps-cycles.md#operational-handoff-and-remaining-limits). |
| Dashboard | PARTIAL / BLOCKED | Strategy-first home, lifecycle/family filters, stable-ID detail and removal of bottom four-tab navigation exist. Comparison remains UNKNOWN and metric sorting disabled. Protected [#739](https://github.com/its-nix/algua/pull/739) is open/draft; full target/browser/production assessment is not accepted. Reuse existing [#707 acceptance UI](https://github.com/its-nix/algua/pull/707); this record creates no duplicate dashboard. [Current scope](../architecture.md#strategy-first-monitor-delivered-and-target). |
| Operations / monitoring | PARTIAL | Existing research/forage/leap timers are enabled; the fourth cycle was timer-launched. Deployed [#776](https://github.com/its-nix/algua/pull/776) retained-fixture readback showed worker 0 / final exit 1, negative title retained, no candidate queue, research health OK while overall health remained false. Historical incidents were not cleared. Research scheduling is not paper/live or full recovery acceptance. |
| Immutable paper release / recovery | PARTIAL implementation; UNKNOWN integrated proof | [`deployment prepare/verify`](../../algua/cli/deployment_cmd.py) and gated frozen paper intake/runtime exist. No complete exact-artifact supervisor release/smoke/schema-compatible recovery entry is established; manual safe halt/forward repair is documented. This is an implementation/integration gap, not merely missing keys. [Existing recovery boundary](../../deploy/systemd/README.md#schema-v48-story-13d-is-forward-only). |

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

## Explicit unresolved inputs and review boundaries

- **BLOCKED:** protected authoritative-isolation [#730](https://github.com/its-nix/algua/pull/730)
  and dashboard [#739](https://github.com/its-nix/algua/pull/739) remain open/draft, unmerged.
  Saved-policy denials block the corresponding production assessments; this record neither
  retries them nor treats source/fixture checks as substitute authorization.
- **PARTIAL / UNKNOWN:** complete immutable paper supervisor release, smoke, failed-release and
  schema-compatible recovery integration, genuine scheduled paper ticks and the separate
  72-hour safe-operation exercise remain unproved or unimplemented in part.
- **BLOCKED operating inputs:** owner-selected paper venue/account, test/paper credentials and
  an explicitly authorized isolated paper exercise are needed for venue evidence. Enrolled
  signer/account/approval/gate feasibility is not proved. Credentials alone cannot qualify
  a losing or non-PIT proxy strategy; strict data, qualification and human-signature walls remain.
- **UNKNOWN:** real missing modalities, broader ML/DL research operation, causal cumulative
  improvement, full comparable leaderboard/drilldowns and risk-bound scheduled portfolio behavior.
  No protected financial/auth/capital control may be weakened to close those rows.

The owner expressly waived **full-suite reruns and CI waiting** for this delivery; focused checks
and scoped independent review are reported, with no blanket full-suite/CI-green claim. This waiver
does not prove CI-failure recovery, authorize protected merges or waive paper/live prerequisites.
This documentation change receives link/diff checks only. No paper/live activation, capital
increase, premium-data purchase or overall completion is asserted.
