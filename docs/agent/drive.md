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

Headers are the contract; column order is free, and you may add your own columns. Renaming or
deleting a required column (`id`/`idea` in Inbox, `slug` in Categories, `key` in Sources, `id` in
Inspirations) stops runs with a `drive_schema` error naming the tab and column — rename it back.

**Never create, copy, re-upload or duplicate these Sheets yourself.** Algua's token can only see
files Algua created (`drive.file`, see below): a Sheet you make by hand — even one named `Inbox` —
is invisible to it, and two Sheets with the same name in the folder is a `drive_schema` error.
Edit the ones Algua made.

**Inbox rules.** Write one idea per row. Within one leap period (~2h) the row gets an `id` and
`status: taken → inspiration <id>`; later the status shows the idea's fate
(`#17 refuted: walkforward_refuted — …`). Editing a taken row changes nothing; add a new row to
revisit an idea. Clearing a row's `id` cell resubmits it. Owner ideas go through leap like foraged
ones (critic + dedup), are processed first, and skip leap's pool-depth gate for 2 days after they
are taken in. Don't sort or delete Inbox rows while a leap run is taking them in.

## How access works

- **Your own Google account**, so everything Algua creates is owned by you and uses your storage.
- **Narrow permission (`drive.file`)**: the token can read and change only files *this app*
  created — its own `Algua` folder and the Sheets in it. The rest of your Drive is invisible to it.
- **One OAuth client per component** inside one Google Cloud project: `algua-ideation` now; a
  future backup job gets its own client, and neither can see the other's files.
- **Agents never hold the token**: the agent runtime seam strips the Drive variables and masks the
  credential file inside the sandbox; only the trusted driver scripts call Drive.

## One-time setup

1. **Google Cloud project** (one for all of Algua): enable the *Google Drive API* and *Google
   Sheets API*. Configure the Google Auth Platform: External audience, your email as support and
   developer contact, home page `https://github.com/its-nix/algua`, privacy policy
   `https://github.com/its-nix/algua/blob/main/PRIVACY.md`, authorised domain `github.com`.
   **Publish the app** (Audience → Publish app). While it is in *Testing*, Google expires refresh
   tokens after 7 days and every run fails with `drive_auth`. `drive.file` needs no Google review;
   you will see an "unverified app" notice once, at consent.
2. **OAuth client**: Clients → Create → *Desktop app* named `algua-ideation`. Save the client JSON
   **outside the repository**, owner-only, e.g. `~/.config/algua/algua-ideation-client.json`
   (`chmod 600`). `client_secret*.json` and `drive.json` are gitignored as a backstop.
3. **Consent** on a machine with a browser (signed in as you), from the checkout:
   ```
   python3 scripts/drive_consent.py \
     --client-secrets ~/.config/algua/algua-ideation-client.json \
     --out ~/.config/algua/drive.json --create-folder Algua
   ```
   Click **Allow** after checking it asks only for "Drive files that you use with this app". The
   script writes the token (mode 0600) and creates Algua's own `Algua` folder, printing
   `ALGUA_DRIVE_FOLDER_ID=...`. Re-running consent later (e.g. after revoking access) omits
   `--create-folder` and keeps the same folder.
4. **VPS.** Copy `drive.json` to `/home/algua/.config/algua/drive.json` (`chmod 600`, owner
   `algua`) and add to `/home/algua/.config/algua/research.env` — the ideation units' env file,
   **not** the trading lane's:
   ```
   ALGUA_DRIVE_CREDENTIALS=/home/algua/.config/algua/drive.json
   ALGUA_DRIVE_FOLDER_ID=<printed by step 3>
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

- Drive unreachable, credentials revoked, or the app left in Testing (7-day token): the run's snapshot export fails, the run ends before
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
