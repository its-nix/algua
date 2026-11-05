# Offline linear training on a fixed historical vintage

```sh
uv run algua model train-linear NAME --request train.json
uv run algua model show NAME --version 1
```

`train.json` is UTF-8 JSON with exactly these six fields:

```json
{
  "schema": "price-linear-proxy-train/v1",
  "bars_snapshot_id": "EXACT_EXISTING_SNAPSHOT_ID",
  "symbols": ["AAA", "BBB"],
  "train_start": "2024-11-01T00:00:00Z",
  "train_end": "2025-11-01T00:00:00Z",
  "l2": 0.001
}
```

This producer implements the approved **fixed-vintage historical-proxy** interpretation only.
It verifies one local daily snapshot with declared `pilot_real_proxy` or `synthetic_fixture`
provenance and checks a complete common XNYS grid for the consumed prices. Unknown provenance
and unsupported layouts refuse. Existing readability verification and separate recomputation of
the existing logical content hash/snapshot ID are both required. Original source metadata,
physical hashes, source verification time, actual fit clocks and all data limitations remain in
the registered provenance. Historical source availability stays **UNKNOWN**.

The [pooled numerical recipe](price-linear-components.md) fits one shared standard scaler and
two shared coefficients for one/five-observed-bar returns and the next adjusted-close return.
Bounds are explicit aware UTC-midnight labels and half-open. Future prices are excluded before
features and next-row targets; up to five prior sessions supply warmup. Missing consumed sessions
or prices refuse rather than fill. The core's disjoint warmup/unlabelled/fitted counts are retained.
There is no random step; the registered seed is null. A consumed-price digest records the exact
ordered numerical input; the existing core defines its features and target deterministically.

For this producer, `training_as_of` is derived from the XNYS close of the last complete target
session. It is a declared computational cutoff for the counterfactual proxy, not vendor knowledge
time. Stored snapshot `as_of`/`created_at`, verification, fitting and model publication clocks
remain separate. This interpretation does not change arbitrary existing ModelRefs, the registry's
digests, or the existing first-decision/PIT/lifecycle checks.

One call fits once and registers once in configured `<data_dir>/models`. A successful repeat
creates a new immutable version. Registration is never automatically retried. Output contains
the existing minimal ModelRef projection plus `proxy` disclosures and a small `fit` summary;
artifact bytes/paths and full source metadata/reports are omitted. Preserve the request, trained
artifact/store, output and exact snapshot for reproduction. This command adds no scratch-worker
transport, lifecycle advancement or model-cleanup permission.

The request fits 64 KiB and the registered report fits 1 MiB. Supported source preflight limits are
512 symbols and 2,000,000 recorded rows; payload inventory is capped at 4096 entries/2048 files.
The numerical core also caps consumed rows/cells. These are supported-workload/materialization
limits, not strict whole-registry I/O or Parquet-expansion guarantees.

An authored research wrapper uses the exact returned literal pin through the existing loader:

```python
from algua.contracts.model_types import ModelRef
from algua.contracts.types import ExecutionContract
from algua.features.price_linear_context import score_price_linear
from algua.strategies.base import StrategyConfig

REF = ModelRef(**EXACT_RETURNED_MODEL_REF)
STRATEGY_INTERFACE = "context_v1"
CONFIG = StrategyConfig(
    name="my_trained_proxy", universe=["AAA", "BBB"], params={},
    execution=ExecutionContract(rebalance_frequency="1d", warmup_bars=5,
                                decision_lag_bars=1),
    construction="equal_weight_positive", needs_model=True, model_ref=REF,
    feature_lookback=5)

def score(context):
    return score_price_linear(context, model_key=REF.name)
```

The pure helper validates the committed producer profile/pin and applies only frozen parameters.
It scores a subset of explicitly trained symbols without registry/data access or fitting.
`warmup_bars=5` is necessary: zero scores alone can still allocate under some construction policies.
Use existing `backtest run` with an evaluation interval beginning after the computed cutoff; do
not prepend training history to evade the first-decision check. Canonical costs and next-bar fills
remain unchanged. Chronological out-of-fit results on a previously examined pilot are not a
globally untouched gate holdout, historical-PIT proof, qualification, or evidence of alpha.
