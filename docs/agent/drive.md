# Drive as the ideation backend — operator setup

Design: [`docs/superpowers/specs/2026-11-12-drive-ideation-design.md`](../superpowers/specs/2026-11-12-drive-ideation-design.md).

Only the **ideation** component uses Drive: the owner's Inbox, Steering (categories + venues),
Inspirations and a read-only Ideas mirror. Trading, gates, the registry's authority, capital and
market data never touch it. Everything is off until `ALGUA_DRIVE_FOLDER_ID` is set.

## What lives where

| Sheet (in the `Algua/` folder) | Tabs | Who writes |
|---|---|---|
| `Inbox` | `ideas`: `id`, `idea`, `why / notes`, `links`, `category`, `status`, `updated` | you write `idea`/`why`/`links`/`category`; Algua fills `id`, `status`, `updated` |
| `Steering` | `Categories`: `slug`, `market`, `horizon`, `enabled`, `notes` · `Sources`: venue registry | you; Algua appends forage venue proposals and stamps yields |
| `Inspirations` | `notes`: one row per inspiration note | forage acceptance, inbox intake, leap's mark-used/exhausted |
| `Ideas` | `pool`: one row per idea with its latest outcome | Algua rewrites it after every leap/research run |

Headers are the contract; column order is free. Algua creates a missing Sheet or tab with its
header on first use.

**Inbox rules.** Write one idea per row. Within one leap period (~2h) the row gets an `id` and
`status: taken → inspiration <id>`; later the status shows the idea's fate
(`#17 refuted: walkforward_refuted — …`). Editing a taken row changes nothing; add a new row to
revisit an idea. Clearing a row's `id` cell resubmits it. Owner ideas go through leap like foraged
ones (critic + dedup) but are processed first and skip leap's pool-depth gate.

## One-time setup

1. **Bot account.** Create a Google account for Algua (e.g. a dedicated Gmail). Share the
   `Algua/` Drive folder with it as **Editor** — and nothing else. That share is the boundary.
2. **OAuth client.** In Google Cloud Console (any project): enable the Drive API and Sheets API,
   create an OAuth client of type *Desktop app*, download its JSON.
3. **Consent** on a machine with a browser, signed in as the bot account:
   `python3 scripts/drive_consent.py --client-secrets client_secret.json --out drive.json`
4. **VPS.** Copy `drive.json` to `/home/algua/.config/algua/drive.json` (`chmod 600`, owner
   `algua`) and add to `/home/algua/.config/algua/research.env` — the ideation units' env file,
   **not** the trading lane's:
   ```
   ALGUA_DRIVE_CREDENTIALS=/home/algua/.config/algua/drive.json
   ALGUA_DRIVE_FOLDER_ID=<the Algua folder id from its URL>
   ```
   Never commit either value: this repository is public.
5. **Migrate** today's files (safe to re-run), as the `algua` user from the checkout:
   `uv run algua research steering migrate`
   Then open the Sheets and check Categories, Sources and Inspirations look right.
6. **Watch one cycle** of forage, leap and research: `journalctl -u algua-leap.service` etc. Every
   Drive request logs one JSON `drive_call` line (`op`, `file`, `tab`, `rows`, `ms`, `ok`,
   `status`) — names only, never ids.
7. **Retire the files** once a clean cycle has run: move `kb/inspirations/*.md` and
   `_sources.yaml` to a dated backup directory. `.opencode/categories.txt` stays in the repo as the
   file backend's default for tests and local development.

## Failure behaviour

- Drive unreachable or credentials revoked: the run's snapshot export fails, the run ends before
  any agent call, and the next timer retries. Research claims also pause (they need categories).
- Publish failures never fail a run; the Ideas Sheet is stale until the next one.
- Errors are JSON envelopes: `drive_disabled`, `drive_auth`, `drive_unavailable`,
  `drive_schema` (a required header is missing — the message names the tab and header),
  `drive_http`.

## Rollback

Unset `ALGUA_DRIVE_FOLDER_ID` in `research.env`. Every driver and command returns to the files;
restore them from the backup made in step 7 if you already retired them.

## Commands

- `research inbox intake` — Inbox rows → inspirations (driver: every leap firing).
- `research steering export --to DIR` — run-start snapshot (drivers set `ALGUA_STEERING_DIR`).
- `research steering migrate [--categories-file P] [--from-kb DIR]` — one-time copy into Drive.
- `research idea publish` — Ideas mirror + Inbox statuses (end of leap/research runs).
- `research inspirations list --source-kind human` — the owner's inspirations only.
