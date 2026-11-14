# Layered drawdown implementation plan

> Implement inline with executing-plans; owner approved the 10% / 50% / 20% policy and continuation. Use focused checks and one bounded final review. No further design-approval ceremony is needed.

**Goal:** Enforce a configurable, signed account policy in paper and live, reducing approved normal exposure at 10% and halting new risk at 20%, with guarded attributed reductions and signed restoration.

**Architecture:** An opt-in per-lane/account policy, separate durable state and immutable events. Existing unconfigured lanes retain their controls. The selected profile replaces its legacy 15% raw-equity drawdown action and routes daily-loss intervention through the same guarded response; it retains independent per-strategy, daily-loss, reconciliation and execution controls. The live broker must still be built from existing verified live authorization before any sell can be submitted.

**Tech stack:** Existing Python/SQLite/Typer/requests; no dependencies. Spec: owner-approved proposal in `2026-11-07-strategy-cicd-design.md`, November 8 amendment.

## Calls settled for implementation

- Defaults: reduce_at=0.10, reduced_fraction=0.50, halt_at=0.20, inclusive; 0 < reduce < halt <= 1. All parameters finite; exposure fraction strictly between zero and one. Policy changes and restoration require the existing enrolled human SSH trust anchor and single-use account-scoped challenges.
- Measure performance capital as initial approved risk capital plus account P&L net of external cash flows since the signed baseline. This is a fixed-capital risk measure, not a claim of time-weighted investment returns. Deposits never erase a percentage loss or latch. Unsupported/in-kind/ambiguous flows pause for human review.
- Retain daily-loss intervention at the stricter of existing configuration and 5%. Adjust its prior-close reference for valued external flows. Unknown account state latches a halt.
- Initial policy and restoration require a flat, settled, reconciled account. Restore explicitly rebases future risk measurement while immutable history remains. Never alter allocations or move money.
- Only one policy per lane/account binding; an account switch fails closed. A signed update preserves severity and history. Legacy resume/global-clear cannot reset this state.
- At reduction/halt: persist state first, cancel and confirm no resting orders, ingest/recover fills, reconcile all attributed holdings, then submit only quantity-capped long reductions. No market-order fallback. Stale/crossed/nonfinite quotes, closed market, unresolved fills, shorts, unattributed holdings or missing live authorization leave the state paused and alert-visible.
- Defaults for guarded exits: regular hours, IEX quotes, <=10 second quote age, <=1% spread, limit no worse than 25bps below the fresh bid, cents rounded upward. These are implementation defaults; rejection never triggers market fallback.
- Normal buys share one account exposure reservation; size each strategy against its reduced allocation. Direct trade-tick must refuse a configured policy unless the broker passed that cycle's account checks. Mid-tick checks re-read durable state; policy/config revision changes stop the old cycle.
- Existing single-operator concurrency model remains required. No assertion of an OS sandbox, safe concurrent venue writers or deployed trust-anchor immutability.

## Tasks

- [x] Pure policy/risk arithmetic and cash-flow classification with boundary, deposit, withdrawal, ambiguity and latched-state tests.
- [x] Durable account state/events/reduction intents, schema v51, single-use signed configure/restore, status/check commands; test replay, cross-account/context, stale state and legacy reset isolation.
- [x] Guarded Alpaca quote and limit-reduction adapter with exact duplicate identity checks and fake HTTP tests; no real broker calls.
- [x] Shared cancel/ingest/reconcile/reduce coordinator, attributed record-before-submit and crash-retry identity. Test partial failure, open-order settlement, stale quote and account mismatch.
- [x] Paper/live cycle and per-order guards, reduced sizing/aggregate reservation, selected-breaker routing and fleet visibility. Test parity and default legacy behavior.
- [x] Focused integration, lint/types/import boundaries/schema fingerprint/size limits; bounded review and fixes. Commit logical changes; report exact checks and remaining capped-live/economic prerequisites.

## Delivery and review

Implemented in `4dc29df` on `feat/pinned-model-frozen-paper`. Documentation follows separately.

Important findings fixed in this change:

- `algua/execution/drawdown_guard.py:69`: keep economic NAV/peak unchanged while reducing sizing.
- `algua/execution/drawdown_actions.py:114`: recheck current account state, halt and live authority
  before each reduction. Durable phases distinguish local aborts from uncertain venue acceptance;
  local revocation cannot poison later signed restoration.
- `algua/registry/drawdown_auth.py:42`: verify flat valuation again after baseline activity capture,
  preventing a deposit race from entering ignored baseline activities with stale equity.
- `algua/execution/drawdown_cycle.py:129`: refresh cash/risk after cancel/ingest/reconcile so a buy
  filled during cancellation cannot leave an overstated cash pool.
- `algua/execution/drawdown_flows.py:56`: deduplicate identical IDs before summing and maintain
  separate baseline and daily flow windows, including prebaseline funding in the daily reference.
- `algua/execution/drawdown_cycle.py:94`: failure of either valuation latches severity 2, preventing
  automatic resumption after the next healthy read.

Focused final verification: **383 passed** across new policy/controller/broker tests and existing
migration/fingerprint, hygiene, size, parity, paper/live breakers, sizing, fleet, CLI, broker,
frozen-model-paper and experimental-qualification tests. The final two review regressions were
also verified independently (4 focused checks passed); no remaining blocking findings in that
bounded review. Ruff passed; Linux mypy passed for 465 source files; import contracts: 31 kept,
0 broken. Full suite/CI repetition intentionally omitted under the owner's delivery policy.
No real broker calls, funding, signer enrollment, timer enablement or strategy activation occurred.

Remaining prerequisites are not claimed complete: active-instance/registry/data location;
credible PIT historical evidence and actual five-session observations; capped frozen-live
qualification consumer and exact-bundle execution; full experimental instrument/capital envelope;
intended-deployment monitoring, recovery, secrets and immutable trust-anchor acceptance. Existing
single-operator discipline remains mandatory. The optional independent risk timer is disabled and
must be configured/accepted before deployment; a nominal minute cadence is not a maximum-loss
or response-time guarantee.
