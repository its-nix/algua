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

GitHub issues track implementation work and reviews. Repository artifacts retain specifications
and acceptance evidence. The [Algua Todoist board](https://app.todoist.com/app/project/algua-6hGjQph9JgcgpC2G)
tracks Lior's actual decisions/access actions. Avoid duplicating generic engineering chores onto
the human board. Respect existing tasks and assignments; do not infer completion from a title.

The 72-hour exercise and actual live sign-off are later acceptance events. Until they occur,
reports must distinguish tests passing, code merged, deployment verified and capital authorized.

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
