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

## Private identity input preparation

Compile stable security identities and explicit dated ticker-change events from local exports:

```bash
uv run algua data sharadar compile-identities \
  --tickers /private/sharadar/TICKERS.csv \
  --actions /private/sharadar/ACTIONS.csv \
  --out /private/sharadar-preparation/identities.json
```

The output must be a new path outside the repository. Details stay in the private artifact;
stdout contains counts, hashes and its path. Input hashes bind the exact bytes parsed.
Missing or ambiguous event pairs and contradictory rename chains refuse compilation.

The current vendor ticker is a restated storage key. This command infers no historical alias
intervals, listing history or universe membership. Coverage and completeness remain unverified;
it publishes no snapshot and changes no trading feed or qualification.

## Stable-identity bars and private universe preview (unqualified)

Stage 1 freezes bars under stable IDs; stage 2 computes a private preview of the frozen
[`us-liquid-common/v1`](agent/daily-universe-rules.md) universe. Both are unqualified: neither
sets `verified_pit`, publishes a universe, imports into the universe store or changes a feed.

```bash
uv run algua data sharadar prepare-bars --sep SEP.csv --tickers TICKERS.csv \
  --actions ACTIONS.csv --identities identities.json --as-of 2026-11-16T00:00:00+00:00
uv run algua data sharadar compute-universe --bars-snapshot ID --identities identities.json \
  --rules deploy/research/us-liquid-common-v1.json --evidence evidence.json \
  --start 2024-01-02 --end 2026-11-16 --out /private/preview.json
```

- **Stable ID** = the compiler key upper-cased: `sharadar:permaticker:N` becomes
  `SHARADAR:PERMATICKER:N` (the DataStore's canonical form). This explicit transform is recorded in
  snapshot metadata and the preview, and the ASCII tie key is the transformed ID in every stage.
- `prepare-bars` hashes the captured SEP/TICKERS/ACTIONS bytes, requires TICKERS/ACTIONS to match the
  hashes in the identity artifact, requires every SEP ticker to be exactly one current storage ticker,
  and reuses the existing raw-bar normalization and action/raw-unit check. No historical alias is
  inferred.
- `compute-universe` needs explicit dated evidence (`algua.sharadar.eligibility_evidence.v1`) bound to
  the identity artifact, bars content hash and rules hash: per-security listing episodes, dated
  domicile/venue/instrument/currency intervals, ranges where listing status is certified complete, and
  certified-absent sessions. It is a declared input; the preview records it as **unverified**.
  Public vendor action types (listed/delisted/exchange/ticker events) do not establish historical
  currency, domicile or common-stock class, so a real historical run stays **blocked** until trusted
  explicit evidence exists.
- Per date, unknown listing status, universe inventory, eligibility field, or expected bar **refuses
  that date** (never excluded, no replacement, no carried-over membership). A certified absence in the
  60-session window excludes. History: a counted >=252 valid sessions in one known continuous episode
  passes even if an older bar prefix is unknown; below 252 with an unknown prefix refuses; below 252
  with the whole episode prefix accounted excludes. If no date computes, nothing is written.

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
