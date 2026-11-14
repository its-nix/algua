# Autonomous paper operation; human authority at live activation

Owner direction, 2026-11-09: remove signatures from routine paper operation so multiple strategies
can be tested and progressed unattended. The previously requested USD5 paper-policy signature is
superseded. This changes paper authorization, not the historical criteria, five-session requirement
or live capital authority. No human signature may be fabricated or applied by an agent.

## Intended flow

`idea → backtested → candidate → paper → eligible evidence → human-signed live activation`

The current enum remains `idea → backtested → candidate → paper → forward_tested → live`.
Paper precedes forward-tested; no new lifecycle stage or raw promotion bypass is introduced.
Strict forward qualification and the historical-plus-five-session experimental route retain their
different evidence meanings. Agents can complete their respective numerical checks without signing.

## Paper behavior

- Normal candidate intake, paper allocation, scheduled execution, stopping, handoff and default
  forward promotion remain automatic through the existing CLI and deterministic gates.
- `risk configure paper --policy FILE` applies a valid policy directly. It performs the existing
  flat/settled-account, exact paper host/account, cash-flow, reconciliation and operator-lock checks.
  It records the actual automated actor/action, never a fake human approval or signer principal.
  Configuration preserves existing severity; adding another strategy does not reconfigure/rebase
  the account. Paper risk configuration supplies no live authority.
- `risk restore paper` needs no signature. Restoration remains an explicit operator action after
  flat settlement/reconciliation, with a reason and immutable event recording the old and new risk
  episode. Recovering prices, restarting or clearing a halt never silently rebases history.
  A deterministic controller still halts/reduces under the policy; an agent may investigate and
  restore paper without involving the owner. Economic returns and failed trials remain recorded.
- The isolated mechanics path accepts honestly recorded paper policy provenance. Its USD5 lifetime
  opening purchase, CSL-only instrument, exact account, durable intent, uncertain-order recovery,
  own-order cancellation, reconciliation and execution restrictions remain intact. This smoke is
  separate from the multi-strategy paper book and earns no qualifying sessions.
- `paper qualify-experimental NAME` records a passing recomputed report for an agent by default;
  `--preview` is read-only. Repeated identical reports are idempotent. A reported actor is provenance,
  not authority. Five genuine scheduled sessions and current historical criteria remain mandatory.
- A versioned migration honestly admits agent/system/human qualification provenance. Preserve all
  existing rows/IDs, foreign keys and append-only protections; do not rewrite old human records as
  agent records or insert automated rows pretending to be human.

## Live boundary

Unsigned paper policies, paper allocations, restored episodes, five-session qualifications and a
bare stage flag can never authorize a live order. The live connector verifies original historical
rows and the exact paper session window independently, including artifact/deployment hashes,
profile, account and freshness. It must not treat a qualification's author as its security proof.
The final human ceremony signs that verified evidence together with exact deployment, accounts,
instruments, live risk policy/provider and capital. Replay/revocation/drift checks remain binding.

Existing signed LIVE risk-policy configuration/restoration, live activation and live capital
increases remain protected. Removing routine paper signatures does not remove real-money controls.
Combining distinct live account-policy and activation ceremonies is a separate future change; it
is unnecessary to unblock paper and is not included here.

Optional authenticated research/forward integrity exceptions do not become unsigned overrides.
The unattended path uses existing default criteria. Non-PIT proxy data, failed history and replay
remain honestly labeled and cannot become qualifying historical or five-session evidence.
Expanding exploratory proxy-paper admission is separate from removing signatures and is not
silently included. Multiple ordinary qualifying strategies can use the existing paper book.

## Implementation seams and delivery

Separate paper account actions from the shared live signing ceremony, reusing baseline validation
and persistence. Update mechanics provenance checks. Allow automatic experimental qualification
and update its live evidence consumer to recompute sources without demanding a human author.
Keep existing lifecycle and live signature verification. Update command help, PRD/operating docs
and the superseded signing instructions so agents do not ask the owner to sign paper again.

Use a coordinated schema migration with all registry writers quiesced and consistent backups.
Do not resume older writers against the new schema. Build/adopt a new immutable paper application;
no mechanics opening exists yet, so no pending smoke is moved across source identities. The five
owner-requested existing paper liquidation orders retain their original broker identities and are
observed without resubmission. The old scheduled cleanup remains disabled.

Focused acceptance must demonstrate unsigned paper configuration/restoration and qualification,
honest provenance/migration, continued rejection of fabricated or changed evidence, and unchanged
live rejection without a valid human signature. Include actual installed CLI checks after rollout;
do not count fixtures, cleanup orders or the mechanics smoke as qualification or economic success.
