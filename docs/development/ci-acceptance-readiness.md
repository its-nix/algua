# CI acceptance — implementation readiness and test matrix

Companion to the [CI acceptance contract](../superpowers/specs/2026-10-30-ci-acceptance-contract.md)
and the [field-level companion](ci-acceptance-fields.md). Baseline `origin/main` and `HEAD`:
`db6860000f87a6cc98469e0e4901fa9c10c0d277`.

## 1. Status

**BLOCKED FOR CODE.** No guard, reducer, workflow change or test described here is implemented, and
no mutation check has been run. Code needs, in order: this docs set reviewed and merged, readiness
refreshed ([§9](#9-coordinator-refresh-slots)), and an explicit admission naming each protected path
([§8](#8-admission-sequence-and-blockers)).

This is a preparatory docs PR that the task card permits to carry a known failing, unchanged
baseline. It is not code readiness and not remote acceptance. No merge, deployment, settings write,
credential use or external write is part of it. Independent Codex review (alguaqa) has not occurred;
this document does not self-certify.

Legend. **PASS / FAIL**: observed. **UNKNOWN**: not observed. **NOT RUN**: deliberately not run.
**(hist)**: observed on 2026-10-30 by an earlier run, dated and not fresh.

## 2. Current state

Against the target of the contract. Facts marked (hist) are re-read at the refresh in
[§9](#9-coordinator-refresh-slots).

| # | Item | Observed | Target | Status |
|---|---|---|---|---|
| S-01 | `required_status_checks` on `main` | `null` | `gate`, `web`, strict | FAIL |
| S-02 | `required_approving_review_count` | `0` | `≥ 1` | FAIL |
| S-03 | `dismiss_stale_reviews` | `false` | `true` | FAIL |
| S-04 | `require_last_push_approval` | `false` | `true` | FAIL |
| S-05 | `require_code_owner_reviews` | `true` | `true` | PASS |
| S-06 | `enforce_admins` | `false` | `true` | FAIL |
| S-07 | rulesets | `[]` | reviewed config ([§7](#7-proposed-branch-protection-configuration)) | FAIL |
| S-08 | force-push and deletion on `main` | `allow_force_pushes.enabled = false`, `allow_deletions.enabled = false` (2026-10-31 readback) | both denied, **and** not bypassable by admins | FAIL for the guarantee: both flags read `false`, but `enforce_admins = false` means they bind non-admins only, so no effective no-rewrite guarantee exists for an admin credential. `head_contains_base` stays refused (S-06) |
| S-16 | `required_conversation_resolution` | `false` | `true` | FAIL |
| S-17 | `restrictions` (push actor allowlist) | `null` (absent from the saved readback) | see [§7](#7-proposed-branch-protection-configuration); the earlier "push restricted to none" proposal was wrong | FAIL, no push restriction exists |
| S-09 | workflow `permissions` | absent (default token reads `read`) | `contents: read` explicit | FAIL |
| S-10 | `timeout-minutes` | absent | `30` / `20`, measured | FAIL |
| S-11 | `persist-credentials` | default true | `false` | FAIL |
| S-12 | `gate`, `web` scheduled for every PR | no `paths` filters, no `if` | same | PASS |
| S-13 | every existing command present | 5 `gate` + 9 `web` ([fields §3](ci-acceptance-fields.md#3-preserved-commands)) | same | PASS |
| S-14 | reducer, collector, workflow guards | do not exist | after admission | NOT BUILT |
| S-15 | trusted QA store | does not exist | OD-4 | NOT BUILT |

Green workflows do not make checks required (S-01). No bypass-prevention claim is supported
(S-06, S-07).

## 3. Historical evidence (2026-10-30, not fresh)

Source: the earlier run of this task's evidence record and raw logs, preserved as the durable task
attachment `ci-blocked-evidence.zip` on task `t_ab3d8099`. It is not in the repository and not part
of any PR, so nothing here links to it. The final baseline check was at 20:01:26 UTC. Items from the Lead's resume
note, with no raw output in this worktree, are labeled **(Lead report)**.

### 3.1 Baseline commands exercised

| Command | Result (hist) |
|---|---|
| `uv sync --locked` | PASS, CPython 3.12.12 |
| `uv run pytest -q` | **FAIL**: 6290 passed, 5 skipped, **1 failed**, 711.25 s |
| `uv run ruff check .` | PASS |
| `uv run mypy algua scripts` | PASS, 360 source files |
| `uv run lint-imports` | PASS, 29 kept, 0 broken |
| `uv sync --project web --locked` | PASS, CPython 3.14.2 |
| `uv run --project web pytest web/backend/tests -q` | PASS, 266 passed |
| `npm ci`, `npm run check`, `npm run build` (web/frontend) | PASS; `check` ran 43 files, 226 tests; `npm ci` warned of 12 vulnerabilities and a jsdom engine mismatch, nothing changed |
| `node scripts/verify-demo-build.mjs prod dist` | PASS, 73 files, none with fixtures |
| `npm run build:demo`, `verify-demo-build.mjs demo dist-demo` | PASS, 74 files, one with fixtures |
| `npm run verify:viewport` | PASS locally, five routes at 390px |
| Focused command (below) | PASS, 217 passed |

```
uv run pytest -q tests/operator tests/test_cli_merge_back.py tests/test_live_gate.py tests/test_human_actor.py tests/test_contracts.py tests/test_lane_parity.py tests/test_risk_limits.py tests/test_holdout_window.py
```

### 3.2 The full-suite failure

The failing test is
`tests/test_planner_environment_lock.py::test_wheel_url_ownership_identity_is_rfc_canonical[ipv6-mapped-ipv4]`
(assertion at `:199`: expected `https://[::ffff:c000:20a]/x.whl`, actual
`https://[::ffff:192.0.2.10]/x.whl`). It reproduces alone with exit 1, on the unchanged baseline
under the **default** interpreter CPython 3.12.12. An independent audit saw the same.

- **(Lead report)** Task 0 ran the full suite under CPython **3.12.3**: PASS, 6325 passed, 5 skipped.
  That is a different interpreter and a different tree, and it is recorded as such. It does **not**
  make the baseline green. The interpreter is **not** to be downgraded to hide the default failure.
- Frozen identity is protected. The failure is **flagged, not an admitted repair**. The Lead routed
  `t_4532ae9d` to `t_90070478` for docs-only protected-repair readiness; **no repair is admitted**
  and none is attempted here.
- Consequence: the full gate on the baseline is not green. A passing run under another interpreter
  is a separate fact, never a substitute.

### 3.3 Remote evidence

| Item | Result | Note |
|---|---|---|
| Main run `39771232513` (push, attempt 1, head `db68600…`) | conclusion **failure** (hist) | job `gate` (check `119799003902`) success; job `web` (check `119799004060`) **failure** at `No horizontal overflow at 390px`: route `/` lacked fixture text `cross_horizon_low_vol`. The existing remote `web` failure is separate from this work and from PR #715. Chrome launched on the hosted image, since the step ran. |
| Same head, `Secret scanning`, `Dependency vulnerabilities (SCA)` | failed (hist) | raw findings not published here |
| PR #715 (Task 0), exact head `97af8dd778f14f4e678d044087fd5966ef8bc1a3` | `gate` SUCCESS, `web` SUCCESS **(Lead report; confirmed by actual read on 2026-10-31, §3.5)** | proves a native PR run can pass both jobs |
| PR #715, `Secret scanning` | FAILURE **(Lead report)** | blocked because the gitleaks **organisation license is missing**. This is **not** a claim that a secret was detected |
| PR #715, `Dependency vulnerabilities (SCA)` | FAILURE **(Lead report)** | an actual vulnerability failure, including `pillow 12.3.0` |

No lock update, dependency change or suppression is made or authorized here for any of these.

### 3.4 Tools and action metadata

`actionlint` 1.7.12 (archive SHA256 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`,
verified against the published checksum) accepted the **baseline** `.github/workflows/ci.yml` with
exit 0. The action refs, peeled commits, `node24` runtime and token defaults are in
[fields §2](ci-acceptance-fields.md#2-workflow-target). This characterizes the baseline. It does
not show that any target workflow exists, parses or runs.

### 3.5 2026-10-31 readbacks

Actual read-only results from the coordinator's refresh. No credential material is recorded, and no
setting, workflow, test or lock was changed. These characterize PR #715, a **different docs PR**.
They are not acceptance of this PR.

| Item | Result |
|---|---|
| Baseline | `HEAD` and `origin/main` still `db6860000f87a6cc98469e0e4901fa9c10c0d277`, fetched |
| PR #715 run | CI run `41123483232`, workflow `286029583` (path `.github/workflows/ci.yml`), app `15368` (`github-actions`), event `pull_request`, attempt 1, head `97af8dd778f14f4e678d044087fd5966ef8bc1a3`, base `db6860000f87a6cc98469e0e4901fa9c10c0d277` |
| Jobs | `gate` `124295849083` success, `1544 s`; `web` `124295849514` success, `74 s`. Both: `labels = [ubuntu-latest]`, `runner_group_name = GitHub Actions`, same head. Jobs listing `total_count` 2 |
| Tested tree | The `gate` raw log proves the checkout: merge commit `711e0e73658863e052cdb9235b0e9b4256d23ab4`, parents `[db6860000f87a6cc98469e0e4901fa9c10c0d277, 97af8dd778f14f4e678d044087fd5966ef8bc1a3]`. The merge's tree and the head's tree are both `2b70903e7eefa784ccc51ccfa45680203e69b50f`. **The PR's current `merge_commit_sha` equals this value, but reading it now does not bind the run to it**: only the log proves what was checked out. It is evidence for one observation, not a producer for mode 2 (CE-12 stays UNKNOWN) |
| Interpreter and tests (hosted `gate`) | CPython `3.12.3` at `/usr/bin/python3.12`; `6323 passed, 7 skipped` in `1492.89 s`. Local runs show 5 skipped. The skip difference is environmental and its reasons are **not established**; no test was changed by this work |
| Workflow blob | `ci.yml` blob at base and at head is `9559f563ec3ed6feddba160597290657d532eaef` |
| Stability | The PR, its head and its run list were read twice and were stable during the observation. No reviewer approvals (reviews list empty) |
| Reads exercised | All of R1 to R16 ([fields §10](ci-acceptance-fields.md#10-api-reads)), **except** a successful non-empty review projection (the list was empty) and a known partial rerun. Subsequent R2 read: `changed_files = 17`, `commits = 1`, matching complete saved lists |
| Paging | A four-page check-run listing (`per_page=1`) reported `total_count` 4 on every page and four unique ids: succeeded. Everything else read was a single page |
| Historical rerun | Run `35925012277`, head `70902419173a94550f0900b0bd097891a5134927`. Attempt 1: `web` failure, `gate` success. Attempt 2: **both jobs success**. Attempt 2's `gate` carries attempt 1's execution times and steps, so the pattern is consistent with a carried-over job, but nothing in the response says so. This closes *a positive historical attempt read*. **Partial-rerun behavior stays UNKNOWN** (CE-11): this is not proof of it |
| Protection | `required_status_checks` null; review count `0`; stale dismissal `false`; last-push approval `false`; code owners `true`; `enforce_admins` `false`; `allow_force_pushes.enabled` `false`; `allow_deletions.enabled` `false`; `required_conversation_resolution.enabled` `false`; `restrictions` null; rulesets empty. Nothing changed |
| Security checks on #715 | `Secret scanning` `124295849992` and `Dependency vulnerabilities (SCA)` `124295849655`: both failure. Fresh job-log reads confirm the missing organisation license and SCA output `Found 52 known vulnerabilities in 6 packages`, including `pillow 12.3.0`. This is not evidence of a detected secret; no license, credentials, lock update or suppression is authorized |
| Tooling | `actionlint` 1.7.12 on baseline `ci.yml`: exit 0 again. Action refs, peeled commits and metadata re-read: identical, three `node24`. No target workflow exists |
| Compatibility | `gh` 2.86.0 rejects `--slurp` with `--jq` (exit 1); use `--paginate --slurp > FILE` then `jq`. The job-log path is `GET /repos/{o}/{r}/actions/jobs/{job_id}/logs`; a mistaken `actions/runs/{id}/jobs/{id}/logs` path returned 404, which is a path error and not a permission result |
| Refresh `web` | All exits 0: backend `266` passed in `1.08 s`; frontend 43 files, 226 tests; `npm ci` with the same jsdom engine warning and a fresh audit summary of **18 vulnerabilities (3 low, 10 moderate, 5 high)** (the earlier run reported 12; advisory counts are time-dependent, no package or lock change); build and production check `73` files, `0` with fixtures; demo `74`, `1` with fixtures; five routes at 390px pass |
| Refresh focused | The prior 217-test focused command plus `tests/test_walkforward_pit.py` and `tests/test_planner_environment_lock.py`: `380 passed, 1 failed` in `50.88 s`; the failure is the same frozen-identity test (§3.2). `tests/test_repo_hygiene.py` and `tests/test_codeowners_parity.py`: `11 passed` in `1.29 s`. No test was added, removed or skipped |
| Full root suite | Default CPython `3.12.12`: **FAIL**, final primary-worktree run `6287 passed, 4 failed, 5 skipped` in `2247.35 s`; the known IPv6 identity assertion plus three dirty-hash determinism assertions. See the execution-contamination disclosure below. Separate **clean detached baseline worktree**, supported `3.12.3`: **PASS**, `6291 passed, 5 skipped` in `2248.63 s`; root Ruff, mypy (`360` files), import-linter (`29 kept, 0 broken`) all exit 0. This comparison does not resolve or hide the default failure; no interpreter pin or lock changed |

**Execution-contamination disclosure and recovery.** The coordinator first ran two interpreters
against the same worktree while documentation/evidence changed. The default run returned
`6289 passed, 2 failed, 5 skipped` (IPv6 and sweep dirty-hash determinism; `2205.02 s`), with Ruff
also seeing a temporary test-generated `liquid10_momentum.py`. The same-worktree `3.12.3` run
returned `6289 passed, 2 failed, 5 skipped` (`2317.02 s`, CLI/parquet determinism). Neither is a
clean acceptance run. A second attempt separated the source/index/environment worktrees, but
wrote both sets of logs into the primary worktree. That still contaminated the primary run:
`algua/backtest/stamps.py:24-57` hashes **all untracked file bytes**, so active evidence files can
change `code_hash` between repeated calls even with documentation frozen. Its full result is the
four-failure default result above. The detached `3.12.3` worktree had no evidence files written
inside it and its entire locked gate passed. All contaminated logs are retained; none is presented
as a new product defect or a green default full suite.

After both runs exited, with output redirected **outside** the repository and no concurrent tree
writes, the following default-interpreter repro returned **197 passed, 1 failed** (`22.02 s`):

```bash
uv run pytest -q tests/test_determinism.py tests/test_cli_backtest_series.py tests/test_sweep.py tests/test_walkforward.py tests/test_planner_environment_lock.py
```

Only the protected IPv6 assertion failed; all dirty-hash/parquet determinism repros passed.
Subsequent primary-worktree Ruff, mypy (`360` files), and import-linter (`29 kept, 0 broken`)
all passed. This is a runner/evidence-placement correction, **not** a product or test change.
The fresh default **full** result remains FAIL, and the earlier unchanged-baseline full result of
`6290 passed, 1 failed, 5 skipped` remains separately dated historical evidence. Do not infer a
fresh clean default full run from a focused repro or a different interpreter.

Both `uv run algua paper merge-back --help` and `uv run algua operator lock-run --help` also
exited 0. Only help was exercised: no operational merge-back, lock-run payload, broker action,
service or registry mutation was invoked.

Duration: the proposed `30` minute `gate` timeout contains the one observed hosted run (`1544 s`,
about 25.7 minutes) with a narrow margin. One run is not a distribution; the cold-cache path is
unmeasured. CE-13 therefore stays open for admission-time measurement.

## 4. Executable readiness

Per `story-delivery.md` §2, readiness executes each pinned invocation rather than assuming it.
Statuses are as of this document; the refresh in [§9](#9-coordinator-refresh-slots) updates them.

| ID | Check | Status |
|---|---|---|
| CE-01 | Baseline `ci.yml` accepted by `actionlint` 1.7.12 | PASS (2026-10-30 and 2026-10-31) |
| CE-02 | Root commands on the default interpreter | FAIL: fresh primary full run 6287 passed / 4 failed / 5 skipped; contamination and stable focused repro (197 passed / 1 IPv6 failed) disclosed in §3.5. Separate clean supported-3.12.3 baseline full gate PASS, never a default-failure waiver |
| CE-03 | `ruff`, `mypy algua scripts`, `lint-imports` | PASS on the clean comparison and final stable primary rerun: 360 typed files, 29 import contracts kept / 0 broken. Earlier transient Ruff failure retained in §3.5 |
| CE-04 | Web backend and all frontend steps | PASS locally on 2026-10-30 and again on 2026-10-31 (§3.5); remote `web` on `main` FAIL (hist). Remote `web` on PR #715 SUCCESS |
| CE-05 | Focused merge and safety command | PASS (hist), 217 passed. Extended with two files on 2026-10-31: 380 passed, 1 failed (same frozen-identity test) |
| CE-06 | Protection and rulesets readback | PASS as a read (2026-10-31); values in §2 |
| CE-07 | `actions/checkout@v7.0.1` exists, metadata, `node24` | PASS (hist), identical on 2026-10-31 |
| CE-08 | `actions/setup-node@v7` exists, metadata, `node24` | PASS (hist), identical on 2026-10-31 |
| CE-09 | `astral-sh/setup-uv@v7` peeled to `37802adc…`, metadata, `node24` | PASS (hist), identical on 2026-10-31 |
| CE-10 | Required context names and numeric `app.id` observed on real check runs | PASS for PR #715: `gate`, `web`, app `15368` / `github-actions`. Not yet observed on this PR |
| CE-11 | Jobs listing of a pinned attempt after a partial rerun | UNKNOWN. A positive historical attempt-2 read exists (§3.5); it does not show how the rerun was requested, so partial-rerun behavior is not established |
| CE-12 | A real trusted producer of the tested merge SHA | UNKNOWN. Mode 2 stays refused whatever this reads. The `gate` log shows the checkout but is not a run-bound attestation |
| CE-13 | Hosted job durations, to ground `30` / `20` minutes | One hosted run: `gate` 1544 s, `web` 74 s. Not a distribution; cold path unmeasured. Open |
| CE-14 | **Target** workflow: `actionlint` and a hosted run | NOT RUN: no target workflow exists and none is admitted |
| CE-15 | A PR run's `head_sha` equals the PR head, and the PR's merge SHA differs | PASS for PR #715: run `head_sha` is the head; the tested commit is the merge `711e0e7…`. The two trees are equal on that PR because the head contains base; the SHAs still differ |
| CE-16 | Raw shapes for reads R1 to R16 ([fields §10](ci-acceptance-fields.md#10-api-reads)) | Partly observed: all exercised, including `changed_files = 17`; a non-empty review projection, a known partial rerun, and rename or copy `previous_filename` remain unobserved |
| CE-17 | `require_clean_main` / drainer behavior under a rejected push | UNKNOWN: hazard from reading source only |

## 5. Test matrix

**Nothing here is implemented or run.** Test files, names and locations are proposals; paths are not
admitted. No CI-specific guard of `ci.yml` exists: no `tests/test_ci*` or `tests/test_workflow*`
file was found. One existing test does read a workflow, `tests/test_opencode_workflow_hardening.py`
(`:27`, `opencode.yml`); it is retained unchanged and is not a gate-job guard. All reducer tests use in-memory fixtures only: no network,
no `gh`, no credentials, no clock beyond an injected `now`. Existing tools only: `pytest`
parametrization and plain assertions; no new property-testing library.

### 5.1 Plans, kept apart

| Plan | Invocation | State |
|---|---|---|
| **A. Existing baseline** (exercised) | the commands of §3.1 | run (hist), see §3 |
| **B. Proposed workflow guard tests** | `uv run pytest -q tests/<ci workflow guard file>` | not written, not run |
| **C. Proposed reducer and collector tests** | `uv run pytest -q tests/<ci reducer file>` | not written, not run |
| **D. Guard mutation checks** (§5.7) | by hand, per guard, after B and C pass | not run |

B and C join the root `uv run pytest -q` in a later PR; a failure there is a refusal of that PR.

### 5.2 Conventions

Each test row is `id | input | expected`. "refuse(X)" means the reducer returns `decision = refuse`
with `X` among `reasons`; all reasons are reported. Every refusal row also asserts `decision` is
never `accept_candidate`. Inputs are derived from the valid control by changing **only** the stated
field. Each parametrized family is one test per value.

### 5.3 Valid controls

| ID | Input | Expected |
|---|---|---|
| VC-01 | Route A. Complete fixture: open PR, non-fork, head contains base, both jobs and checks `completed/success` from the approved app, ordered steps equal policy, workflow blob equal policy, stable rereads, `changed_files` equal to the path list, one allowlisted path, trusted-QA fixture independent and passing, **isolation attestation present, from the policy's trusted source, bound to this head, base, policy blob and content digest, verdict `pass`**, protection sufficient | `accept_candidate`, `reasons = []` |
| VC-02 | Route H. As VC-01 but one non-allowlisted, non-human-only path (so `human_required`), the isolation attestation **absent** (not required on H), the **same passing trusted-QA fixture kept**, and one qualifying human approval at head from a `human_reviewers` id | `accept_candidate`. Human approval does not replace QA: removing the QA fixture here must refuse(`qa_missing`) (RV-T16b) |
| VC-03 | As VC-02 but the path is `.github/workflows/ci.yml` | refuse(`path_requires_human`). Controls that human approval and QA never convert a human-only path |
| VC-04 | The parsed workflow that is the **approved target** | guard passes. A control only; it needs a target workflow that does not exist yet |

### 5.4 Workflow guards (WF)

Static checks on parsed workflow text, in a temporary copy, never on the live file. Each starts from
the VC-04 text and applies one sabotage. Expected: the guard refuses with the named code. YAML is
parsed so the key `on` is not read as a boolean.

| ID | Sabotage | Expected |
|---|---|---|
| WF-01 | remove each of the 14 preserved commands in turn (`gate` 1 to 5, `web` 1 to 9) | refuse(`wf_command_missing`) ×14 |
| WF-02 | remove job `gate`; remove job `web` | refuse(`wf_job_missing`) ×2 |
| WF-03 | reorder two adjacent steps; swap `web` 6 and 7 | refuse(`wf_command_order`) |
| WF-04 | suffix `\|\| true`; add `-k x`; add `--deselect x`; add `--co`; narrow `mypy algua scripts` to `mypy algua` | refuse(`wf_command_altered`) ×5 |
| WF-05 | `paths:` on `pull_request`; `paths-ignore:`; `branches-ignore:`; `types:` that omit `synchronize` | refuse(`wf_trigger_filtered`) ×4 |
| WF-06 | drop `pull_request`; drop `push` to `main`; add `branches: [other]` to `push` | refuse(`wf_trigger_missing`) ×3 |
| WF-07 | job-level `if:`; step-level `if:`; `if: always()` on a step | refuse(`wf_conditional`) ×3 |
| WF-08 | `continue-on-error: true` on a job; on a step; as `defaults` | refuse(`wf_continue_on_error`) ×3 |
| WF-09 | remove top-level `permissions`; `contents: write`; `pull-requests: write`; `id-token: write`; job-level `permissions` block | refuse(`wf_permissions`) ×5 |
| WF-10 | remove `timeout-minutes` from `gate`; from `web`; set `gate: 360`; set `web: 0` | refuse(`wf_timeout`) ×4 |
| WF-11 | `${{ secrets.X }}` in an `env`; `environment: x`; `secrets: inherit` | refuse(`wf_secrets_or_environment`) ×3 |
| WF-12 | `runs-on: self-hosted`; `[self-hosted, linux]`; `{group: g}`; `ubuntu-latest` inside an array | refuse(`wf_runner`) ×4 |
| WF-13 | trigger `pull_request_target`; `workflow_run`; `issue_comment`; `workflow_dispatch`; `schedule` | refuse(`wf_forbidden_trigger`) ×5 |
| WF-14 | checkout without `persist-credentials`; with `true`; add `token`; add `ssh-key`; add `ref`; add `repository` | refuse(`wf_checkout`) ×6 |
| WF-15 | `env: PYTEST_ADDOPTS`; `defaults.run.shell`; `defaults.run.working-directory` | refuse(`wf_env_override`) ×3 |
| WF-16 | `name:` on a job; `matrix`; `needs`; `container`; `services`; reusable `uses:` job; workflow `name` changed | refuse(`wf_identity`) ×7 |
| WF-17 | `package.json` scripts `build`, `build:demo`, `verify:viewport`, `check` each altered | refuse(`wf_npm_script`) ×4 |
| WF-18 | action ref changed to a branch name; to a short SHA; to a non-pinned tag (if OD-1 pins) | refuse(`wf_action_ref`) ×3 |
| WF-19 | extra step added that masks a preserved step; extra step appended (allowed only if it cannot mask) | first refuse(`wf_step_unexpected`); second per policy |
| WF-20 | a malformed YAML file; an empty file; duplicate key | refuse(`wf_unparseable`) ×3 |

### 5.5 Evidence reducer (AE)

| ID | Input | Expected |
|---|---|---|
| AE-T01 | zero bytes | refuse(`evidence_empty`) |
| AE-T02 | invalid JSON; trailing content after the object; a JSON array | refuse(`evidence_malformed`) ×3 |
| AE-T03 | duplicate key | refuse(`evidence_duplicate_key`) |
| AE-T04 | unknown field in the **normalized bundle** at each of: top level, `pull_request`, `runs[]`, `jobs[]`, `jobs[].steps[]`, `check_runs[]`, `reviews[]`, `changed_paths[]` | refuse(`evidence_unknown_field`) ×8 |
| AE-T05 | wrong `schema_version`; missing `schema_version` | refuse(`evidence_schema_unsupported`) ×2 |
| AE-T06 | `NaN`, `Infinity` | refuse(`evidence_malformed`) ×2 |
| AE-T07 | head/base SHA short, uppercase, empty, 41 chars, non-hex | refuse(`head_sha_invalid`) ×5 |
| AE-T08 | `id` as `true`, `1.0`, `"1"`, `0`, `-1` | refuse(`evidence_malformed`) ×5 |
| AE-T09 | timestamp without `Z`, with offset, naive, non-string | refuse(`evidence_timestamp_invalid`) ×4 |
| AE-T10 | a timestamp beyond `now + max_clock_skew_seconds`; `completed_at < started_at`; `updated_at < created_at` | refuse(`evidence_timestamp_future` / `_invalid`) ×3 |
| AE-T11 | `collected_at` older than `max_evidence_age_seconds`; bundle over `max_bundle_bytes` | refuse(`evidence_stale`) / `evidence_malformed` |
| AE-T12 | each required top-level key removed in turn | refuse(`evidence_malformed`) per key |
| AE-T13 | `runs: []`; `jobs: []`; `check_runs: []` | refuse(`run_missing`, `job_missing`, `check_missing`) |
| AE-T14 | **collector**: raw response with an extra additive field | no refusal; the field is absent from the bundle |
| AE-T15 | **collector**: raw response missing a projected field; wrong type | refuse(`api_response_invalid`) ×2 |
| AE-T16 | run, job, and check each with conclusion `failure`, `cancelled`, `timed_out`, `skipped`, `neutral`, `action_required`, `stale`, `startup_failure`, `null`, `"weird"` | refuse(`*_not_successful`, `evidence_malformed` for the unknown) ×30 |
| AE-T17 | run, job, check each with status `queued`, `in_progress`, `waiting`, `requested`, `pending` | refuse(`*_not_completed`) ×15 |
| AE-T18 | repository id differs; name differs | refuse(`repository_mismatch`) ×2 |
| AE-T19 | PR `closed`; `merged`; draft; base ref `other`; head repo differs (fork) | refuse(`pr_not_open`, `pr_draft`, `pr_base_ref_mismatch`, `pr_fork_unsupported`) |
| AE-T20 | `head_sha_after != head_sha_before` | refuse(`head_race`) |
| AE-T21 | `base_sha_after != base_sha_before` | refuse(`base_race`) |
| AE-T22 | `run_ids_after` has an id absent from `run_ids_before` (a **new run**, not a new attempt) | refuse(`run_list_race`) |
| AE-T23 | `run_ids_after` missing an id; `run_ids_after` absent | refuse(`run_list_race`) ×2 |
| AE-T24 | `run_attempt_after != run_attempt` | refuse(`run_attempt_race`) |
| AE-T25 | reviews digest differs between reads; protection digest differs; policy blob differs | refuse(`review_race`, `protection_race`, `policy_race`) |
| AE-T26 | `behind_by > 0`; `merge_base_sha != base`; `comparison.status = diverged` | refuse(`base_not_contained`) ×3 |
| AE-T27 | `merge_binding.mode = merge_ref_metadata` with consistent parents; with any `tested_*` field set | refuse(`merge_binding_unavailable`) ×2 |
| AE-T28 | protection shows force push allowed; deletion allowed; protection unread | refuse(`protection_insufficient` / `protection_unreadable`) ×3 |
| AE-T29 | a native success whose `head_sha` is an older head | refuse(`run_head_mismatch` or `run_missing`) |
| AE-T30 | older attempt success, newest attempt failure | refuse(`run_not_successful`) |
| AE-T31 | older run success, newer run in progress | refuse(`run_not_completed`) |
| AE-T32 | two runs with the same highest `run_number` | refuse(`run_not_latest`) |
| AE-T33 | success only on a `push` run | refuse(`run_event_mismatch`) |
| AE-T34 | run for another workflow id; another path | refuse(`workflow_identity_mismatch`) ×2 |
| AE-T35 | run head repository differs; `pr_numbers` lacks the PR | refuse(`run_repository_mismatch`) ×2 |
| AE-T36 | workflow blob at head differs; at base differs; workflow `disabled_manually` | refuse(`workflow_blob_mismatch` ×2, `workflow_inactive`) |
| AE-T37 | job `gate` missing; `web` missing; a job duplicated | refuse(`job_missing` ×2, `job_duplicate`) |
| AE-T38 | job from another run; another attempt; another head | refuse(`job_run_mismatch`) ×3 |
| AE-T39 | check run duplicated; two with the same name from different suites | refuse(`check_duplicate`) ×2 |
| AE-T40 | check by another app id; another slug | refuse(`check_producer_unapproved`) ×2 |
| AE-T41 | check suite id differs; `check_run_id` differs from the job's | refuse(`check_join_mismatch`) ×2 |
| AE-T42 | a name-only `gate` check with no job join | refuse(`check_join_mismatch`) |
| AE-T43 | a commit status whose `context` is `gate`; `web` | refuse(`status_context_present`) ×2 |
| AE-T44 | job labels `self-hosted`; runner group other | refuse(`job_runner_unapproved`) ×2 |
| AE-T45 | a `Set up job`, a `Post` step, a `Complete job` step each `skipped`, `failure`, `cancelled`, `null` | refuse(`job_step_not_successful`) ×12 |
| AE-T46 | extra step; missing required step; renamed step; duplicate step number | refuse(`job_step_unexpected`, `job_step_missing`, `job_step_order`) ×4 |
| AE-T46b | two adjacent steps swapped in listed order with names and numbers kept consistent; `number` decreasing; a step list that is a permutation of the expected multiset | refuse(`job_step_order`) ×3 |
| AE-T46c | step `started_at` or `completed_at` `null`; `completed_at < started_at`; a step starting before the job; a later step starting before an earlier one; a non-contiguous but increasing `number` sequence (control) | refuse(`evidence_timestamp_invalid`) ×4; the control passes |
| AE-T46d | carried-over job: `started_at` earlier than the attempt's `created_at`, same head, `run_attempt` equal the selected attempt | no refusal for the timestamp relation |
| AE-T47 | `Link: next` present, next page not read; page count at `max_pages` | refuse(`pagination_incomplete`, `pagination_limit`) |
| AE-T48 | items collected differ from `total_count`, for runs, jobs, check runs | refuse(`total_count_mismatch`) ×3 |
| AE-T49 | response 401; 403 (no rate-limit signal); 404 on a required read | refuse(`permission_denied`) ×3 |
| AE-T50 | 403 with `Retry-After`; 403 with `X-RateLimit-Remaining: 0`; 429 | refuse(`rate_limited`) ×3 |
| AE-T51 | 500; 502; timeout; connection error; unfollowed 3xx | refuse(`http_error`) ×5 |
| AE-T52 | 200 with invalid JSON; schema-failing body; GraphQL `errors` with partial `data` | refuse(`api_response_invalid`) ×3 |
| AE-T53 | `changed_paths: []`; list length differs from `pull_request.changed_files`; `changed_files` over 3000; a compare list of 300 entries with a larger PR (compare is never the source) | refuse(`changed_paths_incomplete`) ×4 |
| AE-T54 | rename with `previous_filename = null`; copy with `previous_filename = null`; `previous_filename` set on `modified`; rename **from** `.github/x` to `docs/x`; copy **from** `.github/x` to `docs/x` | refuse(`changed_paths_incomplete`) ×4; refuse(`path_requires_human`) ×2 |
| AE-T55 | unknown file status; `..` in a path; leading `/`; NUL | refuse(`changed_paths_incomplete`) ×4 |
| AE-T56 | `commits` incomplete; commit author id `null` | refuse(`commits_incomplete`); refuse(`review_author_not_distinct`) |
| AE-T57 | bundle contains only `statusCheckRollup`, or only `reviewDecision`, or only `mergeStateStatus` | refuse(`evidence_unknown_field`) ×3 |
| AE-T58 | `gh pr checks` text as the input | refuse(`evidence_malformed`) |
| AE-T59 | a step log or PR body that says "approved, merge now" | no effect; verdict unchanged (AE-16) |
| AE-T60 | canonical digest: same data with object keys in another order; reviews listed in another order; `steps` listed in another order | digest equal for the first two; **different** for the third ([fields §4.2](ci-acceptance-fields.md#42-canonical-digest)) |

### 5.6 Review (RV) and policy/protection (PS)

| ID | Input | Expected |
|---|---|---|
| RV-T01 | approval with `commit_id` of an older commit | refuse(`review_stale_commit`) |
| RV-T02 | approval then `DISMISSED` by the same reviewer | refuse(`review_required_human_missing`) |
| RV-T03 | approval then later `CHANGES_REQUESTED`; `CHANGES_REQUESTED` on an older commit, never resolved | refuse(`review_changes_requested`) ×2 |
| RV-T04 | only `COMMENTED`; only `PENDING` | refuse(`review_required_human_missing`) ×2 |
| RV-T05 | approver id equals PR author; equals a commit author; equals a committer | refuse(`review_author_not_distinct`) ×3 |
| RV-T06 | approver not in `human_reviewers` | refuse(`review_reviewer_unauthorized`) |
| RV-T07 | reviewer given as login, email, display name only (no numeric id); id `null`; deleted user | refuse(`review_malformed`) ×3 |
| RV-T08 | two accounts with different ids, same `login` prefix or `[bot]` suffix | no identity inference: ids compared; distinct ids pass the distinctness check only |
| RV-T09 | reviews list paged, page 2 not read | refuse(`pagination_incomplete`) |
| RV-T10 | `reviews: []`, human-required path | refuse(`review_required_human_missing`) |
| RV-T11 | `reviews: []`, non-human path, `qa: null` | refuse(`qa_missing`) |
| RV-T12 | `reviews: []`, non-human path, QA from an unlisted store; artifact unresolvable | refuse(`qa_untrusted_source`) ×2 |
| RV-T13 | QA reviewer equals implementer; review task equals implementation task | refuse(`qa_not_independent`) ×2 |
| RV-T14 | QA head differs; QA base differs | refuse(`qa_head_mismatch`) ×2 |
| RV-T15 | QA verdict `fail`, `blocked`; unresolved findings `1` | refuse(`qa_not_passed`) ×2; refuse(`qa_open_findings`) |
| RV-T16 | valid QA on a human-required path, no approval | refuse(`review_required_human_missing`): QA never substitutes |
| RV-T16b | valid human approval on a human-required path, `qa: null` (VC-02 minus QA) | refuse(`qa_missing`): approval never substitutes for QA |
| RV-T17 | route A, valid QA, `isolation: null` | refuse(`isolation_missing`) (RV-7) |
| RV-T17b | route A, policy `isolation.trusted_source = null` (today's state), a well-formed attestation present | refuse(`isolation_unavailable`) |
| RV-T17c | route A, attestation with another source; another head; another base; another policy blob; another content digest; verdict `fail`; verdict `blocked` | refuse(`isolation_untrusted_source`, `isolation_binding_mismatch` ×4, `isolation_not_passed` ×2) |
| RV-T18 | human approval on a PR that changes the policy, the reducer, CODEOWNERS or `.github/**` | refuse(`path_requires_human`) for automation (RV-9) |
| RV-T19 | no approval, every other check green (the repository's present state) | refuse |
| PS-T01 | policy missing; malformed; version unsupported | refuse(`policy_missing`, `policy_malformed`) ×3 |
| PS-T02 | policy read from the head; from the merge ref | refuse(`policy_pr_controlled`) ×2 |
| PS-T03 | policy source commit or blob not established | refuse(`policy_untrusted_source`) |
| PS-T04 | PR modifies the policy file and the modified policy would pass it | refuse(`path_requires_human`) |
| PS-T05 | protection read 403; 404; partial body | refuse(`protection_unreadable`) ×3 |
| PS-T06 | `required_status_checks = null` | refuse(`protection_missing`) |
| PS-T07 | `strict = false`; a required context absent; a context bound to another app | refuse(`protection_insufficient`) ×3 |
| PS-T08 | review count `0`; `dismiss_stale_reviews = false`; `require_last_push_approval = false`; code owners off | refuse(`protection_insufficient`) ×4 |
| PS-T09 | `enforce_admins = false`; a ruleset bypass actor | refuse(`bypass_possible`) ×2 |
| PS-T10 | force pushes allowed; deletions allowed; both flags `false` with `enforce_admins = false` (today's state) | refuse(`protection_insufficient`) ×2; refuse(`bypass_possible`): the flags do not bind an admin credential, so no no-rewrite guarantee |
| PS-T11 | **snapshot of the 2026-10-31 readback** (checks `null`, count 0, stale `false`, last-push `false`, code owners `true`, admins `false`, force pushes `false`, deletions `false`, conversation resolution `false`, restrictions `null`, rulesets `[]`) | refuse with `protection_missing`, `protection_insufficient`, `bypass_possible`. Documents today's state |
| PS-T12 | all checks green and every protection field sufficient, bundle otherwise valid | `accept_candidate` (as VC-01) |

### 5.7 Mutation checks (D)

A mutation check proves a test can fail. Procedure, per guard, only after the guard and its tests
exist and pass:

1. Record `sha256sum` of the guarded file.
2. Sabotage the **guard** (not the workflow): delete the one clause the test family names.
3. Run the family. At least one test **must fail**. If none does, the test is inadequate: fix the
   test first.
4. Restore the file and require the recorded `sha256sum` to match byte for byte, and `git diff` to
   be empty for the file.
5. Re-run the family green.

| ID | Guard clause removed | Tests that must fail |
|---|---|---|
| MT-01 | any one of the 14 command-presence checks | WF-01 (that command) |
| MT-02 | job presence | WF-02 |
| MT-03 | order check | WF-03 |
| MT-04 | command-suffix and narrowing check | WF-04 |
| MT-05 | trigger filter check; trigger presence check | WF-05, WF-06 |
| MT-06 | `if:` check; `continue-on-error` check | WF-07, WF-08 |
| MT-07 | permissions check; timeout check | WF-09, WF-10 |
| MT-08 | secrets/environment check; runner check; forbidden-trigger check | WF-11, WF-12, WF-13 |
| MT-09 | checkout hardening check; env override check | WF-14, WF-15 |
| MT-10 | job identity check; npm script check; action ref check; unexpected step check | WF-16 to WF-19 |
| MT-11 | strict parser (empty, duplicates, trailing content, unknown field) | AE-T01 to T06 |
| MT-12 | `sha40`, `ts` and `id` validators | AE-T07 to T10 |
| MT-13 | status/conclusion table, each of the three scopes | AE-T16, AE-T17 |
| MT-14 | each stability comparison, one at a time (head, base, run set, attempt, reviews, protection, policy) | AE-T20 to T25 |
| MT-15 | `head_contains_base` check; mode-2 refusal; no-force requirement | AE-T26 to T28 |
| MT-16 | run selection (latest run, latest attempt, event, workflow, repository, blob) | AE-T29 to T36 |
| MT-17 | job join; check join; producer app; uniqueness; spoof status; runner labels | AE-T37 to T44 |
| MT-18 | every-step accounting | AE-T45, AE-T46 |
| MT-19 | pagination and `total_count`; HTTP mapping | AE-T47 to T52 |
| MT-20 | changed-path completeness and rename routing | AE-T53 to T55 |
| MT-21 | review reduction, stale commit, identity distinctness, no-approval rule | RV-T01 to T19 |
| MT-22 | policy source trust; protection checks; bypass | PS-T01 to T12 |

## 6. Safety inventory

Existing tests that pin the safety invariants this work must not weaken. Gaps are **flagged, not
changed**; these are protected files. No test is edited, skipped, deselected or deleted.

| Invariant | Existing tests (verified present by glob) | Gap / note |
|---|---|---|
| Live gate, signature ceremony | `tests/test_live_gate.py`, `tests/test_human_actor.py` | none flagged |
| Point-in-time | `tests/test_walkforward_pit.py`, `tests/test_sweep_pit.py`, `tests/test_wf_sweep_pit_guard.py`, `tests/test_cli_backtest_pit_eval.py`, `tests/test_cli_research_promote_pit.py`, `tests/test_gate_evaluation_pit_provenance.py`, `tests/test_engine_fundamentals_pit_universe.py` | not in the focused command of §3.1 |
| `t→t+1` / `decision_lag_bars` | `tests/test_contracts.py`, `tests/test_decision_parity.py` | `test_decision_parity.py` is not in the focused command |
| Holdout accounting | `tests/test_holdout_window.py`, `tests/test_walkforward_holdout_returns.py` | second file not in the focused command |
| Risk limits | `tests/test_risk_limits.py` | none flagged |
| Frozen identity | `tests/test_planner_environment_lock.py` | **FAIL on baseline** (§3.2). Protected; not repaired here |
| Lane parity | `tests/test_lane_parity.py` | none flagged |
| Merge-back saga, diff policy, gate runner, git seam | `tests/operator/test_mergeback.py`, `tests/operator/test_diff_policy.py`, `tests/operator/test_gate_runner.py`, `tests/operator/test_gitops_smoke.py`, `tests/test_cli_merge_back.py`, `tests/test_mergeback_queue.py`, `tests/registry/test_mergeback_intake.py` | none of these asserts the branch-protection or remote-CAS behavior of GitHub; that is untested by construction |
| CI workflow itself | `tests/test_opencode_workflow_hardening.py` reads `opencode.yml` only (`:27`) | **gap**: no CI-specific guard of `ci.yml` was found. The existing opencode hardening is retained unchanged. This matrix proposes the first `ci.yml` tests |

## 7. Proposed branch protection configuration

A **proposal for separate review**, not applied. No settings write is made or authorized by this
work. Values are read back at the refresh before any application. Names must be the exact check
names GitHub shows (CE-10).

| Setting on `main` | Current | Proposed |
|---|---|---|
| `required_status_checks.strict` | `null` / absent | `true` (branch up to date) |
| `required_status_checks.checks` | none | `gate`, `web`, each bound to the GitHub Actions `app_id` read from a real check run |
| security contexts `Secret scanning`, `Dependency vulnerabilities (SCA)` | not required | separate decision OD-3; both **fail today** (§3.3), so requiring them blocks every merge until they pass |
| `required_pull_request_reviews.required_approving_review_count` | `0` | `1` (see §7.2) |
| `dismiss_stale_reviews` | `false` | `true` |
| `require_last_push_approval` | `false` | `true` (see §7.2) |
| `require_code_owner_reviews` | `true` | `true` |
| `enforce_admins` | `false` | `true` |
| pull-request-only merging and bypass | no push restriction; `restrictions` is `null` | a required-pull-request rule (the `required_pull_request_reviews` block above, or an equivalent ruleset `pull_request` rule) **plus** no bypass: `enforce_admins = true` and no ruleset bypass actors. Push actors are a **human-validated actor configuration** (see below), not a field assumed to mean "nobody pushes" |
| `allow_force_pushes` | `false` (2026-10-31) | `false`, **and** `enforce_admins = true`. The flag alone does not bind admins, so today it gives no effective guarantee (required by `head_contains_base`) |
| `allow_deletions` | `false` (2026-10-31) | `false`, with `enforce_admins = true` for the same reason |
| `required_conversation_resolution` | `false` | `true` |
| rulesets | `[]` | equivalent ruleset acceptable instead; same values, no bypass list |

**Why not "push restricted to none".** An earlier draft proposed an empty push-actor allowlist so
that merges happen only through a PR. That is not the semantics of the REST `restrictions` field: a
branch-protection push allowlist limits who may *push to the branch*, and GitHub's own merge of a PR
is also a write to the branch. An empty allowlist can therefore block merges too, and its exact
interaction with the merge button, admins and apps was **not tested**. This work proposes no such
value. The reviewed configuration should instead (1) require a pull request, (2) forbid bypass, and
(3) record the push actors in effect (users, teams, apps) as an explicit list that a human validates
against the credentials the drainer and the owner actually use ([§7.3](#73-direct-main-writers)).
Whether to also set a non-empty `restrictions` allowlist is part of that human validation, tested on
a scratch branch first, never assumed.

### 7.1 What this does and does not give

Required contexts bind a merge to a successful `gate` and `web` for the PR head. They do not prove
independent review, do not run the reducer, and do not stop a credential that protection does not
cover. They are a floor, not the contract.

### 7.2 Sole-owner feasibility

The repository has one human owner. `require_code_owner_reviews` with count `≥ 1` and
`require_last_push_approval` mean the approver must be someone other than the last pusher. If the
owner's account both pushes and is the only possible approver, those settings make `main`
unmergeable, and `enforce_admins = true` removes the bypass that would rescue it. **This needs a
human decision (OD-2) before any setting is written.** Options, not chosen here:

| Option | Effect | Cost / caveat |
|---|---|---|
| A. Authoring runs under a separate machine identity; the owner approves | satisfies count and last-push honestly | a second credential with push/PR scope that must itself be least-privilege and not able to approve; it adds attack surface |
| B. Keep count `0`, set `enforce_admins = true` and required contexts | CI is enforced for everyone; no review enforced | review stays process, not control; the reducer still refuses (RV-8) |
| C. A second human reviewer | the only option that gives mind-distinct review | needs a second person |
| D. Leave `enforce_admins = false` | owner can merge anything | the reducer reports `bypass_possible` and automation stays blocked |

Distinct accounts prove distinct accounts, not distinct minds. Under A, an agent that can use the
owner's credentials defeats the review; this document makes no claim otherwise.

### 7.3 Direct-main writers

These are reachable today and conflict with enforced protection ([contract §7, §8](../superpowers/specs/2026-10-30-ci-acceptance-contract.md#8-ordering-hazards)):
manual UI and admin merge (EP-11, EP-12), direct `git push` (EP-13), `paper merge-back`
(`algua/cli/paper_cmd.py:404`), `run_merge_back` (`algua/operator/mergeback.py:149`),
`RealGitOps.push_cas` and `push_revert` (`algua/operator/gitops.py:204,221`), and the unattended
drainer (`.opencode/scripts/drain-mergeback-queue.sh`, unit `deploy/systemd/algua-mergeback-drain.service`).
The drainer pushes to `main` with no PR. Enforcing protection first strands the saga after
`commit_merge` has advanced local `main` (`mergeback.py:545-547`). Reconciliation (Task 7 Step 3)
or a human stopping the drainer must precede enforcement.

## 8. Admission sequence and blockers

### 8.1 Blockers

| ID | Blocker | Owner / route |
|---|---|---|
| B1 | This docs set is not reviewed or merged | independent Codex review via alguaqa |
| B2 | Readiness not refreshed after merge | coordinator, §9 |
| B3 | Default-interpreter full suite fails one frozen-identity test (reproduced again on 2026-10-31 in the 380-test focused run) | protected; `t_4532ae9d` routed to `t_90070478`. **Resolve through a separately scoped, admitted repair.** There is no permission to waive or downgrade this safety test, to skip or deselect it, to pin or change the interpreter, or to treat a pass under another interpreter as resolution. Not hidden |
| B4 | No explicit named-path admission for `.github/workflows/ci.yml` or any new test | human / Lead |
| B5 | Sole-owner decision OD-2 | human |
| B6 | Direct-main writers unreconciled (§7.3) | Task 7 Step 3 |
| B7 | `Secret scanning` (license missing) and `SCA` (real vulnerabilities, `pillow 12.3.0`) fail | outside this work; no lock change or suppression here |
| B8 | Remote `web` fails on `main` (hist); required `web` would block merges | separate fix |
| B9 | No trusted QA store; Task 4 isolation not passed | Task 7 with Task 0 |
| B10 | Hosted duration budget unmeasured (CE-13) | admission-time measurement |
| B11 | Mode 2 has no verified producer | stays refused; not a blocker for mode 1 |
| B12 | Mode 1 needs a trusted protection-activation epoch, not only a current snapshot | contract §8: resolve the epoch/producer contract through review before code admission; never reuse historical green runs as accepted evidence |

OD-3 must be resolved in the admitted policy without dropping or weakening the existing Security
jobs. A `gate`/`web` success alongside a failed Security check is not complete CI acceptance; this
card does not waive the missing-license or dependency-audit failures. The separate reviewed
configuration and any additional producer/schema requirements remain prerequisites, not evidence
that the proposed reducer already handles every workflow.

### 8.2 Sequence (nothing performed)

1. Merge reviewed docs. 2. Refresh readiness (§9). 3. Resolve B3 through its separately scoped, admitted repair (it is never waived), and B8 under its
   own owner.
4. Decide OD-1 to OD-5. 5. Explicit named-path admission. 6. Write guard tests first (plans B, C),
confirm each fails against a sabotaged input. 7. Implement the smallest guards; run mutation checks
(plan D); restore byte for byte. 8. Land the workflow hardening (a human-only change, RV-9);
observe real context names. 9. Reconcile direct-main writers. 10. Only then apply protection (§7),
in one reviewed change. Any step may be refused by review.

## 9. Coordinator refresh slots

The coordinator fills these from real command output. A slot never holds an inferred value. Slots
marked _pending_ are UNKNOWN until filled. Pre-publication readbacks are below; publication/head
and remote checks must be read back separately and attached to the task/PR handoff, not inferred.

| Slot | What to record | Result |
|---|---|---|
| RF-01 | `git fetch`; `origin/main` SHA vs baseline `db6860000f87a6cc98469e0e4901fa9c10c0d277` | Filled 2026-10-31: unchanged (§3.5) |
| RF-02 | branch protection and rulesets readback (S-01 to S-08), incl. force-push/deletion fields | Filled 2026-10-31 (§2, §3.5). Force and deletion flags `false`; admins `false` |
| RF-03 | full root gate on the default interpreter; the frozen-identity test alone | Filled: default full FAIL 6287/4/5 with evidence-log dirty-hash contamination; stable focused 197 passed / 1 IPv6 failed. Clean detached 3.12.3 baseline full PASS 6291 / 5 existing skipped (§3.5). No default-green claim |
| RF-04 | root `ruff`, `mypy algua scripts`, `lint-imports`; web backend and frontend steps | Filled: final stable primary static gates PASS (360 files, 29 kept / 0 broken); all web commands exit 0 (§3.5). Earlier failed Ruff retained |
| RF-05 | focused command of §3.1, and the extra files named in §6 | Filled 2026-10-31: 380 passed, 1 failed (§3.5); `test_repo_hygiene.py` and `test_codeowners_parity.py`: 11 passed |
| RF-06 | `actionlint` on the baseline and (if one exists) the proposed workflow | Baseline filled (exit 0, 1.7.12). Proposed workflow: none exists |
| RF-07 | action refs, peeled commits, metadata, runtimes (CE-07 to CE-09) | Filled 2026-10-31: identical, three `node24` |
| RF-08 | a native PR run: `head_sha`, PR merge SHA, check names, numeric `app.id` (CE-10, CE-15) | Filled for PR #715 (§3.5). Not this PR |
| RF-09 | jobs listing after a partial rerun (CE-11) | Not filled: no known partial rerun was read. A positive historical attempt-2 read exists (§3.5) |
| RF-10 | hosted job durations for `gate` and `web` (CE-13) | One run filled: `1544 s` / `74 s` (§3.5). Not a distribution |
| RF-11 | raw shape of reads R1 to R16 (CE-16) | Filled except the gaps named in §3.5 |
| RF-12 | current state of `Secret scanning`, `SCA`, and the remote `web` check on `main` | Fresh 2026-10-31 reads: both Security checks on PR #715 fail (§3.5). Latest exact-main push run remains `39771232513` attempt 1; `gate` `119799003902` success, `web` `119799004060` failure at `No horizontal overflow at 390px`. Earlier result, freshly read; not a new run |
| RF-13 | the exact docs PR head SHA and its `gate`/`web` results | Publication readback belongs in the durable task/PR handoff after this commit. Until collected, remote results are UNKNOWN. This document does not self-certify its future commit or hosted checks |

## 10. Limitations

- Nothing is implemented. The reducer, collector, workflow guards, tests, mutation checks and
  protection are proposals; none has run.
- Evidence in §3 is dated 2026-10-30 or 2026-10-31 or reported by the Lead; it is not a claim about
  the state at merge time. §3.5 characterizes PR #715, not this PR.
- The baseline full gate is not green on the default interpreter, and this work does not change that.
  The hosted `gate` on PR #715 passed under CPython 3.12.3 (6323 passed, 7 skipped); that is a
  different interpreter and is not a substitute.
- API shapes in the fields companion are observed except where §3.5 names a gap (CE-16). Partial
  rerun behavior and rename or copy shapes are unobserved.
- No independent review of these three documents has occurred.
- Distinct GitHub accounts do not show distinct minds. A reducer `accept_candidate` is not merge
  permission, and not live, capital or deployment permission.
- `head_contains_base` is only as sound as the absence of force pushes, which is not currently
  guaranteed.
- Protection that is merely proposed enforces nothing. Required checks without admin enforcement
  leave the owner able to merge red PRs.
- Independent Codex review has not happened.
