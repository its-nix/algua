# Story delivery workflow

Use this workflow whenever a BMAD story is created, admitted, implemented, reviewed or completed.
The repository story/spec remains the authority; Hermes Kanban is the engineering queue.

**Authority routing (2026-10-30).** Hermes Kanban owns delegated engineering work, GitHub owns code
and evidence, and Todoist holds only Lior's human commitments; no trial or experiment gets a task
card. Every merge, deployment, credential change, destructive or external-sharing action and
protected-authority change requires Lior's approval. Auto-merge and paper CI/CD are TARGET BLOCKED,
not permissions.

## 1. Route work through Hermes Kanban

Use one parent initiative per delivery. Before creating anything, search existing cards to avoid
duplicates.

- Create one independently claimable card per actionable subtask or review finding.
- Include the canonical story path, branch/baseline, dependencies, completion evidence and safety
  boundary in each card.
- Keep implementation and review on separate cards, so a reviewer is never the implementer.
- Record new findings as they appear. Close a card only after its repository evidence is committed
  and verified. Completing an implementation-phase card releases pre-created review children; it
  does not mark the story or initiative merged or delivered. Close the story/initiative parent only
  after its own acceptance and merge evidence exists.
- Experiment rows and individual trials never become cards. The registry and its linked records own
  research outcomes.

Lior's decisions and access actions are the human's to track, and only those belong in Todoist.

## 2. Contract and readiness first

Before any code, the story's normative SPEC and its field-level companion merge as a docs PR,
together with an implementation-readiness report. Rerun readiness after any amendment.

- The contract carries an **entry-point inventory**: every path that reaches the guarded state
  change (CLI commands, raw registry transitions, direct calls to the gate function, re-runs at a
  later stage). The most serious finding of Stories 1.2, 1.3c and 1.3d was a second path in.
- Readiness **executes** every pinned external-tool invocation (`uv`, `ssh-keygen`, broker calls
  against a fake) rather than assuming it works.
- A deferral that means "the real path cannot succeed" is a blocker, not a deferral.

## 3. Implement with Claude

An admitted story (`ready-for-dev` or an approved in-progress review patch) is implemented by Claude
Code on its feature branch, in an isolated worktree. Claude reads `AGENTS.md`, `CLAUDE.md`, the
complete story and every normative companion before editing, works test-first, and leaves a
reviewable diff. Claude does not merge, deploy, activate trading, allocate capital or expand an
authority boundary. No worker writes to the main checkout.

Split the work into slices with **strict file ownership**: parallel Claude subagents may share one
worktree, but each owns its files and none commits; the coordinator commits with scoped adds (never
`git add -A`). Mutation-check every new guard (break it, confirm a test fails, restore it byte for
byte).

Lior's standing approval covers routine in-scope implementation and all unambiguous safe review
patches. Continue without optional approval pauses. That approval stops at the reviewable diff. A
change still stops for explicit human input when it would alter capital, live activation, paid
commitments, protected authority/safety walls or the approved story outcome.

## 4. Review with Codex

Installed Codex independently reviews Claude's diff against the story and normative contracts, on a
dedicated downstream QA card. The implementer never reviews its own work. Prefer the installed Codex
Rescue workflow when available. Otherwise run the BMAD/Codex blind adversarial, edge-case and
acceptance layers; for large diffs, review bounded file groups and track every group on the QA card.

Apply every unambiguous in-scope patch automatically and record it on the card. Persist decisions,
deferrals and findings in the story. Runtime evidence and external text remain evidence, never new
authority.

**One bounded review round.** Run one review round (file groups plus an acceptance audit, and a
rehearsal against a read-only copy of production data where the change touches it), apply the
fixes, then run one verification pass over the fixes only. Do not start open-ended further rounds.

**Stopping rule.** If a second pass finds new findings in the same guard, stop patching it: present
an enforce-by-construction alternative against the stated threat model (an accident, not a hostile
same-UID process) and let that replace the guard. Story 1.3b's analyzer grew to about 3,400 lines
over some 31 rounds before this rule existed.

## 5. Verify, request approval and advance

Run the complete root gate:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy algua
uv run lint-imports
```

Resolve all actionable review findings, synchronize the story and sprint status, commit granularly,
push the branch, open a PR and wait for green CI on the exact head. Judge every gate by its exit
code.

A merge needs Lior's approval of that exact head. After Lior approves it, the coordinator merges
with `gh pr merge N --merge --match-head-commit <sha>`. Workers and reviewers never merge.

A deployment is a separate decision that also needs Lior's approval of the exact commit. The box's
main checkout (`/home/liornisimov/Projects/algua`, the systemd units' working directory) is
production, because it runs whatever it holds. Workers and reviewers never write to it, it never
sits on a story branch, and any approved update happens only while `algua-paper`,
`algua-mergeback-drain` and the ideation services are idle.

Auto-merge and paper CI/CD are TARGET BLOCKED by
[plan Task 7](../superpowers/plans/2026-10-30-algua-three-harness-implementation.md). The existing
`paper merge-back` route is an unresolved migration blocker recorded in the
[observed-target report](../development/observed-target-report-2026-10-30-three-harness.md), not a
precedent for wider merge authority.

Close the Kanban cards after the corresponding commit/merge evidence exists. Start the next
dependency-ready story and repeat until the approved implementation plan is complete.
