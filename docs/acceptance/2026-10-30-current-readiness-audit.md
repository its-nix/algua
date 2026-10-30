# Algua redesign readiness audit — 2026-10-30

**Status:** Read-only current-state audit; not machine acceptance.
**Audited repository:** `its-nix/algua`, `origin/main` and isolated worktree HEAD `db6860000f87a6cc98469e0e4901fa9c10c0d277` (fetched and equal at inspection).
**Mandate:** Approved bundle `/home/liornisimov/.hermes/profiles/algua/handoffs/algua-redesign-2026-10-30` (README + four numbered documents; the separate `kanban-task-ids.json` is routing metadata). No product/runtime changes, data fetch, registry access/write, secrets access, merge, or deployment performed.

## Executive result

**Verdict: NOT READY for autonomous strategy activation, auto-merge, or machine-acceptance claims.** The implemented system has substantial working data, research, paper, frozen-planner, gate and operator machinery; it does not yet meet the approved redesign’s acceptance conditions. Two immediate control blockers are a fail-open research-agent sandbox mode and merge-back’s direct-main writer lacking an enforced independent-review + exact-head hosted-CI attestation. The strategy execution containment gap is separately a hard Task 4 blocker, explicitly recognized as deferred in current `AGENTS.md` and therefore flag-only here. A remote branch-protection read confirms no required checks or minimum approval count, so GitHub does not currently close the merge-back gap.

## Evidence and command record

| Criterion | Status | Evidence |
|---|---|---|
| Baseline and worktree | PASS | `git status --short --branch`, `git rev-parse HEAD`, and `git fetch origin main` showed clean `redesign/readiness-audit` at `db6860000f87a6cc98469e0e4901fa9c10c0d277`; origin/main resolves to the same SHA. No branch checkout/fast-forward performed. |
| Approved requirements | PASS | Read all five bundle documents (`README.md`, `01_PRD_CONSOLIDATION.md`, `02_ARCHITECTURE_DESIGN.md`, `03_IMPLEMENTATION_PLAN.md`, `04_LNX_HANDOFF.md`); read repository `AGENTS.md`, `CLAUDE.md`, `docs/PRD.md` (initial portion), `docs/architecture.md`, `docs/vision-reconciliation.md`, `docs/agent/operating.md`, `docs/agent/story-delivery.md`. Current stories/specs remain in repository `docs/development/` and `docs/superpowers/`; no Task 1-10 approved normative stories were found in the bundle. |
| Data CLI feasibility | PASS (interface only) | `uv run algua data ingest-bars --help`, `data inspect --help`, `data verify --help`, `data ingest --help` executed. `ingest-bars` supports yfinance by default, explicit symbols/start/end/timeframe/adjustment/as-of; output is a persisted parquet snapshot. No ingest or network call was made. `ALGUA_DATA_DIR` and `ALGUA_DB_PATH` can be redirected via `ALGUA_` settings; this is the safe scratch isolation mechanism for a later, separately authorized real fetch. |
| Provider path | PASS (code path exists) | `algua/data/providers/yfinance.py:11-46, 49-107`; normalizes data, rejects empty/missing symbols/columns, returns source metadata. `algua/cli/data_cmd.py:36-42, 78-100` chooses configured data dir and provider. `algua/data/store/bars.py:34-91` uses canonical schema, content identity, immutable manifest/payload publication. These checks establish an ingest path, not current network availability, 2-year coverage, stable historical adjustments, delisting coverage, or a genuine PIT universe. |
| Runtime timer state | PASS (observation only) | Read-only `systemctl --user list-timers --all` and sanitized `systemctl --user show` for five Algua timers/services. Research, leap, forage, paper, mergeback-drain timers were active; associated oneshot services were inactive/dead after recorded successful recent runs at inspection. This is not health/acceptance: no job outputs, research outcome counts, paper session evidence or unattended-cycle quality was inspected. No service state changed. |
| GitHub branch policy | FAIL | `gh api repos/its-nix/algua/branches/main/protection`: `required_status_checks=null`, `required_approving_review_count=0`, `require_code_owner_reviews=true`, `enforce_admins=false`. CODEOWNERS is advisory without enforced approval/check requirements. |
| Current exact-SHA checks | UNKNOWN / NOT GREEN | GitHub check-runs API at exact SHA listed 8 runs: root `gate` success, `web` failure, `Secret scanning` failure, `Dependency vulnerabilities (SCA)` failure, and four Dependabot successes. These are not required branch-protection checks. No claim that those failures are introduced by this audit or resolved. Exact failing details: web `https://github.com/its-nix/algua/actions/runs/39771232513/job/119799004060`; secret scanning `https://github.com/its-nix/algua/actions/runs/39771232536/job/119799004244`; SCA `https://github.com/its-nix/algua/actions/runs/39771232536/job/119799003784`. |
| Open PR collisions | PASS (reviewed list) | `gh pr list --state open` showed #707 (`1569fb96…`, acceptance dashboard), #712 (`8818d32e…`, planner/risk contract), #713 (`7f4baa53…`, sprint docs), and Dependabot #694/#670. #707 adds dashboard and acceptance fixtures/workflow but no `docs/acceptance/` report file; #712 touches planner/risk and a story; #713 touches deployment README/installer and development sprint/story docs. This report path is non-overlapping with those reviewed file lists. Recheck before any future PR. |
| Root tests | FAIL | `uv run pytest -q`: **6290 passed, 5 skipped, 1 failed** (684.30s). Exact failure: `tests/test_planner_environment_lock.py::test_wheel_url_ownership_identity_is_rfc_canonical[ipv6-mapped-ipv4]`; expected canonical IPv4-mapped IPv6 URL `https://[::ffff:c000:20a]/x.whl`, got `https://[::ffff:192.0.2.10]/x.whl`. Re-run of only that test reproduced in 1.16s. This is on unchanged audited HEAD; not introduced by this docs-only report. |
| Root static gates | PASS | `uv run ruff check .`: passed; `uv run mypy algua`: passed, 359 source files; `uv run lint-imports`: 29 kept, 0 broken. |
| Web backend | PASS | `uv run --project web pytest web/backend/tests -q`: 266 passed. |
| Web frontend | PASS | After `npm ci` in `web/frontend`, `npm run check`: 43 test files / 226 tests passed; `npm run build`: passed; `npm run build:demo && npm run verify:viewport`: passed (5 routes at 390px, no horizontal overflow). The first viewport invocation before building `dist-demo` failed due to missing generated input; reran with the documented prerequisite, then passed. `npm ci` reported 12 package audit vulnerabilities (5 low, 2 moderate, 5 high); no remediation attempted. |
| Change status | PASS | No tracked product file changed; only this report is intended for commit. No live/research acceptance tests, ingest, hostile code, or scheduler activation were performed. |

## Verified findings (severity, evidence, recommendation)

### Critical — autonomous research launcher can fail open on filesystem confinement (shipped control defect)

`.opencode/scripts/run_agent.sh:106-129` defaults `ALGUA_AGENT_SANDBOX=auto` to `none`, then upgrades to `bwrap` only when `bwrap` is present. Explicit `none` is accepted. In contrast, `deploy/systemd/algua-research.service:3-13` describes bwrap as the kernel write wall and claims the agent cannot modify authoritative state; Task 4 plan §149-164 explicitly requires refusing autonomous execution when isolation is absent. The actual VPS executable availability was not checked. **Recommendation:** scope a fail-closed launcher fix and test absent-bwrap + explicit-none refusal before any autonomous operation relying on that claim. Do not remove the existing sandbox or broaden access.

### Critical — autonomous merge-back writes `main` without review/hosted exact-head CI attestation (active authority path; target blocker)

`algua/operator/mergeback.py:524-554` runs local quality gate, commits its tree, then invokes CAS push; `algua/operator/gitops.py:204-214` pushes directly to `refs/heads/main`. `algua/operator/gate_runner.py:46-54` runs pytest/ruff/mypy/lint-imports only; it does not prove an independent review or GitHub CI at the exact candidate SHA. The live branch protection API read shows no required checks, zero minimum approvals, and admin bypass allowed. `CLAUDE.md:85-96` documents this autonomous path. **Recommendation:** keep this path disabled for strategy-writing automation until a protected policy enforces independent review and successful required checks bound to the proposed exact head (and handle direct push/revert writer). Do not alter protection settings or turn on auto-merge in this task; those are human-controlled. The existing `operator/diff_policy.py` CODEOWNERS-aware allowlist is useful but is not equivalent to review/CI attestation.

### Critical — generated strategy code has no OS privilege boundary in execution lanes (Task 4 hard blocker; explicitly deferred, flag-only)

Backtest evaluation imports strategy implementations in-process (`algua/evaluation/backtest_run.py:57`; `algua/strategies/loader.py`); working-tree planner paths are in the authoritative process. Frozen paper uses a child process (`algua/live/frozen_child.py:1-18, 47-51`) and validates bundle/wire identities, but this child is a Python subprocess, not by that fact alone an unprivileged filesystem/network/syscall sandbox. The actual frozen invocation is bounded (`algua/live/frozen_invocation.py`); bounds do not establish hostile-code privilege separation. Current `AGENTS.md` explicitly records strategy runtime sandboxing as deferred exposure. **Recommendation:** treat Task 4 as a blocking security workstream before promoting arbitrary generated strategy code into trusted paper/live execution; independently adversarially test ambient filesystem, network, environment, registry and broker reachability. Do not implement or reinterpret this residual inside this audit. External deployment user/container boundaries were not inspected.

### Important — direct `paper merge-back` entrypoint relies on operator discipline for paper-cycle exclusion (shipped path-level gap)

`algua/cli/paper_cmd.py:445-453` documents that direct invocation is mutually exclusive with paper cycles “BY OPERATOR DISCIPLINE”; only the automated drainer wraps it in `algua operator lock-run`. The merge-back-specific lock (`:479-482`) serializes merge-backs, not the paper tick’s `operator.lock`. The drainer script uses the shared lock (`.opencode/scripts/drain-mergeback-queue.sh:94`). A human/other caller can therefore bypass the concurrency protection that the scheduled route has. **Recommendation:** make the core command acquire shared exclusion itself or make the entrypoint inaccessible outside the wrapper; cover direct and scheduled entrypoints with a concurrency regression test. No concurrent operation was run.

### Important — research freshness health bound conflicts with actual timer cadence (shipped observability inconsistency)

`deploy/systemd/algua-research.timer:2-17,33` specifies every six hours; `algua/operator/loop_health.py:41-44` gives research a three-hour stale threshold and labels the timer hourly. Thus an otherwise normally scheduled loop can be labeled stale before its next firing. `algua/config/settings.py:88-100` also states 4 runs/day consistent with six-hour schedule. **Recommendation:** one cadence source or test that timer period and staleness bound remain consistent. Do not change runtime scheduling as an audit fix.

### Important — aggregate ops health omits leap and forage (shipped coverage gap)

`algua/operator/loop_health.py:50` defines `LOOPS=("research", "paper", "mergeback")`; `deploy/systemd/algua-leap.timer:18` and `algua-forage.timer:11` show separately scheduled loops. The CLI describes health as all autonomous loops (`algua/cli/ops_cmd.py:35`). Failures of those timers therefore cannot be surfaced by this aggregate. **Recommendation:** add digest/health coverage for leap and forage or narrow the command’s completeness statement, with tests. This is independent of central research initiation design.

### Important — pilot tier/limitations are not a structured, end-to-end evidence field (Task 1 target gap)

`algua/data/models.py:33-46` has generic snapshot metadata (`provider`, symbols, range, `as_of`, source, free-form `source_metadata`) but no typed data tier, universe-generation method or limitations. Backtests carry snapshot IDs (`algua/backtest/result.py` and `algua/tracking/mlflow_tracker.py`), but the approved `pilot_real_proxy`/PIT-vs-survivorship qualifiers are not enforced through backtest → registry → board; `algua/registry/strategy_board.py:25-48` selects latest identity-bound gate metrics but exposes no tier/freshness fields. **Recommendation:** a smallest vertical slice is additive pilot metadata at ingest and propagation through experiment evidence and read-only board, with tests proving pilot proxy cannot be surfaced as PIT. Do not alter frozen bar contract `docs/contracts/bar-schema.md` or claim historical point-in-time coverage.

### Important — Tasks 2–3 need additive multi-input scoring and portfolio aggregation (target gaps)

`algua/strategies/base.py:31-43` defines separate fundamentals, news and model callable types; the full loader path should be inventoried for any specific safety finding, but the approved universal multimodal context is not evidenced by current fields. Existing allocation (`algua/registry/allocations.py`) handles allocation/book constraints; the requested deterministic multi-strategy target portfolio algorithm is not established by package presence. **Recommendation:** after Task 1 metadata contract, admit one combined-context vertical slice with timestamp/hash/rejection tests; then a pure allocator contract with fixed budgets/constraints and lane-parity tests. Treat portfolio risk policy or execution changes as protected review, not an implicit extension.

### Important — research initiation is split across three independent timers (approved design mismatch)

At inspected HEAD, `deploy/systemd/algua-research.timer:33` runs every 6h; leap `deploy/systemd/algua-leap.timer:18` runs every 2h at :30; forage `deploy/systemd/algua-forage.timer:11` runs daily. The installed host showed all three timers active. This differs from the approved single research initiation scheduler, though their independent roles/locks are described intentionally in current docs. **Recommendation:** do not disable or replace timers during this audit; first define/test a single coordinator preserving leap/forage behavior, ownership, locks, bounded runtime and rollback. Scheduler cutover is operationally sensitive and requires separate reviewed admission.

### Important — cumulative research memory is present, but causal selection/budget policy is not established (partial target gap)

Durable idea outcomes/scorecard/negative-result modules exist (`algua/registry/idea_scorecard.py`, `algua/registry/negative_results.py`, `algua/registry/idea_attempts.py`). This audit did not execute two cycles or establish that later choices are driven by prior evidence, effective breadth, cost or novelty budgets. The design’s causal learning acceptance remains **UNKNOWN**, not a claim that memory is absent. **Recommendation:** test a pure bounded selection policy and persist its decision trace; evaluate two successive cycles before claiming causal learning.

### Important — Task 8 leaderboard is not yet the approved home/evidence UI (target gap)

The current root view/navigation is not verified to be the approved strategy-first homepage; current board contract `algua/registry/strategy_board.py:1-11, 25-48` expressly says lifecycle-ordering/no ranking and omits pilot provenance/freshness. Open PR #707 is an acceptance dashboard, not the described leaderboard. Inspect `web/frontend/src/main.tsx`, `App.tsx`, `StrategyBoard.tsx` when admitting Task 8; do not treat an acceptance evidence dashboard as the strategy product UI or feed UI sort into promotion. **Recommendation:** UI task after evidence fields/read-only API contract, and separate UI acceptance from strategy authority.

### Minor — three different research cadence claims in timer, installer, docs/health

The timer says 6h (`deploy/systemd/algua-research.timer:2-17,33`), the installer message says every 2h (`deploy/systemd/install-user-units.sh:192`), and deployment README lines 315-319 say every 2h; health code says hourly (`algua/operator/loop_health.py:41-44`). The timer is the actual installed unit source; documentation/installer and health mismatch. **Recommendation:** reconcile in the existing deployment-doc task; avoid a second schedule change.

## Task 1–10 status map and minimum admission graph

| Task | Current-state result | Status |
|---|---|---|
| 0 Docs / authority | Bundle states explicit Kanban-engineering / GitHub-evidence / Todoist-human split. `docs/agent/story-delivery.md:3-19` still directs engineering to Todoist. PR #713 currently does not touch that file. Queue migration must be written in `docs/vision-reconciliation.md` without changing runtime controls. | FAIL (reconciliation needed) |
| 1 Real-data pilot | yfinance provider/CLI/snapshot contract exists; no observed 2y dataset, immutable pilot evidence, structured `pilot_real_proxy` lineage, or real network test. | PARTIAL; acceptance UNKNOWN |
| 2 Multimodal strategy | Separate optional modality forms exist; universal combined AsOfContext not established. | PARTIAL |
| 3 Multi-strategy allocator | Existing allocations/book risk exist; new deterministic cross-strategy aggregation not established. | PARTIAL |
| 4 Strategy containment | Research sandbox may fail open; execution child not equivalent to privilege isolation; live in-process risks. | FAIL / BLOCKER; protected scope |
| 5 Research factory | OpenCode research loop, retries/locks/queue and JSON CLI exist; three independent initiation timers remain; 10 cycles not evidenced. | PARTIAL; acceptance UNKNOWN |
| 6 Cumulative learning | Scorecard/negative results exist; causal budget/use not evidenced. | PARTIAL; acceptance UNKNOWN |
| 7 Merge/release | Local four-check gate, diff policy and CAS exist; no exact-head independent review/required check enforcement; mutable paper service not proven immutable. | FAIL / BLOCKER |
| 8 Leaderboard | Existing read-only board is meaningful but not approved home/tier/freshness complete. #707 acceptance dashboard is adjacent, not equivalent. | PARTIAL |
| 9 Incident/handoff | Ops telemetry/alerts exist, but story-delivery queue authority is stale and incident/evidence contract incomplete. | PARTIAL |
| 10 Machine acceptance | No evidence here of 10 unattended cycles, >=100 real-data attempts, recovery drills, signed independent signoffs, or actual scheduled forward-session completion. | UNKNOWN; do not certify |

**Proposed DAG (small, non-overlapping; map onto existing cards/stories rather than duplicate plan):**

1. **Docs/reconciliation Task 0** (docs PR; owned by existing docs card) → **Task 1 metadata/readiness slice** (data CLI/store/result/board; no raw dataset commit; real network sample later only to isolated scratch). The audit report itself is not the Task 1 acceptance report.
2. From the stable Task 1 evidence contract, parallelize **Task 2 combined strategy context** and **Task 5 research-cycle recovery/scheduler characterization** only if file ownership is disjoint; Task 5 timer cutover remains a separate approval-gated operation.
3. **Task 3 allocator** depends on Task 2 contract and safety design; keep it pure/contract-first before integration to live/paper planner.
4. **Task 6 learning policy** depends on stable attempt/provenance fields and Task 5 durable cycle output.
5. **Task 4 containment** is its own protected security story; no Task 7 autonomous strategy activation/merge or broad code authority until adversarial isolation proof passes. This requires a separate explicit human review boundary.
6. **Task 7 merge/release** depends on Task 4 plus required-check/review policy design and deployment review; no branch-protection mutation or auto-merge in this audit.
7. **Task 8 UI** depends on Task 1/2 evidence API; no UI-derived promotion.
8. **Task 9 incident handoff** can run after operational telemetry inventory, but should not overlap same docs files as Task 0.
9. **Task 10** depends on every accepted slice above, verified live/scheduler/data prerequisites, actual 10 unattended cycles + 100 real-data attempts and all test/recovery evidence; only then can acceptance be evaluated. It is not a milestone achievable from this report.

## Protected boundaries and conflicts

- Do not touch live activation/signers/approval, capital/risk defaults, broker credentials, operational registry, active systemd timers, immutable artifact policy, root CODEOWNERS/branch protection, or mutable main checkout.
- Keep yfinance pilot explicitly a current-survivor proxy unless historical identity, delisted securities, and PIT eligibility are evidenced. `as_of`/download timestamp does not retroactively create PIT correctness; adjusted-price history may be revised. Two years is a data tier, not investment readiness.
- A replay is not elapsed paper. Infrastructure errors/data unavailable are not negative alpha; preserve exact outcomes/denominators.
- PR #707 overlaps the acceptance-dashboard area but not this report path. PR #713 owns systemd docs/installer and sprint docs; schedule discrepancy fix belongs there or a follow-up scoped PR, not this audit. PR #712 owns planner/risk; do not mix strategy containment/portfolio modifications into it.
- GitHub branch settings show the exact-head/review enforcement gap; do not treat unmerged design approval, local tests, CODEOWNERS, or a passing push-triggered CI check as approval to write `main`.

## Tests and safety/integrity assessment

**Tests inspected/run:** `uv run algua data ... --help` passed. Full root `uv run pytest -q` ran and returned **6290 passed, 5 skipped, 1 failed**; the failure is the unrelated current-HEAD IPv4-mapped IPv6 canonicalization test described above, and a focused rerun reproduced it. `ruff`, `mypy algua`, `lint-imports` (29 kept, 0 broken), web backend (266 passed), frontend check (43 files/226 tests), production build, demo build and 390px viewport (5 routes) passed. No yfinance fetch, real snapshot, scheduler acceptance, hostile-strategy test or mutation check was performed. The full gate is therefore **not green**. The source commit is unchanged and the test failure is outside this documentation-only audit scope; report it to Lead rather than patching it here.

The operator additionally reports a separate CI-strengthening card `t_ab3d8099` in another worktree and a latest remote `web` failure for expected `/` text `cross_horizon_low_vol`, while reporting local frontend checks/viewport pass on that worktree. This audit made no workflow/test changes and does not duplicate that lane. Our own local frontend test/build/viewport commands passed after building `dist-demo`; the prior exact-SHA API failure at `39771232513` is not verified as the same run/current PR head. Do not treat either local or remote results as evidence of the other.

**Safety assessment:** Authenticated live-stage ceremony and `t→t+1` are documented/enforced existing invariants and were not modified. Frozen paper’s content-bound child/wire validation is substantive but does not itself supply OS privilege isolation. Research bwrap fallback and merge-back main writer/review gap are material controls. No current state was changed.

**Residual risks:** This is source/config and API-state evidence at a single commit, not a deployment penetration test. Actual `/opt/algua` deployed revision/user, container/seccomp/network policy, bwrap availability, bwrap hostile-strategy boundary, paper/live strategy execution inputs, timer logs, private runtime registry, and data snapshots were not read. Current check-run failures are noted but causality is unknown. No tool output here proves yfinance endpoint access or full pilot completion.

## Independent review and provenance

Codex CLI v0.164.0 was authenticated (`codex login status`: logged in) and run as `codex exec --sandbox read-only --ephemeral -C . ...` against this pinned worktree. It independently surfaced the sandbox fallback, code execution containment, direct-main merge-back, cadence/health, metadata, scheduler, memory, UI and acceptance gaps. I checked concrete source claims against the repository and GitHub API. Some Codex wording was narrowed where unsupported: timer intervals were verified from timer definitions; direct merge-back concurrency is documented in code as a disciplined caller restriction, therefore a real public-entrypoint safety gap but not evidence that a race actually occurred. No claim is made that external host isolation is absent.

**Human approval needed:** Yes before changing branch protection, merge/release authority, safety/containment boundary, scheduler activation/cutover, credentials/capital, or promoting generated strategy execution. This report authorizes none of those.
