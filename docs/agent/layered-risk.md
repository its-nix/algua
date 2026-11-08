# Layered account drawdown

The owner-approved starting policy reduces the normal approved exposure budget to 50% at an
inclusive 10% drawdown and halts new risk at an inclusive 20%. Thresholds and the reduction fraction
are configurable through an authenticated account policy. Nothing activates by default.

## What is measured

Risk NAV is the initial approved risk capital plus account P&L net of external cash flows since
the signed baseline. Its high-water mark determines drawdown. It is a fixed-capital risk measure,
not a time-weighted investment return. Unallocated cash and later deposits cannot dilute losses
against the approved risk capital. Economic strategy NAV remains unchanged when its sizing budget
is reduced; otherwise the reduction itself would manufacture a strategy drawdown.

A distinct prior-close cash-flow window adjusts daily loss, including funding already present at
baseline capture. Identical activity IDs count once; conflicting/missing history refuses. New
cash flows require exact occurrence timestamps, finite amounts and consistent signs. In-kind or
ambiguous flows pause for review. Existing initial cash activities with date-only timestamps can
contribute to the daily adjustment only where their date lies unambiguously after the prior close.
The daily intervention remains at the stricter of the existing configured limit and 5%.

## Response and recovery

The controller persists severity before cancellation. It confirms cancellation, ingests fills,
recovers uncertain attributed orders and reconciles broker holdings before any reduction. It
refreshes cash and risk state after cancellation because a resting buy may have filled meanwhile.
At 10% it reduces existing per-strategy holdings as well as new-order sizing. A shared pool caps
aggregate buys to both remaining approved exposure and non-borrowed cash. At 20% it submits only
risk-reducing long exits when the venue is healthy. An accepted order is never reported as a fill.

Controlled exits use fresh, uncrossed quotes with positive displayed size, a bounded spread and
regular-market status. Defaults: IEX, maximum quote age 10 seconds, maximum spread 1%, and a sell
limit no worse than 25bps below the bid, rounded upward to cents. Sub-dollar exits require a
separately reviewed price-tick implementation. There is no market-order fallback. Unsupported
fractional limits, venue failures, closed markets or stale quotes keep the intervention pending.

Reduction plans and ledger intents are durable before POST. Their phases distinguish known local
abort (`not_submitted`) from uncertain venue acceptance (`submitting`); uncertainty retains the
original client-order identity and pauses if lookup cannot resolve it. A prepared plan left by a
crash can be cleaned without inventing a venue action. Live authorization and account state are
rechecked before each live reduction. A risk policy supplies no strategy live authority.

Severity survives price recovery, deposits, restarts, `paper resume-all` and legacy peak rebasing.
Human restoration explicitly rebases future risk measurement and retains immutable history.
Configuration and restoration require a flat reconciled account; changes preserve severity until
a separate signed restoration. Genuine unresolved submitted orders prevent restoration.

## Commands

The policy file requires `normal_capital` as a positive USD decimal string chosen by the owner.
Optional fields: `reduce_at`, `reduced_fraction`, `halt_at`, `quote_age_seconds`, `max_spread`,
`limit_offset`, `feed`. No example dollar value here constitutes a capital authorization.

```sh
uv run algua risk status
uv run algua operator lock-run -- algua risk configure paper --policy /path/to/policy.json
```

The first configure invocation prints a challenge under `algua-go-live`; it changes no policy.
Save its exact `challenge` text, sign with the existing enrolled human key, then complete:

```sh
ssh-keygen -Y sign -n algua-go-live -f /path/to/human-key /path/to/challenge.txt
uv run algua operator lock-run -- algua risk configure paper --policy /path/to/policy.json \
  --signature /path/to/challenge.txt.sig
uv run algua operator lock-run -- algua risk check paper
```

`risk restore paper` uses the same challenge/signature flow and requires a flat settled account.
Use `live` for the live lane. `risk check live` verifies an existing allocated LIVE strategy's
current signed authorization before constructing a trading broker; with no valid source it can
only observe/cancel. Frozen live remains refused by the existing gate. No command here promotes,
allocates, funds or activates a strategy. Serialize checks and policy changes with `operator
lock-run`; independent concurrent venue writers remain unsupported.

## Monitoring and deployment

The controller runs before strategy setup/refresh/reconciliation returns on configured account
cycles. Direct trade-tick cannot bypass it: configured accounts require a fresh guarded run-all
cycle, and every normal order rechecks its state. The selected profile replaces the legacy 15%
raw-equity drawdown response; unconfigured lanes keep it. Independent global halts and strategy
limits remain binding. `fleet health` treats a blocked or halted account as unhealthy even if a
legacy halt was cleared. `risk status` exposes the policy, current state and human action.

Optional `deploy/systemd/algua-risk@.service` / `.timer` templates provide nominal minute checks
independent of the daily strategy-session marker, under the shared operator lock. They are not
installed or enabled by this change. A busy operator can defer checks. Configure runtime
credentials, notification delivery (`ALGUA_ALERT_CMD`), the correct checkout and DB, a runtime-
unwritable trust anchor and bounded cycle durations before deployment. Validate monitoring and
fault recovery in the intended deployment before real-money acceptance.

These thresholds intervene when checked; gaps, outages and execution delays can exceed 20%.
The initial capital/instrument envelope, capped frozen-live consumer and signed activation remain
separate prerequisites. Fixtures establish mechanics, not a profitable strategy or live acceptance.

API references checked during implementation: [latest quote](https://docs.alpaca.markets/us/reference/stocklatestquotesingle-1),
[orders](https://docs.alpaca.markets/us/reference/postorder),
[account activities](https://docs.alpaca.markets/us/docs/account-activities),
[fractional trading](https://docs.alpaca.markets/us/docs/fractional-trading).
