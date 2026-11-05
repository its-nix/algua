# Real-data sweep throughput and retention

On 2026-11-04, four existing bars-only mechanisms each ran a 25-configuration grid through
the actual `algua backtest sweep` command. All four commands exited zero. The scratch registry
recorded four sweep parents and 100 distinct trial configuration identities. This is a finite
engineering benchmark, with no OpenCode session, newly authored hypothesis or investment
qualification. A separate final-artifact audit passed 3,638 checks after the collector stopped.

## Inputs and attribution

The frozen image extends commit `1c965f607e8a676c731a3acb7224f73acff0db56` with four private
strategy copies. Each copy changes only `CONFIG.name` and the explicit 150-symbol universe;
the algorithm syntax tree, execution contract and other defaults are preserved. The full
frozen source digest is
`99e7f49ede0176dcf04a40a58f23fca70daee74b31b603165a824d0eee9fb20d`.
The private fixture's Git HEAD is `49e536b3b5be3f6d679787fed6e92b38a8b1ca0f`; recorded runtime
code stamps also include their actual dirty suffixes. The published base SHA alone is not the
identity of the executed private fixture. One inherited ignored Markdown report is present in
the frozen source but absent from that fixture's Git index; every frozen Python file is tracked.

The existing yfinance pilot contains 150 symbols, 501 NYSE sessions and 75,150 bars. Its snapshot
is `61a2bda1e636d017`, with logical payload SHA256
`e63c513cf2b5820d0ef468de7c22e8ab53552a07c1f81a1b625c7849ac1dc550`.
The interval is `[2024-11-01T00:00:00Z, 2026-11-03T00:00:00Z)`; the last session is November 2.
Selection used the sorted first 150 names of a current S&P400 constituent list. This is a
survivorship-biased, non-point-in-time proxy. The seven recorded limitations remain:

- `adjusted_close_vendor_revisable`
- `corporate_actions_unverified`
- `delisted_names_absent`
- `event_timing_unavailable`
- `historical_market_cap_unavailable`
- `point_in_time_universe_unavailable`
- `survivorship_biased_selection`

No new market data was fetched during the benchmark. Commands used the local
`StoreBackedProvider`; its method-call count was not instrumented. The container had no network.

## Executed grids

All commands used the same snapshot and interval, `--windows 3 --holdout-frac 0.2
--rank-by mean_sharpe --top 25`. Fees and slippage were each 0.0005 per side in their existing
recorded units. The actual seed is `null`; this case does not invent a numerical seed.

| Existing strategy | Private copy | Grid, 25 combinations each | Command seconds |
| --- | --- | --- | ---: |
| `momentum/cross_sectional_momentum.py` | `benchmark150_xs_momentum` | `lookback=10,20,30,45,60`; `construction.top_k=3,5,10,15,20` | 16.283 |
| `mean_reversion/peer_median_oversold_rebound.py` | `benchmark150_peer_rebound` | `vol_lookback=10,15,20,25,30`; `spike_z=1,1.5,2,2.5,3` | 40.495 |
| `low_volatility/market_residual_low_volatility.py` | `benchmark150_residual_lowvol` | `lookback=10,20,30,45,60`; `construction.top_k=3,5,10,15,20` | 26.769 |
| `quality/ulcer_quiet_momentum_quality.py` | `benchmark150_ulcer_quality` | `lookback=20,30,40,50,60`; `ulcer_weight=0.25,0.5,1,1.5,2`; fixed `momentum_lookback=20`, `skip=5` | 28.962 |

The feature-history declarations remain 60, 33, 121 and 168 respectively. Peer rebound retains
its existing `return_lookback=3`. Only cross-sectional momentum uses its existing panel fast
path; the other strategies use canonical decision evaluation. Each configuration simulates the
full period once and then derives research windows. Three windows plus the private holdout are
not four separately executed simulations. The sweep computes private holdout information
internally; its public output and retained memory withhold those metrics. This benchmark did
not inspect them or invoke promotion.

The four numerical commands took 112.509 seconds combined. The whole collector took 151.493
seconds, including setup, retention and its final failure. These are one-machine measurements,
not a sustained throughput guarantee. Limits were two CPUs, 4 GiB memory, 256 PIDs, 1 GiB
temporary storage, no network, dropped capabilities and no new privileges, with a non-root
UID. The image root and pilot/input mounts were read-only; the owned main checkout and worker
under the output mount were writable and hash-verified. The 1 GiB temporary-storage limit was
the `/tmp` tmpfs. Per-command and whole-case deadlines were 1,800 and 7,200 seconds. The 2 GiB
output budget was a sampled soft stop, not a hard filesystem quota.

## Retained results and cleanup

The original collector checked all 100 effective configuration hashes, public parameters,
parent links, fees, slippage, snapshot metadata and three-window stability metrics. The actual
registry contained 104 public run rows and four breadth rows summing to 100. No trial was
truncated. Sparse child provenance must be interpreted through its exact sweep parent;
children do not independently repeat every parent field.

| Grid | Negative mean research-window Sharpe | Zero | Positive |
| --- | ---: | ---: | ---: |
| Cross-sectional momentum | 4 | 0 | 21 |
| Peer rebound | 20 | 0 | 5 |
| Residual low volatility | 16 | 0 | 9 |
| Ulcer quality | 6 | 0 | 19 |
| Total | 46 | 0 | 54 |

These are signs of the recorded research-window aggregate across a searched grid. They do not
count independent alphas, holdout successes, expected live returns or gate decisions.

The actual `research memory capture` published 104 evaluations to the existing local MLflow
store. Artifact SHA256 is
`409202f58e016047f00cf8dc05d82ad7daf1db37d59f78227e138168b01a79fe`.
The archive retains public inputs and stability metrics, original run IDs, exact parent
references, costs, limitations and negative results. It does not retain every raw per-window
simulation record. Its labels remain `UNVERIFIED_WORKER`, `authority=none`,
`evaluated_worktree_verified=false`, `model_bytes_preserved=false` and unknown unrecorded
variant failures. A SHA receipt verifies retained bytes; it does not establish economic truth.

The existing `cleanup-check` passed, the actual driver removal path pruned the worker and its
scratch registry, and a real `research memory show` after removal returned the same complete
public archive. No optional prompt projection was exercised here. The complete 104-row archive
must not be described as 104 observations delivered through the separately bounded 24-row
prompt interface.

## Original collector failure

After the sweeps, capture, planned engineering stop, verified removal and post-removal readback,
the external collector queried the existing idea scorecard. That CLI returned valid JSON and
exit zero, but the collector then accessed a nonexistent `scorecard['totals']` key. The legacy
scorecard groups results under `by_venue`, `by_category`, `by_obscurity` and `by_inspiration`.
The original collector therefore exited one with `KeyError: 'totals'` and did not write its final
PASS receipt or final authority-state export. That failure is preserved. No simulation was
rerun to obtain a successful wrapper exit, and no original PASS receipt has been reconstructed.

The one engineering idea attempt was deliberately finished through `setup_failed` with
`run_error` and reason `setup_failed:1`, after capturing numerical worker exit zero. This is a
controlled engineering terminal outcome, not a negative alpha verdict or evidence that an
OpenCode worker failed. The separate audit inspected finalized private database copies and
confirmed zero authority economic evaluations, search breadth, gate decisions, lifecycle
advances and trading records, with exactly that one engineering attempt. It did not infer these
counts from the missing `totals` field or restore scratch rows into authority.

The independent audit recomputed all 100 configuration identities and compared all 104 raw,
public and archived rows, exact parent references, metrics, costs and limitations. It verified
the retained artifact SHA and byte-identical public readback before and after removal. Source,
pilot and earlier evidence inventories remained unchanged. The owned checkout's final Git
index was checked by entry mode, path, blob and recomputed tree, alongside physical source
hashes; no claim of byte-identical pre/post Git index files is made. Its original overly strict
index-byte assertion is preserved in the audit history. This separate audit establishes the
bounded numerical/retention results while leaving the original collector's failed exit intact.

## Acceptance boundary

This case demonstrates actual finite sweep computation and public-result retention across four
existing mechanisms. It does not demonstrate 100 independent research hypotheses, a model call,
causal use of memory, ten unattended research cycles, elapsed forward testing, portfolio
qualification, paper deployment or live readiness. Raw private evidence remains outside the
repository; the [aggregate receipt](real-sweep-benchmark.json) records public identities and
counts only.
