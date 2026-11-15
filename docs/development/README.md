# Development cycle

Product authority is [the canonical vision](../PRD.md); current implementation is mapped in
[architecture](../architecture.md). Follow [the delivery policy](../agent/story-delivery.md) for
small runnable changes, proportional checks and bounded review. No planning framework, readiness
report, separate specification PR or sprint ceremony is required for routine work.

This directory retains technical contracts, story acceptance criteria and dated delivery evidence.
The [epics](epics.md) capture the September artifact-freeze-first breakdown, not a replacement for
the current PRD or later owner decisions. Readiness reports and retrospectives record their dated
assessments; their process instructions do not override the current delivery policy. Existing
technical safety contracts and protected-review requirements remain binding. A code merge is not
authorization to deploy, trade or allocate capital.

The owner reconfirmed the November strategy-delivery target on 2026-11-14: historical economic
qualification plus short scheduled paper operational qualification (PRD §16). Story 2.1's older
blanket unrelaxed-defaults predicate needs policy revision before implementation. Preserve its
auditability and no-agent-waiver goals; this decision does not relax current executable gates.

The [Algua Todoist board](https://app.todoist.com/app/project/algua-6hGjQph9JgcgpC2G) is the shared
execution board for agents and Lior. GitHub retains code, review and implementation evidence;
repository artifacts retain technical contracts and dated acceptance records. Respect existing
claims and link related deliverables rather than maintaining a competing sprint/task queue.
Do not infer completion from a title.

The 72-hour exercise and actual live sign-off are later acceptance events. Until they occur,
reports must distinguish tests passing, code merged, deployment verified and capital authorized.

## Integration reconciliation — 2026-11-15

The approved daily milestone and shared-board direction are merged in
[PR #839](https://github.com/its-nix/algua/pull/839). Older proposal branches and PR evidence remain
available; closure is not implementation or acceptance. The canonical local `main` checkout was
fast-forwarded to that merge; historical worktrees remain retained snapshots, not deployment inputs.
Uncommitted historical qualification notes were preserved on
[`archive/qualification-docs-2026-11-15`](https://github.com/its-nix/algua/tree/archive/qualification-docs-2026-11-15),
not merged into current operating instructions. No source or user audio was discarded.

| Retained proposal | Disposition / next action |
|---|---|
| [#713](https://github.com/its-nix/algua/pull/713), [#715](https://github.com/its-nix/algua/pull/715) | Closed as superseded integration proposals. Current PRD/architecture/operating guides replace the old status, coordination and preparation workflow; historical story evidence remains dated. |
| [#714](https://github.com/its-nix/algua/pull/714), [#716](https://github.com/its-nix/algua/pull/716) | Closed historical audits/inventories. Their old results are not current readiness or implementation admission. |
| [#717](https://github.com/its-nix/algua/pull/717) | Closed/deferred CI-contract proposal. Reuse relevant evidence requirements during scoped release work; current manual-CI/proportional-check policy remains. |
| [#718](https://github.com/its-nix/algua/pull/718) | Closed/deferred wheel-identity proposal. Reproduce the reported failure on current source before a protected correction; the old proposed contract is not normative. |
| [#707](https://github.com/its-nix/algua/pull/707) | Closed/deferred Allure acceptance-report framework, distinct from the merged operational dashboard. Retain useful scenarios for later scoped reuse, without adding a framework prerequisite. |
| [#670](https://github.com/its-nix/algua/pull/670), [#694](https://github.com/its-nix/algua/pull/694) | Closed/deferred optional pandas/Arrow major-version widening. Current constraints/lock remain; reopen justified upgrades against current source. |
| [#730](https://github.com/its-nix/algua/pull/730) | Open blocked runtime-isolation draft. Conflicts with current main; requires scoped current-source assessment and applicable human review. Historical test claims are not current-head acceptance. |

After reconciliation, resume the shared board's ordered research/data and operations/recovery
tracks. Security/accounting defects interrupt either track. The pending comparison with external
trading frameworks may inform the next roadmap discussion; no new functionality or changed
authority is inferred from it. Git synchronization does not establish the VPS's installed revision.

## Artifact-freeze delivery record

[Story 1.1 — planner extraction](stories/1-1-extract-in-process-decision-planner.md),
[Story 1.2 — explicit deployment epochs](stories/1-2-record-working-tree-deployments.md) and
[Story 1.3a — two-phase planner boundary](stories/1-3a-complete-two-phase-planner-boundary-in-process.md)
are implemented, independently reviewed and merged. None of those merges is a deployment.
[Story 1.3 — frozen planner artifacts](stories/1-3-materialize-and-execute-frozen-planner-artifacts.md)
is complete as an aggregate parent outcome, delivered through its child stories. The
[2026-09-25 readiness assessment](implementation-readiness-report-2026-09-25.md) found it too large
for one implementation/review cycle, and the approved
[Sprint Change Proposal](sprint-change-proposal-2026-09-25.md) divides it into Stories 1.3a–1.3d.
[Story 1.3b](stories/1-3b-materialize-and-verify-recoverable-planner-artifacts.md) is done
(PR #676). [Story 1.3c](stories/1-3c-execute-frozen-planners-in-paper.md) is done (PR #680).
[Story 1.3d](stories/1-3d-bind-operational-evidence-and-qualification.md) is done (PR #683), with
deployment-bound invocation evidence and frozen qualification implemented under its
[normative evidence contract](specs/spec-story-1-3d-frozen-evidence-and-qualification/SPEC.md).
The [readiness review](implementation-readiness-report-2026-09-30-story-1-3d.md) is historical. The older
[readiness assessment](implementation-readiness-report-2026-09-24.md) covers only Story 1.1, not
either whole epic. [Deferred findings](stories/deferred-work.md) retain pre-existing issues outside
the active story boundary.

Use `docs/PRD.md` and `docs/architecture.md` directly rather than copying them here.
`sprint-status.yaml` is retained as a delivery record; it is not a required development workflow
or proof of merge, deployment, qualification or trading authority.
