"""Research-only dense inference reference with hand-authored, UNTRAINED fixture weights.

Register the supplied bytes and declared metadata first; no training or model I/O occurs here.
The two ReLU hidden layers consume one/five-observed-bar returns from the immutable context.
"""
from __future__ import annotations

import hashlib

import pandas as pd

from algua.contracts.model_types import ModelRef, compute_provenance_digest
from algua.contracts.strategy_context import AsOfContext
from algua.contracts.types import ExecutionContract
from algua.features.dense_network import DenseNetworkError, FrozenDenseNetwork
from algua.features.price_linear import FEATURE_ORDER, return_features
from algua.strategies.base import StrategyConfig

GENERATED_BY = "agent"
STRATEGY_INTERFACE = "context_v1"

# Architecture is 2 -> 2 -> 2 -> 1, with both hidden ReLUs active in the executable fixture.
ARTIFACT_BYTES = FrozenDenseNetwork(FEATURE_ORDER, [
    {"weights": [[1, 0], [0, 1]], "bias": [0, 0]},
    {"weights": [[1, -2], [-1, 1]], "bias": [0.005, -0.01]},
    {"weights": [[1, 0.5]], "bias": [-0.002]},
]).to_json()
TRAINING_SNAPSHOT_ID = None
TRAINING_AS_OF = "2020-01-01"  # Illustrative declared pin, not evidence of historical training.
HYPERPARAMETERS = {"architecture": [2, 2, 2, 1], "hidden_activation": "relu"}
EVAL_REPORT = {"status": "hand_authored_inference_fixture", "trained": False}
_DIGEST = hashlib.sha256(ARTIFACT_BYTES).hexdigest()[:16]
MODEL_REF = ModelRef(
    name="model_dense_scores", version=1, digest=_DIGEST, training_as_of=TRAINING_AS_OF,
    provenance_digest=compute_provenance_digest(
        digest=_DIGEST, training_snapshot_id=TRAINING_SNAPSHOT_ID,
        training_as_of=TRAINING_AS_OF, code_hash=None, hyperparameters=HYPERPARAMETERS,
        seed=None, eval_report=EVAL_REPORT),
)
CONFIG = StrategyConfig(
    name="model_dense_scores", universe=["AAPL", "MSFT", "NVDA"], params={},
    execution=ExecutionContract(rebalance_frequency="1d", decision_lag_bars=1, warmup_bars=5),
    construction="equal_weight_positive", needs_model=True, model_ref=MODEL_REF,
    feature_lookback=5,
)


def score(context: AsOfContext) -> pd.Series:
    """Return finite scores using only the supplied closed history and exact model handle."""
    model = FrozenDenseNetwork.from_json(context.models[MODEL_REF.name].artifact_bytes)
    if model.features != FEATURE_ORDER:
        raise DenseNetworkError("dense reference requires return_1/return_5 in order")
    bars = context.features["bars"].frame
    wide = bars.reset_index().pivot(index="timestamp", columns="symbol", values="adj_close")
    if set(wide.columns) != set(context.universe):
        raise DenseNetworkError("dense reference requires bars for every scoring symbol")
    wide = wide.reindex(columns=list(context.universe)).iloc[-6:]
    features = return_features(wide)  # No filling; validate consumed prices before warmup handling.
    if len(wide) < 6:
        return pd.Series(0.0, index=list(context.universe), dtype="float64")
    return model.predict(features.xs(wide.index[-1], level="event_label"))
