# Paper broker mechanics smoke preparation

## Approved implementation, 2026-11-09

The owner approved implementation and deployment of the isolated paper path. The CLI is now
`paper mechanics`, with its own journal and a dedicated account-risk registry. This is separate
from strategy admission: no mechanics order/fill becomes a strategy, tick, scheduled paper
observation, experimental qualification or live authority. The earlier preparation below retains
its original evidence and design rationale; its missing-command stop point is superseded by this
implementation, not by a synthetic passing gate.

The deployed entry is `/usr/local/sbin/algua-paper`, run by the owner over SSH. It executes the
immutable application as the separate `algua-paper` OS user; paper credentials belong in the
root-owned `0600` file `/etc/algua/paper.env`, never in the research environment or chat. Use the
read-only `paper mechanics account` command first to verify the actual account and CSL's active,
tradable/fractionable status. Credentials, a validated paper policy and an open regular market
remain runtime prerequisites; setup does not imply that a broker test has run.

```sh
algua-paper paper mechanics account
algua-paper risk configure paper --policy /var/lib/algua-paper/policy.json
# Paper policy configuration applies directly; there is no human signature/challenge.
algua-paper paper mechanics --state /var/lib/algua-paper/mechanics.db \
  --risk-db /var/lib/algua-paper/risk.db --expected-account ACCOUNT_UUID init --symbol CSL
algua-paper paper mechanics --state /var/lib/algua-paper/mechanics.db \
  --risk-db /var/lib/algua-paper/risk.db --expected-account ACCOUNT_UUID step
```

Use the same common options before `status` or `close`. The opening identity and USD5 purchase
budget are committed before the POST. Uncertain acceptance keeps the original identity consumed;
retrying polls it rather than creating another order. The fixed policy-derived ID also prevents a
second ledger from opening again under the same policy. Closing cancels only the verified own
opening before waiting for complete fills, then uses the existing healthy-quote bounded limit exit.
Both drawdown intervention levels fully close this one-order smoke, a stricter response than
partial exposure reduction. Paper configure/restore and mechanics share the existing operator lock.

Finish/close a mechanics run before switching its immutable release. Source/dependency drift
refuses further operation; recover an outstanding order using the original recorded release,
not by editing its receipt or creating a fresh ID. No paper/strategy/live timer or automated
merge-back is enabled by these commands. The separate real-broker acceptance card remains open
until account observations, fills, reconciliation and settled closeout actually occur.

## Installed bootstrap, 2026-11-09

Application source `6ef7a677354b230387cc22dd80970bd8c2ef9170` is installed under
`/opt/algua/releases/`, selected by the root-owned `/opt/algua/paper-current`. Its verified
application digest is `01c949949e238f0603334ca1a672de4a89b10a00f3c0b273be839326fbd7d064`
(26,016 inventoried files). The tree and trust anchor are root-owned; the pre-created
`.git/operator.lock` is the sole runtime-writable control-file exception. This is a manual,
owner-approved first install, not a synthetic cohort release. The Python standard library and OS
remain external runtime dependencies.

`deploy/scripts/algua-paper-entry.sh` records the installed root entry. It permits the paper
mechanics and paper-policy surface only, launches a confined transient service as `algua-paper`,
and binds the physical application, private state, import path and paper host. There is no timer.
The USD5/CSL policy file was prepared but unsigned at the original install. Installed `version` and empty-registry checks
passed; account discovery refused with `isolated Alpaca paper credentials are not configured`.
No mechanics order or qualifying paper session had occurred at that install.

The later November 9 owner amendment removes the paper-policy signing requirement. Configuration
and explicit restoration record automated provenance and retain account/risk/reconciliation checks.
Five owner-requested pre-existing-position liquidation orders were subsequently accepted by the
paper venue; those are cleanup orders, not mechanics or qualifying strategy sessions. Their
pending/fill state must be read from original broker identities, never inferred from this document.

Research source is separately deployed at the same application commit. Its existing registry was
backed up and migrated from v49 to v52; the separate MLflow database was backed up and upgraded.
Both integrity checks passed. Retained memory readback and the pinned 300-symbol profile dry run
passed before previously enabled research timers and the dashboard were restored.

## Historical preparation, 2026-11-08

Prepared against `d55c325` plus the then-current working diff. **Preparation and offline
fixture evidence only.** No broker request, order, credential installation, service activation,
lifecycle advancement or qualification credit was performed. Actual account results remain the
separate owner-blocked task `6hfCrg6qX8q4fvgG`.

## Historical admission boundary before the approved mechanics command

There is **no existing pre-qualification CLI seam that opens a real paper-venue mechanics
position**. The proxy dataset cannot establish candidate eligibility, so it cannot honestly
unlock `paper intake` and venue ticks.

| Existing surface | What it can prove |
| --- | --- |
| `paper account` (`algua/cli/paper_cmd.py:285`) | Paper credentials/connectivity and balances. It places no order and does not print account ID. |
| `backtest replay` (`algua/cli/replay_cmd.py:38`) | Historical mechanics through `SimBroker`, without stage, broker API or operational evidence writes. It cannot establish venue acceptance. |
| `paper run` (`algua/cli/paper_cmd.py:181`) | An admitted paper tenant's simulator run; it is neither an admission bypass nor a venue smoke. |
| `paper trade-tick` / `paper run-all` (`algua/cli/paper_cmd.py:803`, `:901`) | Real venue execution only for admitted paper/forward-tested tenants. These paths may write operational evidence and must not be used to manufacture pre-qualification credit. |
| `risk check paper` (`algua/cli/risk_cmd.py:82`) | Existing signed account-risk assessment, cancellation and attributed risk reduction. It does not originate a new strategy position for a smoke. |

**Important, protected design review required:** choose an explicit admission/evidence boundary
for paper-only broker mechanics before adding any order-producing path. Reuse the existing
`AlpacaPaperBroker`, sizing/reservation, durable client-order identity, venue ingestion/recovery,
reconciliation and risk-controller seams. Specify how isolated mechanics intents/fills are
attributed while remaining ineligible for research gates, candidate/forward transitions,
experimental session qualification and live authorization. An arbitrary Python call into the
broker, a synthetic passing gate, a raw stage/DB edit or an invented CLI command is not the
missing implementation. This document implements none of them.

## Proposed execution envelope and stop point

These are reviewable limits for a later authorized smoke, not authority to execute now:

- Use a dedicated Alpaca **paper** account and dedicated `ALGUA_DB_PATH` / `ALGUA_DATA_DIR`
  outside production. Start with no positions or open orders and no other tenant, operator,
  timer or interactive writer. Do not reuse a populated account or production registry.
- Pin the only broker host to `https://paper-api.alpaca.markets`; the existing paper adapter
  independently rejects other hosts (`algua/execution/alpaca_broker.py:484`). Supply paper keys
  only to the isolated process; no live credentials, live account or live command is involved.
  Record the account ID from the owner's paper dashboard and require it to match the signed
  risk-policy baseline. Host allowlisting alone does not prove account identity.
- Proposed total approved paper exposure and cumulative opening purchases: **USD 5.00**.
  One owner-reviewed liquid, active/tradable, fractional-capable stock or unleveraged ETF;
  long-only, no borrowing, one opening order, at most one outstanding opening order.
  No second opening purchase after a cancel/timeout/restart; recover the original ID first.
  Exits must be bounded to actual held quantity and cannot create a short position.
- Proposed signed paper risk policy: `normal_capital: "5.00"`, one permitted symbol,
  `reduce_at: "0.10"`, `reduced_fraction: "0.50"`, `halt_at: "0.20"`; retain the existing
  stricter daily-loss limit and healthy-quote/limit-reduction requirements. Thresholds
  intervene when checked and are not a dollar-loss guarantee. Minimum-size refusal ends the
  smoke; do not increase the ceiling to make an order pass.
- Serialize later risk/configuration/execution through existing `operator lock-run`, with
  no unattended units enabled for this manual smoke. Retain source commit, lock hash,
  account identity, exact permitted symbol, owner-approved ceilings and UTC session/window.

With the owner's paper credentials supplied to that isolated environment, the existing
connectivity-only command is `uv run algua paper account`. This preparation did not run it.
Use [the existing signed policy ceremony](layered-risk.md#commands) if the execution design is
approved; an unsigned policy invocation creates a challenge, not an applied policy.

**Stop before order placement today.** The remaining design must enforce the USD 5 cumulative
opening-purchase limit and evidence exclusion at the new admission boundary; current risk-policy
exposure limits alone do not impose a lifetime purchase budget. Do not use `paper allocate`,
`paper intake`, `paper trade-tick` or `paper run-all` as a workaround for missing qualification.

## Proposed acceptance sequence after reviewed admission exists

| Step | Required observation / stop condition |
| --- | --- |
| Baseline | Owner confirms exact dedicated paper account, empty positions/orders, isolated DB/data/source and signed policy. Any mismatch stops. |
| Submit once | Persist one attributed intent/client-order ID before sending no more than USD 5. Record request time and venue order ID; acknowledgement is not a fill. |
| Cancel / partial fill | Cancel only that intent's order; re-list and ingest actual fills. If already filled, record that outcome. A partial cancel or missing fill publication remains unresolved; do not assume flat. |
| Uncertain acceptance / restart | Stop the process before any fresh submit; restart against the same DB/account and resolve the original client-order ID. No retry with a new ID and no duplicate opening purchase. If the venue cannot safely induce this case, mark it fixture-only. |
| Ledger / reconciliation | Deduplicate activities, backfill delayed order attribution and compare ledger quantities/cash with venue truth. Unknown activity, stale marks, ingest failure or a quantity mismatch stops new exposure. |
| Risk / exit | Exercise threshold/restart behavior in fixtures; do not manufacture broker losses or change the account baseline. Actual exit uses the existing guarded attributed reduction path only when admitted by the reviewed design. Accepted exit remains pending until fills, no own open orders and reconciled flat positions are confirmed. |
| Closeout | Preserve JSON/exit codes, IDs, timestamps, fills, ledger/reconcile and policy state. Separate real observations from fixture-only cases. Assert zero candidate/forward/live or scheduled-session qualification credit. Revoke smoke credentials/access after flat settled closeout. |

The current market-order tick cannot guarantee an observable cancel window or partial fill.
Do not increase size or add test orders to force those outcomes. The actual broker task can
remain partially verified even when deterministic fixture coverage passes.

## Offline fixture evidence

Ran the existing network-disabled Linux helper with these existing selectors:

```sh
.superpowers/sdd/2026-11-07-pinned-model-frozen-paper/linux-exec-admin pytest -q \
  tests/test_alpaca_broker.py::test_submit_buy_delta_posts_notional \
  tests/test_alpaca_broker.py::test_cancel_open_orders_partial_failure_raises \
  tests/test_alpaca_broker.py::test_submit_timeout_then_retry_reuses_client_order_id \
  tests/test_alpaca_broker.py::test_recovery_accepts_an_order_that_really_reached_the_book \
  tests/test_live_ledger_ingest.py::test_ingest_is_idempotent_on_activity_id \
  tests/test_live_ledger_ingest.py::test_late_attribution_backfills_orphan_fill \
  tests/test_live_ledger_orders.py::test_recover_stranded_preserves_phantom_on_404_paper \
  tests/test_paper_exit_drain.py::test_t2_a_siblings_resting_order_survives \
  tests/test_paper_exit_drain.py::test_t3b_late_published_fill_is_refused \
  tests/test_drawdown_controller.py::test_normal_cycle_shared_cap_and_mid_tick_revision_guard \
  tests/test_drawdown_controller.py::test_accepted_but_unacknowledged_reduction_recovers_original_identity \
  tests/test_drawdown_controller.py::test_reduced_state_survives_price_recovery_and_legacy_resume \
  tests/test_drawdown_controller.py::test_twenty_percent_halts_flat_and_only_signature_restores \
  tests/test_drawdown_controller.py::test_cash_is_refreshed_after_a_buy_fills_during_cancellation \
  tests/test_paper_venue_reconcile.py::test_trade_tick_fails_closed_on_ingest_fetch_failure \
  tests/test_cli_paper.py::test_trade_tick_recovers_stranded_fill
```

**19 passed (7.24s)**, including four real-order recovery statuses (`filled`,
`partially_filled`, `new`, `accepted`) against mocked transport. These prove existing code
mechanics with temporary registries/fake venues, not real broker execution or a full process
crash acceptance exercise. No new harness or command was added. Full-suite and actual broker
validation were intentionally omitted; the admission design and real-account task remain open.
