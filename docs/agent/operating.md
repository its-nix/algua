# Operating Playbook (detail)

This expands `CLAUDE.md` with the why behind the rules.

Product direction comes from [the vision of record](../PRD.md); current implementation gaps and
historical references are tracked in [the reconciliation record](../vision-reconciliation.md).
The vision does not itself change runtime controls or grant a new merge/deployment permission.
The owner-approved opt-in policy reduces exposure at 10% drawdown and halts at 20%; see
[layered risk](layered-risk.md). Unconfigured accounts retain their legacy default.

## The live gate
Lifecycle stage lives in the SQLite registry (`algua/registry`). State is a *record*,
not a wall: because agents can write the registry, a bare `stage='live'` flag is not a
security boundary. The legacy strict route is a signed ceremony requiring a human actor AND a
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
The strict forward certificate is not waivable in-band. The separate owner-approved
[capped frozen-live route](capped-live.md) uses current historical criteria plus five paper sessions,
its own qualification and an exact-capital human signature. It does not change strict evidence.

## Autonomous paper

The owner removed routine paper signatures on 2026-11-09. Paper account-policy configuration and
explicit restored episodes, ordinary intake/allocation/ticks/promotion, and recording a passing
five-session qualification run without a human ceremony. Actor fields record actual provenance,
not authority. Paper controls still enforce account isolation, settlement, risk, reproducibility
and evidence integrity. Restoring a halted paper account needs a reason and a reconciled flat
baseline; a restart or new strategy cannot silently rebase it.

Live qualification consumers independently verify original evidence; an unsigned paper record or
paper risk policy never substitutes for the final live signature. Signed live policy/restoration
and capital controls remain unchanged. See the [design](../superpowers/specs/2026-11-09-autonomous-paper-design.md).

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
