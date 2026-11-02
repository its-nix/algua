# Walk-forward public disclosure

Ordinary walk-forward research publishes the existing research-window measurements and stability
statistics. The reserved final tail is exposed only by the existing `research promote` gate path,
which commits its single-use burn before evaluating that tail. Neither a read nor ordinary WF
recording burns a holdout. This repair does not change simulation, gate criteria, authentication,
capital rules, provider inputs, identities, schema or historical records.

## What the public windows measure

`algua/backtest/walkforward.py::_segment_bounds` partitions a single simulation's ordered return
series of length `n`. Let `h = int(n * holdout_frac)`, `train_n = n - h`, and `u = train_n - embargo`.
The public research region is `[0, u)`. It is divided into `windows` contiguous segments of
`floor(u / windows)` bars; the last segment receives the remainder. `[u, train_n)` is the purge
gap, and `[train_n, n)` is the reserved tail. Segment indices are half-open; reported `start`/`end`
are the first/last included bar dates. Each public segment has at least five bars.

These public segments are **in-sample/selection/pre-holdout research windows**, not independent
OOS folds. The implementation
runs a strategy once and segments its return series. It does not train a separate model for each
window. Earlier inputs may supply feature history, and the research windows can be reused for
selection. Neither their mean Sharpe nor their dispersion is a concatenated-series or holdout
Sharpe.

Window records retain the existing canonical `metrics_from_returns` definitions and names:

- `n_bars`: the number of included return observations.
- `total_return`: `product(1 + r) - 1` within this window.
- `ann_return`: `252 * mean(r)`; `ann_volatility`: `sqrt(252) * std(r, ddof=1)`.
- `sharpe`: annualized arithmetic excess return divided by annualized volatility, with the
  existing zero risk-free assumption. The core's existing zero-volatility sentinel is zero;
  inspect volatility alongside it. This repair does not recalibrate the core or gate statistics.
- `max_drawdown`: the minimum of `equity / running_peak - 1`, with running peak floored at 1.
- Other existing window metrics (`sortino`, `cagr`, `calmar`, `hit_rate`, `tail_ratio`, `skewness`,
  `kurtosis`) keep the definitions and undefined-value conventions in `backtest/metrics.py`.

The four existing public stability measures have the following exact definitions:

| Result key | Ledger column | Definition |
|---|---|---|
| `mean_sharpe` | `mean_window_sharpe` | Unweighted arithmetic mean of the window Sharpes. |
| `std_sharpe` | `std_window_sharpe` | Population standard deviation across window Sharpes (`ddof=0`). |
| `min_sharpe` | `min_window_sharpe` | Minimum window Sharpe. |
| `pct_positive_windows` | `pct_positive_windows` | Count of windows with `total_return > 0` divided by window count; a fraction, not 0–100. |

A measured zero or negative value remains that value. Missing/non-finite public stability
measurements remain unavailable (`null`/UNKNOWN), never an invented zero. A sweep parent's
`mean_trial_sharpe` is the existing mean **across combinations** of their mean-window Sharpes;
it does not populate `mean_window_sharpe`. No public aggregate return/drawdown or replacement
three-axis metric is introduced.

## Recording and read inventory

| Entrypoint / consumer | Disclosure behavior |
|---|---|
| `WalkForwardResult.to_dict()` | Closed public result projection; excludes tail metrics, tail returns, market returns and unknown nested result fields. Private attributes remain available internally. |
| `backtest walk-forward`, including `--summary` and `--track` | Uses the public result projection and public recorder. CLI help names research windows. |
| `registry/runs.py::walk_forward_metrics`, `record_walk_forward_run` | Maps only the four explicit window/stability columns. Never reads tail metrics. |
| `RunLedgerMixin.record_run` / `_insert_run_locked` | For ordinary `walk_forward`, `sweep`, `sweep_trial`, stores only their public metrics/config namespaces. Caller flags, supplied identities, gate pointers or strategy IDs cannot enable tail fields. |
| `record_sweep_trials` / `record_sweep_run` | Keeps explicit per-combination window stability and opaque user parameters; no OOS aliases or per-trial series. |
| `RunLedgerMixin.get_run` / `list_runs` | Projects historical ordinary windowed rows on read, preserving `sqlite3.Row` compatibility. Private aliases, nested outcome metadata, components and series pointers are withheld. Sort/limit uses NULL for unavailable ordinary sample metrics, preventing a hidden-tail ranking side channel. |
| `run_list_payload`, `run_detail_payload`, `run_series_payload` | Public row projection; ordinary overflow aliases are withheld. Sweep parents keep only the documented `mean_trial_sharpe` overflow. Ordinary series pointers cannot export a private vector. |
| `runs list`, `runs show`, `runs series` | Same shared projections, including raw JSON stdout exports and sorted/limited queries. There is no separate CSV/export route in this baseline. |
| `/api/runs`, `/api/runs/{id}`, `/api/runs/series` | Real CLI subprocess adapter serves those same projections. GETs do not burn or modify evaluation evidence. |
| `runs board` / `/api/strategy-board`, including opt-in evidence | Baseline board reads the latest **gate** per stable strategy ID; ordinary WF rows never become gate evidence. Existing lineage/snapshot/cost validation remains in place. |
| `Research.tsx`, `ScatterISOOS.tsx`, `TrialDistribution.tsx`, `ReturnOverlay.tsx`, strategy details | Existing consumers use the preceding APIs, gate rows and explicit trial-window columns. No independent database/holdout reader or fallback reconstruction exists. Gate scatter/board evidence remains available. No UI rewrite is included. |
| `log_walk_forward` / `log_sweep`, including SQLite tracker delegation | Metrics and `result.json`/`sweep.json` artifacts use the closed public projections, including nested sweep entries. Explicit user parameter namespaces are retained. |
| `knowledge/metrics.py::latest_run_metrics` → KB `RESULTS` block | Historical WF and sweep metrics use closed public vocabularies; ambiguous legacy kinds expose no measurements. No historical MLflow run is rewritten. |
| `evaluation/sweep_run.py::sweep_task` and its research-run-all / mergeback callers | Uses projected sweep output and public sweep recorders; measured breadth remains unchanged. |
| `registry/allocations.py::portfolio_risk_estimates` | Reads gate evidence rather than private-backed ordinary WF columns. Existing identity, as-of, observation-floor and allocation formulas are unchanged. No production caller currently invokes this helper. |
| `research promote` → `promotion.run_gate` | Records a public-window WF sibling, then maps private tail scalars only into the gate row using the original sample mapping. Existing burn, reuse, failure, auth and gate decisions are unchanged. The private vector remains in the existing sibling-only holdout store. |

Historical ordinary WF `*_oos` columns are **legacy UNKNOWN** on public reads, even if a later
matching gate/burn/config exists. They are never relabeled, backfilled, deleted or retro-burned.
Explicit historical window columns retain their existing meaning. Database contents remain
unchanged by projection; this repair does not erase evidence of earlier disclosure. Existing
already-authorized gate scalars and gate history remain gate evidence.

The public configuration projection keeps explicit `params` and sweep `grid` namespaces opaque
and lossless, including nested values and keys that happen to resemble outcome names. It selects
known configuration/input-metadata fields rather than recursively stripping user keys. Arbitrary
`result`, diagnostics, raw JSON and caller authority flags are not public metadata. Snapshot IDs,
content hashes and lineage IDs are never replaced. Public admission is all-or-nothing for
complete known INPUT source-metadata shapes. Canonical storage validity and public admission are
separate: arbitrary string maps remain legal INTERNAL input metadata, while unknown additions,
partial shapes and mixtures make ordinary public provenance unavailable (the existing safe INVALID
wrapper). This does not declare the original internal snapshot invalid or rewrite it. No supplied
hash, public flag or unrestricted namespace admits unknown metadata. Admitted canonical records
retain every original byte/value, including the original validated research envelope; unsupported
records are never stripped, rehashed or presented as a complete original record.

File/directory fields use basename strings, with no untyped object/list JSON payloads.
Supported source-metadata producers, inventoried from the current code:

| Producer | Complete input keys (all values are strings) |
|---|---|
| Generic local `DataStore.ingest_bars` / `ingest_file` | Empty producer map. |
| `data/providers/yfinance.py::get_bars` | `library=yfinance`, `timeframe` matching the record, `adjustment=none`; provider `yfinance`. |
| `data/providers/alpaca.py::get_bars` | `api=alpaca`, HTTPS `base_url` on the existing data host, matching `timeframe`, `adjustment=raw+all`; provider `alpaca`. |
| `data/importers/firstrate.py::import_bars` chunk | `vendor=firstratedata`, `symbol` belonging to the record, `raw_file`, `adjusted_file`; provider `firstrate`. |
| `data/importers/databento.py::import_bars` chunk | `vendor=databento`, member `symbol`, `raw_file`; provider `databento`. |
| `cli/data_cmd.py::import_bars` FirstRate consolidation | `vendor=firstratedata`, `raw_dir`, `adjusted_dir`; provider `firstrate`. |
| `cli/data_cmd.py::import_bars` Databento consolidation | `vendor=databento`, `raw_dir`, `corp_actions_file`, lowercase SHA256 `corp_actions_sha256`, `ca_schema_version=1`; provider `databento`. |

`data/store/bars_streamed.py` adds the complete group `observed_start`, `observed_end` (matching
the record), `content_hash_algorithm=bars-symbol-merkle-v1`, plus independently optional
`requested_start` / `requested_end` canonical dates within observed coverage. The group is admitted
with each known base shape; incomplete groups are unsupported. `data/provenance_binding.py` may
add the existing `research_provenance` envelope independently to any supported shape. Its strict
canonical parser, declared coverage/provider binding and original snapshot identity are still
validated separately. The envelope's closed fields do not extend the producer namespace.

`data/refresh.py` forwards provider metadata without adding fields. `scripts/pilot_proxy.py` uses
`ingest-bars --provider yfinance` plus the existing typed pilot declaration: its supported shape
is yfinance plus `research_provenance`. Selection/download audit details stay in the separate
campaign artifacts; they are not additional snapshot source-metadata fields. This inventory
requires no provider, storage, schema or hash-algorithm change.

**R1 supersession:** the original review's exactness requirement applies to admitted complete
records. Its unrestricted supplementary/future-field positive expectation is explicitly superseded
by the approved closed INPUT admission decision. The former mixed importer/future-field product
fixture and original reports/probes are preserved in the execution handoff; they are not claimed
to pass unchanged. In particular, the original independent R1 probe combines importer fields with
provider `fixture`, outside supported producer shapes. The replacement positive controls use actual
producer outputs and exact canonical records, while unsupported-but-canonical controls prove no
lossy surrogate or false original binding is published.

Safe invalid markers preserve the distinction from absence across repeated projection. Known
measurements/counts accept their numeric types, never raw JSON strings or booleans. Costs require
the existing complete schema/constants and finite nonnegative fees/slippage. Invalid measurements
become unavailable; invalid costs/provenance stay INVALID. No historical record is rewritten.

The new metadata projector retains CODEOWNERS protection; the ledger projector is covered by the
existing `registry/store/` rule. Ownership tests include both. No protection rule is weakened.

## Verification boundary

Synthetic disjoint public/private sentinels exercise the actual recorder, generic store, CLI
(default and summary), HTTP GET → CLI subprocess, tracking calls, raw JSON, historical rows,
unknown/zero/negative statistics and opaque parameters. Existing synthetic promotion controls
exercise single-use burns, preflight failures, post-peek failures, retry/reuse and authenticated
human flows. Reversible mutations verify the guards can fail the relevant tests.

The author report and command logs are under the authorized `holdout-repair-execution` handoff.
Independent whole-diff review and the coordinator's one staged, frozen full-root gate remain
required. PR736 stays draft/held; its public-window UI adaptation is separate. No real reserved-tail
experiment, production-registry inspection, deployment or historical data operation is acceptance
evidence for this patch.
