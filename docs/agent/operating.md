# Operating Playbook (detail)

This expands `CLAUDE.md` with the why behind the rules.

Product direction comes from [the vision of record](../PRD.md); current implementation gaps and
historical references are tracked in [the reconciliation record](../vision-reconciliation.md).
The vision does not itself change runtime controls or grant a new merge/deployment permission.
The 10% experimental-account pause is an owner-settled policy that Story 2.6 has yet to implement;
the current configured default is documented separately in that record.

**Authority routing (2026-10-30).** Hermes Kanban owns delegated engineering work, GitHub owns code
and evidence, and Todoist holds only Lior's human commitments; no trial or experiment gets a task
card. Every merge, deployment, credential change, destructive or external-sharing action and
protected-authority change requires Lior's approval. Auto-merge and paper CI/CD are TARGET BLOCKED,
not permissions.

## Three harnesses

The [approved design](../superpowers/specs/2026-10-30-algua-three-harness-design.md) gives each
responsibility one owner: Hermes develops the machine, OpenCode operates research, and Algua's
deterministic code owns data, simulation, promotion, portfolio, risk, execution and ledgers. That is
target direction. The [observed-target report](../development/observed-target-report-2026-10-30-three-harness.md)
records what exists today, including schedulers and merge routes that do not match it yet. Neither
document changes a runtime control. A Hermes profile is a same-UID role, not an OS sandbox, so a role
prompt is never a security boundary.

## The live gate
Lifecycle stage lives in the SQLite registry (`algua/registry`). State is a *record*,
not a wall: because agents can write the registry, a bare `stage='live'` flag is not a
security boundary. Going live is a two-step signed ceremony requiring a human actor AND a
valid forward-test certificate:

1. Run `registry transition <name> --to live --actor human` (no `--signature`) — the CLI verifies
   a fresh forward certificate exists (newest evaluation for current identity+strategy: PASS,
   ≤10 sessions old, clean record + account hygiene), then issues a cryptographic challenge bound
   to the strategy's current code+config hash and returns it as JSON (with the certificate summary).
2. Sign the `challenge` value with your enrolled SSH key:
   `ssh-keygen -Y sign -n algua-go-live -f <key> <file>`
3. Re-run: `registry transition <name> --to live --actor human --signature <file>.sig` — the CLI
   verifies the signature, consumes the single-use challenge, and advances the stage to `live`.

The challenge is single-use and expires after 10 minutes. Trust the signature, never the flag.
The forward certificate is not waivable in-band.

## Module boundaries

The full implemented package map is in [architecture](../architecture.md). The original
foundation responsibilities below remain useful orientation, not an exhaustive system inventory.

- `contracts/` — pure types/protocols. No I/O, no other algua imports.
- `calendar/` — market sessions; depended on by both backtest and live.
- `registry/` — lifecycle source of truth (`db`, `store`, `approvals`).
- `config/` — pydantic settings (env prefix `ALGUA_`).
- `cli/` — the shared command surface; `main.py` is the entry point.

## JSON everywhere
Commands print indented JSON so an agent can parse results and a human can read them.
Parse stdout; use exit codes for pass/fail (e.g. `doctor`, illegal `transition`).
