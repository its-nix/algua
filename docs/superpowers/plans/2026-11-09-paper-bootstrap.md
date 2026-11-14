# Paper bootstrap implementation plan

> For agentic workers: use the existing isolated checkout and proportional tests. Implement the independent tasks below concurrently, then integrate and deploy the exact checked commit.

**Goal:** deploy the corrected research system and prepare a bounded, isolated Alpaca paper mechanics path.

**Architecture:** retain the existing CLI, broker, risk and event/recovery seams. Reject newer registry schemas before migration work; use a distinct mechanics ledger so no mechanics event can become research, strategy, paper-session, qualification or live evidence. Separate the immutable paper application/anchor and paper credential user from the mutable research checkout.

**Tech stack:** existing Python 3.12/uv, SQLite, Typer, Alpaca paper REST adapter and systemd.

**Spec:** `docs/agent/paper-mechanics-smoke.md` and the private `PAPER_RELEASE_PREFLIGHT.md`; owner approved implementation and deployment on 2026-11-09. This approval supplies no live signature, funding, gate relaxation or forged data authority.

## Constraints and review focus

- Paper-only endpoint and exact expected account, one permitted symbol from the approved midcap sample, USD 5 maximum cumulative opening purchase for the approved smoke; no borrowing/shorts.
- Persist the original intent/client-order ID before submission. Uncertain acceptance is recovered under that identity; no second opening order or fresh-ID retry.
- Require isolated paths/account and empty baseline; unexpected holdings/orders/activity fail closed. Exits may only reduce verified actual held shares.
- Keep signed risk-policy requirements and account guard checks; absent credentials/policy leave the command ready but blocked, never silently bypass them.
- No schema version bump for the refusal guard; old/current partial schemas still bootstrap. Refusal occurs before schema writes and preserves newer contents.
- Coordinate all active registry/tracking writers for migration. Never run old v49 code after v52 cutover or old MLflow against a migrated archive.
- Preserve snapshots, original retained receipts/checkpoints, logs and consistent backups. No blind database restore after new activity. Live/paper strategy timers and merge-back remain disabled unless separately applicable; a manual mechanics smoke earns zero forward credit.

## Tasks

1. **Registry compatibility guard:** add a red regression in `tests/test_registry_db.py` for a newer marker with sentinel data/schema; make `algua/registry/db/migrate.py::migrate` refuse before any bootstrap SQL, retaining existing current/pre-stamped/legacy tests and CLI JSON behavior. Focused checks, then commit.
2. **Paper mechanics command:** add focused execution/state and CLI modules/tests; compose under `paper mechanics` in `algua/cli/main.py`. Reuse `AlpacaPaperBroker` sizing/lookup/cancel, store a private durable single-opening budget/identity, verify expected account and signed risk guard, and expose account/init/step/status/close operations with JSON. Mock submit/fill/cancel/restart/unknown acceptance, cap, host/account mismatch, missing policy and zero authoritative evidence. No real order until credentials and policy are ready.
3. **Pinned research profile:** use the existing driver/goal/context seams to propagate snapshot c63d16f44419cb96, [2024-11-01,2026-11-08), exact 300-symbol CONFIG and proxy limitations consistently into chooser/author/interpret. Reject incomplete/drifted profile rather than silently choosing data. Preserve existing defaults for unconfigured profiles and no runtime/model choice outside run_agent.sh. Focused driver tests and dry preparation.
4. **Deploy:** freeze the checked source/dependency identity; inspect/record active services and locks, quiesce writers, take consistent registry/tracking backups, install the immutable paper code/anchor and private paper credential template, migrate with the new exact code, verify retained archive readback/data/schema and restart the previously enabled research/monitor services. Keep first-install separate from the existing nonempty-cohort release consumer. Record failure/safe state; do not fake approval/manifest rows.

The primary agent owns SSH mutations and final integration. Implementers own disjoint files, report actual focused checks and do not operate Todoist, credentials, deployment or live controls.
