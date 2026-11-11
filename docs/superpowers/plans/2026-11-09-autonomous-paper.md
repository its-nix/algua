# Autonomous paper implementation plan

> For agentic workers: use subagent-driven development for the two independent changes; the primary
> owns integration, docs and deployment. Existing isolated feature worktree is clean at `04fd1c3`.

**Goal:** remove human signatures from routine paper risk actions and experimental qualification.

**Architecture:** split unsigned paper actions from signed live authority; qualification authorship
is provenance while live independently verifies the evidence and human activation signature.

**Tech stack:** existing Python 3.12, SQLite, Typer, uv, Alpaca paper and systemd deployment.

**Spec:** `docs/superpowers/specs/2026-11-09-autonomous-paper-design.md`.

## Constraints and review focus

- Preserve live signatures, current historical criteria, five real scheduled paper sessions,
  next-bar execution, immutable evidence and JSON CLI results. Never fabricate human provenance.
- No unsigned paper action may write live policy/approval/allocation or authorize live orders.
- Configuration preserves severity. Explicit paper restoration requires settled reconciliation
  and records its reason/history; never automatically erase a failed test on restart.
- Migration preserves old qualification IDs/data/constraints and refuses future schemas. Quiesce
  all writers for rollout; do not run old code against the new database.
- Existing pending paper cleanup sells keep their original IDs; never resubmit during deployment.

## Task 1: unsigned paper account actions

Files: `algua/registry/drawdown_auth.py`, focused new paper account module as needed,
`algua/cli/risk_cmd.py`, `algua/execution/paper_mechanics_broker.py`, focused risk/CLI/mechanics tests.

- [x] Add focused regressions for direct unsigned paper configure/restore, exact paper host/account,
  flatness/pending orders, preserved severity, honest provenance/reason and unchanged signed LIVE.
- [x] Reuse baseline/flow/reconciliation/CAS persistence; split only the signature requirement.
  Require a reason for explicit paper restore. No schema change/fake human principal is needed
  merely to record automated paper actions; record explicit paper action provenance in state/events.
- [x] Update mechanics to accept legitimate automated paper policy while keeping USD5/CSL bounds.
- [x] Run focused tests, lint/types for changed modules, self-review; primary commits scoped files.

## Task 2: automatic five-session qualification

Files: `algua/cli/paper_experimental.py`, `algua/registry/experimental_qualification.py`,
`algua/registry/capped_qualification.py`, qualification/handoff diagnostic text,
`algua/registry/db/{experimental.py,migrate.py,constants.py}`, focused qualification/DB/live tests.

- [x] Add regressions for automatic agent recording, explicit preview, idempotence, failed/drifted
  report refusal, honest agent provenance and agent-produced evidence requiring final LIVE signing.
- [x] Add v53 migration accepting real human/agent/system qualification actors, preserving rows/IDs,
  foreign-key integrity and append-only triggers. Fresh/partial schemas and repeat migration work.
- [x] Default CLI records a passing report; retain preview flag. Remove the redundant intermediate
  human signing requirement and keep independent live source re-verification and final signature.
- [x] Run focused tests and self-review; primary commits scoped files. Frozen-world tests run
  sequentially to avoid their temporary-source fixture races.

## Task 3: integrate, document and deploy

- [x] Independently review each diff and the combined paper/live boundary; fix concrete findings.
- [x] Amend current PRD/operating/layered-risk/capped-live/mechanics docs and supersede the private
  signing helper so the owner is no longer told to sign a paper policy.
- [x] Run focused integration, root Ruff/mypy/import contracts and whitespace checks; omit full
  suite/CI under delivery policy. Commit exact source before building.
- [x] Take consistent registry backup with writers paused; migrate via new CLI; build/adopt exact
  immutable paper application/anchor. Update root paper selector/helper and mutable research source
  together; preserve original pending liquidation receipts and no mechanics identity migration.
- [x] Verify installed unsigned paper CLI behavior. If sells are still pending, report the genuine
  flatness prerequisite; no signature challenge is requested, no fill or qualification invented.
- [x] Restore prior services/timers, update existing Todoist cards, report actual checks/limits.

Ruling: existing optional authenticated research/forward relaxation commands stay protected; the
normal unattended path uses current default gates. Removing them would change evidence policy,
which the owner did not ask to weaken. Paper-only risk actions and five-session recording are the
current manual bottlenecks and are in scope.

## Completion evidence, 2026-11-09

Source implementation commits: `a1d0abd` (paper risk), `33ef6e6` (automatic qualification/v53),
`e459140` (operating docs/help and installed entry). Application source deployed at exact
`e459140f4e9e6a35e941d413610739f3bd7d4723`, digest
`392cb13113b56a6e9c3d5f049d65d4070922e0399756f8c14b8197437ea20e97`.

Bounded combined review found no Important/Critical issue. Actual checks: 223 integration tests,
23 capped-live tests with agent-authored qualification, 212 focused qualification/schema checks,
96 paper-risk/controller/mechanics checks plus final focused regressions; final text/help check
rerun 64 passed. These groups overlap. Root Ruff, mypy (491 sources), imports (31 kept/0 broken),
whitespace and shell syntax passed. Full suite/CI intentionally omitted under fast-delivery policy.

VPS: exact nonroot build/26,023-file inventory, immutable adoption/anchor, coordinated backups and
v52→v53 registry migrations with integrity/FK checks passed. A missing default bundle ref stopped
initial deployment before migration; corrected to explicit branch fetch. Original backups retained;
no old-code DB rollback. Dashboard/timers restored. Installed unsigned configure refused actual
unsettled positions/orders with no signing challenge; no policy or mechanics session fabricated.

One already-approved USD5/CSL round trip is scheduled at 14:33UTC through the installed CLI,
subject to flatness and regular-hours checks; original cleanup orders were not resubmitted.
Future runtime/round-trip acceptance remains open. The private human paper-signing script is
retired; no human signing action is requested for paper.
