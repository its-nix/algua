# Parallel daily-roadmap execution plan

> For agentic workers: use subagent-driven development for bounded independent tasks, subject to
> `AGENTS.md` and the proportional delivery policy. This is an orchestration plan for owner review;
> worker dispatch, claims and implementation have not started.

**Goal:** complete small verified roadmap slices in parallel without competing writers or expanding authority.

**Architecture:** one orchestrator owns dependencies, acceptance and integration; workers own isolated
worktrees and bounded deliverables. Reuse Todoist, Git/PR evidence, existing tests, the canonical
research records and the OpenCode runtime seam. Do not build another scheduler or task database.

**Stack:** Python 3.12/uv, existing Linux verification environment, Claude/Grok/Codex CLIs and
OpenCode through `.opencode/scripts/run_agent.sh` for research jobs.

**Spec:** [PRD §25](../../PRD.md#25-development-sequence),
[operating guide](../../agent/operating.md), [delivery policy](../../agent/story-delivery.md),
[comparison proposals](../../research/2026-11-15-external-trading-frameworks.md).

## Global constraints

- Preserve live signatures, capital limits, protected reviews, PIT/reproducible evidence, JSON CLI
  outputs, module boundaries and `decision_lag_bars >= 1`. Protected/deferred changes are flag-only
  until their required review; plan approval is not approval of an unseen integrity diff.
- One task, owner, branch and worktree per independent deliverable. Start from a recorded current
  main SHA. Never reuse an old historical worktree or overwrite another agent's work.
- Only the orchestrator integrates, updates shared task state and operates an authorized deployed
  lane. Workers use isolated scratch state, tests and labeled fixtures, never production authority DBs.
- OpenCode research keeps its narrower approved strategy/metadata scope and candidate ceiling;
  all loop launches use the existing seam and configured role models. No alternate research driver.
- No broker/live credentials or raw licensed vendor rows in worker prompts, logs or external models.
  Purchases, protected changes, live activation and capital increases retain their human boundaries.
- Initially at most three workers total, across native subagents and CLI processes, plus the
  orchestrator. Limit heavy Linux test runs to one at a time; preserve the existing six-worker cap.
  Native-agent tool slots and host resource limits may reduce concurrency further.
- Check authentication/quota before dispatch. Installed CLIs do not prove usable independent
  subscriptions; OpenCode can share the same underlying provider quota as another worker.
- Use existing subscriptions/configurations and explicit per-job wall/turn limits. Record actual
  usage where available; no new paid commitments or blind retrying after provider exhaustion.

## Ownership and dispatch

The orchestrator prepares a short self-contained brief: task ID, base SHA/worktree, requested
behavior, allowed paths/interfaces, evidence needed, exclusions and bounded checks. Workers return
the root cause, commit, tests actually run, unresolved risks and handoff. They do not spawn nested
workers, broaden scope, merge main or claim work owned by someone else.

Claim only unassigned Ready cards using the existing board protocol; reread for competing claims.
The broker/release card already has a codex claim: identify its session/owner and coordinate before
reassigning or operating that lane. Reserve shared-file/interface changes with the orchestrator.

Use Claude and Codex for bounded engineering, Grok for independent challenge/review, and OpenCode
for research authorship/interpretation through its existing roles. These are initial assignments,
not assertions that one vendor is universally better. Reassign on observed quality/quota limits
without changing accepted scope or losing the worker's commit/evidence.

## Wave 1 — independent blockers

| Task / initial worker | Candidate paths and interface ownership | Acceptance and focused verification |
|---|---|---|
| Research loop — Codex; card `6j2cp5Q2RGq2mm2p` | `.opencode/scripts/run-research-loop.sh`, associated research prompts and `algua/cli/idea_cmd.py`; driver/idea tests | Reproduce reported invalid `claimed` status and stale KB paths on current source. Fix the actual cause; do not add a fake lifecycle state or silently rewrite production rows. Check valid claims, invalid-status JSON and durable outcomes using `tests/test_cli_idea.py`, `tests/test_cli_idea_ops.py` and affected driver tests. If schema/protected repair is required, return a concrete flagged finding. |
| Web/Inbox security — Claude; card `6j2cp5Xj8crhC6JG` | `web/backend/extract.py`, push routes in `web/backend/main.py`, `web/backend/push.py`; reserve any Inbox CLI/store change before editing | Reproduce and address fetcher address-binding/NAT64, push ownership and intake-lock reports in separate small commits. Use `web/backend/tests/test_extract.py`, `test_push_api.py`, and affected Inbox tests. No network-policy or authority relaxation; no authenticated external messages. |
| Fleet P&L accounting — Codex; card `6j2cp5WXQ8cFvXHG` | `algua/portfolio/equity_curve.py`, `algua/cli/fleet_cmd.py` and existing read-side registry interfaces | Demonstrate allocation cash-in/out is not profit while real gains/losses remain visible. Use `tests/test_equity_curve.py` and `tests/test_cli_fleet_equity.py`; preserve lane/retirement/gap behavior. Protected risk, execution or qualification effects are flagged for review rather than changed. |

- [ ] Dispatch these three workers after the execution plan is accepted and claims/preflight pass.
- [ ] As a slot frees, assign Grok a read-only scoped review in its own worktree against the exact
  implementer diff. Review correctness/acceptance once; use fixes-only follow-up if needed.
- [ ] The orchestrator verifies actual diffs/test output, resolves shared-file conflicts and
  integrates accepted changes one at a time. Do not rely only on a worker's completion claim.
- [ ] If a diagnosis crosses another lane's files, stop that edit, settle ownership, then continue
  independent work. Overlapping root-cause work becomes one task, not parallel conflicting fixes.

## Wave 2 — data and research, with operations in parallel

- [ ] Prepare installed-source/sample acceptance for the merged Sharadar adapter. Actual VPS
  changes are serialized by the orchestrator under existing deployment permissions and locks.
- [ ] Freeze exact historical-universe rules before examining returns; implement historical
  identity/action/terminal/PIT work only in dependency order and through protected review.
- [ ] Use OpenCode in a separate research worktree to prepare/run the bounded read-only signal
  comparison: simple baseline, one analyst signal, then an optional critic/debate ablation.
  Predeclare timing, horizon, observations and model-cost budget; use existing ledgers and genuine
  prospective observations where model training/text vintages are unknown. No trading or
  qualification credit follows. Real model/data collection starts only with valid inputs and budget.
- [ ] In parallel, coordinate the existing operations owner on broker/restart and compatible
  release recovery. Retained PR #730 supplies historical material, not permission to merge its
  stale isolation implementation. Prepare the current-source protected decision first.
- [ ] Admit dashboard changes that expose evidence, costs, freshness and failure states when their
  underlying outputs are defined. Keep cosmetic work behind the operating slice.

## Integration and acceptance

Workers commit small logical changes in their own worktrees. The orchestrator integrates onto
current main sequentially, preserving review/protected requirements and running focused checks
for each change. Broader checks are used for material integrated behavior, not imposed on every
small fix. Linux-dependent CLI tests run in the established Linux environment, not a misleading
macOS pass. Do not disable useful tests or reclassify an unrun check as green.

Only mark Done after the requested behavior and its scoped evidence exist. Source merged,
installed, data-qualified, paper-qualified and live-authorized remain separate states. Keep task
claims, base/head commits and outcomes in Todoist/PR evidence so interruption does not cause repeat work.

The daily milestone ends with reconciled frozen scheduled paper behavior, observed recovery and
72 hours correct operation or a predefined safe halt. Five genuine successful paper sessions for
a surviving qualified strategy and exact human-signed live activation remain separate outcomes.
Elapsed exchange sessions cannot be parallelized or replaced by replay. No deadline forces a candidate.
