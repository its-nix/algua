---
title: 'Task 8 strategy-first leaderboard — frontend slice'
type: 'feature'
created: '2026-10-31'
status: 'in-progress'
---

## Contract

This same-PR contract authorizes only the Task 8 frontend slice under
`web/frontend/{src,scripts}`. It supersedes the older strategy-board clauses that prohibited a
leaderboard and made lifecycle the intended permanent default, but it does not change promotion,
gate, lifecycle, capital, deployment, data, API, or backend authority.

The private home route `/` is the strategy-first monitor: one row per stable `strategy_id`, the
identity-bound latest gate supplied by `strategy-board/v1` (never the best historical gate), real
lifecycle/family labels, and nullable OOS Sharpe/return/drawdown/sample/timestamp. Missing evidence
is `UNKNOWN`; numeric zero remains zero; non-finite payloads fail closed. Operational warnings use
the existing `/api/triage` health read and remain visible on the homepage with stale, partial,
unknown, failure, retry, and full-diagnostics affordances.

`strategy-board/v1` has no comparison period or data-tier field. `n_obs_oos`, gate timestamps, and
data-provider provenance do not establish comparability. Therefore every current row is
`NONCOMPARABLE`: metric-sort controls are visible but disabled, the reason is always visible, and
the server's deterministic order is retained. Sorting remains exploratory-only when a future,
reviewed contract supplies genuine comparable metadata; it can never feed promotion or imply
expected profit. Paper/live/backtest evidence is not mixed into one ranked metric.

Stage and family filters are client-side over the complete payload, include unknown family, and
show an honest empty intersection. Rows route through unambiguous `/strategy/:id`; that resolver
maps the stable board identity to the existing name-keyed detail API, visibly preserves stale or
failed-refresh lookup state, and cross-checks the returned `registry.id` before displaying or
fetching further evidence. A mismatched or absent registry identity fails closed with retry and
back affordances. `/s/:name` remains the legacy fallback and numeric names are never interpreted
as IDs there. `/funnel` redirects to `/research`.
The four-tab bottom bar is removed; `/now`, `/fleet`, `/money`, and `/research` remain accessible
secondary links. No actions are added.

## Missing propagation slice / partial Task 8 acceptance

This is intentionally partial Task 8 acceptance. The backend currently cannot propagate a
reviewed comparison-period identity or data-quality tier through `algua runs board` and
`GET /api/strategy-board`. Consequently this slice does **not** accept metric ranking, data-tier or
period filtering, freshness/age verdicts, or portfolio/paper/live comparisons. It displays the
observed gate timestamp and marks age, tier, and period `UNKNOWN`. Completing those capabilities
requires a separate backend/contract slice; this frontend does not infer them from yfinance,
sample counts, gate dates, stage, or family.

## Boundaries and evidence

- Read-only frontend and demo/test fixtures only; no dependency, lock, backend, core, safety,
  credential, promotion, lifecycle, capital, merge, deploy, or live change.
- Tests cover stable identity/latest-run preservation, null/zero/non-finite behavior, lifecycle and
  family/stage filters, unavailable sorting, links/routes, visible operational warnings, and
  loading/stale/error/empty/retry states.
- Required evidence is `npm run check`, `npm run build`, `npm run build:demo`,
  `npm run verify:demo-build`, and viewport coverage at 390px plus the leaderboard's
  860px desktop boundary and 1440px. Root and backend gates are owned by the parent integration run.

### Bounded independent QA corrections (F1/F2)

Identity-error Retry revalidates both the board mapping and the name-keyed detail, including when
that mapping has not changed. The exact registry-ID guard remains unchanged: null/mismatched
identity displays no evidence and starts no series request. Integrated resolver/detail tests hold
the recovery response pending to assert that boundary before accepting matching recovered detail.
Desktop board columns use flexible minima rather than fixed widths that exceed the 860px viewport.
Focused red/green reproduces the original missing second detail read and 860→864px overflow;
unchanged parent QA evidence remains applicable outside these corrections. Independent focused
fix-verification is still required; this does not expand partial Task 8 acceptance.
