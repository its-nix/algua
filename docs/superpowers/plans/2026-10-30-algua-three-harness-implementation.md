# Algua Three-Harness Redesign Implementation Plan

> **Provenance and status.** This publishes source package file `03_IMPLEMENTATION_PLAN.md`, SHA-256
> `66f2c2f2076086146a8cbd9053bbd662a1881485da4f9dfc514aab6403d2df52`. The original source was proposed
> for owner review. Owner direction is approved: Lior approved this direction by mandate on
> 2026-10-30. The new controls described here are not implemented and are not operational permission.
> Hashes, baselines and blockers are in the
> [observed-target report](../../development/observed-target-report-2026-10-30-three-harness.md), and
> slice status is in the
> [readiness report](../../development/implementation-readiness-report-2026-10-30-three-harness.md).
>
> **Precedence.** Where this plan conflicts with current controls, the current controls win until a
> separately reviewed change replaces them: [PRD](../../PRD.md) §§18–19, `AGENTS.md`, `CLAUDE.md`,
> contracts, code and tests. Lior's approval is required for every merge and deployment. Each step
> below about automatic merge, automatic deployment or a schedule switch is TARGET, is TARGET BLOCKED
> today and needs separately reviewed authority. Publishing this plan admits no task.
>
> **Existing work these tasks must use, not duplicate.** Task 4 builds on the frozen scope of
> [Story 1.3](../../development/stories/1-3-materialize-and-execute-frozen-planner-artifacts.md), but
> that child process is process separation, not an authority sandbox. Task 7 relates to
> [Story 2.8](../../development/stories/2-8-validate-releases-in-paper-before-live.md). Task 8 starts
> from the completed [strategy-board spec](../../development/stories/spec-strategy-board.md). Task 10
> relates to [Story 2.10](../../development/stories/2-10-run-the-72-hour-unattended-acceptance.md) and
> PR #707. PR #712's planner safety fix is a dependency for Tasks 2 to 4. This plan creates no
> duplicate live or capital story or status.
>
> **Skill names.** The source recommended `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` for task-by-task work. Those names are historical recommendations,
> not a claim that either is available. Steps use checkboxes. Treat all code signatures below as
> proposed contracts; conflicts with currently enforced safety types require an explicit, reviewed
> reconciliation, not silent relaxation.

**Goal:** Build and verify the complete Hermes-development / OpenCode-research / deterministic-Algua platform on a pinned ~2-year real yfinance dataset, with no paid-data dependency and no real-money activation.

**Architecture:** One Algua repo and registry. Hermes Kanban owns **engineering**, OpenCode operates independently and owns **strategy research**, and Algua owns deterministic data/backtests/portfolio/risk/execution. Small reviewed vertical slices, no duplicate schedulers or task systems, production engine never trusts unreviewed strategy Python.

**Tech stack:** Python 3.12, uv, Typer JSON CLI, SQLite/Parquet, pandas, vectorbt, MLflow, OpenCode CLI, systemd, GitHub Actions, React + TypeScript/Vite (existing Algua frontend), and FastAPI (existing web backend). `pytest`, Ruff, mypy, import-linter, Vitest and viewport checks.

**Spec:** [three-harness design](../specs/2026-10-30-algua-three-harness-design.md). PRD reconciliation: [Vision of Record](../../PRD.md).

**Baseline inspected:** `its-nix/algua` main `db6860000f87a6cc98469e0e4901fa9c10c0d277` (2026-10-22) and `its-nix/os` main `583f065c04baadce81f30a925fd4b8feb34c4e67` (2026-10-27). Re-check branch tips and open PRs before implementation. Open Algua PRs observed: #707 acceptance dashboard, #712 planner safety fix, #713 sprint docs, plus Dependabot. Rebase/coordinate before editing their areas.

## Global constraints

- **Do not activate real-money trading, increase capital, bypass the human-signed live wall, or expose broker credentials to research agents.** No subscription or paid data purchase is authorized.
- Preserve protected code and `CODEOWNERS`, `t→t+1`, point-in-time knowability, holdout consumption/search-breadth accounting, data provenance, risk limits, frozen deployment identity and account-wide reconciliation.
- For any *new* authorization (automatic merges or paper deploy), prove enforcement through integration tests and a separate security review; do not assume a role prompt is a boundary.
- Experimental market data is **real** and pinned but is `pilot_real_proxy`; it cannot claim a PIT-correct historical $500M–$10B universe, nor justify real-money activation. Never relabel replay as elapsed paper evidence.
- One systemd **research initiation** schedule; preserve market-session paper clock and trusted merge-queue locking where needed. Avoid overlapping old/new writers.
- OpenCode operates research; Hermes owns engine/data/portfolio/risk/operator/web engineering; Algua CLI/registry owns deterministic outcomes and their provenance.
- Hermes Kanban = engineering tasks, GitHub = code/evidence, Todoist = human commitments only. Experiment rows do not become Kanban cards.
- TARGET: exact-head CI and independent review before any allowlisted automatic merge, which needs separately reviewed authority. Today every merge needs Lior's approval. Protected changes require owner approval; no automatic live deployment or capital-impacting behavior change.
- Use isolated branches/worktrees, preserve dirty user changes, avoid public commits of data, credentials, customer/account information or paid datasets.
- Use incremental vertical slices; no wholesale code rewrite simply to change an agent backend.

## Review focus — five scenarios to pin to owning tests

1. **Untrusted strategy code** attempts registry, broker, filesystem, network or credential access: child process is denied and account/authority state is unchanged (Task 4).
2. **Historical replay misrepresented as forward evidence:** gate and UI refuse progression/labeling; no fabricated broker-clock session (Tasks 1, 5, 7, 9).
3. **Job crash while a claim/merge is in-flight:** idempotent recovery does not duplicate trials, commit twice or submit a duplicate order (Tasks 5, 7).
4. **Mixed-modality look-ahead / model version swap:** context and model binding reject future-known inputs and mismatched artifacts; no bypass via alternative adapter (Task 2).
5. **Auto paper deployment during active tick or forward-only schema migration:** do not deploy/rollback unsafely; quiesce, verify and reach safe state on uncertainty (Task 7).

## Workstreams and dependencies

**Foundation (Tasks 0–1)** → **contracts & portfolio (Tasks 2–4)** → **research operating loop & learning (Tasks 5–6)** → **delivery & UI (Tasks 7–9)** → **independent acceptance (Task 10)**. Some UI and engineering tasks may run in parallel after contract stability. Each task is a reviewable increment and may be split into smaller PRs if its tests reveal genuine independent responsibilities.

---

### Task 0 — Publish the accepted design and reconcile authority

**Files**
- Modify: `docs/PRD.md`, `docs/architecture.md`, `docs/vision-reconciliation.md`, `docs/agent/operating.md`, `docs/agent/story-delivery.md`, `AGENTS.md`, `CLAUDE.md` (only statements that conflict with ratified policy)
- Create: `docs/superpowers/specs/2026-10-30-algua-three-harness-design.md`
- Modify in separate Nix OS PR: `its-nix/os/profiles/algua/ROLE.md` and, if necessary, `its-nix/os/docs/ARCHITECTURE.md`
- Tests: repository link/doc tests and a small contract assertion for authority routing if the repo has one

**Interfaces:** Creates the source-of-truth responsibility map consumed by all subsequent tasks. Do not make docs changes that themselves grant new runtime permissions.

- [ ] **Step 1:** Inspect main, open PRs, existing schedules, real deployed unit paths, current runtime authorizations and protected CODEOWNERS/branch settings; record observed-versus-target matrix.
- [ ] **Step 2:** Add a contract test/static review proving agent work is not described as Todoist-managed and that the human live gate is unchanged.
- [ ] **Step 3:** Reconcile the exact PRD sections, preserving all nonconflicting existing PRD text; document superseded UI and agent-harness decisions explicitly.
- [ ] **Step 4:** Run docs/link, repository hygiene and existing CI; independent product/security review.
- [ ] **Step 5:** Open PR(s) with checks, diff summary and an ADR for the new control-plane split; merge only with Lior's approval (new automation is not enabled yet).

**DoD:** No conflicting authoritative instructions, no silent permission expansion, reviewed product direction captured in canonical sources.

### Task 1 — Real-data pilot, immutable snapshot and honesty labels

**Files**
- Reuse/modify as needed: `algua/data/providers/yfinance.py`, `algua/data/store/bars.py`, `algua/data/manifest.py`, `algua/data/capabilities.py`, `algua/cli/data_cmd.py`, `algua/cli/research_batch_cmd.py`
- Create: `algua/contracts/data_tier.py` (pure value types, if a single metadata field is insufficient)
- Tests: `tests/test_data_providers.py`, `tests/test_data_store.py`, `tests/test_data_capabilities.py`, `tests/test_research_gates.py`; new `tests/test_pilot_data_tier.py`

**Interfaces:** `DataTier` with `pilot_real_proxy | verified_pit | synthetic_fixture`; `PilotDataManifest(snapshot_id, start, end, provider, universe_method, limitations)` persisted in existing metadata/provenance; downstream experiment read returns this tier unchanged. Do not introduce a second snapshot store.

- [ ] **Step 1:** Write tests that a yfinance snapshot retains its exact content ID and data-tier limitations through backtest → registry → run projection; assert that `pilot_real_proxy` cannot be represented as PIT-verified.
- [ ] **Step 2:** Run focused tests and confirm failure on the missing tier/lineage wiring.
- [ ] **Step 3:** Implement minimal metadata plumbing and a repeatable bounded data-ingest command/script for ~150–300 securities over ~2 years; capture chosen tickers as an explicit **proxy** universe with provenance. Verify metadata first, not market-cap accuracy we cannot prove.
- [ ] **Step 4:** Run tests; sample missing bars, splits, handling of delisted symbols, stale sessions and revision effects. Persist one immutable fixture/research snapshot and compare checksum across reloads.
- [ ] **Step 5:** Full gate + independent integrity review; PR with snapshot/selection recipe but **without** raw vendor data in public Git.

**DoD:** Real-data research can run against a stable snapshot with automatically visible limitations; provider swap requires no research engine redesign. No paid data.

### Task 2 — One multimodal strategy interface

**Files**
- Create: `algua/contracts/strategy_context.py` (versioned `AsOfContext`/`AsOfView` contracts, pure or import-light)
- Modify: `algua/strategies/base.py`, `algua/strategies/loader.py`, `algua/contracts/types.py`, `algua/evaluation/inputs.py`, `algua/backtest/decision_path.py`, `algua/models/registry.py` only when necessary for pinned models
- Tests: `tests/test_strategies_base.py`, `tests/test_strategies_base_fundamentals.py`, `tests/test_strategies_base_news.py`, `tests/test_model_config_and_loader.py`, `tests/test_decision_parity.py`; new `tests/test_multimodal_context.py`

**Interfaces**

```python
@dataclass(frozen=True)
class AsOfView:
    kind: str
    knowable_at: datetime
    snapshot_id: str
    frame: pd.DataFrame    # defensive copy on read; never mutable authoritative state

@dataclass(frozen=True)
class AsOfContext:
    decision_ts: datetime
    universe: tuple[str, ...]
    features: Mapping[str, AsOfView]
    models: Mapping[str, ModelHandle]

class ResearchStrategy(Protocol):
    def score(self, context: AsOfContext) -> pd.Series: ...
```

Use existing `LoadedStrategy` and `Strategy` protocol adapters until interface parity is proven, then remove mutually exclusive modality-specific branches. Model use is pinned per artifact with training-as-of <= its first permitted decision; names and revisions cannot drift.

- [ ] **Step 1:** Add tests: bars+news+model simultaneously; missing required modality fails closed; a future-known news row is invisible; tampered model ref/hash rejected; duplicate/NaN score output rejected.
- [ ] **Step 2:** Confirm tests fail under the current mutually-exclusive `needs_*` behavior.
- [ ] **Step 3:** Implement context normalization and a single `score(context)` path; preserve existing pure strategy adapter behind a compatibility shim only while all legacy strategies/tests are migrated.
- [ ] **Step 4:** Test a rule-based strategy, a model-based strategy and a **real** combined-input case if timestamped source data is available; use synthetic fixtures only to test missing and future-known input safety.
- [ ] **Step 5:** Run parity/backtest/test gates + independent Quant/Engineering review; commit and merge with Lior's approval. TARGET: automatic merge only if the diff is within separately reviewed code authority.

**DoD:** Every strategy type uses one signature and finite score output; no data source is implicitly fetched from inside strategy code; protected model/temporal gates are intact.

### Task 3 — Deterministic multi-strategy portfolio aggregation

**Files**
- Create: `algua/portfolio/allocator.py` (risk-budget/aggregation logic)
- Modify: `algua/portfolio/construction.py`, `algua/registry/allocations.py`, `algua/live/planner.py`/its facade only through tested seams, `algua/backtest/engine.py` where needed
- Tests: `tests/test_portfolio_construction.py`, `tests/test_allocations.py`, `tests/test_lane_parity.py`; new `tests/test_portfolio_allocator.py` and `tests/test_book_portfolio_parity.py`

**Interfaces**

```python
@dataclass(frozen=True)
class PortfolioConstraints:
    max_gross: float
    max_weight_per_symbol: float
    max_turnover: float | None


def allocate_targets(
    strategies: Mapping[str, pd.Series],
    budgets: Mapping[str, float],
    constraints: PortfolioConstraints,
) -> pd.Series: ...
```

Existing sizing, order intents, account-wide book controls and risk guards remain authoritative. Budgets are adjusted deterministically using persisted, appropriately estimated vol/overlap; never use a current equity curve to peek into a past allocation.

- [ ] **Step 1:** Test two strategies wanting the same symbol, conflicting weights, zero qualified candidates, unavailable risk estimates, fractional/small capital, and cash remainder; assert caps, deterministic ordering and no borrowing.
- [ ] **Step 2:** Confirm failing tests on missing allocator.
- [ ] **Step 3:** Implement simple capped volatility-aware budgets and overlap controls with a safe default; expose one net account target for deterministic planner/execution.
- [ ] **Step 4:** Run same scenarios through backtest/paper-plan tests; verify next-eligible-session fills, turnover hysteresis, no retroactive signal use and the valid all-cash outcome.
- [ ] **Step 5:** Full gate; independent portfolio/risk review and protected-path approval as required.

**DoD:** End-to-end portfolio target can combine 2+ independently evaluated strategies, remains legal under all risk walls and reproduces deterministically.

### Task 4 — Enforced strategy runtime isolation (blocker for broad auto-merges)

**Files**
- Evaluate/modify: `algua/live/frozen_child.py`, `algua/live/frozen_dispatch.py`, `algua/live/frozen_wire.py`, `algua/registry/frozen_runtime.py`
- Modify: `algua/operator/diff_policy.py`, `algua/strategies/loader.py`, `algua/operator/gate_runner.py`, run-sandbox/deploy configuration as warranted
- Tests: `tests/test_frozen_child.py`, `tests/test_frozen_paper_isolation.py`, `tests/test_opencode_workflow_hardening.py`; create `tests/test_untrusted_strategy_containment.py`

**Interfaces:** Untrusted strategy process accepts `AsOfContext` or a validated frozen wire representation; returns a versioned finite score vector only. Privileged supervisor alone owns broker, account, ledger, policy and network capabilities.

- [ ] **Step 1:** Confirm actual threat model: generated strategy Python can `import os`, do dynamic imports or read environment. Test with deliberately hostile strategy attempts against broker tokens, registry writes, socket access and parent filesystem.
- [ ] **Step 2:** Confirm controls **fail closed** when kernel isolation or policy is absent (no silent `sandbox=none` on autonomous runs); compare existing `bwrap`, frozen child, working-tree and paper paths.
- [ ] **Step 3:** Implement the smallest reviewed hard boundary (separate unprivileged process/user/container with no secrets/network, narrow read-only inputs/output). Characterize both research and **authoritative strategy execution**, not just authoring.
- [ ] **Step 4:** Regression-test that replay/backtest/paper planning remain equivalent and that a malicious output cannot set exposure or change live gate state.
- [ ] **Step 5:** Independent adversarial security review + full CI. **Do not enable broad strategy auto-merge/automatic paper activation until passing.**

**DoD:** Research-generated strategy code can be loaded and evaluated without ambient authority. This task may require its own protected approval even if previous low-risk auto-merge policy is approved.

### Task 5 — Autonomous OpenCode research factory (one initiator)

**Files**
- Modify/rework: `.opencode/agents/{research,author,interpret,forage,leap}.md`, `.opencode/skills/*/SKILL.md` within approved skills, `.opencode/scripts/run_agent.sh`, `.opencode/scripts/run-research-loop.sh`, `.opencode/scripts/{forage,leap}.sh`
- Modify: `deploy/systemd/algua-research.{timer,service}`, retire independent duplicate research-ideation scheduling **only after parity and activation**; leave trusted paper and queue locks intact
- Reuse: `algua/cli/idea_cmd.py`, `algua/cli/idea_ops_cmd.py`, `algua/cli/research_batch_cmd.py`, `algua/operator/loop_health.py`
- Tests: `tests/test_forage_leap_launchers.py`, `tests/test_agent_runtime_seam.py`, `tests/test_loop_health.py`, `tests/test_idea_attempts.py`; new `tests/test_research_cycle_recovery.py`

**Interfaces:** One durable `research_cycle_id`, `claim_token`, immutable run `context`, bounded `max_hypotheses`, `max_wall_time`, `max_cost`, `worker_limit`, result `attempts[]` with terminal status + evidence URLs. Keep existing CLI JSON envelope and append-only records.

- [ ] **Step 1:** Record the current schedules and disabled/error states; test one research cycle on a pinned real-data snapshot with a deliberately failing worker and a duplicated claim. Assert one final outcome per claim.
- [ ] **Step 2:** Refactor the current 1,000+ line shell driver only where a smaller deterministic adapter is justified; keep unique behavior (scratch registry, fencing tokens, bounded digest, merge-back serialization). Use one OpenCode CLI invocation per research reasoning task, **not** per numerical sweep trial.
- [ ] **Step 3:** Wire specialized OpenCode worker roles/skills and model/provider configuration. Restrict auth/credentials; enforce process limits, fail-closed sandbox and typed outputs.
- [ ] **Step 4:** Exercise full cycle: read prior knowledge -> select campaign -> generate strategy -> run numeric batches -> interpret -> independently review -> write outcomes/lineage -> new campaign. Test crash recovery, provider exhaustion, empty idea pool and repeat-run idempotency.
- [ ] **Step 5:** With Lior's approval of the cutover, switch schedules with one coordinated cutover and rollback plan, confirm `systemctl list-timers` shows exactly one research initiator, and demonstrate two successive real-data cycles.

**DoD:** OpenCode runs genuine independent research while Hermes is offline; one scheduler/one registry, visible claims, bounded costs and no duplicate work.

### Task 6 — Cumulative learning and research resource allocation

**Files**
- Reuse/extend: `algua/registry/idea_scorecard.py`, `algua/registry/idea_attempts.py`, `algua/registry/negative_results.py`, `algua/knowledge/experience.py`, `algua/research/idea_dedup.py`, `.opencode/skills/leap-hypotheses/SKILL.md`
- New only if needed: `algua/research/campaign_policy.py` (pure selection policy)
- Tests: `tests/test_idea_scorecard.py` if present, `tests/test_idea_attempts.py`, `tests/test_negative_results.py`, `tests/test_knowledge_sync.py`; new `tests/test_campaign_policy.py`

**Interfaces:** `CampaignChoice(category, hypothesis_id, reason, prior_evidence_ids, budget)`; pure function accepts prior aggregate scorecard + novelty bounds + resource budget, returns a deterministic candidate menu; OpenCode chooses/explains within constrained options.

- [ ] **Step 1:** Test that a rejected family changes future selection, duplicate hypotheses are not re-run without new reason, errors are not misclassified as negative alpha, and some budget remains for novel directions.
- [ ] **Step 2:** Record truthful denominator and trial-count behavior for invalid, unfinished and successful attempts; fail the tests on current incomplete evidence paths.
- [ ] **Step 3:** Add minimal reusable reading/feedback surface to existing registry; consolidate family notes in the existing KB, no second orchestration database.
- [ ] **Step 4:** Run two consecutive research cycles and independently inspect why the second campaign changed. Quantify throughput, novelty, duplicates and root causes without claiming guaranteed improvement.
- [ ] **Step 5:** Full gate and independent review; merge only under current authority.

**DoD:** Evidence causally influences future research, and every attempt remains reproducible and auditable.

### Task 7 — Allowlisted auto-merges, immutable paper CI/CD and rollback

**Status:** TARGET BLOCKED. This whole task needs separately reviewed authority, and it must not bypass or duplicate Story 2.8's release-validation scope.

**Files**
- Modify: `.github/workflows/ci.yml`, `algua/operator/diff_policy.py`, `algua/operator/mergeback.py`, `.opencode/scripts/drain-mergeback-queue.sh`, `deploy/systemd/algua-paper.service`, `deploy/systemd/README.md`
- Create: `deploy/scripts/release-paper.sh` (or similarly small production release entry, isolated from untrusted PR execution)
- Tests: `tests/operator/test_diff_policy.py`, `tests/operator/test_mergeback.py`, `tests/test_repo_hygiene.py`, `tests/test_checkout_guard.py`; new `tests/test_release_paper.py`

**Interfaces:** Candidate merge allowed only if `(allowlisted_diff && independent_review_at_head && all_required_ci_green_at_head && strategy_isolation_passed)`. Paper deployment is pinned by exact content digest + provenance, validates service quiescence and read-only post-release health; rollback to known-good only if schema-compatible.

- [ ] **Step 1:** Test direct-main push bypass, stale approval after force-push, protected-file edits disguised as strategy code, and a paper tick concurrent with deploy. They must refuse.
- [ ] **Step 2:** Install fail-closed PR checks for protected path changes and exact-head independent review; create a trusted merger with least-privilege token. Never infer CI passed from an old SHA or aggregate status only.
- [ ] **Step 3:** Reconcile the existing `paper merge-back` direct-main mechanism, preserving authoritative evidence replay and locks while removing its ability to bypass the new verified merge policy. Eliminate competing direct-main writing paths after parity.
- [ ] **Step 4:** Build immutable paper release on CI; VPS deployment pulls exact trusted artifact, holds lock/quiescence, smoke-tests, verifies lifecycle health. Test rollback and safe halt on forward-only schema migrations.
- [ ] **Step 5:** Verify no live/research secrets on public PR runners, no untrusted PR execution on persistent VPS, no implicit changes to approved live artifacts; run full CI and independent security review.

**DoD (TARGET):** Once separately reviewed authority exists, approved low-risk paths auto-merge and paper-deploy without manual babysitting; live capital and protected engine cannot change through these mechanisms.

### Task 8 — Strategy-first leaderboard and independent UX review

**Files**
- Create: `web/frontend/src/screens/Leaderboard.tsx` (reuse existing Research/StrategyBoard UI logic)
- Modify: `web/frontend/src/App.tsx`, `web/frontend/src/main.tsx`, `web/frontend/src/screens/Research.tsx`, `web/frontend/src/screens/StrategyDetail.tsx`, `web/frontend/src/components/StrategyBoard.tsx`, `web/frontend/src/types.ts`, `web/frontend/src/theme.css`
- Modify if needed: `algua/registry/strategy_board.py`, `algua/cli/runs_cmd.py`, `web/backend/main.py`
- Tests: `web/frontend/src/components/StrategyBoard.test.tsx`, `web/frontend/src/screens/StrategyDetail.test.tsx`, `web/frontend/src/invariants/word-budget.test.tsx`, `web/frontend/scripts/verify-viewport.mjs`; new `web/frontend/src/screens/Leaderboard.test.tsx`

**Interfaces:** `GET /api/strategy-board` remains read-only, one row per stable strategy ID, with latest evidence; additive attributes `data_tier`, `n_obs_oos`, `freshness` if needed. Sort is **UI exploratory** and never selection logic for promotion. The current `strategy-board/v1` contract stands until a separately admitted UI contract replaces it; see the [supersession record](../../vision-reconciliation.md#strategy-leaderboard-supersession-2026-10-30).

- [ ] **Step 1:** UX specialist creates desktop/mobile strategy-first wireframe with action/result hierarchy, explicit stage tags, unknown/stale/error states, and no four-tab bottom navigation.
- [ ] **Step 2:** Add tests: one row/identity, zero/unknown values honest, comparable-only OOS sorting, stages including candidate/forward_tested, click/detail navigation, latest-not-best run selection, mobile 390px.
- [ ] **Step 3:** Implement minimal React/Vite redesign reusing existing `StrategyBoard` and detail components; preserve diagnostic access and avoid a second frontend framework.
- [ ] **Step 4:** Independent UI/UX agent inspects real screenshots in 390px mobile + desktop, tests keyboard behavior, exact metric labeling and evidence disclosure. No invented/demo production metrics.
- [ ] **Step 5:** Run web/backend/frontend and full root CI; merge and deploy the monitor release only with Lior's approval.

**DoD:** Mobile-first strategy leaderboard is the primary interface; bottom navigation removed; every visible metric is real, qualified or UNKNOWN, and drill-down is correct.

### Task 9 — Hermes development and incident handoff

**Files**
- Nix OS: `profiles/algua/ROLE.md`, scoped specialist role files where approved, `skills/packs.json`, `docs/ARCHITECTURE.md` only if necessary
- Algua: `docs/agent/story-delivery.md`, `docs/agent/operating.md`, `algua/operator/alerts.py`, `algua/operator/loop_health.py`, optional `algua/cli/ops_cmd.py` read-only summary
- Tests: `tests/test_loop_health.py`, `tests/test_operator_alerts.py`; Nix OS existing role/config checks

**Interfaces:** One minimal aggregate machine-health/incident payload with `fingerprint`, `severity`, `first_seen`, `last_seen`, `evidence_refs`, `reproduction`, `owner=algua-lead`, `required_action`. No account secrets, raw model prompts, or private downloaded data in public issues/Discord.

- [ ] **Step 1:** Test worker failure vs. negative economic result: only reproducible systemic failures become Hermes engineering incidents. Ensure dedup across retries.
- [ ] **Step 2:** Add read-only operational issue summary; Hermes Lead claims deduplicated issue, delegates bounded fix and independent verification, routes PR+CI+release evidence back to the originating issue.
- [ ] **Step 3:** Reconcile role contracts: Hermes **builds** the engine, OpenCode **operates** research; never duplicate every experiment as a Kanban task. Keep LNX portfolio supervision rather than deep per-trial polling.
- [ ] **Step 4:** Verify one closed incident -> test -> reviewed PR -> merge/deploy approved by Lior -> observed recovery and return evidence.
- [ ] **Step 5:** Independent role/governance review, documentation and passing tests.

**DoD:** Hermes can improve Algua from real operational evidence without hijacking the research schedule or directly rewriting strategy returns.

### Task 10 — Real operational acceptance (no premium-data purchase)

**Files:** `docs/acceptance/2026-10-30-algua-machine-acceptance.md` (create after real test execution), test logs and immutable registry/GitHub references; use existing acceptance dashboard PR #707 if reviewed rather than duplicating it.

- [ ] **Step 1:** Establish a fixed two-year real-data snapshot and actual deployment/environment commit identities. Record missing PIT coverage honestly.
- [ ] **Step 2:** Run 10 unattended production-like OpenCode research cycles and >=100 recorded attempts/variants across several families; save full failure/claim/lineage counts.
- [ ] **Step 3:** Independently reproduce selected outcomes from code, pinned snapshot and config; prove duplicate attempts, failed jobs, cost assumptions and data-tier qualifiers remain visible.
- [ ] **Step 4:** Exercise multimodal contracts and 2+ strategy portfolio aggregation; demonstrate visible leaderboard and correct detail evidence.
- [ ] **Step 5:** Inject a worker crash, failed data refresh, CI failure and failed paper deployment; verify bounded recovery or safe halt with durable incident.
- [ ] **Step 6:** Verify paper-session operation on its real schedule and a separate historical accelerated replay; show explicit labeling, no fabricated elapsed forward sessions, and immutable live wall unchanged.
- [ ] **Step 7:** Quant Reviewer and Engineering Reviewer sign off their own test evidence; mark each criterion PASS/FAIL/UNKNOWN. Do not assert all passed if any unverified.

**DoD:** Algua's full intended machine, as implemented, has demonstrated consistent autonomous behavior **on limited real data** and has an evidence-backed list of remaining data/investment limitations. Only then propose a premium dataset purchase, still requiring human approval.

---

## Acceptance commands, unchanged foundation

```bash
uv sync --locked
uv run pytest -q
uv run ruff check .
uv run mypy algua scripts
uv run lint-imports
uv run --project web pytest web/backend/tests -q
cd web/frontend && npm ci && npm run check && npm run build && npm run verify:viewport
```

Run focused tests after each slice, then the full CI gate before any merge. For safe operational integration test runs, use test credentials/fixtures and a sandboxed scratch registry; real-market input data does not imply real brokerage orders.

## Cutover and rollback rules

Every cutover below needs Lior's approval; none is authorized by this plan.

- **Control-plane cutover:** capture current schedulers + code/DB locations; start new research orchestrator with old research-initiation timers disabled as one reviewed release. If the new system fails, halt the new one before restoring the old one; never permit two writers to claim the same authoritative research idea pool concurrently.
- **Strategy API cutover:** run the old/new adapters against identical pinned input windows and compare score/weight/decision outcomes; remove the compatibility adapter only after all supported strategies have parity.
- **Paper release:** use immutable release digests and deploy-time locks. Forward-only SQLite migrations may make direct downgrade unsafe; define a tested safe-stop/forward-repair path rather than promising universal rollback.
- **Authority cutover:** do not auto-merge strategies into a privileged process until Task 4 containment and Task 7 verified-policy tests pass. If controls fail, halt merge/paper promotion; do not weaken them as an incident workaround.
- **Source of truth:** do not let autonomous workers rewrite owner PRD, signing policy, CODEOWNERS or skill governance to satisfy a failing gate.

## Plan review / execution handoff

Prior to implementation, review the PRD consolidation and design for owner intent, then publish reviewed docs into their intended GitHub paths. Ask LNX to create *one parent Kanban initiative* with task cards for the independent deliverables (not one card per experiment); route specialist work to Hermes and operations to OpenCode. LNX must report actual PR numbers, exact-head CI, test evidence, observed cycles, and any human-only decisions. No actual Algua code/deployment changes have been performed by generating this plan.
