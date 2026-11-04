# Public experiment retention before research cleanup

This bounded increment retains operational research evidence in the configured local MLflow
SQLite store. It neither imports worker registry rows nor changes gate, search-count, lifecycle,
approval or economic authority. Archives are labelled `UNVERIFIED_WORKER`, `authority=none`.
MLflow artifacts remain mutable operational evidence; their SHA receipt detects subsequent
changes. They must never become promotion authority.

The implemented modules are `operator/research_memory.py`,
`operator/research_memory_projection.py`, `tracking/research_archive.py` and the shared
`registry/read_snapshot.py`. The `research memory` CLI and trusted research-driver/queue adapters
connect this retention contract to research cleanup. No command in this group removes a worker;
the existing trusted cleanup callers require a successful fresh `cleanup-check` before removal.

## Capture contract

1. The trusted controller creates the cycle through its existing API. After the real authority
   backup into `.funnel-scratch/data/algua.db`, before starting a worker, call
   `ResearchMemory.seed(worker_root)`. This appends an immutable seed checkpoint to the existing
   `research-cycles/<cycle_id>.json`, under its existing lock. Retrying never advances the seed.
2. After the worker stops and the trusted driver records its result commit, call
   `capture(worker_root, worker_exit=actual_exit, source_commit=actual_commit)`. The bounded
   snapshot verifies the inherited run prefix before excluding its IDs. A registry reset,
   deletion, mutation or reused ID refuses capture rather than masquerading as zero experiments.
3. Capture publishes canonical JSON, reads the actual MLflow artifact, verifies its SHA and
   content, and only then appends an immutable receipt. A retry after publication but before the
   receipt recovers the same MLflow run; a different payload for the cycle refuses replacement.
4. Pass `receipt['reference']` through the existing cycle finish `evidence_ref`. This supplies
   provenance for an attempt outcome without granting the evidence any decision authority.
5. Immediately before any removal, under the caller's existing worker/queue serialization,
   require `cleanup_allowed(worker_root)`. It reads the actual stored bytes again, verifies the
   receipt and seed, and compares a fresh public snapshot with the archived payload. A metadata
   boolean or the existence of a receipt is insufficient. Any uncertainty retains the source.

The cycle metadata, MLflow database and artifact root must resolve outside the disposable worker.
Only a configured local `mlflow-sqlite` backend is supported. Disabled, remote, incompatible or
unavailable tracking refuses cleanup. Archiving failure is an operational failure, never an
economic rejection of the hypothesis. Missing seed checkpoints cannot be reconstructed after
the worker has run: retain those legacy worktrees for an explicit recovery decision.

## What survives

Only post-seed `backtest`, `walk_forward`, `sweep` and `sweep_trial` rows are projected. Each has
a cycle-scoped source reference, original local run ID, lineage, strategy name, run time,
declared input config, public metrics and existing code/config/dependency/data/snapshot/seed
provenance. Supported model pins survive as references, without resolving or copying model bytes.
Pins retain the producer's 16/16-hex digests or the existing v1 legacy 64/64 form, never mixed widths.
Valid training cutoffs retain their original bare-date, naive or aware spelling; legacy aware ISO
spellings remain accepted. This preserves metadata compatibility, not proof of model use or PIT
qualification. Archive/receipt/source SHA256 fields remain full 64-hex values.
Sweep parents also retain only the public overflow statistic `mean_trial_sharpe`. Ordinary
windowed research retains only the current public window vocabulary. Negative results survive.

Ordinary config must round-trip exactly through the existing public config projection. Unsupported
namespaces refuse capture and cleanup rather than silently lose declared inputs. Adding support
requires a reviewed public projection for the producer's actual schema. Malformed raw config,
including duplicate JSON keys at any nesting level, model references or lineage also refuse
before a legacy reader can salvage them. Public params and grids remain opaque declared input
namespaces; the archiver does not recursively strip or reinterpret them.

The existing `backtest portfolio` producer has a separate closed public input admission. Only a
complete `portfolio_replay` config with `portfolio-replay-result/v1`,
`in_sample_research_replay` and `is_forward_test=false` is accepted. Its original manifest,
general sleeve configs/identities, budgets, constraints, risk assumptions, source provenance,
costs, limitations and measured or undefined metrics survive whole. Data-only checks bind the
declared book/config digests and source metadata, then bind the outer backtest row's NULL local
strategy ID, name, provenance and IS metrics. The record has no model components, parents or
extra metrics. No engine, authored strategy, model or source artifact is loaded to validate it;
these remain unverified worker declarations, with no qualification or trading authority.

Windowed replay namespaces, incomplete/unknown result shapes, private metadata, result paths,
gate/holdout additions and inconsistent record bindings refuse capture and cleanup. Source JSON
still fits 64 KiB per field; a larger expanded replay config retains the worker even when its
original manifest was small. A valid retained portfolio input above 16 KiB is omitted whole from
campaign context, with explicit input-size coverage, while its complete archive remains intact.
The namespace-specific allowance makes the existing 8,086-byte two-sleeve pilot record eligible
by size inside the unchanged 24 KiB context. Earlier records and final whole-tail trimming still
determine inclusion; no metric controls selection and no per-idea result attribution is inferred.

No raw registry, MLflow or knowledge-vault blobs, claim credentials, gate rows, holdout metrics,
private result diagnostics or unknown overflow values are archived. Inherited rows contribute
only a bounded checkpoint digest/count, never a row export. The digest covers inherited run rows
and their known public sweep overflow; it supplies continuity evidence, never authority.

Coverage reports the retained evaluation/kind counts and actual sweep truncation markers.
Failures before the ledger recorder and unpersisted sweep variants remain `UNKNOWN`; the
archive does not invent them. Model bytes are not preserved and evaluated worktree verification
is explicitly false. Source references and declared pins are not a claim of full reproducibility.

Bounds are 20,000 projected rows, 20,000 inherited-prefix rows including known overflow,
128 MiB DB plus WAL, 64 KiB per input JSON field, 16 MiB canonical artifact and a five-second
SQLite query deadline. Exceeding a bound retains all scratch; the archive never silently clips
its input to admit deletion. The snapshot copies DB and committed WAL without opening SQLite
on the source, refuses a changing source or rollback journal, and never migrates worker data.

## Temporary model-worker retention

Until durable model artifact retention exists, verified public evidence alone cannot admit
cleanup of a model-bearing worker. This approved temporary policy retains the whole worker
when its verified current public evaluations contain any `model_refs`, whether or not an
external copy is claimed. Capture, show and bounded context/prompt reference projection still
work; `coverage.model_bytes_preserved` remains false. Retention does not copy, resolve,
deserialize or publish model bytes, or make them available to the next scratch worker.

The known default store is `<worker>/.funnel-scratch/data/models` in both modern and legacy
research layouts. Metadata-only `lstat` inspection treats every leaf object as presence,
including an empty directory, file, special file and symlink/dangling symlink. From the existing
seed's canonical worker root, scratch/data ancestors must be real stable directories. A
symlink ancestor, missing/non-directory ancestor, changed metadata or failed inspection retains
the worker. The guard never traverses store contents or classifies arbitrary unregistered bytes
elsewhere. Inherited rows keep their existing checkpoint-only representation; no extra source
registry scan or export is introduced.

`cleanup-check` reports fixed `model_references`, `model_store_present` or
`model_store_unverified` refusal reasons in its JSON error. Existing evidence failures retain
their unverified-worktree error. All refusals exit nonzero and remove nothing; ordinary verified
model-free workers with an absent known store keep the existing successful cleanup contract.
The central rule covers driver, mtime, setup and queue cleanup, including fresh fallback checks.
Queue's compatible `research_memory_unverified` skip means cleanup admission was denied; it
does not assert that every refusal is archive corruption. No worker exit, attempt outcome,
terminal queue result, search/gate count or lifecycle state is rewritten for intentional model
retention. Disk retention is deliberate; this adds no prune override or artifact-transport claim.

## Driver and cleanup entry points

These are semantic anchors in the existing driver; line numbers move with root changes.

| Entry or exit | Required integration |
| --- | --- |
| `run-research-loop.sh`, authority DB and tracking configuration capture | Preserve the authority tracking URI before worker scratch environment overrides. Construct this archive only from that trusted configuration. |
| Successful scratch DB backup, before worker launch and after cycle context verification | Seed the actual copied registry once. A failed seed prevents launch; do not mint a later watermark. |
| Worker result and trusted authored-files commit, before `record_outcomes` | Preserve the actual worker exit separately from postprocessing status. Capture/readback with that exit and result commit; supply the MLflow reference to cycle finish. Retention failure records `driver_failed`, exits nonzero, keeps scratch and publishes no completed success/candidates. |
| `cleanup_setup` EXIT trap | If a scratch source exists, require verified retention before removal. A setup failure before a valid seed/source must retain any possibly meaningful scratch; claims still reconcile through the existing controller. |
| Zero-candidate reclaim | Revalidate the stored artifact and current source immediately before both `git worktree remove` and its recursive-delete fallback. |
| Mtime backstop, modern `.runs/<stamp>` and legacy sibling worktrees | Load the original cycle/checkpoint and revalidate. Missing, stale, changed or corrupt archive/metadata means retain. Never synthesize a seed or receipt. |
| `mergeback_queue.cleanup_branch` after all candidates terminal | Hold the existing queue lock through terminal check, verification and removal. Invoke main's CLI from main CWD, with a 30-second subprocess timeout per check. Verify JSON/cycle identity as well as exit status. Revalidate before the recursive fallback; refusal/timeout leaves economic status unchanged. |
| `git worktree prune` registration-only cleanup and transcript log expiry | These do not remove experiment scratch. Transcript retention is a separate existing policy, not evidence of experiment retention. |

The research memory policy applies to research worktrees. The separate leap/forage worktree
cleanup paths do not run this research cycle/scratch protocol and are outside this increment.

The separate CLI adapter uses `registry_conn`, existing settings, `emit` and JSON errors without
importing sibling command modules or rebuilding cycle requests. Its command surface is:

```bash
uv run algua research memory seed --run ID --worker-root PATH
uv run algua research memory capture --run ID --worker-root PATH --worker-exit CODE --source-commit SHA
uv run algua research memory show --run ID
uv run algua research memory cleanup-check --run ID --worker-root PATH
```

`cleanup-check` exits zero only after actual archive/source verification and model-retention
admission; refusals emit JSON with `ok: false`, a retain-worktree error and nonzero exit. The driver invokes these
commands from the main CWD with authority DB/data/tracking values captured before scratch
exports; worker environment and `.env` files never supply their routing. Both supported cleanup
layouts must resolve exactly to the cycle's expected modern or legacy worktree path.

Acceptance evidence uses synthetic fixture databases with actual SQLite/WAL snapshots, the
actual run recorder (including capped sweep children), and actual local MLflow publication and
readback. It covers negative results, inherited exclusion, reset/reused IDs, privacy sentinels,
publication/metadata crashes, retry identity, corrupt/missing/changed artifacts and source,
unsupported schemas/inputs and resource bounds. No fixture result is market evidence.

## Optional campaign context

`research idea cycle-start --public-memory-context` adds a bounded view of retained public
evaluations to the existing hashed `request.context.public_research_memory`. It is default-off
and requires `--menu-only`, `--campaign FILE` or `--choose --choice-dir PATH`. Manual menu capture
and admission must both opt in. The research driver forwards this switch only alongside
`--campaign FILE` or `--choose-campaign`; dry runs perform no archive/model/claim operations.
The normal schedule, runtime seam and model choices are unchanged. This flag alone does not
forward memory into the primary research prompt.

```bash
uv run algua research idea cycle-start --run ID --limit 3 --menu-only --public-memory-context
uv run algua research idea cycle-start --run ID --limit 3 --campaign FILE --public-memory-context
uv run algua research idea cycle-start --run ID --limit 3 --choose --choice-dir PATH --public-memory-context
.opencode/scripts/run-research-loop.sh --choose-campaign --public-memory-context
```

The `campaign-public-memory/v1` object contains receipt references, existing attempt IDs,
lossless bounded public observations and explicit coverage. It is always `UNVERIFIED_WORKER`,
`authority=none`, `association=cycle_only`. Each observation preserves its real scratch source
reference, kind, strategy name, parents, declared model references, provenance, whole supported
inputs and existing public metrics. No model bytes are resolved. Costs, data limitations and
negative values survive when recorded. Missing information and unrecorded variant failures
remain unknown. A cycle's attempt list does not identify which idea produced each evaluation;
never infer per-family negative alpha or alter gate/search/FDR counts from this view.

The adapter resolves terminal attempt rows from the union of the offered choices' existing
`prior_evidence_ids`. It inspects the first 64 by descending actual attempt ID, deduplicates cycles
and selects at most two canonical memory receipts in that order. Conflicting archive references
for a cycle refuse. Legacy absent/non-memory references are explicit unavailable coverage;
selected missing, corrupt or incompatible evidence refuses the operation. Selection never uses
the sign or value of a metric. Within each selected cycle, records use ascending source run ID.

View bounds and deterministic omission are:

- At most two artifacts, 16 MiB each and 32 MiB combined, with no recursive parent/archive reads.
- At most two controller checkpoints, 256 KiB each and 512 KiB combined.
- Ordinary whole input objects above 4 KiB omit the entire observation first. Complete validated
  `portfolio_replay` backtest inputs have a separate 16 KiB allowance. Both are checked after
  full record validation; invalid large records refuse instead of becoming omissions. Public
  inputs are never stripped or truncated to fit, and the complete context still fits 24 KiB.
- Take the first 24 remaining observations, counting later ones as omitted for count. Remove
  whole tail observations until the complete context fits 24 KiB. Never backfill.
- Recompute coverage after each trim: retained equals included plus omitted, and omitted equals
  the disjoint input-size, count and context-size omissions. Sweep truncation markers accompany
  included sweeps only; other markers are counted as omitted.
- Fixed request/wire ceilings are 64 KiB and 25 KiB, with 4 KiB of private stderr diagnostics.
  The chooser's existing 96 KiB complete-prompt and 32 KiB reply limits still apply.

The parent captures feedback and closes its SQLite transaction before launching the fixed trusted
reader. It then checks feedback again. Enabled chooser execution has exactly one pre-choice
read batch and one post-choice revalidation batch; each has a separate 20-second work/result
acceptance deadline including startup, metadata queries, reads, validation and projection. These
are two required phases, up to 40 seconds of accepted memory work, with no retry/reset after a
failed phase. The parent checks its own absolute monotonic clock immediately after the existing
contained runner returns and again after wire/schema validation. A late result is refused even
when the runner reports `timed_out=false`. On failure there is no fallback, replacement chooser
call or claim. Complete process-group teardown/reaping remains mandatory and can exceed the
deadline under kernel scheduling or uninterruptible I/O; this is not a universal return-by-20s
guarantee or a strategy sandbox.

Artifact and checkpoint reads preflight a nonblocking, no-follow regular-file descriptor before
materializing content. They read capped chunks up to the captured size, verify file/path change
stamps and reject oversized, changed, symlink, special-file or unsupported locations. There is
no MLflow whole-file download/copy or cap-plus-one body read. The selected store, experiment,
run, receipt tags, SHA, envelope, original seed and controller context are verified. Lookup
creates no missing store, experiment or run; publication remains a separate producer operation.

MLflow metadata lookup uses a private DB/WAL snapshot to avoid source-side SQLite SHM writes,
with a 128 MiB source-size preflight ceiling per lookup and a five-second SQL query deadline.
Those are distinct from strict artifact/checkpoint read-byte limits: concurrent database growth
can increase copy I/O before the change check refuses. The outer batch deadline includes that
work. No claim is made that all filesystem/database/kernel I/O fits the 32 MiB artifact budget.

After choosing, the selected receipts and deterministic context must match the captured snapshot
before the existing controller/CAS admits claims. The exact five-field choice grammar, offered
`prior_evidence_ids`, ranking, resource limits and authority counts are unchanged. Setup and
manual recovery carry only the original immutable memory snapshot from the correctly bound
checkpoint while independently recomputing every base source/data field. Setup does not fetch a
newer archive. An already started chooser refuses before another archive/model call.

Domain refusals retain the standard JSON envelope, exit 1, `code=invalid_input`,
`retryable=false`, and `error=public_memory_context:<reason>`. This opt-in context demonstrates
retained-memory plumbing; fixture choices do not prove causal autonomous learning, 100 recorded
experiments, ten unattended cycles, paper readiness or profitable alpha.

## Optional primary research prompt

The driver has a separate default-off `--research-public-memory-context` flag. It requires both
`--public-memory-context` and an explicit `--choose-campaign` or `--campaign FILE`; it enables
neither prerequisite implicitly. For example:

```bash
.opencode/scripts/run-research-loop.sh --choose-campaign --public-memory-context --research-public-memory-context
```

For a running admission with nonempty new claims, the driver forwards only the already-admitted
`request.context.public_research_memory`. A pure helper checks the successful running response,
cycle/database/menu bindings, the complete existing selection and exact distinct claimed IDs.
It never reads the archive again. The canonical `research-public-memory/v1` wrapper contains
exactly `schema_version`, `research_cycle_id`, `menu_id`, `snapshot_sha256` and `snapshot`.
The snapshot remains unchanged; the digest covers its canonical UTF-8 JSON. These bindings are
neither a signature nor evidence that a model received or used the data.

The raw admission input is capped at 1 MiB before strict forwarding JSON parsing; the snapshot
and complete wrapper are capped at 24 KiB and 25 KiB respectively. The enabled complete GOAL is
capped at 96 KiB UTF-8, including the single final newline written to the prompt file. Excess or
invalid input refuses setup before scratch creation or worker launch. Nothing is truncated,
silently omitted, reselected or requeried. Existing cycle reconciliation handles those claims;
no worker result or economic verdict is invented. Current claim credentials are never forwarded:
an exact credential collision inside an opaque public value refuses the whole operation.

The old GOAL remains its verbatim prefix. One explicitly untrusted data block labels the snapshot
`UNVERIFIED_WORKER`, `authority=none`, `cycle_only`, including truthful unavailable coverage.
It supplies no qualification, trial/FDR count, per-idea evaluation attribution or permission to
replace the claimed hypothesis. The primary instruction asks existing author/interpret tasks to
receive the same wrapper unchanged when relevant. Actual author task receipt and use require
separate real session evidence; fixture prompt tests prove only the deterministic primary input.

With the flag off, the GOAL bytes are unchanged and neither forwarding helper runs. Dry runs do
not claim, query archives, write a prompt or launch research. Empty/restarted cycles keep their
existing behavior. The original worker pipeline exit, trailer grammar, gates, resources,
retention and publication paths are unchanged. This opt-in adds no third memory read batch,
agent tool, model setting or scheduled service.
