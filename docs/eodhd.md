# EODHD daily-data ingestion

The `eodhd` provider downloads US daily bars into Algua's existing immutable snapshot store.
Backtests read the pinned snapshot locally; they make no EODHD requests. Use Linux or the
project's Linux container for the full CLI (the containment runtime requires Linux `waitid`).

## Free smoke test

Use a fresh private directory, separate from scheduled research and broker state:

```bash
export ALGUA_DATA_DIR=/absolute/private/eodhd-smoke/data
export ALGUA_DB_PATH=/absolute/private/eodhd-smoke/registry.db
export ALGUA_EODHD_API_KEY=demo

uv run algua data ingest-bars --provider eodhd \
  --symbols AAPL,AMZN,TSLA,VTI --start 2025-01-01 --end 2026-01-01 \
  --data-tier pilot_real_proxy --universe-method eodhd-demo-selection
```

Copy the returned `snapshot.snapshot_id`. Verify the stored payload:

```bash
uv run algua data verify --snapshot-id SNAPSHOT_ID
```

For a mechanics-only backtest, explicitly select the demo symbols rather than the example
strategy's normal universe. This is a test selection, **not historical index membership**:

```bash
uv run algua data ingest-universe eodhd-demo-selection \
  --symbols AAPL,AMZN,TSLA,VTI --effective-date 2025-01-01 \
  --source 'Mechanics-only demo selection; not historical index membership'

uv run algua backtest run cross_sectional_momentum \
  --snapshot SNAPSHOT_ID --universe eodhd-demo-selection \
  --start 2025-01-01 --end 2026-01-01
```

Repeat the backtest against the **same snapshot ID** to reproduce metrics. A fresh download can
contain vendor corrections and produces new retrieval provenance; it is not a replay. This test
does not promote a strategy or demonstrate an investable edge. Keep data and private results
outside the public repository. No MCP server, new dependency or broker credentials are needed.

## Semantics and limits

- Set `ALGUA_EODHD_API_KEY` explicitly; `demo` is never selected automatically. Use a personal
  API key for non-demo instruments. Never put keys in source control or command arguments.
- Daily only: `--timeframe 1d`, `--adjustment none` (or `raw`). Use bare US vendor symbols
  such as `AAPL` or `BRK-B`; the adapter appends `.US`. Dotted symbols and foreign exchanges
  are refused instead of guessing an identity mapping.
- Algua windows are `[start, end)`. The adapter translates to EODHD's inclusive dates and clips
  responses locally. Today's unfinished daily bar is excluded.
- OHLC stays raw; `adjusted_close` becomes `adj_close`. EODHD volume is split-adjusted;
  the adapter divides by subsequent split ratios to restore raw share volume, including splits
  **after** the requested end date. It therefore retrieves splits through the retrieval date.
- Typically two API requests per symbol (prices and splits), plus bounded retries for transient
  failures. A free account's 20-call daily allowance is small; demo access has different limits.
- Missing symbols, failed split requests, malformed data and exhausted transport retries abort
  the whole ingestion before a snapshot is published. Missing individual sessions remain absent;
  coverage is not certified and bars are never fabricated or forward-filled.
- Source metadata records retrieval time, response hashes, symbol mapping and volume semantics.
  Retrieval time is **not historical knowledge time**. Prices/adjustments are current vendor
  vintages, not a historical revision archive. Split-feed completeness is not independently proven.
- Historical constituents, delistings, terminal proceeds and fundamentals are not ingested by this
  adapter. The paid membership add-on requires separate integration and acceptance checks.

Start a paid **monthly** prices/membership trial after the free path works, to evaluate actual
midcap coverage. A subscription does not make these snapshots verified PIT or change any gate.

Sources: [daily API](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes),
[splits API](https://eodhd.com/financial-apis/api-splits-dividends),
[adjustment and revision methodology](https://eodhd.com/help/methodology).

## Next-session handoff

The free path has been exercised on the VPS using an isolated source copy: 1,000 genuine demo
bars (250 expected 2025 NYSE sessions for each of AAPL, AMZN, TSLA and VTI), snapshot integrity
verification, two network-disabled backtests with identical metrics, and 32 focused EODHD tests.
Under a one-CPU limit, backtests took about 36 seconds cold and 7 seconds cached, with peak
process RSS about 551 MiB. This is a small mechanics benchmark, not a full-universe capacity test.

After purchasing a monthly subscription:

1. Install the API token privately as `ALGUA_EODHD_API_KEY`; never paste it into a chat, task,
   public report or Git. Do not replace any existing broker credentials.
2. Check paid price/split entitlements on representative midcaps. Then implement the historical
   constituents importer through the existing universe seam; it is **not** part of this adapter.
3. Freeze the intended date range and reconstruct membership, including removed securities.
   Audit gaps, action economics, identities and missing terminal proceeds before qualification.
4. Re-evaluate the intended strategy with new snapshot identities and existing holdout rules.
   Do not silently treat today's corrected history as historically available data.

The EODHD provider remains an explicit ingestion choice. Existing paper/live refresh defaults,
scheduled research inputs and qualification/trading gates are not switched to it by installing
the adapter. Configure operational adoption separately after dataset acceptance.
