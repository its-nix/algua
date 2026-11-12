# Sharadar sample check — owner runbook

This is step A of the PIT data pipeline. See the design at
`docs/superpowers/specs/2026-11-12-pit-data-pipeline-design.md` and the plan at
`docs/superpowers/plans/2026-11-12-pit-data-pipeline.md`. Nothing else in the pipeline is built until this check passes.

This page holds no vendor data and no conclusions about the data. Under the licence, Sharadar rows,
reports and fitness conclusions stay in your private KB (spec §3, §4.14).

## 1. Subscribe

Subscribe to Sharadar Prices with full history on Nasdaq Data Link, using your personal account.

## 2. Choose the adversarial sample

Pick a few securities that between them cover **every** case below. The check fails a sample that
misses one, because an easy sample proves nothing.

| Case | What to pick |
|---|---|
| split | a stock with at least one split |
| dividend | a stock with ordinary cash dividends |
| bankruptcy | a company that went bankrupt and was delisted with nothing left for shareholders |
| acquisition | a company acquired for cash and stock, or for stock only |
| reused ticker | a ticker used by two different companies at different times |

If you can, add a stock-only acquisition and a reverse split.

## 3. Export the three tables

Export SEP, ACTIONS and TICKERS as CSV, filtered to the sample tickers. Use the acquirer's ticker too.

Store them in a directory **outside** the repository, for example `~/algua-private/sharadar-sample/2026-11-xx/`.

At least five trading days later, export SEP again for the same tickers. The second pull measures
whether Sharadar changes old history.

## 4. Run the check

```bash
uv run algua data vendor-check --vendor sharadar \
  --sep ~/algua-private/sharadar-sample/<later>/SEP.csv \
  --actions ~/algua-private/sharadar-sample/<later>/ACTIONS.csv \
  --tickers ~/algua-private/sharadar-sample/<later>/TICKERS.csv \
  --previous-sep ~/algua-private/sharadar-sample/<first>/SEP.csv \
  --report-out <private KB path>/sharadar-sample-check-<date>.json
```

The command refuses three things:
- a `--report-out` inside the repository;
- a `--report-out` file that already exists;
- an export whose columns don't match the documented ones. The error names the missing columns.

The screen shows only check names, statuses and counts. The full report goes to `--report-out` with
file mode 600. The command exits 1 if the sample fails.

On macOS the CLI currently crashes on import (`os.waitid` is Linux-only). Run the command on the
VPS or inside a Linux container until that is fixed.

## 5. Read the result

| Check | Fails when | Meaning of a failure |
|---|---|---|
| `sample_coverage` | a required case is missing | Choose a better sample and rerun. Says nothing about the vendor. |
| `identity` | two securities sharing a ticker overlap in time, or a price row belongs to no security or to several | The vendor's security identity can't support a reused-ticker universe. |
| `raw_units` | split-adjusted `close` × later split ratios ≠ `closeunadj` | Raw prices can't be rebuilt (spec §4.10). A finding hinted `inverted_split_ratio` means the vendor writes the ratio the other way round. The importer can handle that, so note it rather than reject the vendor. |
| `terminal` | a delisted security has no terminal action within 30 days of its last price | Delisted names can't be resolved, and the survivorship check fails. |

Two checks are **for information only** and never fail the run:
- `adjusted_close`: whether the vendor's `closeadj` matches Algua's own back-adjustment. This decides spec §4.10, use `closeadj` or compute `adj_close`.
- `revisions`: how many old rows changed between the two pulls. This is the accepted restatement residual of spec §4.6.

## 6. Record the decision

Record pass or fail, the report path, and anything notable from the findings in your **private KB**,
not in this repository.
- **Pass:** Plan 2 (importer and universe) gets written next.
- **Fail** on `identity`, `raw_units` or `terminal`: the roadmap stops and the provider choice reopens.
