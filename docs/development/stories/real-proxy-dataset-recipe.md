# Current S&P 400 proxy dataset recipe

## Purpose and boundary

`scripts/pilot_proxy.py` builds a bounded, private research proxy from Wikipedia's current S&P 400
constituents table and daily yfinance bars. It is a current-survivor proxy, not a historical
point-in-time universe. It does not verify historical membership, market capitalization,
liquidity, delistings, or PIT eligibility, and it grants no alpha, paper, forward-test, Task 1, or
investment-acceptance claim.

The recipe converts `--output` to an absolute path and only writes beneath a new empty directory
outside the main repository and every linked Git worktree. Raw source bytes, bars, logs, the
isolated home, registry, and manifest therefore remain outside public Git. It refuses an output
containing existing campaign artifacts.

## Run

Use the locked Python environment. The script invokes the absolute installed `algua` executable
beside that interpreter without resolving the interpreter symlink away from its virtual
environment; it does not call write APIs directly.

```bash
<REPO>/.venv/bin/python <REPO>/scripts/pilot_proxy.py \
  --output <ABSOLUTE_NEW_EMPTY_DIRECTORY_OUTSIDE_REPO> \
  --start <YYYY-MM-DD_INCLUSIVE> \
  --end <YYYY-MM-DD_EXCLUSIVE> \
  --count <1_TO_300> \
  --batch-size <1_TO_300> \
  --attempts <1_TO_3> \
  --timeout <1_TO_300_SECONDS> \
  --source-url <HTTPS_MEMBERSHIP_SOURCE_URL>
```

Defaults are count 150, batch size 150, attempts 2, timeout 300 seconds, and Wikipedia's current
`List_of_S%26P_400_companies` page. End is half-open and may not exceed the current UTC date. The
recipe validates the real ingest/inspect/verify help surfaces before downloading the source.
The source URL and every redirect must remain HTTPS. Source retrieval has both curl's total
transfer deadline and a monotonic parent-process deadline, and the response is capped at 8 MiB
while streaming regardless of its advertised size.

The default parser requires the actual HTML `table#constituents` and its unique `Symbol` header. A
strict CSV with a unique `Symbol` header remains supported for a configured source. The original
response bytes—not a derived CSV—are preserved as `constituents.html` or `constituents.csv`, with
their SHA256 and UTC retrieval time. Source symbols are deduplicated and sorted, periods are
explicitly mapped to hyphens for Yahoo IDs, and alias collisions fail closed. The first N are
selected. Every duplicate or beyond-N source row is retained with an exclusion reason; failed
market-data symbols are never silently replaced.

## Bounded execution and evidence

The first two selected IDs form a designated non-campaign probe. With the defaults, all first 150
IDs then form one sequential CLI request and one stable campaign snapshot. A failed request
receives only the configured bounded retries, then falls back to bounded individual requests so
missing-symbol accounting is honest. Timeouts, non-zero exits, invalid JSON, and source-download
failures are recorded with unique bounded per-attempt stdout/stderr logs. Requested symbols are
checkpointed before subprocess entry, and the manifest is checkpointed after every attempt and
batch. The process exits non-zero unless every selected campaign symbol succeeds.

Each successful CLI ingest creates an immutable component snapshot. The recipe does not rewrite or
pretend to consolidate components. Read-only verification requires exact CLI inspect equality,
the existing CLI verify result, normalized `DataStore.read_bars` readback, recomputed logical bars
hash and snapshot ID, declared/actual symbol equality, row counts, half-open range and no-current-
or-future-bar checks, repeated-read digest equality, and physical per-file SHA256. Per-symbol
coverage lists row counts, first/last dates, missing XNYS sessions, and unexpected dates. Gaps and
partial histories are reported, never filled.

Primary private outputs are:

- `<OUTPUT>/campaign_manifest.json` — source/mapping/exclusions, all request attempts, immutable
  component IDs and hashes, audits, total rows, successful symbols, and missing symbols.
- `<OUTPUT>/source/constituents.html` (default) — exact original source response bytes; a custom
  CSV source is retained as `constituents.csv`.
- `<OUTPUT>/data/` — immutable component payloads and data manifest.
- `<OUTPUT>/logs/` — per-attempt stdout/stderr; summaries contain no raw bars.

## Repeatability and limitations

Pinned replay of the preserved source bytes plus the recorded immutable component IDs is exactly
repeatable and auditable. A fresh execution is a new vendor request: the source membership and
yfinance history may revise, so byte hashes, bars, component IDs, and coverage may differ. The
campaign manifest makes that distinction explicit rather than claiming fresh-download identity.

Bars contain raw OHLC and vendor-retrospective `adj_close`. Splits and dividends are not preserved
as an independently verified corporate-action ledger. Current membership omits historical exits
and delistings, selection is survivorship biased, and vendor gaps/revisions remain possible.

The normal successful first-150 request is one campaign component and therefore has one engine-
addressable snapshot ID; the two-symbol probe is explicitly non-campaign. If a batch fails and
individual fallbacks succeed, the resulting campaign has multiple immutable component IDs. The
research engine currently accepts one snapshot ID, so that fallback outcome needs a later,
separately admitted integration mechanism before engine use. Do not bypass `data ingest-bars`,
rewrite data, or manufacture a consolidated snapshot to cross that boundary.

## Same-PR acceptance contract and ownership

This bounded phase owns only `scripts/{__init__,pilot_proxy,pilot_proxy_audit,pilot_proxy_source}.py`,
`tests/test_pilot_proxy.py`, and this contract. The package marker gives mypy one unambiguous module
identity; no installed package, provider, schema, snapshot identity algorithm, or safety wall changes.

Acceptance requires: (1) preserved membership-source bytes/time/digest and deterministic complete
selection accounting; (2) a real small probe followed by bounded CLI requests; (3) at least 150
successful selected symbols with actual approximately-two-year coverage, or an explicit failure;
(4) immutable IDs, exact-ID CLI readback, logical/physical checks and gap accounting; (5) a usable
private pinned payload plus this executable recipe and focused tests; and (6) final root gates and
an independently reviewed PR before any permitted merge. This delivery is the dataset/recipe
phase, not downstream tier propagation or full Task 1/machine acceptance. No merge/deploy authority
is granted here. Root-gate results are attached after execution on the stable source tree rather
than embedding an unexecuted green claim in the contract.

## Read-only pinned replay checks

The recipe runs `algua data inspect --snapshot-id <ID>` and
`algua data verify --snapshot-id <ID>` under its sanitized environment and isolated CWD. To repeat
those checks, use the same installed CLI, set only `ALGUA_DATA_DIR=<OUTPUT>/data` and an isolated
`ALGUA_DB_PATH`, and run outside any directory containing `.env`. **Existing verify attests only
readability/row count, not a cryptographic payload comparison.** The separate audit uses the
following existing read-only path (replace the placeholders; do not ingest/relabel):

```python
from pathlib import Path
from algua.data.files import logical_bars_hash
from algua.data.store import DataStore, compute_snapshot_id

store = DataStore(Path("<OUTPUT>/data"))
record = store.get_snapshot("<PINNED_SNAPSHOT_ID>")
frame = store.read_bars(record.snapshot_id)
canonical = frame.reset_index().rename(columns={"timestamp": "ts"})
digest = logical_bars_hash(canonical)
assert digest == record.content_hash
assert compute_snapshot_id(record.metadata, digest) == record.snapshot_id
assert len(frame) == record.row_count
print(record.snapshot_id, len(frame), digest)
```

The recipe also compares exact inspect/ingest records, actual/declarative symbols and coverage,
repeated readback, half-open bounds, completed UTC dates, and every physical payload-file SHA256.
Those checks do not prove historical eligibility or vendor truth.

## Executed real acquisition and limitations

The initial guessed GitHub CSV URL returned HTTP 404. Wikipedia's actual 400-row constituents
source was used instead. A first corrected-recipe launch received two source HTTP 403 responses,
recorded a failed checkpoint, and exited nonzero before requesting bars. Identifying the public
research client with `User-Agent: AlguaResearchProxy/1.0` fixed that real path, test-first; no
credentials, paid endpoint, fabricated list, or provider rewrite was used. Both failures remain
in private evidence rather than being described as successful downloads.

The final recipe was actually executed with `[2024-10-31, 2026-10-31)`, count/batch size 150,
2 maximum attempts and a 300-second per-attempt timeout. Source retrieved at
`2026-10-31T13:28:28.119541+00:00`, SHA256
`26c10154b866dde2da11d086d0d82898bdea13c8ef869b2e5e9384d74a1c2feb`.
Deterministic sorted first 150 source/Yahoo IDs were AA through FNF; 250 other source rows were
excluded for being beyond the first N. The complete exact lists and mappings are in the private
campaign manifest, not inferred from the endpoints stated here.

- **150 requested = 150 successful**, no missing symbols; **75,150 campaign rows**, 501 XNYS
  sessions per symbol, observed dates **2024-10-31 through 2026-10-30**. No missing XNYS sessions,
  unexpected dates, current/future bars, or filled gaps were found. Weekends and 21 weekday
  non-sessions (including the 2025-01-09 closure) were excluded by the actual XNYS calendar.
- One engine-addressable campaign snapshot **`baaa116a36acee68`**, content hash
  **`4520fe1688c1d4811ec5dc19e2fdc1ed89379e90776ef88af9dbaf3858515c42`**.
  The two-symbol probe **`74960b0c809ffb12`** is non-campaign: 152 ticker requests across probe
  and batch, 150 distinct IDs. The final campaign had no failed attempts or individual fallback.
- Exact-ID CLI inspect equality and verify passed; independent logical-byte-contract SHA256,
  identity recomputation, repeated readback and 150 physical payload hashes passed. Manifest
  SHA256 is `dd99d35e9b3c6d083fa9cc28fcfafe05f19e704d3101d4762297fd2284c047ab`.
- The earlier standalone preflight snapshot `61cac291672a72c4` also had 75,150 rows, but its
  fresh-download content hash differs: 16,827 `adj_close` cells across 92 symbols changed, with
  maximum absolute difference below 0.0002; raw OHLC and volume were unchanged. Exact cause
  (vendor revision versus adjustment recomputation/rounding) is unverified. Both immutable
  downloads remain unchanged. **Fresh download identity is not repeatable; pinned readback is.**

Historical membership, $0.5–10B market-cap eligibility, price/liquidity/listing-age screens,
delistings, and corporate-action/event knowledge time remain **unavailable/unverified**. The
source is an observed current S&P 400 proxy (including its actual security types), not proof of
historical eligibility. No universe was registered/backdated, no holdout was accessed, and no
research/paper/forward/live operation or alpha claim was made. Python 3.12.3 was used explicitly;
the existing Python 3.12.12 wheel-identity baseline issue is not repaired or hidden here.
