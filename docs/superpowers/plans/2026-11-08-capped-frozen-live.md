# Capped frozen-live connector implementation plan

> Execute inline under the owner's approved continuation; focused tests and one bounded final review. No activation, deployment, signer enrollment or funding is performed.

**Goal:** Connect the distinct historical-plus-five-paper-session qualification to human-signed, capital-capped execution of the exact frozen strategy.

**Architecture:** A separate experimental authorization binds the frozen deployment, immutable qualification, account, data-provider policy, signed account risk policy/instrument allowlist and exact capital amount. Existing strict forward certificates and legacy signed-live verification retain their meanings. The new command verifies a human signature before atomically recording matching approval, legal lifecycle transitions and a live allocation. Risk controls and broker effects stay in the supervisor; both lanes share frozen dispatch.

**Tech:** Existing Python/SQLite/Typer; no new dependencies. Implements the approved November 8 fast profile and the substantive seams in Stories 2.3–2.5, with their strict-certificate assumptions reconciled explicitly below.

## Constraints and design calls

- No raw agent/human flag authorizes live. Namespace `algua-go-live`, enrolled key, fresh single-use challenge, exact rebuilt context. Activation requires human actor and matching code/config/dependency approval. The live runner re-verifies the signature against current records, never stage or stored request text alone.
- Five sessions never become a strict forward certificate. Activation records human `paper -> forward_tested -> live` as two legal edges in one transaction when needed, with explicit experimental reasons; neither intermediate stage nor fake strict evidence can escape a failed transaction. Existing raw frozen transitions stay refused.
- New activation includes the exact requested allocation in the human signature (no automatic funding). Initial live capital and instrument symbols have no defaults; the existing signed risk policy supplies the account ceiling and explicit approved-symbol list. Sum of live allocations <= ceiling and current equity; cash-only order reservations, long-only deployment, max gross <=1, buy allowlist. Generic frozen allocation increases are refused; signed activation/resize is the only increase path.
- Require a signed passing experimental qualification, canonical nonreused sealed historical lineage, the exact same five successful contiguous paper sessions and fresh evidence at initial activation (<=5 completed sessions). Reverify immutable source evidence at runtime; it need not acquire new paper sessions after moving live. Signed resize of an unchanged live deployment requires its current valid authority and healthy risk state.
- `paper handoff` first revokes the paper allocation, drains its own orders and closes only its own paper holdings without tripping the kill switch or recording a new tick. Activation requires paper flatness and no allocation/open paper orders; serialize with the existing operator lock.
- Live provider policy includes selected provider, provider-selecting endpoint and exchange. The live account is read with the read-only broker before signing. Reconfiguration, account/provider switch, artifact/epoch/qualification change, revocation or live exit invalidates the authorization. Mid-order checks bind exact authorization row and active deployment.
- Frozen live reads recorded config/gate universe and verified bundle/environment, never imports/rebuilds the checkout. Shared cold-child protocol retains the reviewed-code threat model; it is not an OS sandbox. Signed policy and runtime trust anchor must be immutable to the operator in deployment.
- Working-tree/legacy behavior remains for compatibility; the new capped route never falls back to it. No agent path through the experimental route. Current strict promotion and its statistical criteria are unchanged.

## Tasks

- [x] Extend signed risk policy with an explicit optional instrument list; enforce the live envelope and add pure boundary tests. Empty list refuses new experimental activation.
- [x] Add v52 experimental challenges/authorizations and a pure extended live token. Verify recorded qualification from canonical source rows, including after handoff/live. Add immutable/revocation-only schema and migration tests.
- [x] Implement signed activation/resize, matching approval and legal stage writes in one transaction, exact capital/allocation bounds, replay/expiry/drift refusal and row-bound revocation. Register preview/activation/revoke commands and block unsigned generic frozen allocation increases.
- [x] Add risk-reducing paper handoff, shared frozen planner helper, live frozen tenant/tick dispatch and invocation-linked evidence. Preserve no-checkout/fresh-content/error isolation and supervisor effects.
- [x] Wire live refresh views, source-provider checks, runtime re-verification and envelope guards into normal and risk-only live paths; revoke on live exits.
- [x] Run focused SSH ceremony, corruption/drift, capital, handoff, real-child paper/live parity, restart/refusal and existing gate regressions; Ruff, Linux mypy, imports, schema fingerprint and size. Bounded review, fix real findings, commit.

## Parallel factual research

Read-only remote inspection found the actual VPS at `/home/algua/Projects/algua`, with the research
registry there and pilot bars at `/home/algua/datasets/pilot-2026-11-03/data`. No authoritative
strategy/run/gate/deployment/tick exists yet. Later retained scratch attempts performed numerical
proxy evaluation but failed integrity eligibility, and several had poor validation performance.
Historical membership/delisting inputs are absent. Do not relabel that proxy data as PIT or imply
no numerical work ever ran. Investigate data access and source failures without deploying this
branch or starting unfunded/unqualified trading.

## Delivery verification

The distinct connector is implemented; no production activation/deployment occurred. One bounded
independent review found two Important concurrency defects: revocation overtaken by an in-flight
resize, and stale sizing after a smaller allocation. Both reproduced RED and passed after exact
prior-authority recheck under the write lock and allocation-row binding at each order check.
The final focused run passed 176 tests. The preceding broader paper/live/frozen/qualification
regression passed 315 tests;86 focused schema/hygiene/admission checks also passed. Ruff, Linux
mypy (480 sources), 31 import contracts and schema 52 fingerprint passed. The full suite was omitted
under the owner’s proportional-check policy. Broader production/readiness story acceptance remains
partial, as documented in the capped-live operating guide.

New owner steering pauses the yfinance acquisition until the starting universe is discussed.
No new dataset or historical membership declaration was installed during connector work.
