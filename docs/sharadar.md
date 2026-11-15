# Sharadar prices and selected fundamentals

This direct-API integration writes existing typed snapshots. Strategies consume the same frozen
local data through the normal backtest/context interfaces; no API request belongs in a strategy.
It does not certify data, change qualification gates or switch scheduled research/paper/live feeds.

## Package and credentials

The direct site's five-year **Bundle is $29/month**, including stock prices and fundamentals.
The previously discussed $69/month option is the Full History Bundle, not the minimum package.
Ten years is $49/month. Prices checked 2026-11-15; use the current
[official subscription page](https://sharadar.com/subscribe) before buying. Start monthly.

Install a paid account key privately as `ALGUA_SHARADAR_API_KEY`. For the public AAPL sample,
explicitly set it to `test-api-key`. There is no automatic sample-key fallback. Keep raw data,
normalized snapshots, any vendor-value-bearing reports and keys outside this public repository.

## Ingest and verify

Run on the VPS; full CLI imports use Linux process containment. Keep it the single vendor fetcher,
with research machines receiving only the appropriate frozen snapshots under the agreed data-plane
policy. Use a separate private directory and registry for an acceptance exercise:

```bash
export ALGUA_DATA_DIR=/absolute/private/sharadar-test/data
export ALGUA_DB_PATH=/absolute/private/sharadar-test/registry.db
export ALGUA_SHARADAR_API_KEY=test-api-key

uv run algua data ingest-bars --provider sharadar --symbols AAPL \
  --start 2021-11-15 --end 2026-11-15 \
  --data-tier pilot_real_proxy --universe-method sharadar-sample

uv run algua data sharadar ingest-fundamentals --symbols AAPL \
  --start 2022-01-01 --end 2026-11-15 \
  --metric eps --metric revenue --metric netinc --metric assets

uv run algua data verify
```

Use the returned bars and fundamentals snapshot IDs with a strategy that declares the required
fundamentals. Both legacy and `context_v1` backtests accept `--fundamentals-snapshot ID`.
Repeat against the same snapshot IDs for reproducibility; a new download has new provenance and
may contain vendor corrections. Existing bundled bars-only strategies do not consume fundamentals.

## Semantics and refusals

- Price windows are `[start, end)` and exclude today's unfinished daily bar. Only `1d` with
  `adjustment=none/raw` is supported. Tickers are exact vendor symbols, not inferred aliases.
- Prices/volume arrive split-adjusted. Raw OHLC is reconstructed with `closeunadj / close`;
  volume uses the reciprocal factor. The dated action feed is fetched through retrieval day
  (including splits after the backtest end) and reconciled with the existing raw-units check.
- Spinoff histories are refused pending reviewed mapping to the frozen adjusted-close contract.
  Other imported adjustments remain unverified vendor history, not action-completeness proof.
- Fundamentals use **ARQ only**, keyed by `reportperiod`, not calendar quarter labels. Select
  metric names explicitly. The source's units are retained; no currency conversion is inferred.
  Missing values stay missing, never zero; missing metrics/required columns refuse the download.
- `knowable_at` is the filing date plus **three calendar days** by default, a conservative
  **assumption**, not an observed publication/vendor-delivery timestamp. `--filing-lag-days`
  can increase it (3–31). The fundamental window applies to this assumed availability date.
  Facts whose assumed availability is still in the future are deferred. Source metadata records
  the assumption, deferred filings and missing-value counts. This is exploratory research input;
  the owner-approved price-only PIT standard does not establish fundamental PIT eligibility.
- CSV pagination follows all pages with page hashes, duplicate-page detection and hard bounds.
  Transport retries are bounded; streamed responses have size/time limits. Redirects, missing
  symbols, malformed rows, inconsistent actions and exhausted page bounds fail before publication.
- Private source values and API keys do not appear in provider errors. Metadata includes retrieval
  timestamps and response hashes; retrieval time is not historical knowledge time.

## Remaining paid-data acceptance

The public AAPL sample cannot prove midcap/delisted coverage, reused-ticker identity, merger or
bankruptcy proceeds, historical universe eligibility, or real availability times. Keep the existing
`data vendor-check --vendor sharadar` adversarial checks separate from import success. A complete
paid representative sample and a stricter fundamental PIT standard are still required before
qualification. Stable identity/universe and terminal-event integration are separate work.

Subscriptions do not grant perpetual data retention after cancellation; see the
[personal license](https://sharadar.com/terms). Do not send raw data to third-party model services.

API references: [stocks](https://sharadar.com/docs/stocks),
[fundamentals](https://sharadar.com/docs/fundamentals), [actions](https://sharadar.com/docs/actions),
[adjustment formulas](https://sharadar.com/docs/faqs).
