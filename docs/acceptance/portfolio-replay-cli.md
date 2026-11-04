# Bounded portfolio research replay

`uv run algua backtest portfolio --manifest /absolute/path/to/replay.json` exposes the existing
canonical multi-strategy reference replay. It evaluates the complete requested interval as
**in-sample research**, records one composite `backtest` run in the existing registry, and emits
JSON. It does not register a strategy, qualify a candidate, allocate capital, contact a broker,
operate paper sessions, or produce elapsed forward evidence.

## Manifest contract

The required `portfolio-replay/v1` manifest is a UTF-8 JSON object of at most 65,536 bytes.
Unknown fields, duplicate JSON keys, non-finite numbers, numeric strings and booleans masquerading
as numbers are refused. All fields below are required, including explicit `null` values.

```json
{
  "schema_version": "portfolio-replay/v1",
  "snapshot_id": "0123456789abcdef",
  "start": "2024-01-02T00:00:00+00:00",
  "end": "2024-04-23T00:00:00+00:00",
  "symbols": ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"],
  "sleeves": [
    {"strategy": "cross_sectional_momentum", "budget": 0.5},
    {"strategy": "high52_proximity", "budget": 0.5}
  ],
  "execution": {
    "rebalance_frequency": "1d",
    "decision_lag_bars": 1,
    "allow_fractional": true,
    "max_gross_exposure": 1.0,
    "max_weight_per_symbol": 1.0,
    "allow_short": false,
    "warmup_bars": 0,
    "fees": 0.001,
    "slippage": 0.002,
    "capacity": null,
    "fill_price": "open",
    "target_gross_utilization": 0.95
  },
  "constraints": {
    "max_gross": 0.9,
    "max_weight_per_symbol": 0.5,
    "max_turnover": null
  },
  "initial_cash": 17.5,
  "seed": 19,
  "risk_estimates": {}
}
```

The example snapshot ID is illustrative. Use an existing snapshot containing complete bars for
the explicit symbols. Every loaded strategy's declared universe must fit those symbols. The
command never prunes or replaces a strategy universe. The current S&P400 pilot and the bundled
large-cap examples have different universes; the example is not a claim that they are compatible.

Dates must carry an offset; equivalent instants normalize to UTC. The interval is `[start, end)`.
Each unique sleeve names an existing loaded strategy; budgets are fractions of account equity
whose sum cannot exceed one. Empty `sleeves` produces a valid all-cash replay, with explicit
nonempty symbols still required to define its session grid.

Costs belong to the explicit account execution contract and are not inferred from sleeve
defaults. Fees and slippage are per-side fractions, with the same effective units recorded by
the canonical simulator. `effective_replay_execution` discloses the existing replay adapter's
zero warmup and unit utilization: sleeve targets have already passed construction and warmup,
so those stages must not apply a second time. Supported execution is daily, fractional,
long-only, lag one, without
account capacity. Existing bounds remain 512 sessions, eight symbols, eight sleeves and two
million work units; arbitrary strategy callable wall time is not bounded by this grid limit.

An empty `risk_estimates` uses the allocator's existing conservative unknown-risk fallback.
An optional timeline entry has shape
`"strategy_name": [{"as_of": "2024-01-01T00:00:00+00:00", "volatility": 0.2, "source": "run:123"}]`.
Only declared sleeves may have entries. Future estimates are excluded at each decision. Supplied
estimates are explicitly labeled **unverified research assumptions**; naming a run does not
verify its lineage or confer qualification.

## Result and ledger

The `portfolio-replay-result/v1` payload includes canonical net-of-cost metrics, the effective
manifest, snapshot metadata and limitations when available, captured bars digest, code/config/
dependency identities, each loaded sleeve's exact config and recomputed artifact identity, and
session rows containing returns, simulator equity/cash, current holdings, decision targets and
lagged executable targets. Undefined zero-volatility ratios and a Sortino with zero downside
deviation remain `null`; a measured zero with a defined denominator remains zero.

The composite uses a content-derived `portfolio-replay:<sha256>` name and `strategy_id=null`.
It writes no sleeve metrics, gate/OOS metrics, holdout observations or lifecycle transitions.
The existing `runs.config_json` contains inputs, provenance, labels and scalar results; its
existing scalar-read contract excludes the session path. The path is returned by this command
for a caller to retain as its research artifact. Repeated executions produce
separate real run IDs while preserving composite identity for unchanged inputs and source.
Input/refusal paths and non-finite results are rejected before opening the registry. Sleeve
identities are captured before fresh source loading, rechecked before evaluation and rechecked
after replay before a successful result can be recorded.

The CLI completes ordinary imports for all declared sleeves before capturing any identity, so a
later declared feature import cannot invalidate an earlier capture. Fresh loading and all drift
refusals still apply. This request-level composition does not change the protected hash algorithm
or settle its broader dependence on arbitrary warm-process import state.

This command is one research integration slice. Scheduled account-level paper aggregation,
authoritative strategy isolation, broader multimodal replay, investment qualification and
unattended machine acceptance remain separate requirements.
