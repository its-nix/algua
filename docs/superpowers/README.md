# Design and implementation history

For new work, read the [Vision of Record](../PRD.md), [current architecture](../architecture.md),
and `CLAUDE.md` first. Read the [September reconciliation](../vision-reconciliation.md) for that
dated gap assessment and issue migration.

Files in `specs/` and `plans/` preserve decisions, evidence and implementation instructions as of
their dates. A document marked approved records approval of that design at that time; it does
not establish that all its features shipped or that its roadmap still governs.

Before reusing a plan, check its product assumptions against the current vision, its described
state against code/tests, and its operating commands against `CLAUDE.md`. Preserve useful design
rationale and current integrity contracts. Escalate changes to safety or authority boundaries
through the existing review process.

Historical LORD++/FDR veto and throttle designs are superseded: FDR does not block current
promotion. Do not restore those requirements from an old spec or plan. Current binding promotion
checks are described in `CLAUDE.md` and implemented in the promotion path.

The [November 7 strategy-delivery design](specs/2026-11-07-strategy-cicd-design.md) is the adopted
experimental-delivery target (reconfirmed 2026-11-14), now reflected in PRD §16. Its proposed 20%
drawdown amendment is not adopted. Earlier conflicting qualification plans need revision before
implementation; existing executable gates still apply.

The September 6 PRD and its numbered sections remain available in
[the pre-reconciliation revision](https://github.com/Lior-Nis/algua/blob/d9ed65455a626d3120559eca30fc0ed0818f9084/docs/PRD.md).
Older numerical PRD references refer to that revision unless a notice explicitly maps them to
the current vision. Use section titles alongside numbers in new references.
