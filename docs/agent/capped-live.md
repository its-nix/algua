# Capped frozen live

The separate `capped-frozen-live/v1` route implements the owner's November 8 fast profile:
current historical criteria plus five actual successful scheduled paper sessions. A recorded
experimental qualification is evidence, not live authority and not a strict forward certificate.
The legacy strict certificate route keeps its existing meaning.

The current code provides an opt-in connector, not deployment acceptance or a profitable strategy.
No capital amount, instrument list, provider, signer, account or timer is enabled by this change.

## Operator sequence

1. Produce a candidate through the current historical gates and frozen paper intake. Qualifying
   history must have its canonical nonreused sealed holdout lineage; exploratory proxy data cannot
   be relabeled as qualifying point-in-time evidence.
2. Collect five contiguous successful scheduled paper sessions. Use `paper qualify-experimental`
   to record the exact passing qualification automatically; `--preview` reads it without recording.
   This records numerical evidence with actual agent provenance and supplies no live authority.
3. Use `paper handoff NAME`. It revokes the paper allocation first, cancels only the tenant's
   orders and offsets its paper holdings. Repeat after fills settle until `handoff_complete=true`.
   It does not trip the kill switch, write a new performance tick or mint live authority.
4. Configure the exact live account's [signed risk policy](layered-risk.md). In addition to the
   thresholds, supply `normal_capital` in USD and a nonempty `permitted_symbols` list of personally
   reviewed stocks/unleveraged ETFs. Set the live bars provider explicitly. No default list or
   currency conversion is supplied. Retain the approved initial capital policy in PRD §21.
5. Preview with `live activate-experimental NAME --capital USD`. The default agent actor can
   only preview. `--actor human` prints a fresh challenge, with no activation. Save its exact
   `challenge` value without adding a newline, sign with the enrolled human SSH key under
   `algua-go-live`, and repeat the same command with `--signature FILE`.
6. Only a verified signature atomically records the matching frozen approval, human lifecycle
   edges and exact live allocation. For an initially paper tenant, `paper -> forward_tested -> live`
   are two legal edges in one transaction with explicit experimental reasons. Failure rolls back
   both edges, approval, allocation and nonce. No strict forward certificate is synthesized.

The ceremony binds the exact deployment, manifest, bundle, environment, three artifact hashes,
research gate, qualification/profile/evidence, gate universe, paper/live accounts, provider policy,
signed risk policy/instruments and capital. Initial qualification may be at most five completed
sessions stale. The nonce expires in ten minutes and is single-use.

Increasing capital uses a new signed `activate-experimental` request, bound to the current valid
authority. Generic `live allocate` cannot introduce or increase an allocation on the configured
experimental account. Decreases remain available. No command funds or replenishes an account.
`live revoke NAME --reason TEXT` immediately ends future authority; it does not claim a filled exit.
Leaving live revokes the capped authority and its approval in the lifecycle transaction.

## Runtime and limits

`live run-all` verifies the signature against current frozen content, canonical qualification
sources, provider/account and risk policy before trading. It resolves frozen configuration and
gate membership, and dispatches the same cold-child planner as paper. The supervisor retains all
broker credentials, reconciliation, risk checks, cash reservations, scoped cancellations, order
effects and ledgers. Live ticks link the exact deployment, bars snapshot and successful invocation.
Missing/corrupt content refuses execution; no checkout fallback or artifact rebuild occurs.

The five-session proof remains fixed after handoff; live operation does not require manufacturing
more paper sessions. Runtime still verifies its original source rows. The configured controller
retains the signed 10%/50%-exposure and 20% halt policy, tighter daily-loss controls, cash-only
shared reservations and an explicit buy instrument list. Recovery requires signed human action.

Legacy working-tree/strict behavior remains for compatibility; the new route does not turn those
paths into a fully enforced experimental envelope. Stories 2.3–2.5 therefore remain partially
delivered, especially production readiness and independent failure-path acceptance.

Before real deployment, verify economic reconciliation and restart recovery, monitoring, secrets,
and an installed trust anchor that the runtime user cannot write. The reviewed-code child is not
an OS sandbox. VPS source/data inspection does not establish these deployment properties. Actual
activation still needs the owner's exact USD ceiling, reviewed instruments and human signature.
