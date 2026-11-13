# Drive Ideation Backend (Step 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inbox, Steering, Inspirations and an Ideas mirror live as Google Sheets in the `Algua/` Drive folder; the ideation drivers read a run-start snapshot and write through the CLI.

**Architecture:** A stdlib-only Drive/Sheets client under `algua/knowledge/drive/`. Reads stay on the existing file code, pointed at a snapshot directory (`ALGUA_STEERING_DIR`) that `research steering export` fills from Drive at the start of each run. Writes (accept, mark-used/exhausted, propose, write-yield, intake, publish) go to Drive when `ALGUA_DRIVE_FOLDER_ID` is set; otherwise every path behaves exactly as today.

**Tech Stack:** Python 3.12, typer, stdlib `urllib`/`json`, Google Drive v3 + Sheets v4 REST, bash drivers.

**Spec:** `docs/superpowers/specs/2026-11-12-drive-ideation-design.md`

## Global Constraints

- **No new root dependency.** `pyproject.toml` / `uv.lock` unchanged (the lock is `dependency_hash` identity). Stdlib `urllib` only.
- Drive is enabled iff `ALGUA_DRIVE_FOLDER_ID` is set; unset ⇒ byte-for-byte current behavior, all existing tests green.
- No Drive IDs, links or credentials in the repo (it is public). Logs name files, never IDs.
- Agents never call Drive; only drivers (trusted) run write commands. The snapshot dir is outside the agent's writable worktree.
- No trading / gate / registry-authority / capital / data code imports `algua.knowledge.drive`.
- `lint-imports` passes with no new exemption; `algua.knowledge` still must not import cli, registry, backtest, live, execution.
- Module size ratchet: do not grow pinned files past their pin; put new code in new modules. `algua/cli/idea_ops_cmd.py` (299 lines) must not cross 300.
- Every Drive HTTP call emits one log line: `event=drive_call op file tab rows ms ok status`.
- Focused checks per task; full `uv run pytest -q && uv run ruff check . && uv run mypy algua && uv run lint-imports` at the end.

## Review Focus

1. **Drive returns 429/5xx or times out mid-`accept`/intake** — expected: retried with backoff; a re-run skips already-written rows (keyed by note id / inbox row id), never duplicates. Test in Task 3 and Task 5.
2. **Owner types into the Inbox oddly** — blank rows, rows with only `why`, unknown `category`, a 5,000-char idea, emoji/RTL text — expected: blank/idea-less rows skipped silently, unknown category → `uncategorized_human` + logged, long text truncated to the 16 KB note cap, unicode preserved. Test in Task 5.
3. **Owner edits a Sheet header or reorders columns** — expected: headers are the contract, order is not; a missing required header fails the command with a clear `drive_schema` error naming the tab and header. Test in Task 1.
4. **Snapshot export partially fails** (categories written, inspirations not) — expected: export writes into a temp dir and renames into place only on full success; the driver sees either a complete snapshot or none. Test in Task 4.
5. **Credential file missing/unreadable or refresh token revoked** — expected: `{"ok": false, "error": "drive_auth"}` non-zero exit, no traceback spam, the run ends cleanly. Test in Task 1.

---

## File structure

| File | Responsibility |
|---|---|
| `algua/config/settings.py` (modify) | `drive_folder_id`, `drive_credentials`, `steering_dir` settings |
| `algua/knowledge/drive/__init__.py` | exports `DriveClient`, `DriveError`, `drive_enabled` |
| `algua/knowledge/drive/client.py` | OAuth refresh, HTTP, retry, logging, tab read/append/update/replace |
| `algua/knowledge/drive/tables.py` | typed Sheet tables: Inspirations, Sources, Categories, Inbox, Ideas (headers + row↔dict) |
| `algua/knowledge/drive/snapshot.py` | export Drive → snapshot dir; migrate files → Drive |
| `algua/knowledge/drive/inbox.py` | intake logic (pure over tables) |
| `algua/knowledge/inspirations.py` (modify, thin) | write-side dispatch to Drive; `human` values; snapshot-aware `inspirations_dir` |
| `algua/research/categories.py` (modify) | `categories_file_default()` honors `ALGUA_STEERING_DIR` |
| `algua/contracts/idea.py` (modify) | `Obscurity.HUMAN` |
| `algua/registry/idea_publish_rows.py` | read-only rows for the Ideas mirror + inspiration→ideas map |
| `algua/cli/steering_cmd.py` | `research steering export`, `research steering migrate` |
| `algua/cli/inbox_cmd.py` | `research inbox intake` |
| `algua/cli/idea_publish_cmd.py` | `research idea publish` |
| `algua/cli/main.py` (modify) | mount the three new apps |
| `scripts/drive_consent.py` | one-time OAuth consent → `drive.json` |
| `.opencode/scripts/leap.sh`, `forage.sh`, `run-research-loop.sh` (modify) | intake / export / publish calls, snapshot paths |
| docs: `kb/drive-assets.md`, `CLAUDE.md`, `deploy/systemd/algua.env.example`, `.opencode/categories.txt` header, `docs/agent/drive.md` (new) | operator docs |

---

### Task 1: Drive client + settings + consent script

**Files:**
- Modify: `algua/config/settings.py` (add 3 fields next to `knowledge_dir`)
- Create: `algua/knowledge/drive/__init__.py`, `algua/knowledge/drive/client.py`, `scripts/drive_consent.py`
- Test: `tests/test_drive_client.py`

**Interfaces:**
- Produces:
  - `Settings.drive_folder_id: str | None = None` (env `ALGUA_DRIVE_FOLDER_ID`), `Settings.drive_credentials: Path | None = None` (env `ALGUA_DRIVE_CREDENTIALS`), `Settings.steering_dir: Path | None = None` (env `ALGUA_STEERING_DIR`).
  - `drive_enabled(settings: Settings) -> bool` — `bool(settings.drive_folder_id)`.
  - `class DriveError(RuntimeError)` with `.code: str` ∈ {`drive_auth`, `drive_unavailable`, `drive_schema`, `drive_http`}.
  - `Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]` (method, url, headers, body → status, body). Default uses `urllib.request` with a 30 s timeout.
  - `class DriveClient(folder_id: str, credentials_path: Path, *, transport: Transport | None = None, sleep: Callable[[float], None] = time.sleep)`
    - `@classmethod from_settings(settings) -> DriveClient` (raises `DriveError("drive_auth")` if `drive_credentials` unset/unreadable).
    - `sheet_id(name: str, tabs: Sequence[str]) -> str` — find a spreadsheet by exact name in the folder (Drive v3 `files.list`, `q="'<folder>' in parents and name='<name>' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"`), create it in the folder if absent (Drive `files.create` with `parents`), ensure every tab exists (Sheets `batchUpdate addSheet`). Cached per instance.
    - `read_tab(sheet: str, tab: str, required: Sequence[str]) -> list[dict[str, str]]` — row 1 is the header; returns one dict per non-empty row keyed by header, plus `"_row": "<1-based row number>"`. Missing required header ⇒ `DriveError("drive_schema", f"{sheet}/{tab}: missing header {h}")`.
    - `ensure_header(sheet: str, tab: str, header: Sequence[str]) -> None` — writes header if row 1 empty; appends missing columns to the right if some absent.
    - `append_rows(sheet: str, tab: str, rows: Sequence[Mapping[str, str]]) -> None` — maps by current header; `valueInputOption=RAW`.
    - `update_cells(sheet: str, tab: str, row: int, values: Mapping[str, str]) -> None` — by header name.
    - `replace_tab(sheet: str, tab: str, header: Sequence[str], rows: Sequence[Mapping[str, str]]) -> None` — clear then write header + rows.
  - Every request: bearer token from OAuth refresh (`POST https://oauth2.googleapis.com/token`, `grant_type=refresh_token`), cached until 60 s before expiry; 401 ⇒ one forced refresh then `drive_auth`. 429/500/502/503/504 and `URLError`/timeouts retried via `algua.primitives.retry.call_with_backoff(attempts=4, backoff_base=1.0)`; exhausted ⇒ `drive_unavailable`. Other 4xx ⇒ `drive_http`.
  - Log through `algua.observability.log.get_logger("algua.drive")`, one INFO line per HTTP call with `extra` fields `op, file, tab, rows, ms, ok, status` (sheet *name*, never id).
  - `scripts/drive_consent.py --client-secrets PATH --out PATH`: stdlib loopback flow (`http.server` on 127.0.0.1 random port, prints the consent URL with scopes `https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets`, `access_type=offline`, `prompt=consent`), exchanges the code, writes `{"client_id","client_secret","refresh_token"}` with mode 0600. Not unit-tested; documented in Task 8.

- [ ] **Step 1: Write failing tests** in `tests/test_drive_client.py` using a `FakeTransport` (records calls; scripted responses keyed by (method, url-prefix)):
  - `test_read_tab_maps_rows_by_header_not_order` — header `["status","id","idea"]`, row `["","r1","buy dips"]` ⇒ `[{"status":"","id":"r1","idea":"buy dips","_row":"2"}]`; blank rows dropped.
  - `test_read_tab_missing_required_header_raises_schema` — `required=["idea"]`, header lacks it ⇒ `DriveError.code == "drive_schema"` and message contains `"missing header idea"`.
  - `test_retries_429_then_succeeds` — two 429s then 200 ⇒ result returned, `sleep` called twice.
  - `test_exhausted_5xx_raises_unavailable` — four 503s ⇒ `code == "drive_unavailable"`.
  - `test_missing_credentials_raises_auth` — `from_settings` with `drive_credentials=None` ⇒ `code == "drive_auth"`.
  - `test_revoked_refresh_token_raises_auth` — token endpoint returns 400 `invalid_grant` ⇒ `code == "drive_auth"`.
  - `test_every_call_logs_drive_call_without_ids` — caplog: each HTTP call yields a record with `op` and `file`; folder id string never appears in any log message/extra.
  - `test_sheet_id_creates_missing_sheet_in_folder_and_caches` — `files.list` empty ⇒ one `files.create` with `parents=[folder]`; second `sheet_id` call makes no HTTP call.
  - `test_settings_drive_fields_from_env` — monkeypatch env ⇒ `Settings(_env_file=None).drive_folder_id == "F"`, `drive_credentials == Path(...)`, `steering_dir == Path(...)`.
- [ ] **Step 2: Run** `uv run pytest tests/test_drive_client.py -q` — expected FAIL (module missing).
- [ ] **Step 3: Implement** settings fields, `client.py`, `__init__.py`, `scripts/drive_consent.py` per Interfaces.
- [ ] **Step 4: Run** `uv run pytest tests/test_drive_client.py tests/test_settings_ideation.py -q && uv run lint-imports && uv run mypy algua/knowledge algua/config` — expected PASS / no errors.
- [ ] **Step 5: Commit** `feat(drive): stdlib Drive/Sheets client, settings and consent script`.

---

### Task 2: Snapshot-aware reads + `human` vocabulary

**Files:**
- Modify: `algua/research/categories.py`, `algua/knowledge/inspirations.py`, `algua/contracts/idea.py`, `algua/cli/inspirations_cmd.py`
- Test: `tests/test_knowledge_inspirations.py`, `tests/test_cli_inspirations.py`, `tests/test_research_ideas.py` (or nearest categories test)

**Interfaces:**
- Produces:
  - `categories_file_default()` returns `Path(os.environ["ALGUA_STEERING_DIR"]) / "categories.txt"` when that env var is set and non-empty; else today's repo path. (Stdlib env read keeps the module pure.)
  - `inspirations_dir(settings)` returns `settings.steering_dir / "inspirations"` when `settings.steering_dir` is set; else today's `knowledge_dir / "inspirations"`. `SourcesRegistry.path` follows it (it already derives from `inspirations_dir`).
  - `SOURCE_KINDS` gains `"human"`; `OBSCURITY` gains `"human"`; `Obscurity.HUMAN = "human"` in contracts with `OBSCURITY_RANK[HUMAN]` ranked before `RARE` (owner ideas sort first under `--rare-first`).
  - `RESERVED_HUMAN_CATEGORY = "uncategorized_human"` in `inspirations.py`; `validate_note` accepts it only when `source_kind == "human"`.
  - `list_notes(..., source_kind: str | None = None)` filter; and `list_notes` orders `source_kind == "human"` notes before all others (then newest id first, as today). CLI `research inspirations list --source-kind KIND`.

- [ ] **Step 1: Write failing tests:**
  - `test_categories_default_honors_steering_dir` — env set to `tmp`, file `tmp/categories.txt` with `momentum\n` ⇒ `load_categories() == ["momentum"]`.
  - `test_inspirations_dir_uses_steering_dir_when_set` — `Settings(steering_dir=tmp)` ⇒ `inspirations_dir(s) == tmp / "inspirations"`.
  - `test_validate_note_accepts_human_kind_and_reserved_category_only_for_human` — human note with `category: uncategorized_human` ⇒ no problems; same category with `source_kind: paper` ⇒ `"category: uncategorized_human"` reported.
  - `test_list_notes_puts_human_first_and_filters_source_kind` — notes `2026-11-10-a` (paper), `2026-11-01-inbox-b` (human) ⇒ order `[inbox-b, a]`; `source_kind="human"` ⇒ only `inbox-b`.
  - `test_cli_list_source_kind_flag` — CLI `research inspirations list --source-kind human` returns only human notes.
- [ ] **Step 2: Run** those tests — expected FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `uv run pytest tests/test_knowledge_inspirations.py tests/test_cli_inspirations.py tests/test_idea_contract.py tests/test_idea_contracts.py tests/test_idea_import.py tests/test_cli_idea.py -q` — expected PASS (existing tests unchanged).
- [ ] **Step 5: Commit** `feat(ideation): snapshot-aware steering reads and human inspiration vocabulary`.

---

### Task 3: Drive tables + write-side dispatch

**Files:**
- Create: `algua/knowledge/drive/tables.py`
- Modify: `algua/knowledge/inspirations.py` (dispatch only; keep under its ratchet pin if any)
- Test: `tests/test_drive_tables.py`

**Interfaces:**
- Consumes: `DriveClient` (Task 1); `REQUIRED`, `validate_note`, `parse_note`, `render_doc` (existing).
- Produces (all in `tables.py`; sheet names are exact):
  - Sheet `"Inspirations"`, tab `"notes"`, header `INSPIRATION_HEADER = [*REQUIRED, "leaps", "body", "url_hash", "inbox_row_id"]` (`leaps` = JSON list).
  - Sheet `"Steering"`, tabs `"Categories"` header `["slug","market","horizon","enabled","notes"]` and `"Sources"` header `["key","kind","url","categories","added_by","added_at","yield","extra"]` (`categories` comma-separated; `yield`/`extra` JSON; `extra` holds any other venue keys so a round-trip is lossless).
  - Sheet `"Inbox"`, tab `"ideas"`, header `["id","idea","why / notes","links","category","status","updated"]`.
  - Sheet `"Ideas"`, tab `"pool"`, header defined in Task 6.
  - `class InspirationsTable(client)`: `ids() -> set[str]`; `rows() -> list[dict]`; `append(fm: dict, body: str, *, inbox_row_id: str = "") -> None`; `update(note_id: str, mutate: Callable[[dict], None]) -> dict` (reads row, rebuilds fm incl. `leaps`, applies, writes changed cells; unknown id ⇒ `KeyError`).
  - `class SourcesTable(client)`: `load() -> list[dict]`; `save(venues: list[dict]) -> None` (replace_tab).
  - `class CategoriesTable(client)`: `lines() -> list[str]` — enabled rows rendered as today's file lines (`slug [market=..] [horizon=..]`), disabled rows as `# slug ...`; raises `DriveError("drive_schema")` if no enabled row.
  - Dispatch in `inspirations.py` (when `drive_enabled(settings)`):
    - `accept_new_notes`: identical validation; the "id already exists" check uses `InspirationsTable.ids()`; accepted notes go via `append` (body = text after frontmatter; `url_hash` filled). Seen-file behavior unchanged.
    - `mark_used` / `mark_exhausted`: via `InspirationsTable.update`.
    - `SourcesRegistry.write_yields` / `propose`: load/save via `SourcesTable` (same one-load-one-save rule).
    - The Drive import is lazy inside the dispatch branch so the file path never imports `algua.knowledge.drive`.

- [ ] **Step 1: Write failing tests** with a fake `DriveClient` (in-memory dict of `(sheet, tab) -> list[dict]` implementing the Task 1 method set):
  - `test_accept_appends_rows_and_skips_ids_already_in_sheet` — sheet already has `2026-11-12-foo`; staged `foo` + `bar` ⇒ accepted `["2026-11-12-bar"]`, `foo` rejected with `"id already exists in the vault"`.
  - `test_accept_rerun_after_partial_failure_does_not_duplicate` — fake raises `DriveError("drive_unavailable")` on the 2nd append; first call raises; re-run ⇒ sheet holds each id exactly once.
  - `test_mark_used_appends_leap_and_flips_status_in_sheet` — `leaps` becomes `[7]`, status `used`; second call with 7 leaves `[7]`.
  - `test_sources_roundtrip_is_lossless` — venues with an unknown key `notes: x` survive `save` → `load` unchanged.
  - `test_categories_lines_render_disabled_as_comments_and_require_one_enabled`.
  - `test_file_backend_untouched_when_drive_disabled` — with no folder id, `accept_new_notes` writes files and never constructs a `DriveClient` (monkeypatch it to raise).
- [ ] **Step 2: Run** `uv run pytest tests/test_drive_tables.py -q` — expected FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** `uv run pytest tests/test_drive_tables.py tests/test_knowledge_inspirations.py tests/test_cli_inspirations.py tests/test_module_size_ratchet.py -q && uv run lint-imports` — expected PASS.
- [ ] **Step 5: Commit** `feat(drive): inspirations, sources and categories as Sheets behind the existing writers`.

---

### Task 4: `research steering export` and `research steering migrate`

**Files:**
- Create: `algua/knowledge/drive/snapshot.py`, `algua/cli/steering_cmd.py`
- Modify: `algua/cli/main.py` (mount `steering_app` under `research_app` as `steering`)
- Test: `tests/test_drive_snapshot.py`

**Interfaces:**
- Consumes: Task 3 tables.
- Produces:
  - `export_snapshot(client, dest: Path) -> dict` — writes into `dest.with_name(dest.name + ".tmp")` then `os.replace` to `dest` (existing `dest` removed first). Layout: `dest/categories.txt` (header comment + `CategoriesTable.lines()`), `dest/inspirations/_sources.yaml` (`{"venues": [...]}`), `dest/inspirations/<id>.md` (`render_doc(fm, body)` per row; rows whose id fails `NOTE_ID_RE` are skipped and counted). Returns `{"categories": n, "venues": n, "notes": n, "skipped": n}`.
  - `migrate_files(client, *, categories_file: Path, inspirations_dir: Path) -> dict` — idempotent: categories only if the Categories tab has no rows; sources merged by `key`; notes appended if id absent. Returns counts per kind `{"added": .., "already_present": ..}`.
  - CLI: `research steering export --to DIR` ⇒ `ok({"dir": str(DIR), **counts})`; `research steering migrate [--categories-file P] [--from-kb DIR]` (defaults: repo `.opencode/categories.txt`, `settings.knowledge_dir / "inspirations"`). Both require `drive_enabled`, else `{"ok": false, "error": "drive_disabled"}` exit 1. `DriveError` ⇒ `{"ok": false, "error": e.code, "detail": str(e)}` exit 1.

- [ ] **Step 1: Write failing tests:**
  - `test_export_writes_files_readable_by_existing_readers` — after export, `load_categories(dest/"categories.txt")` and `list_notes(Settings(steering_dir=dest))` and `SourcesRegistry(Settings(steering_dir=dest)).load()` return the sheet content.
  - `test_export_is_all_or_nothing` — fake fails while reading Inspirations ⇒ raises, `dest` does not exist (and a pre-existing `dest` is left untouched).
  - `test_migrate_is_idempotent` — run twice ⇒ second run all `already_present`, sheet row counts unchanged.
  - `test_cli_export_disabled_without_folder` — no folder id ⇒ exit 1, `error == "drive_disabled"`.
- [ ] **Step 2: Run** — expected FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/test_drive_snapshot.py -q && uv run lint-imports` — PASS.
- [ ] **Step 5: Commit** `feat(drive): steering snapshot export and one-time migration`.

---

### Task 5: Inbox intake

**Files:**
- Create: `algua/knowledge/drive/inbox.py`, `algua/cli/inbox_cmd.py`
- Modify: `algua/cli/main.py` (mount `inbox_app` under `research_app` as `inbox`)
- Test: `tests/test_drive_inbox.py`

**Interfaces:**
- Consumes: `InspirationsTable`, `DriveClient.read_tab/update_cells`, `validate_note`, `RESERVED_HUMAN_CATEGORY`, `MAX_NOTE_BYTES`, category list from `CategoriesTable.lines()` (read live — intake runs before export).
- Produces:
  - `intake(client, *, today: date, categories: set[str]) -> dict` returning `{"assigned_ids": n, "taken": [inspiration_id...], "skipped": [{"row": r, "reason": ...}]}`.
  - Rules (spec §6.4): row with empty `idea` ⇒ skip silently (not reported); empty `id` ⇒ write `uuid4().hex[:12]` into `id`; row whose `id` is already an `inbox_row_id` in Inspirations ⇒ no-op. New note: `id = f"{today:%Y-%m-%d}-inbox-{slug}-{rowid[:6]}"` with `slug` = lowercase ascii `[a-z0-9-]` of the idea, collapsed, truncated so the whole id matches `NOTE_ID_RE` (≤ 60 chars after the date); fallback slug `idea` if empty. Frontmatter: `found_at=today`, `source_url=f"inbox:{rowid}"`, `venue="inbox"`, `source_kind="human"`, `category` = row category if in `categories` else `RESERVED_HUMAN_CATEGORY` (unknown non-empty category ⇒ also logged in `skipped`-style `warnings`), `market="us_equities"`, `horizon="daily"`, `mechanism` = idea (first 500 chars), `obscurity="human"`, `status="fresh"`. Body = `idea`, `why / notes`, `links` as markdown sections, truncated so the rendered note ≤ `MAX_NOTE_BYTES`. Then `update_cells(status=f"taken → inspiration {id}", updated=now ISO)`.
  - CLI `research inbox intake` ⇒ `ok(result)`; disabled/DriveError handled as Task 4.

- [ ] **Step 1: Write failing tests:**
  - `test_intake_assigns_ids_and_creates_one_inspiration_per_row`.
  - `test_intake_is_exactly_once` — run twice ⇒ Inspirations has one row per inbox row; second result `taken == []`.
  - `test_edited_taken_row_is_ignored` — change `idea` text after intake ⇒ no new inspiration.
  - `test_clearing_id_resubmits` — blank the `id` cell ⇒ new id, new inspiration.
  - `test_blank_and_why_only_rows_skipped`.
  - `test_unknown_category_falls_back_to_reserved_and_warns`.
  - `test_long_and_unicode_idea_truncated_within_note_cap` — 5,000-char idea with emoji and Hebrew ⇒ note id matches `NOTE_ID_RE`, rendered note ≤ 16384 bytes, unicode preserved in body.
  - `test_drive_failure_mid_intake_rerun_converges` — fail on the status write ⇒ re-run creates no duplicate inspiration and writes the status.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/test_drive_inbox.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(drive): owner inbox intake into the inspirations funnel`.

---

### Task 6: `research idea publish` (Ideas mirror + Inbox status)

**Files:**
- Create: `algua/registry/idea_publish_rows.py`, `algua/cli/idea_publish_cmd.py`
- Modify: `algua/cli/main.py` (merge `idea_publish_app` flat onto `idea_app`, like `idea_ops_app`)
- Test: `tests/test_idea_publish.py`

**Interfaces:**
- Produces:
  - `IDEAS_HEADER = ["id","title","category","status","parked_reason","source","inspirations","latest_outcome","latest_reason","strategy","created_at","updated_at"]` (in `idea_publish_rows.py`).
  - `publish_rows(conn: sqlite3.Connection) -> list[dict[str, str]]` — one row per `ideas` row ordered by id; `source` = comma-joined distinct `venue` from `idea_inspirations` (or `source_type`); `inspirations` = comma-joined inspiration ids; latest attempt = max `outcome_at` from `idea_attempts`; reasons truncated to 300 chars.
  - `ideas_by_inspiration(conn) -> dict[str, list[dict]]` — inspiration id → the published rows of ideas linked to it.
  - `inbox_status(rows: list[dict]) -> str` — none ⇒ unchanged (caller keeps `taken → …`); else per idea `#<id> <status>` plus `: <latest_outcome> — <latest_reason[:120]>` when present, joined by `; `.
  - CLI `research idea publish`: reads registry (read-only), `replace_tab("Ideas","pool", IDEAS_HEADER, rows)`, then for each Inbox row with `id`, finds its inspiration via `inbox_row_id`, writes `status`/`updated` only if changed. Output `ok({"ideas": n, "inbox_updated": n})`. Disabled ⇒ `ok({"skipped": "drive_disabled"})` exit 0 (drivers call it unconditionally). `DriveError` ⇒ JSON error, exit 1 (drivers ignore the exit).

- [ ] **Step 1: Write failing tests** (temp registry via existing test fixtures for ideas/attempts):
  - `test_publish_rows_include_latest_attempt_and_sources`.
  - `test_inbox_status_reflects_refuted_idea` — linked idea refuted with reason ⇒ status contains `#<id> refuted` and the reason.
  - `test_publish_writes_only_changed_inbox_rows`.
  - `test_publish_disabled_is_noop_exit_zero`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/test_idea_publish.py tests/test_module_size_ratchet.py -q && uv run lint-imports` — PASS.
- [ ] **Step 5: Commit** `feat(drive): publish the idea pool mirror and inbox statuses`.

---

### Task 7: Driver wiring

**Files:**
- Modify: `.opencode/scripts/leap.sh`, `.opencode/scripts/forage.sh`, `.opencode/scripts/run-research-loop.sh`
- Test: `tests/test_forage_leap_launchers.py` (extend; uses `--dry-run`)

**Interfaces:**
- Consumes: `research inbox intake`, `research steering export --to`, `research inspirations list --source-kind human`, `research idea publish`.
- Behavior when `ALGUA_DRIVE_FOLDER_ID` is set (unset ⇒ every new block is skipped and the scripts behave as today):
  - **Common:** `STEER_DIR="${RUNS_DIR}/steering-${STAMP}"` (outside the agent `WORKDIR`); after export, `export ALGUA_STEERING_DIR="${STEER_DIR}"`; set `CATEGORIES_FILE="${STEER_DIR}/categories.txt"`, `SOURCES_FILE="${STEER_DIR}/inspirations/_sources.yaml"`, and an `INSPIRATIONS_SRC="${STEER_DIR}/inspirations"` used wherever the script read `${KB_DIR}/inspirations`. Remove `STEER_DIR` on exit (trap).
  - **leap.sh:** (1) `research inbox intake` first — failure logged, run continues; (2) `research steering export` — failure ⇒ `exit 1` with a clear message, before depth/material/agent; (3) depth gate: if the pool is full, proceed anyway when `research inspirations list --status fresh --source-kind human --limit 1` is non-empty (log `depth gate bypassed: fresh owner ideas`); (4) `cp -RL` of inspirations comes from `INSPIRATIONS_SRC`; (5) `research idea publish` at the end, `|| true`.
  - **forage.sh:** export first (failure ⇒ exit 1 before the agent); skip the `SEED_SOURCES` copy block in Drive mode; existing awk/grep/python steering reads use the snapshot paths; `research idea publish` is not needed.
  - **run-research-loop.sh:** `research idea publish || true` once at the end of the run.
  - `--dry-run` prints `would intake/export/publish` lines.

- [ ] **Step 1: Write failing tests** in `tests/test_forage_leap_launchers.py`:
  - `test_leap_dry_run_drive_mode_prints_intake_export_publish_in_order` (env `ALGUA_DRIVE_FOLDER_ID=x`): output order `would intake` < `would export` < `would check depth` < `would publish`.
  - `test_leap_dry_run_without_drive_is_unchanged` — no `intake`/`export`/`publish` lines.
  - `test_forage_dry_run_drive_mode_uses_snapshot_paths` — printed categories/sources paths are under `steering-`.
  - `test_snapshot_dir_is_outside_agent_workdir` — printed `STEER_DIR` is not under the printed worktree path.
- [ ] **Step 2: Run** `uv run pytest tests/test_forage_leap_launchers.py -q` — FAIL.
- [ ] **Step 3: Implement** the shell changes.
- [ ] **Step 4: Run** `uv run pytest tests/test_forage_leap_launchers.py tests/test_ideation_driver_profile.py -q && bash -n .opencode/scripts/leap.sh .opencode/scripts/forage.sh .opencode/scripts/run-research-loop.sh` — PASS.
- [ ] **Step 5: Commit** `feat(ideation): drivers read a Drive snapshot, take in the inbox and publish`.

---

### Task 8: Docs and full check

**Files:**
- Create: `docs/agent/drive.md` (operator setup: bot account, share folder as Editor, OAuth client, `scripts/drive_consent.py`, `drive.json` 0600, env vars in `research.env`, `research steering migrate`, verify Sheets, enable, watch `drive_call` logs, back up and retire `kb/inspirations/*.md`; rollback = unset `ALGUA_DRIVE_FOLDER_ID`)
- Modify: `kb/drive-assets.md` (Drive is the ideation backend for Inbox/Steering/Inspirations/Ideas; still no trading/gate data, still no links to private files), `CLAUDE.md` (steering surfaces line: Steering Sheet in production, files in dev; add the three new commands to the command surface), `deploy/systemd/algua.env.example` (commented `ALGUA_DRIVE_FOLDER_ID`, `ALGUA_DRIVE_CREDENTIALS`), `.opencode/categories.txt` header (production reads the Steering Sheet), `docs/architecture.md` knowledge row (mentions `knowledge/drive`).

- [ ] **Step 1: Write docs** per the list.
- [ ] **Step 2: Run** `uv run pytest -q && uv run ruff check . && uv run mypy algua && uv run lint-imports` — expected all green.
- [ ] **Step 3: Commit** `docs: Drive ideation setup and boundary update`.

---

## Rollout (owner, after merge — not a task)
Per spec §9: create bot account → share `Algua/` → consent → put `drive.json` + `ALGUA_DRIVE_FOLDER_ID` in `research.env` → `uv run algua research steering migrate` → inspect Sheets → watch one forage + leap + research cycle.
