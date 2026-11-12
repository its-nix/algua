# Drive as the ideation backend — step 1 (design)

**Date:** 2026-11-12
**Status:** design, agreed with the owner in a brainstorm on 2026-11-11/12; pending builder check.
**Scope:** the ideation component only (forage → inspirations → leap → idea pool → research
claim). Trading, gates, registry authority, capital, market data and approvals are out of scope
and stay where they are.
**Relates to:** `2026-09-08-ideation-engine-design.md` (the funnel this changes the storage of),
`kb/drive-assets.md` (the Drive boundary note this amends).

## 1. Why

The owner wants Google Drive (Sheets) to be the place the ideation system lives: a surface they
trust, can read and edit from anywhere, and that replaces home-built storage for this part of the
system. Three concrete needs:

1. **An inbox for the owner's own ideas**, flowing into the *existing* funnel exactly once — no
   parallel track, no double processing.
2. **Steering from Drive.** Today the categories list and the venue registry are files on the VPS
   (`.opencode/categories.txt`, `kb/inspirations/_sources.yaml`); changing them means SSH.
3. **Visibility.** The owner cannot easily see what happened to an idea. A readable idea log in
   Drive answers "idea → hypothesis → tested → why it died".

Evidence from the VPS (2026-11-12, read-only): since the 2026-11-05 reset, 84 leap runs (~80%
imported nothing), 30 inspirations, 16 ideas, 15 attempts, 0 strategies registered. Ideation
volume is tiny and single-writer, which is what makes Sheets a reasonable store here. (The
funnel's main blocker is the non-PIT pilot data, which the owner is fixing in parallel; this work
is not expected to fix that.)

## 2. Goals, non-goals, anti-goals

**Goals (step 1)**
- Owner writes ideas into an **Inbox Sheet**; each row enters the funnel once, as an inspiration
  with `source_kind: human`, and the row shows its fate.
- **Steering Sheet** is the single source of truth for categories and venues; the two VPS files
  are retired after migration.
- **Inspirations** are stored in a Drive **Sheet** (one row per note) instead of
  `kb/inspirations/*.md`.
- **Ideas Sheet** is a read-only mirror of the idea pool + attempt outcomes, rewritten by Algua.
- Every Drive call is logged.

**Non-goals**
- Moving the idea pool (`ideas`, `idea_attempts`, `idea_inspirations` tables) to Sheets. That is
  **step 2**, designed separately once step 1 has run reliably for 1–2 weeks (it touches ~30
  modules: campaign selection, research memory, daily budget, claim selection).
- Simplifying the driver scripts. Worth doing; separate work.
- Anything trading-side: registry stages, gates, tokens, allocations, ledgers, bars, approvals.

**Anti-goals (would be a failure even if it "works")**
- Agents getting access to anything in Drive beyond the `Algua/` folder.
- An inbox row processed twice, or an edited row silently re-run.
- Drive being consulted by any trading, gate, risk or capital code path.
- A new root dependency (the root `uv.lock` is part of `dependency_hash` identity; changing it
  touches deployment identity for unrelated reasons).
- Drive IDs, links or credentials committed to this **public** repo.

## 3. Decisions made in the brainstorm (owner's)

- Drive is the ideation backend; trading and data stay put. Two steps; this doc is step 1.
- No wrappers / pre-fetch layers. Keep it simple, log everything, harden as problems appear.
- Inbox ideas go **through leap** (critic pass, dedup against refuted ideas), entering at the same
  point as foraged inspirations.
- If Drive is unreachable, the run fails clearly and the next timer retries. **No local fallback
  copy** on the production path.

## 4. Shape

```
Owner ──► Inbox Sheet ──(research inbox intake, at leap start)──► Inspirations Sheet
                                                                       ▲      │
forage agent ──► staged notes ──(research inspirations accept)─────────┘      │
                                                                              ▼
Steering Sheet ──► categories + venues ──► forage / leap / idea add      leap (unchanged logic)
                                                                              │
                                                       idea pool (SQLite, unchanged in step 1)
                                                                              │
                                     research idea publish (end of leap + research runs)
                                                                              ▼
                                                  Ideas Sheet  +  Inbox status column
```

**Agents never talk to Drive.** They keep calling `uv run algua research inspirations …` /
`research idea …` exactly as today; the CLI's storage underneath changes. One integration point.

### Run-start snapshot (the one rule that makes the above true)
Each driver (forage, leap, research) starts with **one** command:
`uv run algua research steering export --to "$RUN_DIR/steering"` which writes, from Drive,
`categories.txt` (same format as today), `_sources.yaml` (same format), and — for leap —
`inspirations/<id>.md` plus `inspirations.json` (the authoritative fields: venue, obscurity,
category, source_kind per note). `$RUN_DIR/steering` is a **driver-owned directory outside the
agent's writable scratch**. The driver then sets `ALGUA_STEERING_DIR=$RUN_DIR/steering` for
everything it runs, including the agent. With that variable set, every category/source/note
*read* in the CLI uses the snapshot files; only *writes* (accept, mark-used/exhausted,
write-yield, propose, intake, publish) go to Drive, and those run in the driver, never the agent.

Consequences, by design:
- The sandboxed agent never needs the folder id, the credential, or network to Drive
  (`research idea add`'s category check reads the snapshot).
- Shell code that parses `categories.txt` / `_sources.yaml` (forage.sh rotation, hints, venue
  slice, proposal check; leap.sh `CATEGORY_LINES`) keeps working by pointing at the snapshot
  path — a path change, not a rewrite.
- A leap run's trusted import reads venue/obscurity from the run's own snapshot, so a Drive blip
  *after* the agent finished cannot discard the run's ideas.
- If the export fails, the run ends before spending an agent call; next timer retries. This also
  pauses research-loop claims (round-robin needs categories) — accepted: same "fail and retry"
  rule the owner chose.

This replaces the `inspirations export` command in §6.3 (it is folded into `steering export`).

### Drive layout

```
Algua/                 (existing access-controlled folder; ID configured on the VPS only)
  Inbox                Sheet — owner writes
  Steering             Sheet — tabs: Categories, Sources (owner writes; Algua appends proposals/yields)
  Inspirations         Sheet — one row per note (forage + inbox intake write; leap driver marks status)
  Ideas                Sheet — Algua rewrites (read-only mirror)
```

Files are found **by name inside the configured folder** and their IDs cached for the process.
A missing file is created on first use with its header row (except the folder itself).

> Change from the chat: inspirations were discussed as one *Doc* per note. A Sheet row per note
> is the builder's better fit — the notes are already structured frontmatter + a ≤16 KB body,
> status edits become cell updates, and listing/dedup is one read instead of N Doc fetches.

## 5. Access and credential

- **One Google account dedicated to Algua** (e.g. an `algua-bot` Gmail), with **only** the
  `Algua/` folder shared to it as **Editor**. Works whether the owner's Drive is personal or
  Workspace. (A service account cannot create files in a personal My Drive — no storage quota —
  hence a real account.)
- OAuth "installed app" client; a one-time human consent produces a **refresh token**. On the VPS:
  `ALGUA_DRIVE_CREDENTIALS=/home/algua/.config/algua/drive.json` (client_id, client_secret,
  refresh_token; mode 0600) and `ALGUA_DRIVE_FOLDER_ID=<id>` in `research.env`.
  Verified on the VPS (2026-11-12): `research.env` is loaded by the forage, leap and research
  units (via `deployment.conf` drop-ins) and by `algua-web`; the paper lane runs from a separate
  release and does **not** load it, so the trading side never sees the Drive variables. (The
  repo's sample units reference `/etc/algua/algua.env`; the VPS layout is the authority — the
  builder updates `deploy/systemd/algua.env.example`/docs to match, not the reverse.) The
  `algua-web` exposure is accepted for step 1; it can `UnsetEnvironment=` the two variables if
  the monitor never needs Drive.
- Scopes: `drive` + `spreadsheets` (the bot account can only see what is shared with it, which is
  the actual boundary).
- Accepted risk: an agent running model-written code inside its sandbox can read the credential
  and edit/trash the ideation Sheets. Recoverable via Drive version history/trash; no money,
  gates or market data reachable. Revisit if it bites.

## 6. The pieces

### 6.1 Drive client (new)
`algua/knowledge/drive/` — a small client over Google's REST APIs using **stdlib `urllib` only**
(OAuth token refresh, Drive v3 file lookup/create, Sheets v4 `values.get` / `values.update` /
`values.append` / `batchUpdate` for header and tab creation). Pure transport + typed helpers
("read tab as list of dicts keyed by header", "append rows", "update cells by row id",
"replace tab contents"). Retries transient errors (429/5xx) with the existing
`algua.primitives.retry`; everything else raises a typed `DriveError`.

**Logging:** every call emits one JSON log line through `algua.observability.log`:
`{"event":"drive_call","op":..., "file":<name>, "tab":..., "rows":n, "ms":t, "ok":bool,
"status":http}` — names, never IDs, so logs stay safe to paste.

Layering: lives under `knowledge` (which already owns the inspirations domain); imports only
config, primitives, observability. Must pass `lint-imports` without new exemptions.

### 6.2 Storage seam for inspirations, sources and categories
Today `algua/knowledge/inspirations.py` (notes + `SourcesRegistry`) and
`algua/research/categories.py` read/write files. Introduce one small interface per store with two
implementations: the **existing file backend** (kept for tests/local dev) and a **Drive backend**.
Selected by settings: Drive iff `ALGUA_DRIVE_FOLDER_ID` is set. Every existing caller (CLI
commands, leap import, idea add, claim round-robin) goes through the interface, so the slug list
stays single-sourced (the invariant `categories.py` documents).

Note: `research/categories.py` is pure stdlib by design. Keep the *parser* there; the Drive read
happens in the knowledge/CLI layer and hands lines to it.

### 6.3 Inspirations Sheet
One row per note. Columns = the note frontmatter fields (`REQUIRED` in `inspirations.py`: id,
found_at, source_url, venue, source_kind, category, market, horizon, mechanism, obscurity,
status) + `body` + `url_hash` + `inbox_row_id` (empty for foraged notes) + `used_by_ideas`.

Existing semantics preserved:
- `research inspirations accept` — validates staged notes from the forage worktree exactly as
  today (`validate_note`, size cap, seen-hash check) and **appends rows** instead of copying files.
  The seen-file (`inspirations-seen.jsonl` in the data dir) stays as is.
- `list`, `mark-used`, `mark-exhausted`, `write-yield`, `propose` — same CLI/JSON contract, Sheet
  storage.
- The leap driver replaces its `cp -RL "${KB_DIR}/inspirations" …` with a copy from the run
  snapshot (§4 "Run-start snapshot") so the agent keeps reading plain files in its scratch dir.
  Driver changes overall: the snapshot export + `ALGUA_STEERING_DIR` at the top of each driver,
  the steering-file paths pointed at the snapshot, intake (§6.4) and publish (§6.5).

### 6.4 Inbox Sheet and intake
Columns: `id` (Algua fills), `idea` (required), `why / notes`, `links`, `category` (optional,
must be a Steering category if given), `status` (Algua writes), `updated` (Algua writes).

`research inbox intake` (run by `leap.sh` on **every** firing, before the snapshot export and
before any depth/material gate — so a submitted row is marked `taken` within ~2h regardless of
pool depth):
1. Read the Inbox; for each row with `idea` set and **no `id`**: assign a UUID into `id`.
2. For each row whose `id` is **not** already an `inbox_row_id` in the Inspirations Sheet: create
   an inspiration row: `id` = `<date>-inbox-<slug-from-idea>`, `source_kind: human`,
   `venue: inbox`, `source_url: inbox:<row id>`, `category` from the row or `uncategorized_human`
   (see §8), `market: us_equities`, `horizon: daily`, `obscurity: human`, `mechanism` = idea
   text, `body` = idea + why + links, `status: fresh`.
3. Write `status = taken → inspiration <id>` on the Inbox row.

**Exactly-once:** the dedup key is the row's `id`, recorded on the inspiration
(`inbox_row_id`). Re-running intake is a no-op. Editing a taken row changes nothing (the row
already has an inspiration); to revisit an idea the owner adds a new row. Deleting a row's `id`
cell by hand *would* re-submit it — documented as the explicit "resubmit" gesture.

Leap processes human inspirations **first** (ordering in `inspirations list`), so the owner's
ideas are not starved behind forage notes. **Human inspirations bypass leap's pool-depth gate**
(builder's call, §8): the gate exists to stop forage volume overfilling the pool; owner ideas
are few and deliberate, and an owner idea waiting days because the pool is "deep" defeats the
inbox. Leap's per-run idea cap still applies.

Validation additions: `source_kind` gains `human`; `obscurity` gains `human` (keeps the
scorecard's obscurity breakdown honest rather than mislabelling owner ideas).

### 6.5 Ideas Sheet (mirror) and Inbox status write-back
`research idea publish` — reads the idea pool and attempts from SQLite (authority unchanged) and
**replaces** the Ideas tab: one row per idea with id, title, category, source (venue / inbox),
inspiration ids, status, parked reason, latest attempt outcome + reason, strategy name, dates.
Then, for each Inbox row with an `id`, follows inbox row → inspiration → idea(s) → latest attempt
and writes a human-readable `status`, e.g. `hypothesis #17 → refuted: all four windows lost net of
costs`.

Called at the end of `leap.sh` and `run-research-loop.sh` (one line each, failure logged and
ignored — the mirror is never allowed to fail a run). Lives in the CLI layer because it composes
registry (reader) + knowledge.drive (writer).

### 6.6 Steering Sheet
- **Categories tab:** columns `slug`, `market`, `horizon`, `enabled`, `notes`. Replaces
  `.opencode/categories.txt` (same semantics: order matters, slug first, hints optional;
  disabled = commented out).
- **Sources tab:** columns mirror `_sources.yaml` venue entries (`key`, `name`, `url`, …,
  `added_by`, `added_at`, `yield` as JSON). Algua keeps appending forage proposals and stamping
  yields, as today.
- Bad rows are skipped and logged, never crash a run. An empty Categories tab is an error (a run
  with no categories is meaningless).

### 6.7 One-time migration
`research inspirations migrate-to-drive` (idempotent): copies `kb/inspirations/*.md`,
`_sources.yaml` and `.opencode/categories.txt` into the Sheets. After a verified run on the VPS,
the files are moved to a dated backup directory (not deleted) and the forage driver's seed-copy of
`deploy/kb/inspirations/_sources.yaml` is removed. The repo's `categories.txt` stays as the
**file backend's** default for tests/local dev, with a header comment saying production reads the
Steering Sheet.

### 6.8 Docs
Amend `kb/drive-assets.md`: Drive is now the ideation backend for these four Sheets (it currently
says Drive is not a sync process). Update the CLAUDE.md lines describing `categories.txt` /
`_sources.yaml` as the steering surfaces. No Drive links in the repo.

## 7. Failure behavior
- Drive unreachable / auth failure on a **read** the run needs (Steering, Inspirations): the
  command exits non-zero with `{"ok": false, "error": "drive_unavailable", ...}`; the driver's
  existing failure path ends the run; the next timer retries.
- Failure in **publish** (§6.5): logged, run unaffected.
- Partial write in `accept` (append succeeded for some notes): rows are keyed by note id; a re-run
  skips ids already present. Same for intake (keyed by inbox row id).
- Concurrency: timers run one ideation stage at a time; the existing `kb_sync_lock` flock is kept
  around Drive writes from one host. No cross-host writers exist.

## 8. Left to the builder

Calls already made on the builder's behalf (owner may overrule): the run-start steering snapshot
(§4), inspirations as Sheet rows rather than Docs (§4), human inspirations bypassing the depth
gate (§6.4), `uncategorized_human` default category (below), `obscurity: human` (§6.4), accepting
`algua-web` seeing the Drive variables in step 1 (§5).

- Exact module/file split inside `algua/knowledge/drive/` and the interface names.
- Category for inbox rows with no category: my call is a reserved slug `uncategorized_human`
  accepted by validation only for `source_kind: human`; builder may instead have leap assign one.
  Must not break the round-robin claim.
- Column order and header text (headers are the contract; order is not).
- Test strategy: the file backend keeps existing tests green; the Drive backend gets unit tests
  against a fake transport (no network in tests). One manual smoke on the VPS against the real
  folder before switching `ALGUA_DRIVE_FOLDER_ID` on.
- Focused checks per CLAUDE.md: affected tests, `ruff`, `mypy algua`, `lint-imports`, the module
  size ratchet.

## 9. Rollout
1. Merge with Drive disabled (no env var) → behavior identical.
2. Owner creates the bot account, shares `Algua/`, runs the one-time consent to produce
   `drive.json`, and puts it + the folder id on the VPS.
3. Run `migrate-to-drive`; inspect the Sheets.
4. Set `ALGUA_DRIVE_FOLDER_ID` in `research.env`; watch one forage + one leap + one research
   cycle in the logs (`drive_call` lines).
5. After 1–2 weeks of clean runs, write the step-2 design (pool → Sheets).
