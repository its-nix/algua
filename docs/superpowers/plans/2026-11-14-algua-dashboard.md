# Algua Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An always-on, owner-only phone dashboard (Home, Strategies, Inbox) on the existing `web/` monitor, with an Inbox table that feeds leap exactly once, shipped in the same release that removes the Drive ideation backend.

**Architecture:** New facts are exposed as read-only `uv run algua …` JSON commands first (`fleet equity`, `research inbox list`), plus one CLI writer (`research inbox add`). The FastAPI backend in `web/` keeps shelling out to the CLI only; it gains its first owner-gated writes (Inbox, share target) behind the `Tailscale-User-Login` header on a Unix socket. The React PWA is re-skinned black with three tabs. Drive code, drivers' Drive branches and docs are deleted; leap's intake reads the new table.

**Tech Stack:** Python 3.12, Typer CLI, SQLite registry (`algua/registry/db/`), FastAPI + uvicorn (`web/`, own `web/uv.lock`), React + Vite + vite-plugin-pwa, bash drivers, systemd, Tailscale serve.

**Spec:** `docs/superpowers/specs/2026-11-14-algua-dashboard-design.md` (approved mockups in `docs/superpowers/specs/assets/2026-11-14-dashboard/`; mockup source at `~/Projects/algua-dashboard-mockups/stage/examples/` for exact spacing).

## Global Constraints

- Web dependencies go in `web/pyproject.toml` / `web/uv.lock` only; never touch the root `pyproject.toml` dependencies or root `uv.lock` (gate identity).
- The web backend never queries the DB or imports `algua`; it only runs the `algua` CLI (`web/backend/algua_cli.py`).
- The dashboard is read-only except `POST /api/inbox` and `POST /share`; no trading, transition, allocation or live actions.
- Owner check: a write is accepted only when header `Tailscale-User-Login` equals env `ALGUA_WEB_OWNER_LOGIN`; missing or different → 403, envelope `{"ok": false, "error": ..., "code": "forbidden"}`.
- Theme: true black `#000` ground, cards `#111113`, raised `#1a1a1d`, hairline `rgba(255,255,255,0.08)`, ink `#ffffff` / `#a1a1a8` / `#6b6b72`, gain `#2fd27a`, loss `#ff5a52`, pending `#f5b13d`, accent `#00a8ff`; Lato from `docs/brand/fonts/`; type scale 34/22/20/17/15/13/12, nothing secondary under 13px. Black-only (no light theme).
- Inspiration notes keep `MAX_NOTE_BYTES` (16384) and `source_kind: human`, `obscurity: human`, `RESERVED_HUMAN_CATEGORY` when no valid category.
- `kb/inspirations/` stays git-ignored runtime data; never commit inspirations or `_sources.yaml`.
- Import-linter contracts and `tests/test_module_size_ratchet.py` must stay green; `lint-imports` count changes only by the removed Drive contract.
- Commit/push only on the feature branch; the deploy (Task 9) touches the VPS only after the owner's go.

## Review Focus

1. The same link submitted twice while the first is still queued → one item (the second `add` returns the existing one, `"duplicate": true`). Test in Task 2.
2. A scanned PDF with no text, or an oversize upload → the item is still created with `text: null` (no text), uploads over 20 MB → 413 with `code: "too_large"`; extracted text is truncated so the note fits `MAX_NOTE_BYTES`. Tests in Tasks 2 and 5.
3. Leap's intake running while the web app adds an item → each item taken exactly once (`mark_taken` is a conditional `UPDATE … WHERE status='queued'`). Test in Task 1.
4. An article URL resolving to a private/loopback address or redirecting there → no fetch, item stored link-only. Test in Task 5.
5. A strategy with no ticks or no passing gate, and a fleet with no strategies → empty states render, `fleet equity` returns `{"points": []}`; no crash. Tests in Tasks 4 and 7.

---

### Task 1: Inbox table and its registry operations

**Files:**
- Create: `algua/registry/db/inbox.py` (SCHEMA fragment), `algua/registry/inbox.py` (operations)
- Modify: `algua/registry/db/schema.py` (assemble fragment), `algua/registry/db/constants.py` (`SCHEMA_VERSION = 54` + changelog line `# v54: inbox_items — the owner's dashboard Inbox (spec 2026-11-14 §7.3).`)
- Test: `tests/test_registry_inbox.py`

**Interfaces:**
- Produces:
  - Table `inbox_items(id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('link','file','text')), url TEXT, canonical_url TEXT, title TEXT, note TEXT, file_path TEXT, text TEXT, status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','taken')), taken_at TEXT, inspiration_id TEXT)`; index on `status`.
  - `add_item(conn, *, kind: str, url: str | None = None, title: str | None = None, note: str | None = None, file_path: str | None = None, text: str | None = None, now: str) -> tuple[dict, bool]`: returns `(item, duplicate)`; a `link` whose `canonical_url` (via `algua.knowledge.inspirations.canonical_url`) matches a still-`queued` item returns that item and `True`.
  - `list_items(conn, *, limit: int = 50) -> list[dict]`: newest first.
  - `queued_items(conn) -> list[dict]`: oldest first.
  - `mark_taken(conn, item_id: int, *, inspiration_id: str, now: str) -> bool`: `True` only if it flipped a `queued` row.

- [ ] **Step 1: Write the failing tests** in `tests/test_registry_inbox.py` against an in-memory migrated DB (`connect(":memory:")` + `migrate`, as `tests/test_cli_registry.py` does):

```python
def test_add_then_list_newest_first(conn):
    a, _ = add_item(conn, kind="link", url="https://x.com/a/status/1", now="2026-11-14T10:00:00Z")
    b, _ = add_item(conn, kind="text", text="buy the dip in small caps", now="2026-11-14T11:00:00Z")
    assert [i["id"] for i in list_items(conn)] == [b["id"], a["id"]]
    assert a["status"] == "queued"

def test_same_link_while_queued_is_one_item(conn):
    a, dup1 = add_item(conn, kind="link", url="https://Example.com/p?utm_source=x", now="t1")
    b, dup2 = add_item(conn, kind="link", url="https://example.com/p", now="t2")
    assert (dup1, dup2) == (False, True) and b["id"] == a["id"]

def test_mark_taken_flips_once(conn):
    a, _ = add_item(conn, kind="text", text="x", now="t1")
    assert mark_taken(conn, a["id"], inspiration_id="2026-11-14-inbox-x-abc123", now="t2") is True
    assert mark_taken(conn, a["id"], inspiration_id="other", now="t3") is False
    assert queued_items(conn) == []

def test_schema_version_is_54():
    assert SCHEMA_VERSION == 54
```

- [ ] **Step 2: Run** `uv run pytest tests/test_registry_inbox.py -q`. Expected: FAIL (`ModuleNotFoundError: algua.registry.inbox`). If `canonical_url` does not strip `utm_*` and lowercase the host, pick URLs in the duplicate test that it does normalize, and note it.
- [ ] **Step 3: Implement** the fragment, its assembly in `schema.py`, the version bump, and the four functions. `mark_taken` is one `UPDATE inbox_items SET status='taken', taken_at=?, inspiration_id=? WHERE id=? AND status='queued'`, returning `rowcount == 1`.
- [ ] **Step 4: Run** `uv run pytest tests/test_registry_inbox.py tests/test_cli_registry.py -q && uv run lint-imports`. Expected: PASS; contracts kept.
- [ ] **Step 5: Commit** `feat(registry): inbox_items table for the owner's dashboard Inbox (v54)`.

### Task 2: `research inbox add | list | intake` on the table and the files vault

**Files:**
- Create: `algua/knowledge/inbox_notes.py` (pure note builder)
- Modify: `algua/cli/inbox_cmd.py` (rewrite), `algua/knowledge/inspirations.py` (add `write_note`), `algua/registry/idea_publish_rows.py` → rename to `algua/registry/idea_links.py`, keeping only `ideas_by_inspiration(conn)` (delete `publish_rows`, `IDEAS_HEADER`, `inbox_status`)
- Test: `tests/test_cli_inbox.py`, `tests/test_inbox_notes.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces:
  - `build_note(item: dict, *, today: date, categories: set[str]) -> tuple[dict, str]` in `inbox_notes.py`. The note id is `f"{today.isoformat()}-inbox-{slug}-{sha1(str(item['id']))[:6]}"`, where the slug comes from title, else note, else url, else text. Frontmatter carries today's Drive fields with `source_url = item['url'] or f"inbox:{item['id']}"`, `venue: "inbox"` and `inbox_item_id: item['id']`. The body has `## Idea` (title or note), `## Why / notes` (note), `## Link` (url) and `## Extracted text` (text), truncated to fit `MAX_NOTE_BYTES` (reuse the Drive `_fit` logic, moved here).
  - `write_note(settings, fm: dict, body: str) -> Path` in `inspirations.py`: atomic write of `render_doc(fm, body)` to `inspirations_dir(settings) / f"{fm['id']}.md"`; refuses to overwrite.
  - CLI:
    - `research inbox add (--url U | --file PATH | --text T) [--title T] [--note N] [--extracted-text-file F]` emits `{"ok": true, "item": {...}, "duplicate": bool}`.
    - `research inbox list [--limit N]` emits `{"ok": true, "items": [{..., "journey": [{"label": str, "tone": "pending"|"progressed"|"refuted"|"neutral"}]}]}`.
    - `research inbox intake` emits `{"ok": true, "taken": [inspiration_id, ...]}`.
  - Journey labels:
    - `queued` → `[{"label": "Queued for the next leap", "tone": "pending"}]`.
    - `taken` with no idea → `[{"label": "Inspiration", "tone": "neutral"}]`.
    - With idea #N → `+ {"label": "Idea #N", ...}`, then the idea's outcome: `Backtested` (neutral), `Candidate` (progressed), `Refuted: <reason>` (refuted) or `Duplicate of idea #M` (neutral). The last entry is toned and the others are neutral.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_inbox_notes.py`:
    - `test_note_id_is_stable_and_valid` checks the id against `NOTE_ID_RE` and checks that two calls give the same id;
    - `test_unknown_category_falls_back_to_reserved`;
    - `test_long_extracted_text_fits_max_note_bytes` (a 100 KB text gives `len(render_doc(fm, body).encode()) <= MAX_NOTE_BYTES`);
    - `test_link_only_item_has_link_section`.
  - `tests/test_cli_inbox.py`, using the CLI runner + tmp `ALGUA_KNOWLEDGE_DIR` and DB, like `tests/test_cli_inspirations.py`:

```python
def test_add_list_intake_exactly_once(cli, tmp_vault):
    r = cli("research", "inbox", "add", "--url", "https://youtu.be/abc", "--note", "index deletions rebound")
    assert r["ok"] and r["duplicate"] is False
    assert cli("research", "inbox", "list")["items"][0]["journey"][0]["tone"] == "pending"
    first = cli("research", "inbox", "intake")["taken"]
    assert len(first) == 1 and (tmp_vault / f"{first[0]}.md").exists()
    assert cli("research", "inbox", "intake")["taken"] == []
    assert cli("research", "inbox", "list")["items"][0]["journey"][0]["label"] == "Inspiration"

def test_add_requires_exactly_one_source(cli):
    assert cli("research", "inbox", "add")["code"] == "invalid_input"

def test_file_with_no_text_is_still_added(cli, tmp_path):
    f = tmp_path / "scan.pdf"; f.write_bytes(b"%PDF-1.4 no text")
    r = cli("research", "inbox", "add", "--file", str(f))
    assert r["ok"] and r["item"]["text"] is None
```

  The fixture names follow the existing CLI test helpers; adapt them to whatever `tests/test_cli_inspirations.py` uses.
- [ ] **Step 2: Run** `<linux test runner> tests/test_inbox_notes.py tests/test_cli_inbox.py -q`. CLI tests need Linux (`os.waitid`); use the repo's container runner or the VPS. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `add` stores `kind` from the flag. `--file` stores the given path as `file_path`.
  - `--extracted-text-file` lets the web backend pass extracted text without shell-quoting a large string, and the CLI reads it as UTF-8.
  - `intake` loads categories from `categories_file_default()`. For each `queued_items` row it builds and writes the note, then calls `mark_taken`. A note write that fails leaves the item queued and adds `{"item": id, "error": ...}` to `warnings`.
- [ ] **Step 4: Run** the step 2 command plus `uv run pytest tests/test_knowledge_inspirations.py tests/test_idea_publish.py -q`. `test_idea_publish.py` is deleted in Task 3; until then, delete only its `publish_rows` cases. Expected: PASS.
- [ ] **Step 5: Commit** `feat(inbox): research inbox add/list/intake on the inbox table`.

### Task 3: Remove the Drive backend; leap takes the Inbox in on every firing

**Files:**
- Delete:
  - code: `algua/knowledge/drive/` (all), `algua/cli/_drive.py`, `algua/cli/steering_cmd.py`, `algua/cli/idea_publish_cmd.py`, `scripts/drive_consent.py`;
  - tests: `tests/_drive_fake.py`, `tests/test_drive_*.py`, `tests/test_cli_drive.py`, `tests/test_idea_publish.py`, `tests/test_categories_steering.py`;
  - docs: `docs/agent/drive.md`.
- Modify:
  - `algua/cli/main.py` (unmount steering/publish);
  - `algua/cli/errors.py` (drop `_drive_fault` and `drive_*` codes; `drive_unavailable` leaves `RETRYABLE_CODES`);
  - `algua/config/settings.py` (drop `drive_folder_id`, `drive_credentials`, `steering_dir`);
  - `algua/knowledge/inspirations.py` (`inspirations_dir` no longer honours `steering_dir`; drop the injected `store=` parameters and the Sheet branch in `accept_new_notes`);
  - `algua/knowledge/sources_registry.py` (drop the `backend=` seam);
  - `algua/cli/inspirations_cmd.py` (drop store injection);
  - `algua/research/categories.py` (drop the `ALGUA_STEERING_DIR` read);
  - `pyproject.toml` (delete the "only the cli composes the Drive ideation backend" contract);
  - `.opencode/scripts/leap.sh`, `forage.sh`, `run-research-loop.sh` (§ below);
  - `deploy/systemd/algua.env.example` (drop Drive vars);
  - `.opencode/categories.txt` (drop the Drive header note);
  - `CLAUDE.md` (replace the Drive bullet with a Dashboard bullet: Inbox via `research inbox add/list/intake`, dashboard in `web/`);
  - `docs/architecture.md`, `docs/contracts/cli-error-envelope.md`;
  - `kb/drive-assets.md` (delete the "Exception: the ideation backend" section);
  - `.gitignore` (keep `drive.json`/`client_secret*.json` lines: harmless backstop);
  - `PRIVACY.md` stays until the owner revokes the Google app (Task 9), then is deleted with its hygiene whitelist entry.
- Keep: `run_agent.sh`'s Drive env stripping and credential mask (still correct, harmless); `source_kind: human` vocabulary; `--source-kind`/`--found-since` on `inspirations list`.
- Test: `tests/test_forage_leap_launchers.py`, `tests/test_agent_runtime_seam.py`, `tests/test_knowledge_inspirations.py`, `tests/test_cli_inspirations.py`

**Interfaces:**
- Consumes: `research inbox intake` (Task 2).
- Produces:
  - `leap.sh` always runs `uv run algua research inbox intake` before the depth gate; a failure warns and continues.
  - The depth-gate bypass for fresh human notes found in the last 2 days applies unconditionally (no `DRIVE` flag).
  - No steering export, no `ALGUA_STEERING_DIR`, no publish.
  - `forage.sh` reads `.opencode/categories.txt` and the vault's `_sources.yaml` as before #817.
  - `run-research-loop.sh` has no publish.

- [ ] **Step 1: Rewrite the launcher tests first.**
  - In `tests/test_forage_leap_launchers.py`, replace the Drive-mode tests with:
    - `test_leap_dry_run_intakes_inbox_before_depth_check`: `out.index("would intake owner inbox via: uv run algua research inbox intake") < out.index("would check depth: ")`;
    - `test_leap_has_no_drive_branches`: the source contains none of `ALGUA_DRIVE_FOLDER_ID`, `steering export`, `idea publish`, `STEER_DIR`;
    - `test_leap_human_ideas_bypass_depth_gate_unconditionally`: the source contains `--source-kind human`, `--found-since` and `depth gate bypassed`, but not `DRIVE:-0`;
    - `test_forage_has_no_drive_branches`;
    - `test_research_loop_has_no_publish`.
  - Delete the Drive cases in `tests/test_knowledge_inspirations.py` and `tests/test_cli_inspirations.py` (store injection, steering_dir).
- [ ] **Step 2: Run** `<linux test runner> tests/test_forage_leap_launchers.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Delete and edit** per Files. For `leap.sh`, the intake block replaces lines 85–110 of today's Drive block. The dry-run line is exactly `would intake owner inbox via: uv run algua research inbox intake`.
- [ ] **Step 4: Run** the full check.
  - Command: `uv run ruff check . && uv run lint-imports && uv run mypy algua`, plus `<linux test runner> tests/test_forage_leap_launchers.py tests/test_ideation_driver_profile.py tests/test_agent_runtime_seam.py tests/test_knowledge_inspirations.py tests/test_cli_inspirations.py tests/test_cli_inbox.py tests/test_repo_hygiene.py tests/test_module_size_ratchet.py -q`.
  - Expected: PASS. `lint-imports` reports one fewer contract than before.
  - Also expected: `git grep -niE "knowledge\.drive|ALGUA_DRIVE_FOLDER|steering export|idea publish" -- ':!docs/superpowers' ':!.opencode/scripts/run_agent.sh' ':!tests/test_agent_runtime_seam.py'` prints nothing.
- [ ] **Step 5: Commit** `refactor(ideation): remove the Drive backend; leap takes in the dashboard Inbox`.

### Task 4: `fleet equity`, the P&L-indexed portfolio curve

**Files:**
- Create: `algua/portfolio/equity_curve.py` (pure aggregation), or the nearest existing read module if a portfolio package rule forbids it; record that as a Ruling.
- Modify: `algua/cli/fleet_cmd.py` (command)
- Test: `tests/test_equity_curve.py`, `tests/test_cli_fleet_equity.py`

**Interfaces:**
- Consumes: `tick_snapshot_series(conn, strategy_id, name, lane=, since=, limit=)` in `algua/execution/order_state.py` (rows: `tick_ts`, `equity`, `lane`).
- Produces:
  - `pnl_curve(series_by_strategy: dict[str, list[dict]]) -> list[dict]`: returns `[{"session": "YYYY-MM-DD", "pnl": float, "equity": float}]`, ascending.
    - Per strategy and lane, a tick's P&L is `equity_t − equity_{t−1}`, taken over consecutive ticks in that lane.
    - The first tick of a strategy/lane contributes 0. That is entry, not profit.
    - A session's P&L is the sum across strategies, and `pnl` is cumulative from the first session.
    - `equity` is the sum of each strategy's latest equity as of that session.
  - CLI `fleet equity [--lane paper|live] [--since D]` emits `{"ok": true, "lane_filter": ..., "points": [...], "current_equity": float, "change_today": float}`. The lane filter is applied before aggregation. With no strategies it emits `"points": []`, `current_equity: 0.0` and `change_today: 0.0`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_allocation_entry_is_not_profit():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-02", 1010)],
         "b": [tick("2026-11-02", 500)]}           # b enters on the 2nd with 500
    pts = pnl_curve(s)
    assert [p["pnl"] for p in pts] == [0.0, 10.0]   # b's 500 is not a gain
    assert pts[-1]["equity"] == 1510.0

def test_loss_shows_negative():
    assert pnl_curve({"a": [tick("d1", 1000), tick("d2", 980)]})[-1]["pnl"] == -20.0

def test_empty_fleet():
    assert pnl_curve({}) == []
```

  Plus `test_cli_fleet_equity_empty_db_returns_empty_points` (CLI, Linux).
- [ ] **Step 2: Run** `uv run pytest tests/test_equity_curve.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** The session is the UTC date of `tick_ts`. Multiple ticks in a session keep the last. Iterate strategies with `SqliteStrategyRepository(conn).list()` filtered to stages with ticks (paper, forward_tested, live, plus any with series).
- [ ] **Step 4: Run** `uv run pytest tests/test_equity_curve.py -q && <linux test runner> tests/test_cli_fleet_equity.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(fleet): fleet equity, a P&L-indexed portfolio curve`.

### Task 5: Web backend: Inbox writes, owner check, extraction, equity, Unix socket

**Files:**
- Create: `web/backend/owner.py` (owner check dependency), `web/backend/extract.py` (PDF text + article fetch)
- Modify: `web/backend/main.py` (routes), `web/backend/algua_cli.py` (no change expected; reuse `run_cli`), `web/pyproject.toml` + `web/uv.lock` (add `pypdf`, `python-multipart`; `httpx` exists), `web/README.md` (run with `--uds`, owner env)
- Test: `web/backend/tests/test_inbox_api.py`, `web/backend/tests/test_extract.py`

**Interfaces:**
- Consumes: `research inbox add/list` (Task 2), `fleet equity` (Task 4).
- Produces:
  - `GET /api/equity?lane=` wraps `fleet equity`, cached like `/api/book`.
  - `GET /api/inbox` wraps `research inbox list` with no cache.
  - `POST /api/inbox` takes either JSON `{"url"?, "text"?, "title"?, "note"?}` or multipart (`file`, `note?`). It returns 201 with the CLI's item.
  - `POST /share` takes a multipart Web Share Target form with fields `title`, `text`, `url` and `files`. It returns a 303 redirect to `/inbox?shared=1`.
  - `require_owner(request) -> None` raises 403 `forbidden` unless `request.headers.get("Tailscale-User-Login") == os.environ["ALGUA_WEB_OWNER_LOGIN"]`. When the env is unset, every write is refused.
  - Uploads are saved to `$ALGUA_WEB_INBOX_DIR/<uuid>/<sanitized name>`; when unset the default is `<ALGUA_DATA_DIR>/inbox`. Over 20 MB → 413 `too_large`.
  - `extract_pdf_text(path) -> str | None` uses pypdf and returns `None` when the text is empty.
  - `fetch_article(url) -> tuple[str | None, str | None]` returns `(title, text)`. It allows http(s) only. It resolves the host and refuses private, loopback, link-local and reserved addresses, including after each redirect (max 3). It times out after 5 s and caps the body at 2 MB. `x.com`/`twitter.com`/`youtube.com`/`youtu.be` return `(None, None)` without fetching.
  - Extracted text reaches the CLI through `--extracted-text-file` (a temp file deleted after the call).

- [ ] **Step 1: Write the failing tests** (FastAPI `TestClient`, CLI stubbed the way `web/backend/tests/test_api.py` stubs `run_cli`):

```python
def test_write_without_owner_header_is_403(client, monkeypatch):
    monkeypatch.setenv("ALGUA_WEB_OWNER_LOGIN", "owner@example.com")
    r = client.post("/api/inbox", json={"url": "https://example.com/a"})
    assert r.status_code == 403 and r.json()["code"] == "forbidden"

def test_write_with_wrong_owner_is_403(client, monkeypatch): ...
def test_write_refused_when_owner_env_unset(client, monkeypatch): ...

def test_owner_link_calls_cli_add(client, owner, cli_calls):
    r = client.post("/api/inbox", json={"url": "https://x.com/a/status/1", "note": "why"}, headers=owner)
    assert r.status_code == 201
    assert cli_calls[-1][:4] == ["research", "inbox", "add", "--url"]

def test_upload_over_20mb_is_413(client, owner): ...
def test_share_target_redirects_to_inbox(client, owner):
    r = client.post("/share", data={"url": "https://youtu.be/x", "title": "t"}, headers=owner, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/inbox?shared=1"
```

  `test_extract.py`:
  - `test_private_address_is_not_fetched` (monkeypatch DNS → `127.0.0.1`, assert no request made);
  - `test_redirect_to_private_is_refused`;
  - `test_x_and_youtube_are_not_fetched`;
  - `test_pdf_without_text_returns_none`;
  - `test_body_cap`.
- [ ] **Step 2: Run** `uv run --project web pytest web/backend/tests -q`. Expected: the new tests FAIL; the existing ones PASS.
- [ ] **Step 3: Implement** the files above; `uv add --project web pypdf python-multipart`.
- [ ] **Step 4: Run** `uv run --project web pytest web/backend/tests -q && git diff --quiet -- uv.lock pyproject.toml`. Expected: all PASS, and the root lock/pyproject are unchanged.
- [ ] **Step 5: Commit** `feat(web): owner-gated Inbox and share target, article/PDF extraction, equity API`.

### Task 6: Frontend: black theme, three tabs, Home

**Files:**
- Modify: `web/frontend/src/theme.css` (black tokens per Global Constraints, both schemes), `web/frontend/src/App.tsx` (`PRIMARY_LINKS` → Home `/`, Strategies `/strategies`, Inbox `/inbox`; Inbox badge), router file (where routes are declared), `web/frontend/vite.config.ts` (`theme_color`/`background_color` `#000000`)
- Create: `web/frontend/src/screens/Home.tsx`, `web/frontend/src/components/EquityLine.tsx` (port of the mockup's `Line`: min/max scaling, dotted base line, end dot + halo with 18px right inset, optional fill, light moving-average smoothing), fixtures for the demo build
- Test: `web/frontend/src/screens/Home.test.tsx`, `web/frontend/src/components/EquityLine.test.tsx`

**Interfaces:**
- Consumes: `/api/equity`, `/api/triage`, `/api/book`, `/api/strategies`.
- Produces:
  - `EquityLine({ data: number[], width, height, color, base?, fill?, dashed?, lo?, hi?, dot? })`, reused in Task 7.
  - Home layout per `assets/2026-11-14-dashboard/home.jpg`:
    - logo and lane picker ("Paper + live", "Paper", "Live");
    - "Portfolio equity" and the big number;
    - the change line, with the arrow green or red by sign;
    - the curve, plus range pills 1W/1M/3M/YTD/1Y/All (3M default);
    - attention card, only when triage has items;
    - Capital card;
    - Strategies stage-count tiles linking to `/strategies`.

- [ ] **Step 1: Write the failing tests:**
  - `Home renders big number and curve from fixture equity`;
  - `Home shows no attention card when triage is empty`;
  - `Home shows empty state "No equity yet" when points is []`;
  - `EquityLine end dot stays inside width` (the dot's `cx + 8 <= width`);
  - `range pill switch filters points by date`.
- [ ] **Step 2: Run** `cd web/frontend && npm test -- --run Home EquityLine`. Expected: FAIL.
- [ ] **Step 3: Implement.** The existing Leaderboard/Research screens move under `/strategies/research` (routes kept, links from the Strategies segment in Task 7). The old Money screen route redirects to `/`.
- [ ] **Step 4: Run** `cd web/frontend && npm run check && npm test -- --run && npm run build && npm run build:demo && npm run verify:viewport`. Expected: PASS; the demo build renders Home at 390px.
- [ ] **Step 5: Commit** `feat(web): black theme, Home/Strategies/Inbox tabs, Home screen`.

### Task 7: Frontend: Strategies list and Strategy page

**Files:**
- Create: `web/frontend/src/screens/Strategies.tsx`
- Modify: `web/frontend/src/screens/StrategyDetail.tsx` (re-layout per `detail.jpg`; keep the existing evidence sections below the new top), fixtures
- Test: `web/frontend/src/screens/Strategies.test.tsx`, `StrategyDetail.test.tsx` additions

**Interfaces:**
- Consumes: `EquityLine` (Task 6), `/api/strategies`, `/api/strategy/{name}`, `/api/strategy/{name}/series`.
- Produces:
  - **Strategies** layout:
    - segments Operating / Candidates / Research (Research shows the moved Leaderboard/Research views);
    - Operating groups Live, Forward tested and Paper;
    - each row shows the name (one line, ellipsis), "Day N · $slice slice", a 60×32 sparkline (green/red by sign, dotted base), the value and a P&L chip.
  - **Strategy page** layout:
    - back "Strategies", name and stage chip;
    - big value and "since <stage> · <date>";
    - the curve with right-side y labels (max/mid/min), and the dashed **expected** line;
    - a segmented control: 1W / 1M / Since <stage> / Backtest;
    - three metric cells (Sharpe vs backtest, max drawdown vs limit, volatility vs backtest);
    - the next-gate card with sessions progress and each check (value, pass/fail);
    - then the existing sections.
  - The expected line uses the newest passing research gate row in `/api/strategy/{name}` `gates`: `daily = (1 + total_return_oos) ** (1 / n_obs_oos) - 1`, compounded from the first point. It is hidden when the fields are missing.
    - Step 1 also checks `uv run algua registry gates <name>` returns `total_return_oos` and `n_obs_oos`.
    - If it does not, add them to that command's JSON first (CLI change + test) and record a Ruling.

- [ ] **Step 1: Write the failing tests:**
  - `Strategies groups operating rows by stage in order Live, Forward tested, Paper`;
  - `negative P&L chip is red`;
  - `StrategyDetail draws expected line from passing gate`;
  - `StrategyDetail hides expected line when gate fields missing`;
  - `StrategyDetail with no ticks shows "No ticks yet"`;
  - `gate card shows 41 of 63 sessions from fixture`.
- [ ] **Step 2: Run** `cd web/frontend && npm test -- --run Strategies StrategyDetail`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Task 6 step 4 command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): Strategies list and Strategy page with expected-vs-actual`.

### Task 8: Frontend: Inbox screen and Android share target

**Files:**
- Create: `web/frontend/src/screens/Inbox.tsx`
- Modify: `web/frontend/vite.config.ts`, adding to the manifest `share_target: { action: '/share', method: 'POST', enctype: 'multipart/form-data', params: { title: 'title', text: 'text', url: 'url', files: [{ name: 'files', accept: ['application/pdf', 'text/*', 'image/*'] }] } }`. Also the `sw.ts` navigation fallback must not swallow `POST /share`. Fixtures.
- Test: `web/frontend/src/screens/Inbox.test.tsx`, `web/frontend/src/pwa-assets.test.ts` addition

**Interfaces:**
- Consumes: `GET/POST /api/inbox`, `/share` (Task 5).
- Produces:
  - Inbox layout per `inbox.jpg`:
    - title "Inbox" and the line "Everything you send feeds the next leap run.";
    - a list card where each row has a 40px source tile (Play for youtube, chat for x.com, document for files, link otherwise), the title (falling back to the URL host + path), "domain · relative time", and journey chips toned pending (amber) / progressed (green) / refuted (red) / neutral;
    - the tip card "Share straight from any app" (Android only; hidden on iOS);
    - a composer pinned above the tabs: paperclip (file input), field "Paste a link or drop a file", send.
  - A pasted URL becomes `{url}`, other text becomes `{text}`, and a file is sent as multipart.
  - After a send, the list refetches. `?shared=1` shows a toast "Added to Inbox".

- [ ] **Step 1: Write the failing tests:**
  - `pasting a URL posts {url}`;
  - `plain text posts {text}`;
  - `403 shows "Only the owner can add to the Inbox"`;
  - `chips use tone colors`;
  - `?shared=1 shows toast`;
  - in `pwa-assets.test.ts`: `manifest declares share_target POST /share multipart`.
- [ ] **Step 2: Run** `cd web/frontend && npm test -- --run Inbox pwa-assets`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the Task 6 step 4 command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): Inbox screen and Android share target`.

### Task 9: Cut-over on the VPS (owner go required)

**Files:**
- Create: `deploy/systemd/algua-web.service` (or modify the existing one) so uvicorn runs `--uds /run/algua-web/web.sock` with `RuntimeDirectory=algua-web`, `RuntimeDirectoryMode=0700` and `User=algua-web`; `deploy/systemd/README.md` section "Dashboard".
- Modify after revocation: delete `PRIVACY.md` and its whitelist entry in `tests/test_repo_hygiene.py`.

**Interfaces:**
- Consumes: everything above, merged to `main` with the owner's go.

- [ ] **Step 1: Port Drive → files with the OLD code, before pulling.** As `algua` on the VPS, with `research.env` loaded:
  - run `uv run algua research steering export --to /tmp/drive-port` and record its counts;
  - copy `inspirations/*.md` and `inspirations/_sources.yaml` into the runtime vault, without overwriting newer same-id files;
  - diff `categories.txt` against `.opencode/categories.txt`;
  - list untaken Drive Inbox rows (rows with an idea and an empty `status`) to re-add later.

  Expected: the vault's note count is at least the export's notes, and its venues count equals the export's venues.
- [ ] **Step 2: Pull, migrate, verify.**
  - Wait until no algua unit is active.
  - `git merge --ff-only origin/main`, then `uv sync`.
  - `uv run algua registry list` must succeed; the DB is migrated to v54.
  - Remove the `ALGUA_DRIVE_*` lines from `research.env` (back up first) and delete `drive.json`.
  - Re-add any untaken Drive Inbox rows with `research inbox add --text …`.
- [ ] **Step 3: Dashboard service.**
  - Create the `algua-web` user, readable access to the checkout and DB as the README's DB-access note requires; `uv sync --project web`; `cd web/frontend && npm ci && npm run build`.
  - Install the unit with `ALGUA_WEB_OWNER_LOGIN=<owner's tailnet login>`, then `systemctl enable --now algua-web`.
  - `tailscale serve --bg --https=443 unix:/run/algua-web/web.sock`. If this tailscale version refuses Unix targets, stop and use the spec's fallback: a loopback port plus a tested agent network denial. Record that as a Ruling.
- [ ] **Step 4: Verify on the owner's phone.**
  - Home shows real equity.
  - A link, a PDF and an Android share each appear in the Inbox.
  - `curl --unix-socket /run/algua-web/web.sock -X POST -H 'Tailscale-User-Login: x' localhost/api/inbox` as user `algua` fails with "Permission denied".
  - After the next leap firing, each item shows "Inspiration". The journal shows `research inbox intake`, with `taken` listing each once.
- [ ] **Step 5: Owner actions (list them; the assistant does not perform them):**
  - revoke "Algua" at myaccount.google.com → Security → Third-party access;
  - optionally delete the Google Cloud project and the `My Drive/Nix/Ventures/Algua/Ideation` folder.

  Then commit the `PRIVACY.md` removal: `chore: remove the Google app privacy note (app revoked)`.
