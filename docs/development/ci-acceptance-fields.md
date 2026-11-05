# CI acceptance — field-level companion

Companion to the [CI acceptance contract](../superpowers/specs/2026-10-30-ci-acceptance-contract.md).
Status: **proposed, BLOCKED FOR CODE**. The schema here is a **proposal for a trusted read-only
reducer**. It is not authority, and no validator ships with it. Baseline:
`db6860000f87a6cc98469e0e4901fa9c10c0d277`.

GitHub API shapes below were first written from knowledge of the API. They have since been checked
against real read-only responses for PR #715 (a different docs PR, not this one) and one historical
run, recorded in [readiness §3](ci-acceptance-readiness.md#3-historical-evidence-2026-10-30-not-fresh)
and [§3.5](ci-acceptance-readiness.md#35-2026-10-31-readbacks). Each row of §10 says whether its
shape was **observed** or is still **unobserved**. Anything unobserved needs fresh readback before
implementation ([readiness §4](ci-acceptance-readiness.md#4-executable-readiness)); where reality
differs, amend this file rather than loosening the reducer.

**Two schemas, two strictness rules.** The *raw* GitHub responses are not a schema we control and
may gain additive fields. The collector therefore reads them through an **explicit projection**:
it copies only the fields named in §4 and §10 into the *normalized evidence bundle* and drops the
rest. Unknown-field refusal (§1) applies to the **normalized bundle**, never to raw responses. A
raw response that lacks a projected field, or has it with the wrong type, is `api_response_invalid`.
A raw response with an extra field is not an error and not evidence.

## 1. Conventions

| Type | Rule |
|---|---|
| `sha40` | Exactly `^[0-9a-f]{40}$`. Short, uppercase and empty values refuse. |
| `ts` | RFC 3339 UTC ending in `Z`. Offsets, naive values and non-strings refuse. |
| `id` | JSON integer, positive. Booleans, floats and numeric strings refuse. |
| `enum` | Listed values only, case-sensitive. Unknown values refuse. |
| `null` | Allowed only where a field says so. |

Parsing rules for the normalized bundle: UTF-8 JSON object; duplicate keys, `NaN`, `Infinity` and
trailing content refuse; unknown fields refuse at every level of the **bundle**;
`schema_version` must match exactly. A size bound comes from policy. Every list must be present; an
empty list is meaningful only where stated. Every field in §4 is required unless its row says
`null` is allowed.

## 2. Workflow target

"Current" is `.github/workflows/ci.yml` at baseline. Target applies to any admitted implementation.

| Key path | Current | Target | Status |
|---|---|---|---|
| `name` | `CI` | `CI` | PASS |
| `on.pull_request` | present, no filters | present, no filters, default activity types | PASS |
| `on.push.branches` | `[main]` | `[main]` | PASS |
| any other trigger | none | none | PASS |
| `permissions` (top level) | absent | `contents: read` only | FAIL |
| `jobs.<id>.permissions` | absent | absent | PASS |
| `jobs.gate.timeout-minutes` | absent | `30` (proposed, unmeasured) | FAIL |
| `jobs.web.timeout-minutes` | absent | `20` (proposed, unmeasured) | FAIL |
| `jobs.*.runs-on` | `ubuntu-latest` | `ubuntu-latest`, string | PASS |
| `jobs.*.if`, `steps[*].if` | absent | absent | PASS |
| `*.continue-on-error` | absent | absent | PASS |
| `jobs.*.needs`, `strategy`, `container`, `services`, `environment` | absent | absent | PASS |
| `env`, `defaults` at any level | absent | absent | PASS |
| `secrets.*`, `id-token` | absent | absent | PASS |
| checkout `with.persist-credentials` | absent, so default | `false` on both | FAIL |
| checkout `token`, `ssh-key`, `ref`, `repository` | absent | absent | PASS |
| `actions/checkout` ref | `@v7.0.1` | exists, metadata read; pin per OD-1 | PASS (historical, 2026-10-30) |
| `astral-sh/setup-uv` ref | `@v7` | exists, metadata read; pin per OD-1 | PASS (historical, 2026-10-30) |
| `actions/setup-node` ref | `@v7` | exists, metadata read; pin per OD-1 | PASS (historical, 2026-10-30) |

Baseline action facts, read through the GitHub API on 2026-10-30 and re-read on 2026-10-31 with
identical refs, peeled commits and `node24` runtimes (dated evidence, to be re-read at admission):

| Action | Ref | Resolves to | Runtime | Token / credential defaults |
|---|---|---|---|---|
| `actions/checkout` | `v7.0.1` | `3d3c42e5aac5ba805825da76410c181273ba90b1`, same as the pin at `security.yml:18` | `node24` | `persist-credentials` defaults **true**; default `token` is the job `github.token` |
| `actions/setup-node` | `v7` | `949feb2413d6458794dcd2491c4babbbce0c15c1` | `node24` | default `token` is the job `github.token` (read scope under WF-4) |
| `astral-sh/setup-uv` | `v7` | annotated tag object `94527f2e458b27549849d47d273a16bec83a01e9`, **peeled commit** `37802adc94f370d6bfd71619e3f0bf239e1f3b78`, same as the pin at `security.yml:19` | `node24` | default `github-token` is the job `github.token` (read scope under WF-4) |

A tag object is not a commit. Only the peeled commit is a valid full-SHA pin. All three actions
run on `node24`. The default `GITHUB_TOKEN` permission for this repository reads as `read`, and
`can_approve_pull_request_reviews` as `false`. `persist-credentials: false` (WF-5) is still
required because the default would leave a token in `.git/config` for every later step.

`actionlint` 1.7.12 (archive SHA256
`8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`) accepted the **baseline**
`ci.yml` with exit 0 and no findings on 2026-10-30 and again on 2026-10-31, and the baseline run
executed these exact actions on hosted runners. A target workflow file does not exist. That characterizes the baseline. It is **not** evidence that a target workflow exists,
parses or runs: no target workflow has been written. Each target workflow needs its own
`actionlint` run and its own hosted run at admission.

## 3. Preserved commands

Exact strings, in order. Any removal, reorder, narrowing or suffix (`|| true`, `-k`, `--deselect`,
a narrower `mypy` target) fails the guard. Step names are the reducer's `required_steps`.

| Job | # | Step name | Command | Working dir |
|---|---|---|---|---|
| gate | 1 | Install dependencies | `uv sync --locked` | root |
| gate | 2 | Test | `uv run pytest -q` | root |
| gate | 3 | Ruff | `uv run ruff check .` | root |
| gate | 4 | Mypy | `uv run mypy algua scripts` | root |
| gate | 5 | Import boundaries | `uv run lint-imports` | root |
| web | 1 | Install web backend (standalone project — root uv.lock untouched) | `uv sync --project web --locked` | root |
| web | 2 | Backend tests | `uv run --project web pytest web/backend/tests -q` | root |
| web | 3 | Frontend install | `npm ci` | `web/frontend` |
| web | 4 | Frontend check (tsc + vitest) | `npm run check` | `web/frontend` |
| web | 5 | Frontend build | `npm run build` | `web/frontend` |
| web | 6 | Production build carries no fixtures | `node scripts/verify-demo-build.mjs prod dist` | `web/frontend` |
| web | 7 | Demo build | `npm run build:demo` | `web/frontend` |
| web | 8 | Demo build carries fixtures | `node scripts/verify-demo-build.mjs demo dist-demo` | `web/frontend` |
| web | 9 | No horizontal overflow at 390px | `npm run verify:viewport` | `web/frontend` |

Non-`run` steps preserved: `gate` uses checkout and `setup-uv` with `enable-cache: true`. `web` uses
checkout, `setup-uv` with `enable-cache: true`, and `setup-node` with `node-version: 22`,
`cache: npm`, `cache-dependency-path: web/frontend/package-lock.json`.

Indirect behavior also counts. These npm scripts are part of what the commands mean, and a guard
must pin them (`web/frontend/package.json:8-12`):

| Script | Value |
|---|---|
| `build` | `tsc -b && vite build && node scripts/verify-demo-build.mjs prod dist` |
| `build:demo` | `VITE_ALGUA_DEMO=1 tsc -b && VITE_ALGUA_DEMO=1 vite build --outDir dist-demo` |
| `verify:viewport` | `node scripts/verify-viewport.mjs` |
| `check` | `tsc --noEmit && vitest run` |

The `web/frontend/scripts/verify-viewport.mjs` step depends on the earlier `dist-demo` build, so
order is behavior. It also launches `chromium.launch({ channel: 'chrome' })` and the workflow
installs no browser, so it depends on Chrome being on the hosted image.

## 4. Evidence bundle

`ci-acceptance-evidence/v1`. The **normalized** bundle, produced by a read-only collector's explicit
projection (see the header) and reduced with a trusted policy (§5).

> **ILLUSTRATIVE ONLY, NOT A PASSING FIXTURE.** The example below is deliberately **partial and
> nonpassing**: `<...>` placeholders are not valid `sha40` values, `jobs` lists one job where policy
> requires two, `check_runs` and `reviews` are incomplete, and `protection` is empty. The reducer
> must refuse it (`evidence_malformed`, `job_missing`, `check_missing`, `protection_missing`,
> `isolation_missing`). It shows shape only. A passing control fixture is defined in
> [readiness §5](ci-acceptance-readiness.md#5-test-matrix) as `VC-01` and does not yet exist.

```json
{
  "schema_version": "ci-acceptance-evidence/v1",
  "collected_at": "2026-10-30T12:00:00Z",
  "repository": {"full_name": "<owner>/<repo>", "id": 1},
  "pull_request": {"number": 1, "state": "open", "draft": false, "author_id": 1,
                   "changed_files": 1, "base_ref": "main", "head_ref": "<branch>",
                   "head_repository_id": 1, "head_repository_full_name": "<owner>/<repo>"},
  "observed": {"head_sha_before": "<sha40>", "head_sha_after": "<sha40>",
               "base_sha_before": "<sha40>", "base_sha_after": "<sha40>",
               "run_ids_before": [1], "run_ids_after": [1],
               "reviews_digest_before": "<hex64>", "reviews_digest_after": "<hex64>",
               "protection_digest_before": "<hex64>", "protection_digest_after": "<hex64>",
               "policy_blob_sha_before": "<sha40>", "policy_blob_sha_after": "<sha40>"},
  "comparison": {"status": "ahead", "ahead_by": 1, "behind_by": 0, "merge_base_sha": "<sha40>"},
  "merge_binding": {"mode": "head_contains_base", "tested_merge_sha": null,
                    "tested_base_sha": null, "tested_parents": null},
  "workflow": {"id": 1, "path": ".github/workflows/ci.yml", "name": "CI", "state": "active",
               "blob_sha_at_head": "<sha40>", "blob_sha_at_base": "<sha40>"},
  "runs": [{"id": 1, "run_number": 1, "run_attempt": 1, "run_attempt_after": 1,
            "workflow_id": 1, "path": ".github/workflows/ci.yml", "event": "pull_request",
            "head_sha": "<sha40>", "head_repository_id": 1, "pr_numbers": [1],
            "status": "completed", "conclusion": "success", "check_suite_id": 1,
            "created_at": "<ts>", "updated_at": "<ts>"}],
  "jobs": [{"id": 1, "run_id": 1, "run_attempt": 1, "name": "gate", "head_sha": "<sha40>",
            "status": "completed", "conclusion": "success", "started_at": "<ts>",
            "completed_at": "<ts>", "check_run_id": 1, "labels": ["ubuntu-latest"],
            "runner_group_name": "GitHub Actions",
            "steps": [{"name": "Test", "number": 5, "status": "completed",
                       "conclusion": "success", "started_at": "<ts>", "completed_at": "<ts>"}]}],
  "check_runs": [{"id": 1, "name": "gate", "head_sha": "<sha40>", "status": "completed",
                  "conclusion": "success", "app_id": 1, "app_slug": "github-actions",
                  "check_suite_id": 1, "started_at": "<ts>", "completed_at": "<ts>"}],
  "commit_statuses": [],
  "reviews": [],
  "commits": [{"sha": "<sha40>", "author_id": 1, "committer_id": 1}],
  "changed_paths": [{"filename": "<path>", "previous_filename": null, "status": "modified",
                     "blob_sha": "<sha40>"}],
  "protection": {"read_ok": true, "branch_protection": {}, "rulesets": []},
  "qa": null,
  "isolation": null,
  "collection": {"pages": {"runs": 1, "jobs": 1, "check_runs": 1, "statuses": 1, "reviews": 1,
                           "commits": 1, "paths": 1},
                 "total_counts": {"runs": 1, "jobs": 2, "check_runs": 2},
                 "complete": true, "errors": []}
}
```

### 4.1 Field dictionary

Every field of the bundle, with its type and rule. A field without a row here is an unknown field
and refuses. `Refusal` codes are listed in §9.

| Field | Type | Source (§10) | Rule | Refusal |
|---|---|---|---|---|
| `schema_version` | enum | collector | exact | `evidence_schema_unsupported` |
| `collected_at` | ts | reducer clock vs response `Date` | not future; age ≤ policy | `evidence_timestamp_future`, `evidence_stale` |
| `repository.id`, `.full_name` | id, string | R1 | equal policy | `repository_mismatch` |
| `pull_request.state` | enum | R2 | `open` | `pr_not_open` |
| `pull_request.draft` | bool | R2 | `false` | `pr_draft` |
| `pull_request.base_ref` | string | R2 | equals policy `base_ref` | `pr_base_ref_mismatch` |
| `pull_request.head_repository_id` | id | R2 | equals `repository.id` | `pr_fork_unsupported` |
| `observed.head_sha_before`, `_after` | sha40 | R2 before, R2 after | equal | `head_race` |
| `observed.base_sha_before`, `_after` | sha40 | R3 before, R3 after | equal | `base_race` |
| `comparison.*` | mixed | R4 | per §7 | `base_not_contained` |
| `merge_binding.mode` | enum `head_contains_base`, `merge_ref_metadata` | derived | `head_contains_base` only. `merge_ref_metadata` is **reserved and refused**: no verified trusted producer exists | `merge_binding_missing`, `merge_binding_mismatch`, `merge_binding_unavailable` |
| `merge_binding.tested_parents` | list of 2 sha40, or null | none today | **must be `null`** | `merge_binding_mismatch` |
| `workflow.id`, `.path`, `.state` | id, string, enum | R5 | equal policy; `active` | `workflow_identity_mismatch`, `workflow_inactive` |
| `workflow.blob_sha_at_head` | sha40 | R6 at head | equals policy `workflow_blob_sha` | `workflow_blob_mismatch` |
| `workflow.blob_sha_at_base` | sha40 | R6 at base | equals policy `workflow_blob_sha` | `workflow_blob_mismatch` |
| `runs[]` | list ≥ 1 | R7 | all runs for workflow, head, event | `run_missing`, `pagination_incomplete` |
| `runs[].event` | enum | R7 | `pull_request` | `run_event_mismatch` |
| `runs[].head_sha` | sha40 | R7 | equals head | `run_head_mismatch` |
| `runs[].head_repository_id` | id | R7 | equals repo | `run_repository_mismatch` |
| `runs[].pr_numbers` | list of id | R7 | contains PR | `run_repository_mismatch` |
| `runs[].run_attempt`, `run_attempt_after` | id | R8 before, after | equal | `run_attempt_race` |
| `runs[].status`, `.conclusion` | enum, enum or null | R8 | §8, selected run | `run_not_completed`, `run_not_successful` |
| `jobs[]` | list | R9 for selected attempt | exactly policy jobs | `job_missing`, `job_duplicate` |
| `jobs[].run_id`, `.run_attempt` | id | R9 | selected run and attempt | `job_run_mismatch` |
| `jobs[].status`, `.conclusion` | enum | R9 | §8 | `job_not_completed`, `job_not_successful` |
| `jobs[].steps[]` | list | R9 | all steps accounted for, see below | `job_step_missing`, `job_step_unexpected`, `job_step_not_successful` |
| `jobs[].labels`, `.runner_group_name` | list, string | R9 | policy hosted values | `job_runner_unapproved` |
| `check_runs[]` | list | R10, `filter=all` | one per policy context in selected suite | `check_missing`, `check_duplicate` |
| `check_runs[].app_id`, `.app_slug` | id, string | R10 | policy app | `check_producer_unapproved` |
| `check_runs[].check_suite_id` | id | R10 | equals selected `run.check_suite_id` | `check_join_mismatch` |
| `check_runs[].id` | id | R10 | equals `jobs[].check_run_id` | `check_join_mismatch` |
| `commit_statuses[]` | list | R11 | no entry named a required context | `status_context_present` |
| `pull_request.changed_files` | int ≥ 1 | R2 | **the authoritative file count.** Must be ≤ 3000 (the R13 bound) and equal `len(changed_paths)`. Compare's file list is never the count source | `changed_paths_incomplete` |
| `changed_paths[]` | list ≥ 1 of objects | R13 | complete: `len` equals `pull_request.changed_files`; unique `filename`; routes §6 | `changed_paths_incomplete`, `path_requires_human` |
| `changed_paths[].filename` | string | R13 | non-empty, repo-relative, no `..`, no leading `/`, no NUL | `changed_paths_incomplete` |
| `changed_paths[].previous_filename` | string or null | R13 | **required non-null** when `status` is `renamed` or `copied`; **must be `null`** for every other status. A non-null value on any other status refuses; it is never silently allowed or ignored. **Both** names route (§6). For a copy the source path is routed exactly like a rename source; if the source is unavailable the PR refuses | `changed_paths_incomplete` |
| `changed_paths[].status` | enum `added`, `modified`, `removed`, `renamed`, `copied`, `changed` | R13 | known; `unchanged` and unknown refuse | `changed_paths_incomplete` |
| `changed_paths[].blob_sha` | sha40 | R13 (`sha`) | recorded; input to the content digest of §4.2. For `removed` files GitHub reports the removed blob; recorded as given | `evidence_malformed` |
| `isolation` | object or null | Task 4 store (none exists) | see §6 *Strategy isolation attestation*; `null` refuses on every route that requires it | `isolation_missing`, `isolation_unavailable` |
| `collection.complete` | bool | collector | `true`, `errors` empty | `pagination_incomplete`, §9 |
| `collection.pages.*` | int ≥ 1 | collector | one per list read, `≤ max_pages` | `pagination_limit` |
| `collection.total_counts.*` | int ≥ 0 | R7, R9, R10 | equals items collected | `total_count_mismatch` |
| `collection.errors[]` | list of `{read, code}` | collector | empty | per `code` (§10) |
| `pull_request.number`, `.author_id` | id | R2 | equals requested PR; `author_id` is the numeric user id | `evidence_malformed` |
| `pull_request.head_ref`, `.head_repository_full_name` | string | R2 | recorded; `head_repository_full_name` equals `repository.full_name` | `pr_fork_unsupported` |
| `observed.run_ids_before`, `_after` | list of id | R7 before, R7 after | **same set**, from a fresh re-listing after all other reads. A new id is a race | `run_list_race` |
| `observed.reviews_digest_before`, `_after` | hex64 | R12 twice | equal. Canonical digest (§4.2) of the whole paged list | `review_race` |
| `observed.protection_digest_before`, `_after` | hex64 | R15, R16 twice | equal. Canonical digest (§4.2) | `protection_race` |
| `observed.policy_blob_sha_before`, `_after` | sha40 | policy source twice | equal, and equal `policy.source.blob_sha` | `policy_race` |
| `comparison.status` | enum | R4 | `ahead` or `identical` | `base_not_contained` |
| `comparison.ahead_by`, `.behind_by` | int ≥ 0 | R4 | mode 1 needs `behind_by = 0` | `base_not_contained` |
| `comparison.merge_base_sha` | sha40 | R4 | mode 1 needs it equal `base_sha_after` | `base_not_contained` |
| `merge_binding.tested_merge_sha`, `.tested_base_sha` | sha40 or null | none today | **must be `null`.** Mode 2 is refused (§7 step 5) | `merge_binding_mismatch` |
| `workflow.name` | string | R5 | equals policy `workflow.name` | `workflow_identity_mismatch` |
| `runs[].id`, `.run_number`, `.workflow_id`, `.check_suite_id` | id | R7 | `workflow_id` equals policy; `id` unique | `run_head_mismatch`, `evidence_malformed` |
| `runs[].path` | string | R7 | equals policy path | `workflow_identity_mismatch` |
| `runs[].created_at`, `.updated_at` | ts | R7 | not future; `updated_at ≥ created_at` | `evidence_timestamp_invalid` |
| `jobs[].id`, `.check_run_id` | id | R9 | `id` unique | `job_duplicate` |
| `jobs[].name` | string | R9 | equals a policy context exactly | `job_missing` |
| `jobs[].head_sha` | sha40 | R9 | equals head | `job_run_mismatch` |
| `jobs[].started_at`, `.completed_at` | ts | R9 | `started_at ≤ completed_at`, not future. **No relation to the run attempt's `created_at` is required**: a job carried into a later attempt keeps its original execution times (see §10 R9) | `evidence_timestamp_invalid` |
| `jobs[].steps[]` | list of objects | R9 | the **ordered** list equals policy `expected_steps[]` exactly (§4.3) | `job_step_missing`, `job_step_unexpected`, `job_step_order` |
| `jobs[].steps[].name`, `.number` | string, id | R9 | `number` unique and strictly increasing in listed order. Numbers need **not** be contiguous: real jobs skip numbers (`web` runs 1 to 13, then 24 to 27) | `job_step_order` |
| `jobs[].steps[].status`, `.conclusion` | enum | R9 | §8 | `job_step_not_successful` |
| `jobs[].steps[].started_at`, `.completed_at` | ts | R9 | observed non-null on every step of four real job listings, including `skipped` steps. Both required as `ts` for every step of a passing job; `null` or unparseable refuses. `started_at ≤ completed_at`; across steps in listed order `started_at` is non-decreasing; the first step does not start before `jobs[].started_at` and the last does not complete after `jobs[].completed_at`. These ordering rules are observed in the sample, not guaranteed by the API: a violation refuses and is never normalised | `evidence_timestamp_invalid` |
| `check_runs[].id`, `.name`, `.head_sha` | id, string, sha40 | R10 | `head_sha` equals head | `check_join_mismatch` |
| `check_runs[].status`, `.conclusion` | enum | R10 | §8 | `check_not_completed`, `check_not_successful` |
| `check_runs[].started_at`, `.completed_at` | ts | R10 | as jobs | `evidence_timestamp_invalid` |
| `commit_statuses[].context`, `.creator_id` | string, id | R11 | list may be empty; no required-context entry | `status_context_present` |
| `commits[].sha` | sha40 | R14 | complete list, unique | `commits_incomplete` |
| `commits[].author_id`, `.committer_id` | id or null | R14 | `null` is retained and later refuses (§6) | `review_author_not_distinct` |
| `protection.read_ok` | bool | R15, R16 | `true` | `protection_unreadable` |
| `protection.branch_protection`, `.rulesets` | object, list | R15, R16 | projected per [readiness §7](ci-acceptance-readiness.md#7-proposed-branch-protection-configuration); `{}` and `[]` are present values that then fail the policy | `protection_missing`, `protection_insufficient` |
| `qa` | object or null | OD-4 | see §6. Required on **every** route that can end in `accept_candidate`; human approval never replaces it | `qa_missing`, `qa_untrusted_source` |
| `reviews[]` | list, may be empty | R12 | every page; an empty list is a valid read that yields no approval | `pagination_incomplete` |

### 4.2 Canonical digest

Every `*_digest_*` value and `evidence_sha256` is computed one way, so two implementations agree:

1. Build the **projection**: only the fields the bundle names for that list, nothing else.
2. Serialize with RFC 8785 JSON Canonicalization: UTF-8, object keys sorted by code point, no
   insignificant whitespace, integers as decimal, no `NaN` or `Infinity`.
3. Lists are ordered before serializing: `reviews[]` by `id` ascending; `changed_paths[]` by
   `filename` ascending (then `previous_filename`, `null` first); `protection.rulesets[]` by `id`
   ascending; `jobs[].steps[]` keep **listed order**, since order is the point.
4. Digest is lowercase hex SHA-256 of those bytes.

`observed.reviews_digest_*` projects the whole paged review list as in §6. `observed.protection_digest_*`
projects `protection` as in [readiness §7](ci-acceptance-readiness.md#7-proposed-branch-protection-configuration).
The isolation attestation's `content_sha256` (§6) is this digest over `changed_paths[]` projected to
`filename`, `previous_filename`, `status`, `blob_sha`. `evidence_sha256` is this digest over the
whole normalized bundle. Raw GitHub bytes are never hashed.

### 4.3 Every producer step is accounted for, in order

The jobs API lists synthetic steps too (`Set up job`, one `Run <action>@<ref>` step per `uses:`,
`Post Run …` steps, `Complete job`). The reducer does not take a "required subset" and ignore the
rest. It requires:

1. take `steps[]` **in listed order**, never re-sorted, and check `number` is unique and strictly
   increasing; otherwise `job_step_order`;
2. the ordered list of step names equals the policy's `expected_steps[]` for the job **exactly**, in
   the same order. A reordered, extra, missing, renamed or duplicated step refuses
   (`job_step_order`, `job_step_unexpected`, `job_step_missing`). A multiset match alone is not
   enough, because order is behavior;
3. **every** listed step, including `Set up job`, action, `Post` and `Complete job` steps, has
   `status = completed` and `conclusion = success`. A `skipped`, `failure`, `cancelled` or `null`
   step anywhere refuses (`job_step_not_successful`). Real data shows why this matters: in the failed
   historical `web` job the `Post Run actions/setup-node@v7` and `Post Run astral-sh/setup-uv@v7`
   steps were `skipped`, in the passing attempts they were `success`;
4. step timestamps follow the rules in the dictionary above.

Observed expected lists (from the real `97af8dd…` run, one hosted run per job). **They are
examples of the shape policy derives, not pinned values**, and they change whenever the approved
blob changes, including when OD-1 pins actions to SHAs, because action step names embed the ref:

| Job | Ordered `expected_steps[]` observed |
|---|---|
| `gate` (11 steps, numbers 1 to 8, 15, 16, 17) | `Set up job`, `Run actions/checkout@v7.0.1`, `Run astral-sh/setup-uv@v7`, `Install dependencies`, `Test`, `Ruff`, `Mypy`, `Import boundaries`, `Post Run astral-sh/setup-uv@v7`, `Post Run actions/checkout@v7.0.1`, `Complete job` |
| `web` (17 steps, numbers 1 to 13, 24 to 27) | `Set up job`, `Run actions/checkout@v7.0.1`, `Run astral-sh/setup-uv@v7`, `Run actions/setup-node@v7`, `Install web backend (standalone project — root uv.lock untouched)`, `Backend tests`, `Frontend install`, `Frontend check (tsc + vitest)`, `Frontend build`, `Production build carries no fixtures`, `Demo build`, `Demo build carries fixtures`, `No horizontal overflow at 390px`, `Post Run actions/setup-node@v7`, `Post Run astral-sh/setup-uv@v7`, `Post Run actions/checkout@v7.0.1`, `Complete job` |

Policy derives `expected_steps[]` from the approved workflow blob at admission, from a real run of
that blob, and `required_steps` (the §3 names) must appear in it in §3 order.

Step conclusions are defense in depth only: a `continue-on-error` step can still show success,
which is why AE-5 and the static guard carry the real weight.

## 5. Trusted policy object

`ci-acceptance-policy/v1`. Read per PS-1. Never from head or merge ref.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | enum | Exact version |
| `repository_id`, `repository_full_name` | id, string | Bound repository |
| `base_ref` | string | `main` |
| `workflow.id`, `.path`, `.name` | id, string, string | Approved workflow |
| `workflow_blob_sha` | sha40 | Approved content of `ci.yml`. Replaced only by a reviewed change. |
| `required_jobs[]` | list | `{context, required_steps[], expected_steps[]}` for `gate`, `web`. `expected_steps[]` is the full **ordered** step-name list from a real run of the approved blob (§4.3) |
| `isolation.trusted_source` | object or null | Where a Task 4 isolation attestation may come from. `null` means **explicitly unavailable**: no attestation can pass. Today it is `null` because Task 4 has no store |
| `source_app.id`, `.slug` | id, string | GitHub Actions app. Numeric id read from a real check run, not assumed. |
| `hosted_labels`, `hosted_runner_group` | list, string | Approved runner values |
| `max_evidence_age_seconds` | id | Proposed `300` |
| `max_clock_skew_seconds` | id | Proposed `60` |
| `max_pages` | id | Proposed `10`; reaching it refuses |
| `max_bundle_bytes` | id | Proposed `5242880` |
| `allowlist` | object | Task 7 definition. Must reuse `diff_policy` semantics, not fork them. |
| `required_protection` | object | [Readiness §7](ci-acceptance-readiness.md#7-proposed-branch-protection-configuration) |
| `human_reviewers` | list of id | Authorized code owners, numeric user ids only. Never logins, emails or display names |
| `human_only_globs` | list of string | `.github/**`, the policy file, the reducer and its tests, CODEOWNERS. Always human-only (RV-6, PS-3) |
| `source` | object | `{kind: base_commit \| installed_file, commit_sha, blob_sha}` |

## 6. Review evidence

| Field | Type | Rule | Refusal |
|---|---|---|---|
| `reviews[].id` | id | unique | `review_malformed` |
| `.user_id`, `.user_login`, `.user_type` | id, string, enum | required | `review_malformed` |
| `.state` | enum `APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`, `PENDING` | known | `review_malformed` |
| `.commit_id` | sha40 | qualifying approval equals head | `review_stale_commit` |
| `.submitted_at` | ts | not future; required unless `PENDING` | `evidence_timestamp_future`, `review_malformed` |
| `.author_association` | enum | recorded, never sufficient | none |

Effective state: for each `user_id`, order by `(submitted_at, id)`, drop `COMMENTED` and `PENDING`,
take the last. `DISMISSED` means no effect from that reviewer's earlier states.

- Any effective `CHANGES_REQUESTED`, on any commit: `review_changes_requested`.
- `human_required` is true when a path matches CODEOWNERS, the static denylist, or falls outside the
  allowlist. It then needs an effective `APPROVED` at head from a `human_reviewers` id:
  `review_required_human_missing`, `review_reviewer_unauthorized`. A path in `human_only_globs` is
  stronger: it can never reach `accept_candidate`, with or without approval (`path_requires_human`).
- A reviewer id equal to the PR author, or to any commit author or committer:
  `review_author_not_distinct`. A commit with a null GitHub identity also refuses, since it cannot
  be checked.
- The "last pusher" is not on these reads. It stays with `require_last_push_approval` unless
  readback finds a reliable source.

**Identity is numeric and never inferred.** Comparison uses GitHub numeric user ids only. A login,
email, display name, `[bot]` suffix, agent persona or `author_association` is never mapped to a
person. An id that is missing, `null`, or belongs to a deleted user (`ghost`) refuses. Two accounts
operated by one human are indistinguishable to these reads, so distinct ids show *account*
distinctness only, never *mind* distinctness; that limit is stated in the verdict and in
[readiness §10](ci-acceptance-readiness.md#10-limitations).

**Routes.** Human approval and QA provenance are two normative evidence classes (RV-1) and neither
substitutes for the other. Every changed path (both names of a rename or copy) is classified, and
the PR takes the strictest route any path requires. `accept_candidate` is possible on exactly two
routes, and **both need passing CI evidence, sufficient protection (PS-5) and a passing trusted QA
record**:

| Route | When | Additionally requires |
|---|---|---|
| **X** human-only | any path matches `human_only_globs` | nothing can help: always `path_requires_human`, never `accept_candidate` |
| **H** human-reviewed | no X path, at least one `human_required` path | an effective `APPROVED` at head from a `human_reviewers` id, distinct per RV-4 |
| **A** allowlisted | no X path, `human_required` false for every path | a passing isolation attestation (below). Zero GitHub approvals is acceptable here only because QA and isolation both passed |

Absence of an approval is never evidence of independence. Today QA (OD-4) and isolation (Task 4)
have no trusted source, so **every route refuses**: H refuses with `qa_missing` or
`qa_untrusted_source` even when a valid human approval exists, and A additionally refuses with
`isolation_unavailable`. With `required_approving_review_count = 0` GitHub itself reports nothing,
and that is the current state. No path with `human_required = true` can ever be accepted without a
qualifying approval, and no approval can stand in for QA.

### Strategy isolation attestation (proposal)

The earlier draft named `strategy_isolation_passed` as if it were a field. It is **not** a field and
nothing produces it. Task 4 owns strategy isolation and has shipped no attestation. This is a
**proposed**, fail-closed shape for the future record; it grants nothing and is not a Task 4
design.

| Field | Type | Rule | Refusal |
|---|---|---|---|
| `isolation.schema_version` | enum `strategy-isolation-attestation/v1` | exact | `isolation_malformed` |
| `isolation.source` | object | must equal policy `isolation.trusted_source`. A policy value of `null` means unavailable, so nothing matches | `isolation_unavailable`, `isolation_untrusted_source` |
| `isolation.head_sha`, `.base_sha` | sha40 | equal observed head and base | `isolation_binding_mismatch` |
| `isolation.policy_blob_sha` | sha40 | equals `policy.source.blob_sha` | `isolation_binding_mismatch` |
| `isolation.content_sha256` | hex64 | equals the §4.2 content digest of `changed_paths[]` | `isolation_binding_mismatch` |
| `isolation.verdict` | enum `pass`, `fail`, `blocked` | `pass` | `isolation_not_passed` |
| `isolation.completed_at` | ts | not future | `evidence_timestamp_future` |

`isolation: null` on route A refuses with `isolation_missing`. A bundle with the attestation
omitted, unknown-source, or bound to anything but this exact head, base, policy and content never
passes. The attestation is not required on route H.

### QA provenance

Separate from GitHub review. Provenance is a record of who did what; it proves independence only as
far as the store it came from can be trusted.

| Field | Type | Rule | Refusal |
|---|---|---|---|
| `qa.schema_version` | enum | exact | `qa_malformed` |
| `qa.source` | object | trusted store per OD-4 | `qa_untrusted_source` |
| `qa.reviewer_identity`, `.implementer_identity` | string | present, distinct | `qa_not_independent` |
| `qa.reviewer_runtime`, `.reviewer_model` | string | present | `qa_malformed` |
| `qa.review_task_id`, `.implementation_task_id` | string | present, distinct | `qa_not_independent` |
| `qa.reviewed_head_sha`, `.reviewed_base_sha` | sha40 | equal observed | `qa_head_mismatch` |
| `qa.verdict` | enum `pass`, `fail`, `blocked` | `pass` | `qa_not_passed` |
| `qa.unresolved_findings` | int ≥ 0 | `0` | `qa_open_findings` |
| `qa.completed_at` | ts | not future | `evidence_timestamp_future` |
| `qa.artifact_ref` | string | resolvable by trusted store | `qa_untrusted_source` |

`qa: null` refuses with `qa_missing` on routes H and A (every route that can accept).

| Evidence | Shows | Does not show |
|---|---|---|
| GitHub `APPROVED` at head | This account approved this commit | Independence, identity of the mind behind the account, or that the reviewer read it |
| QA provenance | A stated reviewer run examined this head | Human consent, or anything for protected paths |
| CODEOWNERS approval | An authorized owner approved | Automation eligibility on its own |

## 7. Reducer algorithm

Pure function of `(bundle, policy, now)`. No I/O, no writes. All checks run; all reasons are
reported in a stable order. Any reason means `refuse`.

1. Parse policy; `policy_missing`, `policy_malformed`, `policy_untrusted_source`,
   `policy_pr_controlled`. Parse bundle strictly (§1).
2. Check `collection`. Any collection error maps per §9.
3. Bind repository, PR, base ref. Require `head_sha_before == head_sha_after` and the same for base.
4. Refuse `protection_*` and `bypass_possible` unless required protections read as present (PS-5).
5. Bind merge. Only `head_contains_base` is accepted: require `behind_by == 0`,
   `merge_base_sha == base_sha_after` and `comparison.status` in `ahead`, `identical`. This relies on
   `main` never being rewritten, so it is valid only when protection shows **no force push and no
   deletion** on the base. If that is absent or unread, refuse (`protection_insufficient`). Mode 2
   (`merge_ref_metadata`) is refused with `merge_binding_unavailable` until a trusted real producer
   is verified and this file is amended; a bundle that fills `tested_*` fields refuses.
6. Require both workflow blobs equal policy. Route **every** `changed_paths[]` name, both
   `filename` and `previous_filename`, against `human_only_globs`, CODEOWNERS and the allowlist. A
   `.github/**`, policy, reducer or CODEOWNERS path is human-only and gives `path_requires_human`;
   no review or QA record converts it into an automated acceptance (RV-6). Refuse if the list is
   incomplete, contains an unknown status, a rename or copy without `previous_filename`, a
   `previous_filename` on any other status, or if `len(changed_paths)` differs from
   `pull_request.changed_files` (R2) or that count exceeds 3000. The R4 compare file list is not
   consulted: it is truncated at 300 files and is never a count or path source.
7. Select the run: among `runs[]` with matching `workflow_id`, `path`, `event`, `head_sha` and
   repository, take the highest `run_number`, requiring it be unique. Require any other run in the
   set to be older and `completed`.
8. Require selected run's `run_attempt == run_attempt_after`, `completed`, `success`.
9. Require jobs and check runs exactly per §4, joined by suite and id. No name-only matching.
   Account for every step, in order (§4.3).
10. Refuse any required-context entry in `commit_statuses[]`.
11. Apply time rules: `started_at ≤ completed_at`; nothing beyond `now + max_clock_skew_seconds`.
12. Reduce reviews, QA and, on route A, the isolation attestation (§6). Select the route; route X
    refuses; routes H and A need QA; H needs the human approval, A needs isolation.
13. **Stability.** Compare the `before` and `after` values of every `observed.*` pair: head, base,
    **run id set**, review digest, protection digest, policy blob. The run set is re-listed from R7
    *after* all other reads, so a new run id for the same head (not only a new attempt of a known
    run) is a race. Any difference, or an `after` value that is absent, refuses. A reducer never
    repairs a race by re-reading; a new collection yields a new bundle.
14. Emit a verdict.

```json
{"schema_version": "ci-acceptance-verdict/v1", "decision": "refuse",
 "reasons": ["check_missing"], "repository_id": 1, "pr": 1, "head_sha": "<sha40>",
 "base_sha": "<sha40>", "policy_blob_sha": "<sha40>", "evidence_sha256": "<hex64>",
 "evaluated_at": "<ts>"}
```

`decision` is `refuse` or `accept_candidate`. `reasons` is empty only for `accept_candidate`.
There is no field that authorizes a merge.

## 8. Status and conclusion truth table

| `status` | `conclusion` | Result | Code (run / job / check) |
|---|---|---|---|
| `completed` | `success` | pass | none |
| `completed` | `failure`, `cancelled`, `timed_out`, `skipped`, `neutral`, `action_required`, `stale`, `startup_failure` | refuse | `*_not_successful` |
| `completed` | `null` or unknown | refuse | `*_not_successful` |
| `queued`, `in_progress`, `waiting`, `requested`, `pending` | any | refuse | `*_not_completed` |
| absent or unknown | any | refuse | `evidence_malformed` |

A timed-out job may report `timed_out` or `cancelled`. Either refuses, so the contract does not
depend on which.

## 9. Refusal codes

| Group | Codes |
|---|---|
| Envelope | `evidence_empty`, `evidence_malformed`, `evidence_schema_unsupported`, `evidence_unknown_field`, `evidence_duplicate_key`, `evidence_stale`, `evidence_timestamp_future`, `evidence_timestamp_invalid` |
| Binding | `repository_mismatch`, `pr_not_open`, `pr_draft`, `pr_base_ref_mismatch`, `pr_fork_unsupported`, `head_sha_invalid`, `head_mismatch`, `head_race`, `base_race`, `run_list_race`, `review_race`, `protection_race`, `policy_race`, `base_not_contained`, `merge_binding_missing`, `merge_binding_mismatch`, `merge_binding_unavailable`, `changed_paths_incomplete`, `commits_incomplete` |
| Workflow and run | `workflow_identity_mismatch`, `workflow_inactive`, `workflow_blob_mismatch`, `run_missing`, `run_event_mismatch`, `run_head_mismatch`, `run_repository_mismatch`, `run_not_latest`, `run_attempt_race`, `run_not_completed`, `run_not_successful` |
| Job and check | `job_missing`, `job_duplicate`, `job_run_mismatch`, `job_not_completed`, `job_not_successful`, `job_step_missing`, `job_step_unexpected`, `job_step_order`, `job_step_not_successful`, `job_runner_unapproved`, `check_missing`, `check_duplicate`, `check_not_completed`, `check_not_successful`, `check_producer_unapproved`, `check_join_mismatch`, `status_context_present` |
| Collection | `pagination_incomplete`, `pagination_limit`, `total_count_mismatch`, `http_error`, `rate_limited`, `permission_denied`, `api_response_invalid` |
| Review | `review_malformed`, `review_stale_commit`, `review_changes_requested`, `review_author_not_distinct`, `review_required_human_missing`, `review_reviewer_unauthorized`, `qa_missing`, `qa_malformed`, `qa_untrusted_source`, `qa_head_mismatch`, `qa_not_independent`, `qa_not_passed`, `qa_open_findings`, `isolation_missing`, `isolation_unavailable`, `isolation_malformed`, `isolation_untrusted_source`, `isolation_binding_mismatch`, `isolation_not_passed` |
| Workflow guard (static, [readiness §5.4](ci-acceptance-readiness.md#54-workflow-guards-wf)) | `wf_unparseable`, `wf_command_missing`, `wf_command_order`, `wf_command_altered`, `wf_job_missing`, `wf_trigger_filtered`, `wf_trigger_missing`, `wf_forbidden_trigger`, `wf_conditional`, `wf_continue_on_error`, `wf_permissions`, `wf_timeout`, `wf_secrets_or_environment`, `wf_runner`, `wf_checkout`, `wf_env_override`, `wf_identity`, `wf_npm_script`, `wf_action_ref`, `wf_step_unexpected` |
| Policy | `policy_missing`, `policy_malformed`, `policy_untrusted_source`, `policy_pr_controlled`, `protection_unreadable`, `protection_missing`, `protection_insufficient`, `bypass_possible`, `path_requires_human` |

## 10. API reads

All reads, none writes. `{o}/{r}` is the policy repository. `per_page=100` everywhere that paginates;
follow `Link: rel="next"` until absent.

**Observation status (2026-10-31).** Reads R1 to R16 were all exercised against PR #715 or a
historical run, with two gaps: R12 returned an **empty** list (no successful non-empty review
projection was observed), and R9 was never read after a **known** partial rerun. A subsequent R2
read on 2026-10-31 observed `changed_files = 17` and `commits = 1`, matching the complete saved
17-file and one-commit lists. Rename/copy source fields remain unobserved. A four-page R10 listing
(`per_page=1`, `total_count` 4 on each page, four unique ids) succeeded, which exercises paging
and `total_count` reconciliation for check runs only. `gh` 2.86.0 rejects `--slurp` together with
`--jq`; a working collection command is `gh api ENDPOINT --paginate --slurp > FILE`, then `jq` on
the file. The first, failed attempt is kept as a compatibility finding, not hidden. This is a
characterization of how one tool behaves, not an implementation choice. A reducer collector should
not depend on `gh`.

| ID | Read | Fields used | Notes |
|---|---|---|---|
| R1 | `GET /repos/{o}/{r}` | `id`, `full_name` | Binds rename or transfer |
| R2 | `GET /repos/{o}/{r}/pulls/{n}` | `state`, `draft`, `user.id`, `base.ref`, `head.sha`, `head.ref`, `head.repo.id`, `head.repo.full_name`, `changed_files` | Read twice. `base.sha` and `merge_commit_sha` are not used for binding. `changed_files` is the authoritative path count for R13 (observed as 17 on PR #715). |
| R3 | `GET /repos/{o}/{r}/git/ref/heads/{base}` | `object.sha` | Current base tip. Read twice. |
| R4 | `GET /repos/{o}/{r}/compare/{base}...{head}` | `status`, `ahead_by`, `behind_by`, `merge_base_commit.sha` | Used for binding only. Its `files` list is truncated at 300 entries, so it is **neither the path source nor the count source**; do not project it. |
| R5 | `GET /repos/{o}/{r}/actions/workflows/ci.yml` | `id`, `path`, `name`, `state` | |
| R6 | `GET /repos/{o}/{r}/contents/.github/workflows/ci.yml?ref={sha}` | `sha`, `type` | Git blob id, at head and at base |
| R7 | `GET /repos/{o}/{r}/actions/workflows/{id}/runs?head_sha={sha}&event=pull_request` | `workflow_runs[]`, `total_count` | Includes fork-empty `pull_requests`, which refuses. **Read first for selection and again last** (`observed.run_ids_*`) |
| R8 | `GET /repos/{o}/{r}/actions/runs/{id}` | `run_attempt`, `status`, `conclusion`, `check_suite_id`, `path` | Read twice for race check |
| R9 | `GET /repos/{o}/{r}/actions/runs/{id}/attempts/{n}/jobs` | `jobs[]`, `total_count` | Pinned attempt, not the implicit latest. Observed for PR #715 attempt 1 (2 jobs) and for historical run `35925012277` attempts 1 and 2. **Attempt 2 of that run lists a `gate` job with a new job id and `run_attempt = 2`, yet its `started_at`, `completed_at`, steps and runner id are those of attempt 1, and its `started_at` is earlier than its own `created_at`; `runner_group_id` is `null` there.** That is consistent with a successful job being carried into the new attempt, but the response does not say how the rerun was requested, so partial-rerun behavior stays **UNKNOWN** (CE-11), and nothing here proves it. The reducer therefore must not require job times to follow attempt creation. |
| R10 | `GET /repos/{o}/{r}/commits/{sha}/check-runs?filter=all` | `check_runs[]`, `total_count` | Default `filter=latest` is not enough for duplicate detection |
| R11 | `GET /repos/{o}/{r}/commits/{sha}/statuses` | `context`, `creator.id` | Spoof detection only. Combined `/status` is not used; it reports `pending` with zero statuses. |
| R12 | `GET /repos/{o}/{r}/pulls/{n}/reviews` | `id`, `user`, `state`, `commit_id`, `submitted_at`, `author_association` | Read twice (`observed.reviews_digest_*`). Reviews are an unstable input: a review submitted or dismissed between reads invalidates the bundle |
| R13 | `GET /repos/{o}/{r}/pulls/{n}/files` | `filename`, `previous_filename`, `status`, `sha` | The path source, paged to exhaustion. GitHub caps this list at 3000 files: a count above 3000, a count unequal to R2 `changed_files`, a missing `previous_filename` on a rename or copy, or a `previous_filename` on any other status refuses (`changed_paths_incomplete`). No omission, rename or copy collapse, or truncation is accepted. Observed for PR #715 (one page, 17 entries, none renamed or copied, no `previous_filename` key in the saved file), so rename and copy shapes are **unobserved** |
| R14 | `GET /repos/{o}/{r}/pulls/{n}/commits` | `sha`, `author.id`, `committer.id` | Bounded by GitHub; a reached bound refuses |
| R15 | `GET /repos/{o}/{r}/branches/{base}/protection` | Fields in [readiness §7](ci-acceptance-readiness.md#7-proposed-branch-protection-configuration) | Needs admin read. 403 and 404 refuse. Read twice with R16 (`observed.protection_digest_*`); a change between reads, or a policy source that moved, invalidates the bundle |
| R16 | `GET /repos/{o}/{r}/rules/branches/{base}`, `GET /repos/{o}/{r}/rulesets` | Applicable rules, bypass actors | Rulesets read as empty on 2026-10-31 (observed) |
| R17 | `GET /repos/{o}/{r}/actions/jobs/{job_id}/logs` | none projected | Diagnostic only, never an input. The job-log endpoint is keyed by **job id**. A mistaken path `actions/runs/{id}/jobs/{id}/logs` returned 404 during the refresh: record that as a compatibility error in the wrong path, not as a permission result |

Forbidden as inputs, allowed as human diagnostics:

| Surface | Why not |
|---|---|
| `gh pr checks` | Rollup, no attempt, app or workflow identity |
| GraphQL `statusCheckRollup` | Aggregate, name-based |
| GraphQL `reviewDecision` | Aggregate, and null when no review is required |
| GraphQL `mergeable`, `mergeStateStatus` | Computed, asynchronous, dependent on protection |
| `GET /commits/{sha}/status` | Aggregate over legacy statuses |

If GraphQL is ever used for raw lists, the same rules apply: read `pageInfo.hasNextPage` to the end
and treat a top-level `errors` array with partial `data` as a refusal.

HTTP handling:

| Response | Code |
|---|---|
| Any 2xx with invalid or schema-failing body | `api_response_invalid` |
| 401, 403 without rate-limit signal, 404 on a required read | `permission_denied` |
| 403 or 429 with `Retry-After` or `X-RateLimit-Remaining: 0` | `rate_limited` |
| 3xx not followed, other 4xx, 5xx, timeout, connection error | `http_error` |
| Page bound reached | `pagination_limit` |
| Items seen differ from `total_count` | `total_count_mismatch` |
| `Link` next present but not fetched | `pagination_incomplete` |

A retry is a new collection with a new bundle. A reducer never merges pages across collections.
