# Paper mechanics smoke: verified round trip, 2026-11-09

Historical record. The `paper mechanics` command was removed in the lean trim (#826). This note
keeps what its last trial proved, which was previously kept only on the unmerged branch
`feat/pinned-model-frozen-paper` (commit `99d555e`).

## November 9 successful TOST round trip

The trial ran immutable source `b6cdb3a152d19765a2be3b55e6ef437a0089e248` with application digest
`0e18d30a27d2401763c4d81b5444a28844ae67e643647dfa945cc3e65e1e2589`. It completed the new isolated
TOST trial under an unsigned USD5 singleton policy.
- The opening order and the guarded limit exit both filled.
- Separate CLI invocations recovered their original durable identities.
- The journal recorded two fills and `closed`.
- Independent venue reads confirmed equal bought and sold quantities, zero positions and zero open
  orders.

Root-private evidence is on the VPS under `/var/lib/algua-maintenance/20261109-quote-profile/`.
The trial journal is `/var/lib/algua-paper/mechanics-tost-20261109.db`.

This trial establishes the normal broker round trip. It does not establish:
- crash-during-POST acceptance;
- safe release rollback;
- profitability;
- a qualifying scheduled strategy session.

The failed CSL journal, the administrative recovery and the superseded timer's failure remain
distinct records. Closeout:
- The expired one-time timer was disabled and archived.
- Duplicate build applications and superseded host supervisors were removed after verified
  closeout. Their source archives and inventories were kept.

Validation for the repair that preceded the trial:
- 207 focused Linux tests passed.
- Repository Ruff passed.
- Linux Mypy passed on 492 source files.
- 31 import contracts passed.
- A bounded review found no Important or Critical issue.

Full-suite and CI runs were intentionally omitted. No schema migration was introduced.
