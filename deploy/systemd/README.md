# Algua operator — systemd packaging

For the staged research-only VPS profile, use the [VPS research operating runbook](research-vps.md).

A `oneshot` service fired by a `timer` drives the always-on **paper** operator (#486). Each firing
runs `algua operator run`, which decides — via the XNYS calendar gate, a per-session idempotency
marker, and a git-dir-anchored run lock — whether to actually run the wrapped driver command. A
weekend/holiday firing, a re-fire of a session already completed, or an overlap with a still-running
sibling all no-op cleanly.

- `algua-paper.{service,timer}` — the paper trading cycle (`--job paper`), fired **every 20 minutes
  at :07/:27/:47**. It trades at most once per XNYS session — the per-session marker no-ops every
  later firing — so the repetition exists purely to RETRY: a firing that loses `operator.lock` to a
  merge-back drain, or a `deferred: true` reconcile cycle, is re-attempted 20 minutes later instead
  of waiting a day (`session_gate` only ever targets the most-recent COMPLETED session, so a missed
  session is otherwise lost outright, not deferred). The `:07` offset keeps every firing off the
  drainer's `:00/:30` grid. **Daily on purpose, NOT weekdays-only**: the operator wrapper's XNYS
  calendar gate no-ops non-session firings, so the timer never re-encodes the exchange calendar.
- `algua-research.{service,timer}` — the autonomous **research producer** cycle at **factory
  cadence: every 2 hours** (12/day; see
  `docs/superpowers/specs/2026-08-10-strategy-factory-design.md`): an agent ideates → authors
  → backtests/walk-forwards/sweeps → gates (preview `research promote`) up to `candidate` in an
  explore-isolated worktree. See "Autonomous research loop" below.
- `algua-mergeback-drain.{service,timer}` — the **research consumer** (factory slice 3): every 30
  minutes, drains exactly one eligible candidate off the durable `data/mergeback-queue.json` (the
  producer enqueues into it — see "Autonomous research loop" below) and runs the REAL,
  authoritative `paper merge-back` through `algua operator lock-run`, which shares `operator.lock`
  with the paper tick. Trusted plumbing, no LLM, no sandbox. See "Auto merge-back (factory
  slice 3)" below.
- `algua-leap.{service,timer}` — inspirations → structured hypotheses, every 2h at `:30` (between
  research runs), but only when the idea pool is below its refill trigger. See "Ideation engine
  (forage + leap)" below.
- `algua-forage.{service,timer}` — web-search inspiration foraging into `kb/inspirations/`, daily
  `03:00 UTC`. See "Ideation engine (forage + leap)" below.

## Install

Assumes the app is deployed at `/opt/algua` with its virtualenv at `/opt/algua/.venv`, and that
`algua` is on `PATH` for the operator's subprocess (a `.venv/bin` entry or a symlink).

1. Copy the environment file and fill it in (mode `0600`, it holds secrets):

   ```sh
   sudo install -D -m 0600 deploy/systemd/algua.env.example /etc/algua/algua.env
   sudo editor /etc/algua/algua.env
   ```

2. Nothing to set for data (#556): the paper unit runs `algua paper run-all --refresh`, which
   resolves-or-ingests the lane's bars each session — the union of every tickable strategy's
   gate-bound universe plus ledger-held and broker-held symbols, each required to carry its newest
   bar on the session the tick decides on and each universe symbol its history floor; a
   missing/lagging/short symbol fails the cycle closed and the next fire retries. The trailing
   command in `ExecStart` **must exactly match** the `paper` job's argv template
   (`algua paper run-all --refresh`) — an exact-arity structural match — or the wrapper fail-closes
   with `command_mismatch`. `ALGUA_BARS_REFRESH_PROVIDER` (default `yfinance`) picks the provider.
   For a replay or incident forensics run `algua paper run-all --snapshot <id>` by hand, outside
   the timer.

3. Copy the units into place and enable the timer:

   ```sh
   sudo cp deploy/systemd/algua-paper.service deploy/systemd/algua-paper.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now algua-paper.timer
   ```

Inspect with `systemctl list-timers 'algua-*'` and `journalctl -u algua-paper.service`.

## Install as user units (single-box, no /opt deploy)

When the repo lives in a home directory (no `/opt/algua`, no root), install the same units as
**systemd user units** with the idempotent installer:

```sh
deploy/systemd/install-user-units.sh            # render + install + daemon-reload
deploy/systemd/install-user-units.sh --dry-run  # print the rendered units, write nothing
```

For each of `algua-research.{service,timer,path}`, `algua-paper.{service,timer}`,
`algua-mergeback-drain.{service,timer}`, `algua-forage.{service,timer}`,
`algua-leap.{service,timer}`
it renders the `/opt/algua` template to `~/.config/systemd/user/<name>`, replacing `/opt/algua`
with the actual repo root (resolved from the script's own location; a root containing whitespace
or any character outside `[A-Za-z0-9/._-]` fails closed — plain substitution can't safely render
it into a unit), dropping `EnvironmentFile=/etc/algua/algua.env` when that file is missing or
unreadable (keeping the credential-scrubbing `UnsetEnvironment=` lines), and rewriting
`WantedBy=multi-user.target` → `default.target` (timers keep `timers.target`). It preflights
`systemctl --user` reachability before writing anything, stages ALL rendered units and moves them
into place together (render failures abort before any install; the moves themselves are per-unit
atomic, not transactional across units — recovery from a mid-move failure is re-running the
idempotent installer), then runs one `systemctl --user daemon-reload` and **prints** — never
executes — the per-unit enable commands. Re-running is safe: the all-then-move install means the
live unit set is never left half-updated, and the installed units can never drift from the repo
templates for longer than one re-run. Use `loginctl enable-linger <user>` so user timers fire without an active login, and
inspect with `systemctl --user list-timers 'algua-*'` / `journalctl --user -u algua-research.service`.

**Factory cadence (slice 1).** Research fires **every 2h** (`OnCalendar=*-*-* 00/2:00:00 UTC`,
overlaps skip via the launcher's non-blocking flock); paper fires **every 20 minutes at :07/:27/:47
UTC** and trades at most once per session (the calendar gate no-ops non-sessions and the marker
no-ops repeats — do NOT make it weekdays-only, and do NOT collapse it back to a single daily fire:
that is the retry budget for a lost `operator.lock` race); the merge-back drainer fires **every 30
minutes** at `:00/:30`, deliberately disjoint from the paper grid. Enable ALL THREE so paper
evidence starts accruing the moment the first strategy reaches the book.

**Mutual exclusion around the paper tick (#316, closed by factory slice 3).** `paper merge-back`
and `paper trade-tick`/`run-all` mutate the same shared checkout + registry. When the drainer
invokes merge-back through `algua operator lock-run` (its only invocation path — see "Auto
merge-back" below), this is **real kernel-enforced mutual exclusion**: `lock-run` takes the SAME
`operator.lock` `operator run --job paper` takes, so the two can never run concurrently — a
contended attempt is a benign no-op that retries next cycle, never a race. This guarantee is
per-invocation-path, not per-command: a HUMAN running `paper merge-back` directly (bypassing
`lock-run`) still relies on operator discipline, exactly as before — do not run a direct manual
`paper merge-back` while a paper tick may fire (every 20 minutes; in practice, the hours right
after the US close, when the session is newly complete and the tick has not yet recorded it).

## Operator-invoked paper release (deployment contract requires owner review)

`deploy/scripts/release-paper.py` consumes **already materialized, operator-approved** application
releases. It does not build packages, merge/push Git, run intake, enable units, or grant deployment
permission. This is a paper-only supervisor release entry, distinct from a strategy's frozen planner
manifest. The account/path/unit contract below must be reviewed and installed by the owner before
use; adding this script does not activate it or establish production acceptance.

### Draft unprivileged application builder

`deploy/scripts/build-paper-release.py` prepares an **untrusted** artifact, never an approval:

```sh
python deploy/scripts/build-paper-release.py --repository /trusted/source --commit <exact-40-hex-commit> \
  --output /owned/application --descriptor /owned/application-spec.json
```

Run Python 3.12 as a nonroot user in a disposable build environment with `uv` available. The
descriptor is a sidecar outside the application, using the existing `target`/`previous` shape
documented below. The new application profile fetches only the selected commit, uses a clean `main` sparse
checkout omitting only the seven enumerated non-runtime `.claude/skills` aliases, installs with
`uv sync --locked --no-editable`, and inventories the materialized runtime after copying interpreter
links. Fresh Git export and a replacement build environment do not copy local untracked `.env`,
credentials, runtime databases or caches. Build hooks execute only as the unprivileged builder.

`application-runtime.json` records the builder, interpreter and external standard-library source
identity. This is **not** the protected frozen-planner environment profile or a self-contained OS/
stdlib closure. Executable wheel startup shims remain locked/inventory-bound code, not statically
certified safe. The consumer does not verify external base-runtime state; the owner must separately
adopt a compatible trusted base and root-controlled artifact. No ownership repair, authority DB
migration, signing, selection, activation or compatibility approval is performed by the builder.

### Draft opt-in Actions producer (owner review required)

`paper-application-artifact.yml` adds only `workflow_dispatch`, restricted to `main`. After owner
review, dispatch it explicitly with a full source SHA; it never runs on push, PR or a schedule.
The candidate must be an ancestor of fetched `main`. The recipe comes separately from the
[workflow's own commit](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts),
not candidate source. Read-only checkout credentials and runner tokens stay outside the disposable
nonroot build container, which receives only sanitized source, read-only builder/uv and output space.

The producer uploads a tar archive, the unchanged consumer descriptor, provenance and checksums.
It ignores build-produced `.git` before traversal and reconstructs clean sparse metadata from the
verified input, with hooks disabled and fsmonitor false. Runtime file bytes remain inventory-bound;
archive modes preserve executability without granting ownership or approval. The tar retains these
modes through [artifact upload](https://github.com/actions/upload-artifact#permission-loss).
Owner adoption, compatible approved Python/OS base, release compatibility and activation remain
separate prerequisites. Linux CI output alone proves no VPS compatibility. This dependent draft
does not enable deployment, signing, secrets, automatic runs or any persistent-host execution.

### Draft conditional artifact adoption (separate owner decision)

`deploy/scripts/adopt-paper-artifact.py` downloads and materializes files only after an explicit
root-controlled approval request. Install the reviewed entry, its sibling `paper_archive.py` and
trusted `algua` helpers under root-controlled parents, separately from the candidate artifact:

```sh
/root-controlled/python3 -I -S /root-controlled/operator/deploy/scripts/adopt-paper-artifact.py \
  /root-controlled/artifact-approval.json
```

The helper is compiled directly from checked source bytes; adjacent bytecode caches are ignored.
The bounded original approval bytes are parsed and hashed once, so a later request-file rewrite
cannot attribute an earlier adoption to the replacement request.

An optional final numeric argument identifies an already-open credential file descriptor for
private GitHub access. The entry does not discover credentials or run `gh`; credential values and
signed storage URLs must remain private. Authorization is sent only to the fixed
`api.github.com/repos/its-nix/algua` API, never to the HTTPS storage redirect. No workflow is started.

The closed JSON request contains exactly these fields:

```json
{
  "schema": "algua-paper-adoption/v1",
  "approval_ref": "owner-reviewed-exact-artifact-decision",
  "repository_id": 123, "run_id": 234, "run_attempt": 1, "artifact_id": 345,
  "artifact_sha256": "<64 lowercase hex>", "recipe_commit": "<40 lowercase hex>",
  "source_commit": "<40 lowercase hex>", "application_digest": "<64 lowercase hex>",
  "provenance_sha256": "<64 lowercase hex>", "destination": "/root-controlled/fresh-bundle",
  "base": {
    "approval_ref": "separately-reviewed-compatible-base-decision",
    "ci_image": "<exact approved producer image reference>",
    "python_path": "/approved/base/python3.12", "python_sha256": "<64 lowercase hex>",
    "stdlib_path": "/approved/base/lib/python3.12", "stdlib_py_digest": "<64 lowercase hex>",
    "os_release_sha256": "<64 lowercase hex>", "machine": "x86_64", "libc": "glibc 2.39"
  }
}
```

These are owner-supplied identities, not permissions inferred from artifact ownership. Exact run,
attempt, successful manual main workflow, recipe/source, immutable service artifact digest and
provenance must agree. The installed base must already be root-controlled and match the approved
binary, standard-library Python sources, OS, architecture and libc observations. Every stdlib
entry, including native extensions and caches, must be root-controlled. These checks verify
declared identities without executing the base or artifact. It is not a native-library closure or
a portability proof. The observed VPS research Python `/usr` 3.12.3 differs from CI 3.12.12 Bookworm;
no compatible approved base has been proved, and separate `/usr/local` bases were not inspected.

The standalone Linux entry bounds the storage connection/transfer to 2 GiB and a scoped 300-second
wall timer, with progress reads and deadline checks. Each HTTP request has a 30-second socket timeout.
Extraction accepts only the four producer sidecars and regular tar files/directories, with no
duplicate/traversal/link/special entries, at most 100,000 tar members, 512 MiB per file and 4 GiB
total file payload. Checksums, the complete runtime inventory and approved reconstructed Git
metadata digest are checked as data; no artifact Git, Python, hooks or strategy code runs.
A private sibling stage is atomically published without replacement as one fresh bundle containing
`release/`, `release-spec.json`, original `provenance.json` and `adoption.json`. Existing destinations
and racing writers are preserved; failure removes only the private stage. The descriptor retains
the existing consumer shape/digest and binds its path to `release/` in that bundle. Adoption does
not approve release compatibility, mint an approval, migrate a DB, sign, activate or change units.
The separately reviewed release request below remains necessary. Only synthetic disposable adoption
is tested; real Actions delivery, compatible-base adoption and paper activation remain unproved.

Required installation:

- Run the trusted, separately installed operator entry with a root-controlled Python 3.12 interpreter
  using `-I -S`. The entry, its `algua` helpers and every control-path parent must be root-owned and
  nonwritable by the runtime. Never run the administrative entry from the mutable research checkout.
- Both materialized releases, including their Git metadata and `.venv`, must be root-controlled and
  nonwritable by the runtime. They must be clean independent Git checkouts on `main`, with no `.env`,
  symlinks or special files. Full file checksums exclude `.git`; commit and locked-dependency hashes
  are checked separately. Only `.git/operator.lock` and `.git/merge_back.lock` are runtime-owned
  `0600` operational files; absent lock files are created with those permissions, never artifact
  files repaired or ownership changed into approval.
- `current` is an existing root-owned symlink beneath root-controlled parents, used **only for paper**.
  The paper service's `WorkingDirectory` is that literal path. Its canonical `ExecStart` is
  `/usr/bin/env <bindings-below> <current>/.venv/bin/algua operator run --job paper -- algua paper run-all --refresh`.
- The drainer uses a **separate mutable authority checkout**, with `WorkingDirectory` equal to its
  literal configured path and
  `ExecStart=/usr/bin/env <bindings-below> <authority>/.opencode/scripts/drain-mergeback-queue.sh`.
  Both services explicitly declare the same nonroot `User`, matching `runtime_user`. The existing
  installer renders both services against one physical checkout and therefore does **not** satisfy
  this release contract. Mismatches refuse; this entry never rewrites units or the installer.
- The database, shared artifact/data store and root-controlled evidence location stay outside the
  immutable releases. Existing financial permissions and credentials remain configured separately;
  verification receives no inherited credentials. No live/research unit may follow this paper selector.

Both unit commands must start with the root-controlled `/usr/bin/env` and these assignments in
this order, before the executable. `BASE` is the literal `current` path for paper or
`authority_checkout` for the drainer; `CACHE` is `<data_dir>/paper-runtime/paper` or
`<data_dir>/paper-runtime/drainer`. The owner must provision these external cache directories for
the configured runtime user. The prefix overrides conflicting `EnvironmentFile` values and binds
the inner bare `algua` command and Python imports to the same program checked for release.

```text
PATH=BASE/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONPATH=BASE
ALGUA_DB_PATH=<database> ALGUA_DATA_DIR=<data_dir>
PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
XDG_CACHE_HOME=CACHE/cache NUMBA_CACHE_DIR=CACHE/numba MPLCONFIGDIR=CACHE/matplotlib TMPDIR=CACHE/tmp
GIT_OPTIONAL_LOCKS=0
```

For paper, append `GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0=<previous.path> GIT_CONFIG_KEY_1=safe.directory
GIT_CONFIG_VALUE_1=<target.path>`. For the drainer, append `GIT_CONFIG_COUNT=1
GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0=<authority_checkout>`. These are exact approved
physical roots; the selector alias alone does not satisfy Git ownership checks. Release paths use
the same plain absolute path vocabulary as the other configured unit paths.

These are one argv prefix, not shell commands or variable-expansion instructions. Existing
financial credentials remain supplied through the already configured service environment.
Private verification similarly sets `PYTHONPATH` to the exact physical approved release and uses
its own private registry/cache paths; editable imports outside that release cannot supply its core.

Supply a root-owned regular JSON request, not group/other writable, with these exact keys:

```text
schema: "algua-paper-release/v1"
approval_ref: owner's release approval reference
current, authority_checkout, database, data_dir, evidence: absolute configured paths
systemd_scope: "system" or "user" (the already configured manager)
runtime_user: existing nonroot User declared by both services
target, previous: {path, commit, lock_sha256, files, digest}
compatibility: {schema_sha256, target_digest, previous_digest, rollback_approved, approval_ref}
frozen_manifests: complete nonempty list of active frozen PAPER/FORWARD_TESTED manifest digests
```

`files` maps **every regular release file except `.git/**`** to its SHA-256. `lock_sha256` equals
the `uv.lock` checksum. `digest` is SHA-256 of UTF-8 JSON containing `commit`, `lock_sha256` and
`files`, with sorted keys, compact separators and no nonfinite numbers. This is an operational
application checksum, not a replacement for strategy identity or planner provenance. The request
is bounded to 16 MiB. `previous` is the currently selected approved release, not an inferred ancestor.

The compatibility approval binds **both application digests** and the observed schema fingerprint:
SHA-256 of compact sorted-key JSON `[user_version, rows]`, where rows are
`SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name`. The fingerprint detects drift;
its equality is **not proof of compatibility**. The owner must separately review compatibility and
explicitly set `rollback_approved` for the known-good previous release. No version-number inference,
registry restore, epoch rewrite or trigger removal is performed.

After those prerequisites, an operator may invoke the trusted installed entry:

```sh
/root-controlled/python3 -I -S /root-controlled/operator/deploy/scripts/release-paper.py /root-controlled/request.json
# Explicit recovery of an interrupted invocation using the SAME approved request and receipt:
/root-controlled/python3 -I -S /root-controlled/operator/deploy/scripts/release-paper.py /root-controlled/request.json --recover
```

The entry holds the existing operator and merge-back locks on the paper releases and authority
checkout, stops only paper/drainer timers and refuses an active service without killing it. It records
and fsyncs selection intent, atomically selects the approved release, then runs existing
`deployment verify`, `fleet health` and `ops machine-health` as the configured nonroot runtime User.
These checks use a private consistent registry copy: their existing migration paths cannot alter the
real registry, and a schema change on the copy refuses. Private DB/cache ownership is prepared for
the runtime; its environment contains only the explicit data paths and local execution/cache settings.
Private checks trust only their exact approved physical release path through a per-command Git
`safe.directory` setting; branch/cleanliness checks remain active. Active legacy, working-tree or unmigrated paper
tenants refuse this frozen-paper release entry; it does not migrate or reactivate them.
The paper loop must be observed `ok`/`idle`; unrelated research incidents do not veto this paper check.
Existing fleet and frozen-content checks remain binding. No order or broker/account call is launched.

Only timers that were already active are restarted after healthy verification. An ordinary failed
release returns nonzero even after successful, explicitly compatible recovery. Unknown compatibility
or failed recovery never resumes scheduling. A failed stop or unverifiable quiescence is not reported
as a stopped lane: its durable incomplete phase requires operator attention. An already running
service is never killed by this entry. `--recover` uses the original request-bound
receipt and rechecks the previous release before resuming. Do not treat a successful fixture run as
paper trading, elapsed forward evidence, an automatic merger, or live authorization.

## Schema v48 (Story 1.3d) is forward-only

Story 1.3d's registry schema (v48) adds the append-only `frozen_invocations` table, the
`tick_snapshots.frozen_invocation_id` column and triggers that refuse a frozen deployment's tick
unless it links that tick's successful final planner invocation. Rolling back to pre-1.3d code on a
v48 database leaves all of this in place (the older `migrate()` re-stamps `user_version` but drops
nothing), and that code never writes the link. Any frozen deployment's tick would then be refused
by `tick_snapshots_frozen_link` **after that tenant's orders are sent**, aborting `run-all`. Legacy
and working-tree ticks are unaffected.

Before a rollback, keep the paper and merge-back services stopped and verify that the target
release supports the deployed database schema. For frozen deployments, choose a supported path:

- **Retire every frozen deployment.** `algua registry transition <name> --to retired` retires the
  strategy's active deployment. It first drains the strategy's resting paper orders, so it needs
  the paper credentials and a reachable paper venue (run it from this main checkout, while the
  paper and merge-back services are idle). List the strategies that have one with:

  ```sql
  SELECT s.name FROM strategy_deployments d
  JOIN deployment_artifacts x ON x.id = d.artifact_id
  JOIN strategies s ON s.id = d.strategy_id
  WHERE x.source_kind = 'frozen' AND d.retired_at IS NULL;
  ```

- **Keep the lane stopped and repair forward.** If schema-compatible rollback cannot be
  established, retain the database, frozen artifacts and invocation evidence, then deploy a
  reviewed compatible release before resuming operation.

Retirement alone does not establish compatibility with every schema change. Preserve the
`tick_snapshots_frozen_link` trigger and the other integrity guards throughout recovery; disabling
them is not a rollback procedure.

## Why the wrapper, not just the timer

**Calendar gate.** The timer fires every calendar day at a fixed wall-clock time, but the market is
open only on XNYS sessions. `algua operator run` resolves the most-recent *completed* XNYS session as
of now (respecting early/half-day closes) and no-ops when there is none (weekend, holiday, or before
that day's close). This makes the exact `OnCalendar=` time non-critical and immune to DST drift — the
gate, not the clock, decides whether a cycle acts.

`Persistent=true` covers a **missed window after downtime** — if the box was off across the scheduled
fire, systemd runs the unit once on next boot to cover the window it slept through. It is **NOT** a
failed-run retry mechanism: a unit that ran and exited non-zero is not re-executed. Retry of a
failed/crashed session comes solely from the marker being left unwritten — the **next** scheduled fire
re-attempts (the gate is `due` again).

**Session-idempotency marker.** `operator_sessions.json`, written beside the DB
(`$(dirname ALGUA_DB_PATH)`), records the last session each job ran (an enriched audit entry binding
the full canonical argv). A re-fire of a session already completed is suppressed (`already_ran`). The
marker is written ONLY after a run the job's completion predicate accepts — NOT bare `rc==0`: a
`deferred:true` cycle (the driver chose not to trade) exits 0 but is left unrecorded so the next fire
retries. A failed run likewise leaves it untouched, with the driver's own ingest-and-reconcile-before-
trade as the double-trade backstop. Marker reads **FAIL CLOSED**: an absent marker is benign (run), but
a present-but-corrupt marker (`marker_corrupt`) alerts and exits 1 — the operator must inspect/repair
the file before the loop resumes, so "must not run twice" holds unconditionally.

**Run lock (`operator.lock`).** Acquired at the repo's per-worktree git dir (not `db_path.parent`),
non-blocking, held across gate → run → record. It serializes overlapping fires (a slow cycle still
running when the next window opens) and — once the deferred research job lands — run-all vs merge-back.
An overlap within the job's expected duration is a benign no-op (`reason:"locked"`, exit 0, no alert);
a holder wedged **past** that grace is surfaced via an `operator_lock_stuck` alert (the fleet would
otherwise quietly stop trading). The kernel releases the flock on holder death, so a hard kill never
wedges the next fire.

**Direct-invocation residual risk.** `operator.lock` serializes runs that go through `operator run`;
it does **not** guard a *direct* `algua paper run-all` / `paper trade-tick` / (future) `merge-back`
that bypasses the wrapper. During the always-on window, **direct/manual invocation of these drivers is
prohibited by operator policy** — an operator-discipline contract (matching the `paper run-all`
docstring), not a kernel-level mutual-exclusion guarantee. The deeper backstop is run-all's
ingest-and-reconcile-before-trade: an accidental overlap reconciles/defers, it does not
blind-double-trade.

**Alert hook.** When a run fails, the wrapper classifies it (`global_halt` / `breach` / `job_failed`)
and calls the operator alert hook; anomalies (`marker_corrupt`, `calendar_out_of_bounds`,
`operator_lock_stuck`, `session_gap`, `completion_unconfirmed`, `unknown_job`, `command_mismatch`) fire
their own alert kinds. Every alert always lands as a structured `operator_alert` log record; if
`ALGUA_ALERT_CMD` is set, the alert JSON is also piped to that command — **split with `shlex` and run
with `shell=False` under a 10s timeout** (no shell interpolation of the payload; wrap any
pipe/redirect in a script). Delivery is best-effort and never crashes the run. A `calendar_out_of_bounds`
alert means the exchange calendar has run past its precomputed horizon — **refresh the calendar /
upgrade `exchange-calendars`**.

## Autonomous research loop

`algua-research.{service,timer}` runs the candidate **producer** — the piece that was "out of scope"
when only the paper operator shipped. It uses the **explore-isolated** topology. Each firing runs
`.opencode/scripts/run-research-loop.sh`, which:

- creates a throwaway git worktree on `research-run/<stamp>` so the **code** the agent authors never
  touches your working tree or `main`;
- seeds a **per-run scratch funnel** from the real registry via sqlite's consistent online backup, and
  wires the agent to it — `ALGUA_DB_PATH`, `ALGUA_KNOWLEDGE_DIR`, `ALGUA_MLFLOW_TRACKING_URI` point at
  scratch; only `ALGUA_DATA_DIR` (the immutable snapshots) is the real one, shared read-only. So the
  agent's walk-forward/sweep/promote see the REAL accumulated breadth and burned holdouts (a
  realistic pass/fail **preview**), but every write lands on the copy — **exploration can never mutate
  the authoritative breadth / gate / holdout rows**, and wasted search never inflates the real DSR
  trial count;
- runs `opencode run` (bounded by `TIMEOUT`, default 45m) to drive ideate → author → walk-forward/sweep →
  `research promote` (preview) up to `candidate`, then writes a report to `kb/research-runs/<stamp>.md`
  on the branch, ending in a machine-readable trailer naming, per hypothesis, its verdict and — for a
  passed preview — a `merge_back` object (strategy/universe/window). The launcher validates each
  `merge_back` (branch is NEVER trusted from the trailer; strategy must match a module THIS run's own
  commit actually added) and enqueues every valid one to `data/mergeback-queue.json` for the automated
  drainer (factory slice 3) to run for real — see "Auto merge-back" below.

**Why isolated and not "direct authoritative".** `opencode run` runs unsandboxed and could edit
`promotion.py`/`gates.py` in its mutable worktree; strategy code and gate code are the
same Python package, so if the agent ran against the real funnel it could execute altered gate logic
against the real registry. CODEOWNERS only gates *merges to main*, not a live agent's local execution.
Exploration therefore runs on a throwaway copy, and the **only** path to the authoritative funnel is
`paper merge-back` — whose diff-policy rejects gate-core edits *before* the merge and whose promote runs
trusted (main + allowlisted diff) code. That is the trusted reconciler.

**Prerequisites.** `opencode` must be on `PATH` and **authenticated** for the user the unit runs as
(`opencode run` is invoked headless with `(the MCP sandbox bypass is gone; see forage.sh)` inside the isolated
worktree). Enable with `sudo systemctl enable --now algua-research.timer`.

**The authoritative step is now automatic (factory slice 3).** A passed *preview* is a candidate,
not a promotion. The launcher enqueues every valid `merge_back` it parses from the report trailer;
the merge-back drainer (`algua-mergeback-drain.timer`, every 30m) runs the REAL
`paper merge-back --branch research-run/<stamp> --strategy <name> --universe <u> --start D --end D`
for it through `algua operator lock-run`. That is the trusted, authoritative promote (real recorded
breadth, real single-use holdout burn) + gated code merge + paper intake. The agent
**cannot go live** (human-signed cryptographic wall) and cannot merge the CODEOWNERS-protected
integrity files. A human can still force one through immediately instead of waiting for the next
drain cycle: `uv run algua paper merge-back --branch <b> --strategy <s> --universe <u> --start D
--end D` (see "Direct-invocation residual risk" above for why that bypasses the shared lock).

**Cadence and the trial count.** The timer runs at **factory cadence: every 2h, 12 runs/day**
(`OnCalendar=*-*-* 00/2:00:00 UTC`). That rate is safe for the funnel *because* exploration is
scratch: a cycle's `research promote` is a preview that records NO breadth and burns NO holdout on
the authoritative funnel. Breadth is recorded only by an actual `paper merge-back` run, and every
recorded sweep raises the DSR trial count (max of a strategy's own lifetime combos and the
funnel-wide combos in the 90-day window) that the advisory deflated-Sharpe signal is computed
against for ALL future strategies. So the producer can run as often as configured; the drainer
paces the *merge-backs* (one per 30-minute cycle). The holdout is single-use *per strategy*, so the
loop keeps authoring new strategies on the existing snapshot. The real per-cycle costs are compute/API (tune `N_HYPOTHESES` / `TIMEOUT` in
the env file; provider rate-limit hits are recorded per run and are recorded per run in the
digest — see below) and disk (auto-pruned; see below).

**Run digest (feedback contract, slice 1; schema widened in slice 3).** After **every firing** — a
completed run (success, agent failure, or timeout), a lock-skip, or a setup failure — the launcher
appends **one JSON line** to the durable, authority-side digest at `data/research-runs.jsonl`
(beside the authoritative DB; `ALGUA_RESEARCH_DIGEST_PATH` overrides). Fields: `stamp`, `branch`
(`null` if the run branch was never created), `thesis`, `outcome` (`"completed"` |
`"skipped_lock"` | `"setup_failed"`), `exit_code`, `timed_out` (bool, `timeout` exit 124), `wall_s`,
`n_strategy_files` (strategy files in the driver's commit), `hypotheses` — a list of
`{"title", "verdict", "merge_back"}` objects (slice 3; an OLDER digest line's `hypotheses` are
bare title strings — both shapes are read by the anti-dup context builder, no historical rewrite),
`preview_gate` (`{"passed": bool, "failed_checks": [...]}` or `null`, UNCHANGED — the cheap
aggregate "did anything look promising" signal, kept alongside the new per-hypothesis `verdict`),
`trailer_parse_error` (bool for completed runs), `rate_limited` (bool, grepped from the in-worktree
agent log), `report` (`research-run/<stamp>:kb/research-runs/<stamp>.md` — migrated off the repo
root in slice 3; see "Auto merge-back" for why). A skipped/setup-failed firing produces a line with
`outcome != "completed"` and null-ish run fields (`exit_code`/`wall_s`/`n_strategy_files`/`report`
null — for a lock-skip `branch` too — plus `hypotheses` `[]`, `preview_gate` and
`trailer_parse_error` null: no trailer was expected). The trailer itself is parsed defensively:
only the last 64KB of the report is read, the fenced ```json block must be **EOF-anchored**
(nothing but whitespace after its closing fence), and the schema is strictly validated —
any violation yields `hypotheses [] / preview_gate null / trailer_parse_error true`. A single
hypothesis's malformed `merge_back` (bad strategy/universe/date format, an unrelated strategy name,
a duplicate strategy claim, start>end, end>today) drops ONLY that candidate's merge-back
candidacy — logged, never a reason to invalidate the rest of the trailer or the run. This is the
improve-algua backlog: `trailer_parse_error`/`rate_limited`/`timed_out` clusters are machinery
bugs to fix, `preview_gate.failed_checks` clusters show where hypotheses die. The digest also feeds the next runs' anti-dup prompt context
(recent hypothesis titles, injected as sanitized untrusted data). A digest write failure warns but
never fails the run; the digest never stores raw report prose.

**Categories (ideation engine).** `.opencode/categories.txt` lists the operational categories
under the research principles in PRD §§3, 8–10; the research
launcher claims ideas from the pool per run (`--category` restricts), it no longer rotates a
thesis.

**Contention.** The driver holds a non-blocking `data/research-loop.lock` for the whole cycle and skips
(no-op) rather than queue if another research cycle holds it — so the 2h cadence can never stack
overlapping cycles (with `TIMEOUT=45m` + `SYNC_TIMEOUT=5m` under `TimeoutStartSec=4200`, each slot has
~50m of headroom anyway). It does **not** contend with the paper operator (research writes only
scratch; the sole authoritative writer, `paper merge-back`, has its own `merge_back.lock` + operator
policy), and research fires on the hour while paper fires at `:07/:27/:47`, so the two grids never
coincide either.

**Failure propagation.** The driver captures the `opencode run` exit code and propagates a non-zero
(timeout=124, or an auth/runtime error) so the systemd unit **fails** rather than silently reporting a
no-op cycle as success. `TimeoutStartSec` (4200s) must stay above the driver's `TIMEOUT + SYNC_TIMEOUT`.

**Worktree cleanup (automatic, outcome-keyed — #555).** Run worktrees live at
`<checkout>/.runs/<stamp>` (gitignored). A run that enqueued **zero** merge-back candidates has its
worktree removed by the launcher at run end; a **candidate** run's worktree is kept until the
merge-back drainer's `cleanup-branch` step removes it once every queue item on its branch is
terminal. Post-run the branch is renamed `research-run/<stamp>--<s1>+<s2>+...` to carry the
validated candidate names (the directory keeps the bare stamp). Before any removal the run's
`research-loop.log` is archived to `.runs/logs/<branch>.log` (pruned after 30 days). The old mtime
pruner (`RESEARCH_WORKTREE_RETENTION_DAYS`, default 7) remains as a **backstop** only — it also
still scans the legacy `../algua-research-*` location during transition. Reap on demand with
`git worktree remove .runs/<stamp>`; the authored code persists on the run branch either way.

## Ideation engine (forage + leap)

Two more units feed the idea pool the research loop claims from (spec
`docs/superpowers/specs/2026-09-08-ideation-engine-design.md`). Three timers now share one
staggered grid, each on its own cadence, all kept off the **paper tick's** minutes (`:07/:27/:47`):

| unit | schedule | does |
|---|---|---|
| `algua-research.timer` | every 2h at `:00` | claims ideas from the pool, authors/backtests/gates them (unchanged) |
| `algua-leap.timer` | every 2h at `:30`, between research runs | inspirations → structured hypotheses, but only when `research idea depth` is below its refill trigger AND the vault still holds a non-exhausted note (either gate exits fast, no worktree) |
| `algua-forage.timer` | daily `03:00 UTC` | web search → inspiration notes under `kb/inspirations/`, rotating `FORAGE_SLICES` categories per run so every category is foraged at least weekly |

`algua-leap.timer` **shares the merge-back drainer's `:30` minute**, and that is deliberate: leap
takes no `operator.lock` — only the drainer and the paper tick contend for that. Leap, forage and
the research loop each serialize against THEMSELVES only, on their own
`data/{leap,forage,research-loop}.lock` flock, so an overlapping firing of the same unit skips
cleanly instead of queueing.

**Privileges (spec §9).** All three run a sandboxed agent behind `.opencode/scripts/run_agent.sh`, which re-imposes a kernel write wall with bwrap
(writes confined to its throwaway run worktree) with a TRUSTED, unsandboxed DRIVER doing every
authoritative write after the agent exits: the forage agent gets the shell network off and only
the runtime's own web search (the FORAGE_MCP bypass is GONE: OpenCode configures MCP declaratively in opencode.json, so no wall has to drop —
loudly logged) and no registry path at all, with the driver validating and landing survivors via
`research inspirations accept`; the leap agent gets no web access and a THROWAWAY SCRATCH COPY of
the registry (it can read the real pool's history but write only scratch), with the driver doing
the real `research idea import` (re-dedup, eligibility, cap), the critic ledger, and the
inspirations bookkeeping; the research agent is unchanged (shell network on for `uv`, scratch
registry copy, `claim` before / `record-outcome` after via the driver, `link` via the drainer). No
agent in this trio ever holds a path to the authoritative registry or vault directly.

**The vault's sources registry.** `kb/inspirations/` is runtime state and git-ignored; the tracked
artifact is the SEED at `deploy/kb/inspirations/_sources.yaml`, which `install-user-units.sh` (and
`forage.sh` at startup, so a relocated `ALGUA_KNOWLEDGE_DIR` self-heals) copies to
`${ALGUA_KNOWLEDGE_DIR:-<repo>/kb}/inspirations/_sources.yaml` **only when that file is absent** —
your curation and the `write-yield` stamps are never overwritten.

**Settings** (env file; see `deploy/systemd/algua.env.example`): `ALGUA_RESEARCH_RUNS_PER_DAY`,
`ALGUA_RESEARCH_HYPOTHESES_PER_RUN`, `ALGUA_IDEA_POOL_FLOOR_DAYS`, `ALGUA_IDEA_POOL_CEILING_DAYS`,
`ALGUA_IDEA_CLAIM_TTL_MINUTES`, `ALGUA_IDEA_PREVIEW_HOLD_HOURS` drive the pool-depth math
(`refill_at`/`ceiling` = `runs_per_day * hypotheses_per_run * {floor,ceiling}_days`); `LEAP_MAX_IDEAS`
bounds hypotheses per leap; `FORAGE_MAX_NOTES`/`FORAGE_SLICES`/`FORAGE_MCP` bound notes per forage
run, the category rotation width, and the MCP opt-in.

**Done.** `uv run algua research idea depth` shows a non-empty pool that recovers above
`refill_at` within one leap interval after a research run; `uv run algua research idea scorecard
--days 90` shows `n >= 1` for at least one venue once forage + leap + research have each fired;
`journalctl --user -u algua-forage.service` / `journalctl --user -u algua-leap.service` show
completed runs.

## Auto merge-back (factory slice 3)

The candidate **consumer** is now an always-on timer (`algua-mergeback-drain.{service,timer}`),
closing the last human-run gap between the research loop and the authoritative funnel. Three
pieces make this work together:

**The queue (`data/mergeback-queue.json` + `data/mergeback-queue.lock`).** One JSON object file:
`{"items": {"<strategy>@<branch>": {strategy, universe, start, end, branch, enqueued_at,
attempts, status, last_attempt_at, last_result}}}`. `status` ∈ `pending` (fresh, or lock-contention
left it alone) | `gate_failed` (retryable, capped) | `terminal_failed` (diff-policy-rejected /
promote-failed / gate-failed-exhausted — never retried) | `promoted_allocated` / `promoted_queued`
/ `already_done` (terminal success). BOTH writers — the research driver (enqueue) and the drainer
(status update) — mutate it ONLY under `mergeback-queue.lock` (a dedicated, non-blocking flock with
a short bounded retry; queue mutations are sub-second), via
`.opencode/scripts/mergeback_queue.py`'s atomic tmp+fsync+`os.replace` read-modify-write (the same
standard idiom, in this bash-driven side of the system). The research driver only enqueues (idempotent
on the `(strategy, branch)` key — a re-enqueue of an existing key is a no-op, since a branch is
produced exactly once per research-run stamp); it never runs merge-back itself, so queue depth can
never extend a research cycle past its own `TIMEOUT` budget.

**The drainer (`.opencode/scripts/drain-mergeback-queue.sh`).** Trusted, unsandboxed, no LLM. Every 30
minutes it selects **exactly one** eligible item (`pending`, or `gate_failed` with
`attempts < MAX_MERGEBACK_ATTEMPTS=3` past a linear backoff window since its last attempt — draining
more per cycle risks self-overlapping the next 30-minute firing, since a single quality gate already
runs ~9 minutes) and invokes
`algua operator lock-run -- algua paper merge-back --branch <b> --strategy <s> --universe <u>
--start <a> --end <e>` as a bash ARRAY (never a shell string, even though these values are already
format-validated). It classifies the result and updates the queue entry under the lock:
`promoted_allocated`/`promoted_queued`/`already_done` → terminal (kept for audit);
`diff_policy_rejected`/`promote_failed` → `terminal_failed`, never retried (the branch content
itself is wrong — retrying wastes a gate cycle for a guaranteed-identical outcome); `gate_failed` →
retried up to the cap, then `terminal_failed` (the merge-back JSON does not expose which quality-gate
phase failed, so this is the flat cap, not a same-phase-twice refinement); lock contention on
`operator.lock` (the paper tick is running) or an unparseable/hard-failure result → the item is left
**completely untouched** (not even `last_attempt_at` moves) and is NEVER counted as an attempt.

**`algua operator lock-run -- <command...>`** (new, additive-only command in
`algua/cli/operator_cmd.py`): resolves the SAME `operator.lock` `operator run --job paper` uses,
acquires it via the existing `operator_run_lock` primitive, and runs the trailing command with
stdout/stderr/exit-code **transparently passed through** (no wrapper envelope on the ran path, so a
caller parsing this process's stdout parses exactly what the wrapped command printed) — or, on
contention, prints its own `{"ok": true, "ran": false, "reason": "locked"}` and exits 0 without ever
running the wrapped command. It **deliberately bypasses `session_gate`/`SessionMarker` entirely**:
merge-back has no notion of "once per trading session" (it fires many times a day), so reusing the
session-gated `operator run` wrapper would silently cap it at once per session. Merge-back therefore
gets **no `OPERATOR_JOBS` manifest entry** — `lock-run` is a parallel, purpose-built command, not a
new job key. Zero lines of `run_session` (`algua/operator/session_runner.py`)/`session_gate`/the
existing `run` command are touched by
its existence.

## Draft verified-PR admission (not activated)

The Task7 bypass-removal increment makes `paper merge-back` refuse direct publication to
`main`, including automatic revert pushes. It can adopt an **already merged** PR only after
exact-head independent review, named check-run/app identities, a trusted integrated-tree
attestation binding base/head/tree/check IDs, and explicit Task4 **authoritative strategy
execution** attestation. Authoring sandbox success is insufficient. No production attestation
or admission policy has been issued; Task4 remains unproved.

`ALGUA_MERGEBACK_ADMISSION` selects a bounded, root-controlled descriptor, never a worker
receipt. Its `merge-pr-admission/v1` fields are `repository`, `pull_request`, `head_sha`,
`base_sha`, `reviewer_ids`, `required_checks`, `checked_tree` and `isolation` (plus `schema`).
The attested execution baseline must have no subsequent changes outside the existing allowlist.
Deployment also requires an immutable reviewed operator and trusted GitHub CLI/host; a root-owned
JSON file alone establishes neither. The checked-tree attestation producer is not implemented.

Missing evidence stays operationally pending without burning queue retry budgets. Old direct-main
journals require owner recovery. A failed strict promotion remains in history with
`reviewed_revert_pending`; no automatic rollback publication occurs. A trusted autonomous merger, artifact-producing CI and reviewed-revert completion remain gaps. Current
repository CI remains manual, and this platform-delivery waiver never supplies strategy CI proof.
All new safety/recovery behavior requires human review before merge or activation.

### Draft publication phase (default off)

`ALGUA_MERGEBACK_PUBLISH_PR=1` permits the existing merge-back entry/drainer to publish one
allowlisted candidate to `its-nix/algua`, base `main`, on `algua-research/<full-head-SHA>`.
Every unpublished commit must be linear and allowlisted, with a 128-commit cap; reverted protected
edits refuse before publication. An empty-expected ref lease is create-only CAS, never permission
to replace an existing ref. New PRs are drafts with a fixed body; worker text, claims and provider
errors are not copied into them. No strategy is imported or executed by this phase.

Strictly matched creation/reuse returns a non-authoritative `publication` observation in CLI JSON
and queue `last_result`, without writing an admission journal or consuming retry budgets. Closed
unmerged PRs, identity mismatches and races remain pending. Publication never supplies review,
CI, checked-tree or Task4 proof; the separate admission requirements above remain mandatory.

Remote refs/base can move after observations. This phase is not a base-CAS merger and assumes no
strict server checks or merge queue. Trusted immutable operator/Git/GitHub CLI/host configuration
and a separately scoped publication credential are deployment prerequisites; none is installed or
issued here. The one additive protected CLI JSON field and these new workflow semantics require
human review of this dependent draft before merge/activation; prior PR788 review does not cover it.


### Optional independent risk watcher

`algua-risk@.service` and `algua-risk@.timer` provide nominal minute account-risk checks without the
paper job's once-per-session marker. Instances are `paper` or `live`; the command runs under the
same operator lock. They are opt-in templates, not enabled by the installer or this implementation.
Configure the signed account policy and verify the deployment's account, data, alert delivery,
immutable signer anchor and live authority first. Checks may defer while the operator lock is held.
See [layered risk](../../docs/agent/layered-risk.md). Never infer live activation from a policy or
a timer file's existence.
