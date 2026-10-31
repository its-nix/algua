---
id: SPEC-2026-10-30-ci-acceptance-contract
status: proposed
gate: BLOCKED FOR CODE
companions:
  - ../../development/ci-acceptance-fields.md
  - ../../development/ci-acceptance-readiness.md
sources:
  - ../../agent/story-delivery.md
  - ../../architecture.md
  - ../../PRD.md
---

> **Canonical contract, not yet in force.** Once merged through review, this file and its two
> companions are the complete contract for CI acceptance under Task 7 of the approved three-harness
> plan. Until then it binds nothing. It never grants authority: it changes no workflow, test, gate,
> policy, branch setting, token or deployment. A later implementation needs its own explicit
> admission (§10).

# CI acceptance contract

**Date:** 2026-10-30
**Baseline:** `origin/main` and `HEAD` at `db6860000f87a6cc98469e0e4901fa9c10c0d277`
**Status:** BLOCKED FOR CODE. Requires: docs reviewed and merged, readiness amended from real
command results, and explicit admission of the protected workflow and test changes.

**What this PR is.** A preparatory **docs-only** PR, permitted by the current task card to carry a
known failing, unchanged baseline. It is **not** code readiness and **not** remote acceptance. The
baseline's full default-interpreter test run fails one frozen-identity test that this work did not
touch and must not repair (it reproduced again in the 2026-10-31 focused run)
([readiness §3](../../development/ci-acceptance-readiness.md#3-historical-evidence-2026-10-30-not-fresh)).
Merging these documents admits nothing: not a workflow change, not a test, not a guard, not a
setting.

## 1. Scope

This is a scoped contract for the CI and acceptance part of Task 7. It is not a competing redesign
or migration plan. Task 0 owns the canonical guides and the three-harness design and plan. Audit
`t_88536d89` owns broader readiness. This work is not mirrored to Todoist, by explicit task mandate;
Task 0 owns queue reconciliation.

In scope:

- the target shape of `.github/workflows/ci.yml` jobs `gate` and `web` (§3);
- a read-only evidence reducer **proposal** that decides whether CI and review evidence for one
  exact PR head is complete (§4, §5);
- where acceptance policy comes from and what protections it needs (§6);
- every path that reaches acceptance or `main` today (§7);
- the ordering hazards an implementation must respect (§8).

Out of scope: any code, test, workflow or settings change; merge automation; paper or live
deployment; strategy isolation (Task 4); allowlist changes. Existing diff policy denies this
change, and its allowlist must never be changed to admit it.

A green workflow is not enforcement. See [readiness §2](../../development/ci-acceptance-readiness.md#2-current-state)
for what is enforced today.

## 2. Terms

- **Gate jobs:** the `gate` and `web` jobs of the workflow at `.github/workflows/ci.yml`.
- **Exact head:** the 40-hex commit that `refs/pull/N/head` points to at observation time.
- **Tested tree:** the tree the job actually checked out. A native `pull_request` run checks out
  `refs/pull/N/merge`, not the head.
- **Reducer:** a pure, read-only function from a collected evidence bundle plus a trusted policy to
  a verdict. It writes nothing and holds no merge credential.
- **`accept_candidate`:** the reducer's only non-refusing verdict. It means "evidence is complete
  for this head at this instant". It is not permission to merge.
- **Trusted policy:** the policy object of §6, never read from PR-controlled content.
- **Must / must not:** normative for any admitted implementation.

## 3. Workflow requirements (target)

Field-level values, the current value of each and the exact command list are in
[fields §2 and §3](../../development/ci-acceptance-fields.md#2-workflow-target).

| ID | Requirement |
|---|---|
| WF-1 | `gate` and `web` must be scheduled for every PR to `main`, docs-only PRs included. `pull_request` and `push` to `main` stay. No `paths`, `paths-ignore` or `branches-ignore` filter. |
| WF-2 | No job or step `if:`, no `continue-on-error`, and no aggregate job that can turn a failure, skip or cancellation into success. |
| WF-3 | Every existing step and command is preserved, verbatim and in order. No test may be weakened, skipped, deselected or deleted. New steps may be added only if they cannot mask a preserved step. |
| WF-4 | The workflow declares `permissions: contents: read` explicitly. No other scope, at any level. |
| WF-5 | Every `actions/checkout` sets `persist-credentials: false` and sets none of `token`, `ssh-key`, `ref`, `repository`. |
| WF-6 | `timeout-minutes: 30` on `gate`, `20` on `web`. These are **proposed** values. They must be measured before admission (readiness CE-13) and amended rather than fixed by dropping steps. |
| WF-7 | Both jobs run on GitHub-hosted, ephemeral Ubuntu runners: `runs-on: ubuntu-latest`, a single string. No self-hosted label, runner group or privileged runner. |
| WF-8 | No `secrets.*`, `environment:`, `id-token`, signing, deploy or merge token in either job. The ambient `GITHUB_TOKEN` exists and is bounded by WF-4; it is not "no token". |
| WF-9 | The gate jobs must not be fed by `pull_request_target`, `workflow_run`, `issue_comment`, `workflow_dispatch` or `schedule`. Nothing may execute PR code with elevated privilege. |
| WF-10 | No `env`, `defaults` or `shell` override that can change command meaning (for example `PYTEST_ADDOPTS`). |
| WF-11 | Workflow name `CI`, path `.github/workflows/ci.yml` and job ids `gate`, `web` are stable identities. No `name:`, matrix or reusable workflow on those jobs unless trusted policy changes first. |
| WF-12 | Every action reference is validated for real syntax, existence, metadata and runtime before admission, not assumed (readiness CE-07 to CE-09). Pinning is decision OD-1. |

Scheduling alone does not guarantee a run. A PR with a merge conflict, a `[skip ci]`-class commit
message, disabled Actions or a Dependabot/first-time-contributor approval hold can produce no run
or a run in `action_required`. WF-1 therefore cannot stand alone: **a missing run is a refusal**
(AE-3), and enforcement needs required contexts (§6.3).

`security.yml` and `opencode.yml` are not gate jobs. They are inventoried in §7 and governed by
decision OD-3.

## 4. CI evidence requirements (reducer proposal)

This section is a **proposal for a trusted read-only reducer**. It is not authority and it is not a
shipped validator. No such code exists today. The schema, algorithm and refusal codes are in
[fields §4 to §9](../../development/ci-acceptance-fields.md#4-evidence-bundle).

| ID | Requirement |
|---|---|
| AE-1 | **Default refuse.** Anything malformed, empty, missing, duplicated, truncated, unknown or unparseable refuses. Unknown fields and enum values refuse **in the normalized evidence bundle**. Raw GitHub responses may gain additive fields; the collector reads them through an explicit projection that keeps only named fields, so an additive raw field neither refuses nor becomes evidence. A missing or mistyped projected field refuses. There is no warning tier. |
| AE-2 | **Typed exact binding.** Bundle binds repository (name and numeric id), PR number, base ref, base SHA, head SHA. All SHAs are full 40-hex lowercase. |
| AE-3 | **Positive proof only.** Each required job must be positively found, `completed` and `success`, from the approved workflow and source app. Absence of a failure proves nothing. |
| AE-4 | **Producer identity.** A check counts only through the join check run → job → run → workflow id and path, with `event = pull_request` and the approved app. A context string alone never counts. |
| AE-5 | **Workflow content identity.** On `pull_request`, GitHub runs the workflow from the merge commit, so a PR can edit the file that judges it and keep the same context names. The workflow blob at head must equal the blob approved by trusted policy. A PR that touches `.github/**` must refuse automation and route to human review. |
| AE-6 | **Latest relevant run and attempt.** Enumerate all runs of the approved workflow for the head and event. Only the newest run's newest attempt counts. A newer in-progress or non-success attempt refuses, whatever older attempts say. Any-success scans are forbidden. |
| AE-7 | **All pages.** Every list read follows pagination to exhaustion and reconciles against `total_count` where the API provides one. A partial list refuses. |
| AE-8 | **Unique contexts.** Each required context appears exactly once in the selected attempt. Duplicate or colliding contexts refuse. A commit-status (`/statuses`) entry using a required context name refuses as spoofing, it does not satisfy the check. |
| AE-9 | **Success vocabulary.** Only `status = completed` with `conclusion = success` passes. `failure`, `cancelled`, `timed_out`, `skipped`, `neutral`, `action_required`, `stale`, `startup_failure`, `null` and every unknown value refuse. |
| AE-10 | **No aggregate shortcuts.** `statusCheckRollup`, combined status, `reviewDecision`, `mergeable`, `mergeStateStatus` and `gh pr checks` output are never inputs. They are diagnostics. |
| AE-11 | **Merge-ref binding.** See §4.1. |
| AE-12 | **Collection errors refuse.** Any non-2xx, rate limit, missing permission, timeout, partial body or invalid JSON refuses and never degrades to "assume unchanged". |
| AE-13 | **Time.** Future timestamps, unparseable timestamps, `completed_at` before `started_at`, and bundles older than policy age refuse. Commit dates are author-controlled and are never freshness evidence. |
| AE-14 | **Race invalidation.** Head, base, the latest run attempts, and the **whole run list** are read before and again after collection. A new run id for the same head, not only a new attempt of a known run, refuses. Reviews, protection and the policy source are re-read too; each must be stable, or the bundle is invalidated. Any difference refuses; the reducer never patches a race by reading again. |
| AE-15 | **Stale inputs.** Every acceptance input binds this head and this base. Evidence for an older head or base, or a rerun that leaves those unproven, refuses. |
| AE-16 | **No trust escalation.** Evidence text never grants permission. Step logs, PR bodies, check output and QA prose are data. |
| AE-17 | **Reducer is not the merge.** A final trusted merge needs a compare-and-swap on the head, for example `gh pr merge --match-head-commit` or the REST merge `sha` parameter. That belongs only to a separately approved Task 7 slice and is not implemented or authorized here. |
| AE-18 | **Changed paths are complete or refused.** The path list comes from the fully paged PR files read (R13), and its length must equal the PR's own `changed_files` count (R2); more than 3000 files refuses. The compare file list truncates at 300 files and is never a path or count source. An omitted file, a rename or copy that shows only the new name, a `previous_filename` on any other status, a truncated list or an unknown status refuses. Both `filename` and `previous_filename` are routed; a copy's source is routed like a rename's, and a copy whose source is unavailable refuses. |
| AE-19 | **Every producer step is accounted for, in order.** Each step of each required job, including set-up, action, post and completion steps, is `completed` and `success`, and the **ordered** step-name list, in listed order with strictly increasing numbers, equals the policy's expected list exactly. An extra, missing, renamed, reordered, skipped or unfinished step refuses. Step timestamps follow the rules in [fields §4.1](../../development/ci-acceptance-fields.md#41-field-dictionary). |

### 4.1 Head SHA versus merge SHA

A native PR run tests `refs/pull/N/merge`, a synthetic merge of head and the base tip **at the
event**. The check run and workflow run are reported against the PR **head**. So:

- `run.head_sha` must equal the exact head. It must never be compared to `pull.merge_commit_sha` or
  to the runtime `GITHUB_SHA`, and neither of those is a substitute for the other.
- `pull.merge_commit_sha` is GitHub's *current* test merge. It can be newer than the tested merge,
  so it proves nothing about a completed run.
- A rerun reuses the original event's ref and SHA. It does not retest against a newer base.
- A green run on an arbitrary branch, a `push` run, or a run whose head repository differs from the
  PR's never counts.

The reducer must prove the tested tree is the tree that would land. It accepts exactly one mode
(`merge_binding.mode`) and refuses if that mode does not hold:

1. **`head_contains_base` (the only accepted mode).** `compare(base_sha...head_sha)` reports
   `behind_by = 0` and `merge_base = base_sha`. Every base the run could have merged is an ancestor
   of the head, so the test merge's tree equals the head's tree, whichever base the run saw. This
   needs no producer trust. **It relies on `main` never being force-rewritten**: if history could
   be rewritten, an ancestor relation observed now proves nothing about the base the run merged.
   Therefore the reducer also requires protection to show no force push and no deletion on the base
   (PS-5), **and no bypass**. If that protection is **absent, unreadable or bypassable, the mode is
   refused** (`protection_insufficient`, `bypass_possible`). Today the 2026-10-31 readback shows
   `allow_force_pushes.enabled = false` and `allow_deletions.enabled = false`, but also
   `enforce_admins = false`. Those flags then bind non-admins only, so **no effective guarantee
   against rewriting `main` exists**, and the mode refuses everywhere until protection is reviewed
   and applied. The flags are asserted; the guarantee is not.
2. **`merge_ref_metadata` (reserved, refused).** A run-bound record would give `tested_merge_sha`
   with parents `[tested_base_sha, head_sha]`. No trusted producer of that record has been
   verified: as far as this author knows the Actions REST run object exposes no merge SHA, and a
   workflow step that emitted one would be trustworthy only under AE-5. The path stays **unavailable
   and refused** (`merge_binding_unavailable`), and a bundle that fills the `tested_*` fields
   refuses. It can be enabled only by amending this contract after a real producer is verified by
   readback (readiness CE-12), then reviewed and merged.

Mode 1 refuses every PR that is behind base. That is the intended strict up-to-date behavior.

**What one real run showed (2026-10-31, PR #715, not this PR).** The run's `head_sha` was the PR
head `97af8dd…`; the `gate` job log proved the checkout was merge commit `711e0e7…` with parents
`[db68600…, 97af8dd…]`; merge tree and head tree were both `2b70903e…`, as mode 1 predicts when the
head contains the base. The PR's current `merge_commit_sha` read the same value, but that current
read alone does not bind the run: only the log proved what was checked out. The log is a human
diagnostic and not a trusted producer, so mode 2 stays refused.

## 5. Review evidence requirements

GitHub reports that a review is `APPROVED`. It does not report that the reviewer was independent.
No API field proves independence, and this contract never claims one does.

| ID | Requirement |
|---|---|
| RV-1 | **Two separate, both normative evidence classes.** GitHub human approval and agent QA provenance are distinct records, with distinct refusal codes. Neither substitutes for the other: human approval never satisfies the QA requirement, and QA never satisfies a human requirement. |
| RV-2 | **Exact head.** A counting GitHub review has `commit_id` equal to the exact head. A counting QA record has reviewed head equal to the exact head. |
| RV-3 | **Latest effective state.** Reduce each reviewer's whole, fully paged history to its latest effective state. `DISMISSED` cancels. `COMMENTED` and `PENDING` carry no effect. An unresolved `CHANGES_REQUESTED`, on any commit, refuses. |
| RV-4 | **Distinct identity.** A counting human reviewer's numeric user id differs from the PR author and from every commit author and committer. Identity is the numeric id only: no login, email, display name, bot suffix or persona is mapped to a person, and nothing is guessed. A null, missing or deleted-user identity refuses. Distinct ids prove distinct *accounts*, not distinct people; that limit is stated, not hidden. |
| RV-5 | **QA independence.** QA provenance names reviewer and implementer identities, runtime, task ids, reviewed head and base, verdict, unresolved finding count, time and an artifact reference. Reviewer and implementer must differ. The record must come from a trusted store. No such store exists in this repository today, so QA evidence currently refuses (`qa_untrusted_source`). |
| RV-6 | **Path routing.** A change touching any path outside the Task 7 allowlist, or matching CODEOWNERS, or matching the static denylist, requires qualifying human approval from an authorized code owner (**route H**). Agent QA can never satisfy this, and that approval can never satisfy RV-5 either: route H still needs passing trusted QA, CI evidence and sufficient protection to reach `accept_candidate`. Both names of a rename or copy are routed. |
| RV-7 | **Allowlisted automation** (**route A**, future) needs trusted QA evidence, CI evidence, safe diff policy and a Task 4 **isolation attestation**, all required. The attestation is a proposed typed record, not an existing field: it names its source, the exact head, base, policy blob and changed-content digest, and a verdict ([fields §6](../../development/ci-acceptance-fields.md#strategy-isolation-attestation-proposal)). An attestation that is omitted, from an unlisted source, or bound to anything but the exact identity never passes. The policy value `isolation.trusted_source = null` means explicitly unavailable, and today it is `null`: Task 4 has shipped no producer. |
| RV-8 | **No-approval acceptance, defined exactly.** Zero GitHub approvals is never evidence of independence. `accept_candidate` without any GitHub approval is possible only on route A: every changed path (both rename or copy names) is non-human-required **and** RV-5 trusted QA passes **and** CI evidence passes **and** RV-7 holds **and** protection is sufficient. Otherwise it refuses. Today QA and isolation cannot be satisfied, so every PR with no approval refuses, including when the repository's review count is 0. |
| RV-9 | **Human-only paths stay human-only (route X).** `.github/**`, the trusted policy, the reducer, its tests and CODEOWNERS are human-only. Human approval makes such a PR *reviewable and mergeable by a human*; it does **not** make an autonomous diff eligible, no QA or isolation record can convert it, and the reducer returns `path_requires_human` and never `accept_candidate` for it. |

The three routes (X human-only, H human-reviewed, A allowlisted) are tabulated in
[fields §6](../../development/ci-acceptance-fields.md#6-review-evidence). No route widens what is
automated today: they only state which records each path class needs, and every one refuses until a
trusted QA store (OD-4) and, for route A, a Task 4 attestation exist.

## 6. Policy and protections

### 6.1 Trusted policy source

- PS-1: Policy must not come from PR-controlled content. It is read at the observed base commit or
  from an installed, immutable location outside the PR's tree, never from the head or merge ref.
- PS-2: The reducer records the policy source, commit and blob, and refuses if they cannot be
  established. Missing policy refuses.
- PS-3: A PR that changes the policy, any `.github/**` file, CODEOWNERS or the reducer cannot be
  accepted by the policy it changes. All such changes remain **human-only**, even when reviewed:
  review lets a human merge them, and never makes an autonomous diff eligible (RV-9).
- PS-4: Agents must not change policy, CODEOWNERS or signing anchors to satisfy a failing check.

### 6.2 Missing protection blocks automation

PS-5: Automation is blocked regardless of green checks unless a successful read shows the required
protections are present. A 403, 404 or partial read refuses. Current protection does not meet this
(readback in [readiness §2](../../development/ci-acceptance-readiness.md#2-current-state)), so
automated acceptance is blocked today whatever the evidence says.

### 6.3 Proposed protections

The proposal is a **separate reviewed configuration** in
[readiness §7](../../development/ci-acceptance-readiness.md#7-proposed-branch-protection-configuration).
It lists exact contexts, strict up-to-date, stale dismissal, approval count, last-push approval,
admin enforcement, a required-pull-request rule with no bypass, no force push and no deletion, and a
human-validated list of the push actors in effect. It deliberately does **not** propose an empty
push allowlist: that is not the REST semantics of `restrictions`, and it can block merges as well as
direct pushes. This contract applies no setting. The
sole-owner constraint in that section needs a human decision first (OD-2).

## 7. Entry-point inventory

Every path that reaches acceptance or `main`. **Current** rates the path against the target of this
contract, not against its own original purpose. Field-level reads are in
[fields §10](../../development/ci-acceptance-fields.md#10-api-reads).

| ID | Entry point | Location | What it does today | Current | Target |
|---|---|---|---|---|---|
| EP-01 | Actions `pull_request` | `.github/workflows/ci.yml:4` | Runs `gate` and `web` on the merge ref for every PR. Green is not required. | FAIL | §3 plus required contexts |
| EP-02 | Actions `push` to `main` | `.github/workflows/ci.yml:5-6` | Runs after a commit is already on `main`. Detection, not prevention. | FAIL as acceptance | Post-merge signal only; never PR evidence |
| EP-03 | Actions rerun (UI/API) | No repo symbol | Creates a new attempt on the original event ref. Can flip the visible result. | FAIL | AE-6, AE-14, §4.1 |
| EP-04 | Merge ref checkout | `.github/workflows/ci.yml:12,30` | Default checkout of the synthetic merge. Tested SHA differs from head SHA. | UNKNOWN | §4.1 |
| EP-05 | `security.yml` jobs `sca`, `secret-scan` | `.github/workflows/security.yml:14,54` | Run on the same triggers. Header asks for required-check status; none is set. Both are **FAILING** on PR #715's Task 0 head (readiness §3): `secret-scan` is blocked because the gitleaks organisation license is missing, which is **not** a claim that a secret was found; `sca` reports real vulnerabilities, including `pillow 12.3.0`. No lock update or suppression is made or authorized here. | FAIL | OD-3 |
| EP-06 | `opencode.yml` comment trigger | `.github/workflows/opencode.yml:3-7,39` | Secret-bearing job on owner/collaborator comment, behind environment `opencode`. Read-scoped token. Not acceptance evidence. | UNKNOWN | Never feeds acceptance (WF-9) |
| EP-07 | `gh pr checks` | No repo caller (`gh pr` appears only in docs and `opencode.yml` uses `gh api`) | Human diagnostic rollup. | Diagnostic | Forbidden as input (AE-10) |
| EP-08 | REST check runs, commit status, reviews | No repo caller | Available; nothing in the repo consumes them. | Not built | §4, §5 via [fields §10](../../development/ci-acceptance-fields.md#10-api-reads) |
| EP-09 | GraphQL rollups | No repo caller | Available aggregate. | Not built | Forbidden as input (AE-10) |
| EP-10 | Documented PR merge | `docs/agent/story-delivery.md:81-82` | `gh pr merge N --merge --match-head-commit <sha>` after "green CI". Head CAS exists; green is not enforced and base is not bound. | FAIL | AE-17 under Task 7 |
| EP-11 | Manual UI merge | GitHub UI, no repo symbol | Available with zero required reviews or checks. | FAIL | Protection (§6.3) |
| EP-12 | Admin merge or bypass | GitHub, `enforce_admins=false` | Admin can bypass what protection exists. | FAIL | OD-2 |
| EP-13 | Direct push to `main` | `git push`, no repo control | Reachable by any credential protection does not stop. No tracked hook exists in this tree (`.claude/` holds only skills). | FAIL | Protection (§6.3) |
| EP-14 | `paper merge-back` CLI | `algua/cli/paper_cmd.py:402` (command decorator), `:404` `merge_back` | Merges a branch to `main` and pushes with no PR. Invokable directly, outside `lock-run`. | FAIL | Reconcile under Task 7 Step 3 |
| EP-15 | Domain saga | `algua/operator/mergeback.py:149` `run_merge_back` | Same path as a direct import; seams injected, including `run_gate`. | FAIL | Task 7 Step 3 |
| EP-16 | Remote push seam | `algua/operator/gitops.py:204` `RealGitOps.push_cas`, `:221` `push_revert` | Fetch, compare, plain `git push`, re-verify. Fast-forward semantics give the safety, not an atomic lease. Called from `mergeback.py:489,553,397,659`. | FAIL as acceptance | Remove direct write path after parity |
| EP-17 | Local hermetic gate | `algua/operator/gate_runner.py:85` `run_hermetic_quality_gate`, `_GATE_COMMANDS:49`; bound by `gitops.py:173` `commit_merge(expected_tree=...)` | Pins and gates the staged tree on the box. Strong local tree CAS. Not remote, not exact-head CI, not independent, and narrower than CI (no `scripts` in mypy, no `web` job, `--frozen` not `--locked`). | PASS for local tree binding; FAIL as acceptance | Keep as extra check, never as CI evidence |
| EP-18 | Already-present path | `algua/operator/mergeback.py:494-511` | A tip already on `origin/main` skips diff policy and gate, proceeds to promote. Writes nothing to `main`. | UNKNOWN | Assess in Task 7 Step 3 |
| EP-19 | Queue producer | `.opencode/scripts/run-research-loop.sh:196` `_validate_merge_back`; `.opencode/scripts/mergeback_queue.py` `enqueue` | Enqueues validated candidates. Does not merge. | Not acceptance | Unchanged |
| EP-20 | Queue drainer | `.opencode/scripts/drain-mergeback-queue.sh:94-114`; `deploy/systemd/algua-mergeback-drain.service:22`; `mergeback_queue.py` `select_and_reserve`, `record_attempt` | Unattended, one item per firing, drives EP-14 under `lock-run`. | FAIL | Task 7 Step 3 |
| EP-21 | `operator lock-run` | `algua/cli/operator_cmd.py:209` `lock_run` | Runs any trailing command under `operator.lock`. Mutual exclusion only, no acceptance logic. | Not acceptance | Unchanged |
| EP-22 | QA handoff | `docs/agent/story-delivery.md:49-67`; no in-repo symbol or store | Codex review is a process. No machine-readable record is bound to a head. | FAIL | RV-5, OD-4 |
| EP-23 | Dependabot PRs | `.github/dependabot.yml` | Open ordinary PRs into EP-01; `github-actions` updates touch `.github/**`. | FAIL | Human-review route (RV-6) |
| EP-24 | Box fast-forward deploy | `docs/agent/story-delivery.md:85-88` | Consumes `main`; production runs what the checkout holds. | Out of scope | Task 7 paper release |

`evaluate_diff` (`algua/operator/diff_policy.py:171`) guards EP-14 only. It denies `.github/`,
`tests/`, `algua/operator/` and build config statically, denies CODEOWNERS paths, and rejects
everything else outside `algua/strategies/<family>/**.py` and `kb/**`. It does not guard EP-10 to
EP-13.

## 8. Ordering hazards

1. **Protection before reconciliation breaks production flow.** If protection starts rejecting the
   direct push while the drainer is active, then `commit_merge` has already advanced local `main`
   and journaled `merge_sha` (`mergeback.py:545-547`) before `push_cas` fails. A rejected push
   raises `CalledProcessError`, not `RemoteMovedError`. The queue records transient failures up to
   `MAX_TRANSIENT_FAILURES` (`mergeback_queue.py:131`). Other items then hit `LocalMainDriftError`
   (`mergeback.py:254`), because their journal cannot explain the commit. `require_clean_main`
   (`algua/operator/checkout_guard.py:75`) does not compare with origin, so paper ticks would run
   code that is on no remote. Task 7 Step 3 must land, or the drainer must be stopped by a human,
   before such protection is enabled.
2. **Workflow change before identity policy.** Trusted policy must name the workflow blob that the
   admitted workflow change produces. Otherwise every PR refuses, or the check is written to trust
   the PR. The implementation must sequence this explicitly.
3. **Required contexts before the workflow has run.** A required context that never reports blocks
   merges. Contexts must be observed on real runs first (CE-10).
4. **Automation before isolation.** Strategy auto-merge stays disabled until Task 4 passes.
5. **Old evidence before protection activation.** A current protection snapshot does not prove that
   the branch was protected when a historical green run executed. Before admitting mode 1, the
   reviewed policy must establish a trusted activation epoch and require newly collected/run
   evidence after that epoch, or verify the actual tested merge through a separately reviewed
   producer. Historical runs characterized here cannot be grandfathered into acceptance. This
   producer/epoch choice remains an implementation-admission blocker, not an assumed guarantee.
6. **Sole owner and review enforcement.** Raising `required_approving_review_count` to 1 while one
   human owns every credential that authors PRs blocks that owner's own merges, and
   `enforce_admins=true` removes the escape hatch. A human must decide OD-2 *before* the setting is
   written, or the repository becomes unmergeable (including by the documented
   `gh pr merge --match-head-commit` path). See
   [readiness §7.2](../../development/ci-acceptance-readiness.md#72-sole-owner-feasibility).
6. **Direct `main` writers before enforcement.** Making the base branch reject direct pushes and
   force pushes stops EP-13 through EP-16 and EP-20 alike (hazard 1). Required contexts, strict
   up-to-date and no-force protection are one reviewed change set applied in the order given in
   [readiness §8](../../development/ci-acceptance-readiness.md#8-admission-sequence-and-blockers),
   never piecemeal: `head_contains_base` (§4.1) is unsound without no-force, and required contexts
   without reconciled writers strand the drainer.
7. **Required contexts versus admin bypass.** While `enforce_admins=false`, required contexts bind
   only non-admins; the owner can still merge a red PR. The reducer treats that as `bypass_possible`
   and refuses automation, whatever the checks say.

## 9. Boundaries

No live activation, capital change, deployment, settings write, credential issue or external write
results from this contract. Blanket owner merge intent does not override the no-merge,
protected-path, allowlist, live or capital boundaries. The human-signed live wall, PIT, `t→t+1`,
holdout accounting, risk limits, frozen identity and lane parity are unchanged;
[readiness §6](../../development/ci-acceptance-readiness.md#6-safety-inventory) lists their existing
tests.

## 10. Admission

Code stays blocked until all of these are true:

1. This contract and companions are reviewed (independently, by Codex through alguaqa; this work
   does not self-certify) and merged.
2. Readiness is **refreshed after the merge** from real command results, with every required CE row
   filled and every refresh slot of
   [readiness §9](../../development/ci-acceptance-readiness.md#9-coordinator-refresh-slots) completed.
3. An explicit admission names each protected path to be changed (for example
   `.github/workflows/ci.yml` and each new test file), one by one. A blanket owner merge intent, or
   an admission of "CI work", does not satisfy this. The diff-policy allowlist is not changed.
4. The frozen-identity failure on the baseline is **resolved through a separately scoped, admitted
   repair** under its own protected ownership (readiness §8, blocker B3). It is not fixed by this
   work, and nobody here may waive or downgrade that safety test, skip or deselect it, or change the
   interpreter to avoid it.

Every change to `.github/**`, the policy file, the reducer or CODEOWNERS stays human-only even after
all four hold (RV-9).

Then the implementation works test-first. Each new guard has a test that fails before the guard
exists, is mutation-checked by sabotage, and is restored byte for byte. Those test ids are in
[readiness §5](../../development/ci-acceptance-readiness.md#5-test-matrix). **No test or mutation
check in that matrix has been implemented or run.**

## 11. Decisions needed

| ID | Decision | Recommendation | Owner |
|---|---|---|---|
| OD-1 | Pin `ci.yml` actions to full commit SHAs? | Yes. `security.yml` and `opencode.yml` already pin, and `.github/dependabot.yml` describes pinning as the norm. The peeled commits read on 2026-10-30 are `checkout` `3d3c42e5…`, `setup-node` `949feb24…`, `setup-uv` `37802adc…` ([fields §2](../../development/ci-acceptance-fields.md#2-workflow-target)); they must be re-read at admission. Not part of the original mandate, so it is a decision rather than a requirement. | Human, at admission |
| OD-2 | How does a sole owner satisfy required review without bypass? | Separate machine identity for authors; see [readiness §7.2](../../development/ci-acceptance-readiness.md#72-sole-owner-feasibility). | Human |
| OD-3 | Are `sca` and `Secret scanning` also required contexts? | Yes, as a separate reviewed change, since `security.yml` already asks for it. Their permissions are outside this contract. | Human, at admission |
| OD-4 | Where does a tamper-resistant QA record live? | A store the implementer cannot write. Until decided, QA evidence refuses. | Task 7 with Task 0 |
| OD-5 | Which trusted policy location? | Read at base commit from a CODEOWNERS-protected path under `.github/`, which `diff_policy` also denies. Exact filename left to Task 7. | Task 7 |
