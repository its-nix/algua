# algua-monitor — web monitor

A web monitor for the algua fleet, **read-only except the owner's Inbox and push subscriptions**.
Both write paths require the owner identity and same-origin guard (see "Inbox writes"). This directory is a
**standalone uv project** (own `web/uv.lock`) — slice B is the backend: a small
FastAPI app whose only seam to the platform is running the `algua` CLI as a
subprocess and serving its JSON (with a short TTL cache, singleflight, and loud
stale-serving when the CLI fails).

## Run

```sh
# one-time: install web deps (creates web/.venv + web/uv.lock)
uv sync --project web

# run the backend (from the repo root)
uv run --project web python -m backend.main
# or:
uv run --project web uvicorn backend.main:app --host 127.0.0.1 --port 8787
```

Endpoints:

- `GET /api/fleet` — `algua fleet health` rollup (10s cache TTL; serves stale
  with `stale: true` + error metadata if the CLI fails).
- `GET /healthz` — backend liveness.
- `GET /api/research-memory?limit=20` — retained attempt references, including failed/excluded runs.
- `GET /api/research-memory/<cycle>` — archive/checkpoint-verified public worker observations.
- `GET /api/equity?lane=paper|live` — `algua fleet equity`, the P&L-indexed portfolio curve
  (30s cache, like `/api/book`).
- `GET /api/inbox?limit=N` — `algua research inbox list`, items with their journeys (no cache).
- `POST /api/inbox` — owner only. JSON `{"url"?, "text"?, "title"?, "note"?}` (exactly one of
  `url`/`text`) or multipart (`file`, `title?`, `note?`); 201 `{"ok", "item", "duplicate"}`.
- `POST /share` — owner only. The PWA's Web Share Target (`title`, `text`, `url`, `files`);
  303 to `/inbox?shared=1`.

### Inbox writes

The only writes in this app. Each one runs `algua research inbox add` (the Inbox's only writer):

- **Owner check.** A write is accepted only when the `Tailscale-User-Login` header (stamped by
  `tailscale serve`) equals `ALGUA_WEB_OWNER_LOGIN`. With that env unset or blank every write is
  refused (403 `forbidden`). Both write routes also require
  `Sec-Fetch-Site` to be absent, `none` or `same-origin` (`same-site` is refused: every tailnet
  service shares the ts.net site). `/share` logs the value it saw, one line per share, so the
  Android share target's real value can be confirmed from the service log.
- **Uploads** (≤ 20 MB, else 413 `too_large`) are saved to
  `$ALGUA_WEB_INBOX_DIR/<uuid>/<sanitized name>`; unset, that is `<ALGUA_DATA_DIR>/inbox`
  (`ALGUA_DATA_DIR` as the root settings read it, default `data`, relative to the repo). The
  backend does not read the repo's `.env`, so set `ALGUA_DATA_DIR` in the service environment if
  the CLI's data root is not the default.
- **Extraction.** PDF text (pypdf) and text files are passed to the CLI via
  `--extracted-text-file` (a temp file, deleted after the call). Article links are fetched once,
  best effort: http(s) only, every resolved address (and every redirect hop, at most 3, and the
  connected peer) must be public, 5 s total, 2 MB body cap, proxies ignored. x.com, twitter.com,
  youtube.com and youtu.be (and subdomains) are never fetched: the link plus the note is the item.

Open **Research → Open latest result** to inspect archived metrics even when the registered
strategy board is empty. The visible evaluation selector distinguishes parameterized sweeps and
diagnostic benchmarks. Public dated windows show returns, Sharpe and bar counts; legacy missing
windows remain unavailable. **Download retained metrics CSV** includes source references and raw
scalar/window measurements (return/drawdown fractions), with worker evidence and no-authority
labels. These views never import scratch records as gate/lifecycle authority.

When a frontend build exists (`web/frontend/dist/index.html`, overridable via
`ALGUA_WEB_DIST`), the backend also serves it: hashed `/assets/*` with an
immutable cache header, `sw.js`/`manifest.webmanifest` with `no-cache` (so
service-worker updates propagate), and an `index.html` catch-all for deep
links (`/funnel`, `/s/x`). Without a build it runs api-only (logged at
startup). A background poller (interval `ALGUA_WEB_POLL_SECONDS`, default 600)
prewarms the fleet + strategies cache so an idle monitor still opens warm.

## Deploy (systemd + tailscale)

Assumes the repo at `/opt/algua` (matching the other units) and the env file at
`/etc/algua/algua.env` (see `deploy/systemd/README.md`). In order:

1. Root deps — provides `.venv/bin/algua`, the CLI the backend execs:

   ```sh
   cd /opt/algua && uv sync
   ```

2. Web backend deps — provides `web/.venv/bin/uvicorn`:

   ```sh
   uv sync --project web
   ```

3. Frontend build — the `dist/` the backend serves:

   ```sh
   cd web/frontend && npm ci && npm run build
   ```

4. Install and start the service. It is a **system** unit running as its own dedicated user
   (`algua-web`), NOT a user unit and NOT the uid the forage/leap/research agents run as
   (`install-user-units.sh` deliberately does not install it): the owner-header boundary below
   only holds if the agents' uid cannot open the socket.

   ```sh
   sudo useradd --system --no-create-home --shell /usr/sbin/nologin algua-web
   sudo install -m 0640 -o root -g algua-web /dev/null /etc/algua/web.env   # then fill it in:
   #   ALGUA_WEB_OWNER_LOGIN=owner@example.com
   #   ALGUA_DB_PATH=/opt/algua/data/algua.db        # these three MUST equal research.env's
   #   ALGUA_DATA_DIR=/opt/algua/data                #   values, or Inbox items are written
   #   ALGUA_KNOWLEDGE_DIR=/opt/algua/algua-kb       #   where intake never looks
   #   ALGUA_WEB_VAPID_SUB=mailto:ops@example.org    # push contact (optional, see below)
   sudo cp deploy/systemd/algua-web.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now algua-web
   ```

   The unit's DB-access note applies: `algua-web` must be able to read and write the data dir
   (e.g. a shared group with setgid), because SQLite WAL sidecar `-shm`/`-wal` files and the
   idempotent `migrate()` need it even for read-only commands. The unit already provides the
   `/run/algua-web` 0700 socket directory (step 5); for dev, run uvicorn directly (see "Run").

   **Push contact.** `ALGUA_WEB_VAPID_SUB` is the VAPID `sub` claim (a `mailto:` or `https:`
   contact for the push service). It defaults to the non-personal `mailto:admin@localhost`; some
   push services reject a non-routable contact, so set a real one if pushes do not arrive.

5. Tailscale exposure — one-time: enable **MagicDNS** and **HTTPS
   certificates** for the tailnet in the admin console. The backend listens on a **Unix
   socket** in a directory only the service user can open (tailscaled runs as root and still
   can), so no other process on the box can reach it and forge the owner header:

   ```sh
   # algua-web.service creates /run/algua-web (0700, owned by algua-web) and runs uvicorn
   # --uds /run/algua-web/web.sock; for a manual run:
   #   sudo install -d -m 0700 -o algua-web /run/algua-web
   #   sudo -u algua-web env ALGUA_WEB_OWNER_LOGIN=you@example.com \
   #     uv run --project web uvicorn backend.main:app --uds /run/algua-web/web.sock
   tailscale serve --bg https:443 unix:/run/algua-web/web.sock
   ```

   uvicorn chmods the socket itself to `0666`, so the **0700 directory is the boundary**: keep the
   socket inside a directory only the service user (and root) can open, never directly in `/run`
   or `/tmp`. `/run` is tmpfs, so under systemd create that directory with
   `RuntimeDirectory=algua-web` + `RuntimeDirectoryMode=0700` rather than the one-off `install -d`.

   Check first that the installed tailscale accepts a `unix:` target (`tailscale serve --help`;
   recent releases do). If it does not, the spec's fallback applies: a loopback port
   (`--host 127.0.0.1 --port 8787`, `tailscale serve --bg https:443 http://127.0.0.1:8787`) **plus
   a confirmed, tested sandbox network denial for agent runs**, since every local process can
   reach a loopback port and set the header itself.

6. Access the monitor ONLY via `https://<box>.<tailnet>.ts.net`. The service
   worker (and future push) need the ONE stable secure origin — hitting the
   bare tailnet IP is a different origin, which breaks the PWA install, its
   cache, and any notification subscription.

## Network rule

**Production listens on the Unix socket (`--uds`) ONLY. Never bind 0.0.0.0.** Tailnet access
goes through `tailscale serve`, which proxies to the socket and stamps `Tailscale-User-Login`.
Reads have no auth layer (the tailnet is the boundary); writes additionally need that header to
equal `ALGUA_WEB_OWNER_LOGIN`, which is only trustworthy because nothing but tailscaled can reach
the socket. The `--host 127.0.0.1` runs above are for local development.

## Preconditions

- **Prod path:** the backend prefers direct exec of `<repo>/.venv/bin/algua` —
  run root `uv sync` first so that binary exists.
- **Dev fallback:** if `<repo>/.venv/bin/algua` is missing, it falls back to
  `uv run --no-sync algua ...` (slower; logged once at startup).

## Demo build (fixture-served, no backend)

`web/frontend` also ships a **demo** build: a byte-stable, fixture-served bundle for previewing
every screen without a live backend (used by the monitor-redesign harness — `npm run
verify:viewport` renders it headlessly at a 390px mobile viewport). Build it separately from the
real production bundle:

```sh
cd web/frontend
npm run build:demo   # VITE_ALGUA_DEMO=1, outputs dist-demo/
```

The demo transport (`src/transport.ts`) swaps in fixture data (`src/fixtures/`) in place of
`fetch()`; every screen renders identically in both modes because neither knows which one it's
in. **Two guards keep this demo-only and out of the real deploy path:**

1. **The production bundle must never carry fixture data.** `npm run build` (the command the
   deploy steps above run) ends with `node scripts/verify-demo-build.mjs prod dist`, which greps
   the built output for a fixture sentinel string and fails the build if it's present — so a
   stray `VITE_ALGUA_DEMO=1` left set in a shell can't silently ship 14 invented strategies as
   real data. `vite.config.ts` also aliases `./fixtures` away entirely for a non-demo build (a
   Vite plugin that throws at *resolve* time if anything imports it), which is airtight against
   tree-shaking gaps the grep alone could miss.
2. **The demo build must never reach the network.** `demoJSON()` never calls `fetch`, and
   `src/push.ts`'s web-push plumbing (which does call `fetch` directly, bypassing the transport)
   short-circuits to `'unsupported'` whenever `DEMO` is true, so the demo's ENABLE ALERTS control
   never fires a real `Notification.requestPermission()` or `/api/push/*` request.

Run `node scripts/verify-demo-build.mjs demo dist-demo` to confirm the demo build the other way —
that it DOES carry fixture data (an unfixtured demo build would render every screen empty).

## Dependency isolation

Web dependencies (fastapi, uvicorn, httpx, ...) must **NEVER** be added to the
root project: the root `uv.lock` is identity-bearing — its hash is part of the
`dependency_hash` stamped into gate artifacts, so touching it invalidates
promotion identity. All web deps live here, locked in `web/uv.lock`.

Retained attempt rows also show `reported_falsification_assessment` separately from qualification.
This is an advisory worker claim projected from a matching completed operational run digest,
not a gate result or archive-integrity guarantee. Legacy or unmatched reports display `unknown`.
