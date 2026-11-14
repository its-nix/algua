# Operating Playbook (detail)

This expands `CLAUDE.md` with the why behind the rules.

Product intent comes from [the vision of record](../PRD.md); implementation status is evidenced in
[architecture](../architecture.md) and source/tests. This playbook, `CLAUDE.md` and `AGENTS.md`
define present operating permissions. The [September reconciliation](../vision-reconciliation.md)
is a dated assessment, not a current gap register. Product targets do not change runtime controls
or grant merge/deployment permission.

The established experimental-account pause policy is 10%, pending implementation; the current
generic book breaker defaults to 15%. The November proposal of 20% remains an undecided amendment.
The target experimental route uses historical economic qualification plus approximately five
completed scheduled paper sessions for operational qualification (PRD §16). Current `paper promote`
still requires its existing forward gate; no new qualification route is implemented by this prose.

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
- `calendar/market_calendar.py` — config-free session calculations; depended on by backtest and live.
  `calendar/factory.py::get_calendar` reads settings per call for operational exchange selection;
  calendar imports neither CLI nor registry.
- `registry/` — lifecycle source of truth (`db`, `store`, `approvals`).
- `config/` — pydantic settings (env prefix `ALGUA_`).
- `cli/` — the shared command surface; `main.py` is the entry point.

## JSON everywhere
Commands print indented JSON so an agent can parse results and a human can read them.
Parse stdout; use exit codes for pass/fail (e.g. `doctor`, illegal `transition`).
