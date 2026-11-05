"""Actual registry/loader/canonical inference with hand-authored, untrained dense weights."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pandas as pd
import pytest

from algua.backtest._sample import SyntheticProvider
from algua.backtest.engine import run, simulate
from algua.backtest.errors import BacktestError
from algua.contracts.model_types import ModelHandle
from algua.data.research_provenance import (
    SYNTHETIC_LIMITATION,
    DataTier,
    ProvenanceDeclaration,
)
from algua.data.serve import StoreBackedProvider
from algua.data.store import DataStore
from algua.models import register
from algua.strategies.base import LoadedStrategy
from algua.strategies.loader import StrategyNotFound, load_strategy, load_tradable_strategy
from algua.strategies.ml import model_dense_scores as reference


@pytest.fixture
def bars_provider(tmp_path):
    """An actual immutable snapshot of explicitly synthetic bars, not a fabricated handle."""
    start, end = datetime(2023, 1, 3, tzinfo=UTC), datetime(2023, 3, 1, tzinfo=UTC)
    symbols = reference.CONFIG.universe
    bars = SyntheticProvider(seed=1).get_bars(symbols, start, end, "1d")
    bars = bars[(bars.index >= start) & (bars.index < end)]
    store = DataStore(tmp_path / "synthetic-bars")
    record = store.ingest_bars(
        provider="synthetic-fixture", symbols=symbols, start=start.date().isoformat(),
        end=end.date().isoformat(), as_of="2023-03-02T00:00:00Z", source="synthetic-fixture",
        frame=bars.reset_index(),
        provenance=ProvenanceDeclaration(DataTier.SYNTHETIC_FIXTURE,
                                        "dense-inference-fixture/v1", (SYNTHETIC_LIMITATION,)),
    )
    return StoreBackedProvider(store, record.snapshot_id)


@pytest.fixture
def model_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    return tmp_path / "models"


def register_reference(root, **overrides):
    metadata = dict(
        training_snapshot_id=reference.TRAINING_SNAPSHOT_ID,
        training_as_of=reference.TRAINING_AS_OF,
        code_hash=None,
        hyperparameters=reference.HYPERPARAMETERS,
        seed=None,
        eval_report=reference.EVAL_REPORT,
    )
    metadata.update(overrides)
    return register("model_dense_scores", reference.ARTIFACT_BYTES, root=root, **metadata)


def test_actual_registration_and_loader_bind_exact_bytes_and_full_provenance(model_root):
    version = register_reference(model_root)
    strategy = load_strategy("model_dense_scores")
    assert version.as_ref() == reference.CONFIG.model_ref
    assert version.digest == hashlib.sha256(reference.ARTIFACT_BYTES).hexdigest()[:16]
    assert version.training_snapshot_id is None and version.seed is None
    assert version.eval_report == {"status": "hand_authored_inference_fixture", "trained": False}
    assert strategy.strategy_interface == "context_v1"
    assert strategy.required_features == frozenset({"bars"})
    assert strategy.required_models == {version.name: version.as_ref()}
    assert strategy.model_handle.artifact_bytes == reference.ARTIFACT_BYTES


def test_canonical_context_backtest_dense_scores_after_warmup_with_next_bar_lag(
    model_root, bars_provider,
):
    register_reference(model_root)
    strategy = load_strategy("model_dense_scores")
    start, end = datetime(2023, 1, 3, tzinfo=UTC), datetime(2023, 3, 1, tzinfo=UTC)
    result = run(strategy, bars_provider, start, end, seed=1)
    assert result.strategy == "model_dense_scores"
    assert result.model_ref == reference.CONFIG.model_ref.as_dict()
    assert result.seed == 1
    assert result.snapshot_id == bars_provider.snapshot_id
    portfolio, executed, _ = simulate(strategy, bars_provider, start, end)
    assert (executed.iloc[:6] == 0).all().all()
    assert executed.iloc[6:].abs().sum().sum() > 0
    assert portfolio.orders.records_readable.iloc[0]["Timestamp"] >= executed.index[6]
    assert not pd.isna(result.metrics["sharpe"])


def test_missing_model_refuses(model_root):
    with pytest.raises(StrategyNotFound):
        load_strategy("model_dense_scores")


def test_discovery_and_config_inspection_need_no_registered_model(model_root):
    from algua.strategies.loader import list_strategies, load_strategy_config

    assert "model_dense_scores" in list_strategies()
    assert load_strategy_config("model_dense_scores").model_ref == reference.MODEL_REF
    assert not model_root.exists()


@pytest.mark.parametrize("change", [
    {"training_as_of": "2020-01-02"},
    {"training_snapshot_id": "invented-training"},
    {"eval_report": {"status": "rewritten"}},
    {"hyperparameters": {"architecture": "different"}},
])
def test_changed_training_provenance_does_not_satisfy_reference_pin(model_root, change):
    register_reference(model_root, **change)
    with pytest.raises(StrategyNotFound, match="does not match"):
        load_strategy("model_dense_scores")


def test_tampered_artifact_bytes_refuse_before_scoring(model_root):
    version = register_reference(model_root)
    artifact = model_root / version.name / "v1" / "artifact.bin"
    artifact.write_bytes(reference.ARTIFACT_BYTES + b" ")
    with pytest.raises(StrategyNotFound):
        load_strategy("model_dense_scores")


def test_registry_valid_but_invalid_dense_payload_refuses_in_canonical_context(
    model_root, bars_provider,
):
    register_reference(model_root)
    original = load_strategy("model_dense_scores")
    invalid = b'{"schema":"frozen-dense/v1","features":[],"layers":[]}'
    version = register("model_dense_scores", invalid, training_snapshot_id=None,
                       training_as_of=reference.TRAINING_AS_OF, code_hash=None, root=model_root)
    strategy = LoadedStrategy(
        config=original.config.model_copy(update={"model_ref": version.as_ref()}),
        construct_fn=original.construct_fn,
        strategy_interface="context_v1",
        model_handle=ModelHandle(version=version, artifact_bytes=invalid),
        score_fn=reference.score,
    )
    with pytest.raises(BacktestError, match="dense"):
        run(strategy, bars_provider, datetime(2023, 1, 3), datetime(2023, 2, 1))


def test_context_reference_remains_research_only(model_root):
    register_reference(model_root)
    with pytest.raises(ValueError, match="context"):
        load_tradable_strategy("model_dense_scores")
