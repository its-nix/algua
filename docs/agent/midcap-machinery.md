# Liquid-midcap machinery sample

Owner approval, 2026-11-08: start with daily U.S. mid-cap strategies and target multi-day holds
of roughly 2–20 sessions. The first universe is a current S&P MidCap 400 proxy with price >= $10,
60-session median raw-close × volume >= $20M, and >=252 distinct observed sessions. Observed
history is not proof of a listing date. Select up to 300 names by sector round-robin, ordered by
liquidity within each sector. A pool below 150 is reported honestly; never silently lower a floor.

`scripts/midcap_screen.py` is a read-only screen/audit of a verified canonical bars snapshot and
the retained membership-source HTML. It records every inclusion/exclusion, source digest, bars
identity, exact thresholds and sector counts. It never creates a PIT universe, approval or
qualification. `broker_tradability_verified=false` remains explicit: Alpaca active/tradable status
still needs an authenticated read before operational admission.

The initial acquisition used the existing `data ingest-bars --provider yfinance` seam with
`--data-tier pilot_real_proxy` and the exact source digest in `--universe-method`. The canonical
snapshot retains all seven proxy limitations. No membership is backdated. All downloaded payloads,
membership HTML, private manifests and order traces belong outside Git.

## Machinery walkthrough

On Linux with the locked environment and an isolated `ALGUA_DATA_DIR`, `ALGUA_DB_PATH` and
`ALGUA_KNOWLEDGE_DIR`:

```bash
uv run algua data verify --snapshot-id SNAPSHOT
uv run python -m scripts.midcap_screen --data-dir DATA --snapshot SNAPSHOT \
  --membership-html constituents.html > screen.json
uv run algua backtest run midcap_weekly_momentum_smoke --snapshot SNAPSHOT \
  --start 2024-11-01 --end 2026-11-08 --register
uv run algua backtest walk-forward midcap_weekly_momentum_smoke --snapshot SNAPSHOT \
  --start 2024-11-01 --end 2026-11-08 --windows 4 --holdout-frac .2 --summary
uv run algua backtest sweep midcap_weekly_momentum_smoke --snapshot SNAPSHOT \
  --start 2024-11-01 --end 2026-11-08 --param lookback=20 --summary
```

`midcap_weekly_momentum_smoke` pins the actual selected 300-symbol November 8 sample. Its fixed
20-session adjusted-price momentum ranks at the latest completed Friday anchor; the basket may
stay selected across multiple weeks. This demonstrates a multi-day style, not a hard holding-age
exit. It retains the normal one-bar execution lag, concentration guard and 10bps per-side combined
modeled costs. There is one declared parameter combination, not an optimization or new alpha claim.
Appending future data cannot change earlier scores, and the vectorized scorer is checked against
every prefix of its canonical scorer. A changed sample requires a new reviewed strategy revision;
the screen does not silently mutate the existing strategy.

The costed backtest gives exploratory economic metrics only. It does not establish
investability from current-survivor proxy data. An observed full backtest is not an untouched
holdout. Keep strict promotion refusals; five real paper sessions remain five elapsed sessions.
Liquidity screening uses Yahoo's reported volume; IEX-only volume is not an interchangeable input.

## Recorded initial acquisition

- Snapshot `c63d16f44419cb96`: 400 symbols, 201,760 bars, requested `[2024-11-01,2026-11-08)`;
  latest observed bar November 6. Canonical verification passed.
- 398 passed the economic/data screen; two failed the price floor. Sector-balanced selection
  retained 300 across all 11 source sectors; 98 passed but were outside the sample cap.
- This is a machinery sample. No source deployment, timer switch, brokerage orders, funding,
  approval or live activation follows from its acquisition.
