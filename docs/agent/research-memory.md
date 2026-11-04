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
3. Capture publishes canonical JSON, downloads the actual MLflow artifact, verifies its SHA and
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
Sweep parents also retain only the public overflow statistic `mean_trial_sharpe`. Ordinary
windowed research retains only the current public window vocabulary. Negative results survive.

The config must round-trip exactly through the existing public config projection. Unsupported
namespaces, including `portfolio_replay` in this baseline, refuse capture and cleanup rather
than silently lose declared inputs. Adding support requires a reviewed public projection for
the producer's actual schema. Malformed raw config, model references or lineage also refuse
before a legacy reader can salvage them. Public params and grids remain opaque declared input
namespaces; the archiver does not recursively strip or reinterpret them.

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

`cleanup-check` exits zero only after actual archive/source verification; unverified evidence
emits JSON with `ok: false`, a retain-worktree error and nonzero exit. The driver invokes these
commands from the main CWD with authority DB/data/tracking values captured before scratch
exports; worker environment and `.env` files never supply their routing. Both supported cleanup
layouts must resolve exactly to the cycle's expected modern or legacy worktree path.

Acceptance evidence uses synthetic fixture databases with actual SQLite/WAL snapshots, the
actual run recorder (including capped sweep children), and actual local MLflow publication and
download. It covers negative results, inherited exclusion, reset/reused IDs, privacy sentinels,
publication/metadata crashes, retry identity, corrupt/missing/changed artifacts and source,
unsupported schemas/inputs and resource bounds. No fixture result is market evidence.
