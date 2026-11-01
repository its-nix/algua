from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from algua.contracts.model_types import (
    ModelHandle,
    ModelRef,
    ModelVersion,
    compute_provenance_digest,
)
from algua.contracts.strategy_context import AsOfContext, AsOfView
from algua.contracts.types import CapacityLimit, ExecutionContract
from algua.data.research_provenance import (
    SYNTHETIC_LIMITATION,
    DataTier,
    ProvenanceDeclaration,
)
from algua.data.store import DataStore
from algua.models import get_version_with_bytes, register
from algua.portfolio.construction import equal_weight_positive
from algua.portfolio.overlays import OverlaySpec, get_overlay_policy
from algua.research.multimodal_context import (
    ContextError,
    LegacyStrategyAdapter,
    build_as_of_context,
    score_context,
)
from algua.strategies.base import LoadedStrategy, StrategyConfig
from scripts.multimodal_context_exercise import run_exercise


def _bars() -> pd.DataFrame:
    index = pd.DatetimeIndex(
        [
            "2025-01-02T00:00:00Z",
            "2025-01-02T00:00:00Z",
            "2025-01-03T00:00:00Z",
            "2025-01-03T00:00:00Z",
        ],
        name="timestamp",
    )
    frame = pd.DataFrame(
        {
            "symbol": ["A", "B", "A", "B"],
            "open": [10.0, 20.0, 1000.0, 2000.0],
            "high": [11.0, 21.0, 1001.0, 2001.0],
            "low": [9.0, 19.0, 999.0, 1999.0],
            "close": [10.0, 20.0, 1000.0, 2000.0],
            "adj_close": [10.0, 20.0, 1000.0, 2000.0],
            "volume": [100.0, 100.0, 100.0, 100.0],
        },
        index=index,
    )
    return frame.sort_values(["timestamp", "symbol"])


def _news() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source": ["fixture", "fixture"],
            "article_id": ["visible", "future"],
            "symbol": ["A", "B"],
            "published_at": pd.to_datetime(
                ["2025-01-01T12:00:00Z", "2025-01-02T12:00:00Z"], utc=True
            ),
            "knowable_at": pd.to_datetime(
                ["2025-01-01T12:00:00Z", "2025-01-02T12:00:00Z"], utc=True
            ),
            "headline": ["visible", "FUTURE_SENTINEL"],
            "url": [None, None],
            "body": [None, None],
            "retracted": [False, False],
        }
    ).sort_values(["symbol", "source", "article_id", "knowable_at"]).reset_index(drop=True)


def _model_ref(tmp_path) -> ModelRef:
    version = register(
        "fixture-ranker",
        json.dumps({"A": 0.25, "B": -0.25}).encode(),
        training_snapshot_id="synthetic-training-fixture",
        training_as_of="2025-01-01T00:00:00Z",
        code_hash="fixture-code",
        hyperparameters={"nested": {"depth": 1}},
        seed=7,
        eval_report={"fixture": {"verified": True}},
        root=tmp_path / "models",
    )
    return version.as_ref()


def _exercise_manifest(tmp_path, *, tier: DataTier = DataTier.PILOT_REAL_PROXY):
    campaign = tmp_path / "campaign-pinned"
    store = DataStore(campaign / "data")
    limitations = (SYNTHETIC_LIMITATION,) if tier is DataTier.SYNTHETIC_FIXTURE else ()
    record = store.ingest_bars(
        provider="fixture",
        symbols=["A", "B"],
        start="2025-01-01",
        end="2025-01-04",
        as_of="2025-01-04T00:00:00+00:00",
        source="fixture",
        frame=_bars().reset_index(),
        provenance=ProvenanceDeclaration(tier, "fixture-selection", limitations),
    )
    manifest = campaign / "campaign_manifest.json"
    manifest.write_text(
        json.dumps({"components": [{"campaign": True, "snapshot": record.to_dict()}]})
    )
    return manifest, store, record


class _CombinedStrategy:
    required_features = frozenset({"bars", "news"})

    def __init__(self, ref: ModelRef) -> None:
        self.required_models = {"ranker": ref}

    def score(self, context: AsOfContext) -> pd.Series:
        bars = context.features["bars"].frame
        news = context.features["news"].frame
        assert set(news["headline"]) == {"visible"}
        weights = json.loads(context.models["ranker"].artifact_bytes)
        closes = bars.groupby("symbol")["adj_close"].last()
        return closes + pd.Series(weights)


def test_combines_bars_news_and_verified_model_as_of_decision(tmp_path):
    ref = _model_ref(tmp_path)
    strategy = _CombinedStrategy(ref)
    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=_bars(),
        bars_snapshot_id="real-bars-fixture",
        news=_news(),
        news_snapshot_id="synthetic-news-fixture",
        required_features=strategy.required_features,
        model_refs=strategy.required_models,
        model_registry_root=tmp_path / "models",
    )

    scores = score_context(strategy, context)

    assert scores.to_dict() == {"A": 10.25, "B": 19.75}
    assert context.features["bars"].frame.index.max() == pd.Timestamp("2025-01-02T00:00:00Z")
    assert context.features["bars"].source_timestamp is None


def test_future_news_values_are_masked_before_context_copy_or_strategy_access():
    class FutureValue:
        def __deepcopy__(self, memo):
            raise AssertionError("future-known value was copied before the PIT mask")

    news = _news()
    news.loc[news["article_id"] == "future", "body"] = FutureValue()

    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=_bars(),
        bars_snapshot_id="bars-fixture",
        news=news,
        news_snapshot_id="news-fixture",
        required_features={"bars", "news"},
        model_refs={},
        model_registry_root=None,
    )

    assert context.features["news"].frame["article_id"].tolist() == ["visible"]


def test_legacy_adapter_preserves_signal_construction_overlay_and_capacity():
    overlay = OverlaySpec(
        policy="trailing_stop",
        params={"lookback": 2, "stop_pct": 0.1, "cooldown_bars": 0},
    )
    config = StrategyConfig(
        name="legacy",
        universe=["A", "B"],
        execution=ExecutionContract(
            rebalance_frequency="1d",
            capacity=CapacityLimit(
                reference_aum=1000.0,
                max_participation_rate=0.01,
                adv_window_bars=1,
            ),
        ),
        construction="equal_weight_positive",
        overlays=[overlay],
        feature_lookback=2,
    )
    loaded = LoadedStrategy(
        config=config,
        signal_fn=lambda view, params: pd.Series({"A": 1.0, "B": 1.0}),
        construct_fn=equal_weight_positive,
        overlay_fns=(get_overlay_policy("trailing_stop"),),
    )
    bars = _bars()
    bars.loc[(bars.index == pd.Timestamp("2025-01-03T00:00:00Z")) & (bars["symbol"] == "A"),
             ["open", "high", "low", "close", "adj_close"]] = [8.0, 8.0, 8.0, 8.0, 8.0]
    bars.loc[(bars.index == pd.Timestamp("2025-01-03T00:00:00Z")) & (bars["symbol"] == "B"),
             ["open", "high", "low", "close", "adj_close"]] = [20.0, 20.0, 20.0, 20.0, 20.0]
    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-03T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=bars,
        bars_snapshot_id="bars-fixture",
        required_features={"bars"},
        model_refs={},
        model_registry_root=None,
    )
    adapter = LegacyStrategyAdapter(loaded)
    view = context.features["bars"].frame
    expected_scores = loaded.signal(view)
    expected_weights = loaded.construct(expected_scores, view)

    pd.testing.assert_series_equal(adapter.score(context), expected_scores)
    pd.testing.assert_series_equal(adapter.target_weights(context), expected_weights)
    assert expected_weights.to_dict() == {"A": 0.0, "B": 0.02}


def test_missing_required_modality_fails_closed(tmp_path):
    with pytest.raises(ContextError, match="missing required.*news"):
        build_as_of_context(
            decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars", "news"},
            model_refs={},
            model_registry_root=None,
        )


def test_decision_timestamp_must_be_timezone_aware():
    with pytest.raises(ContextError, match="timezone-aware"):
        build_as_of_context(
            decision_ts=datetime(2025, 1, 2),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars"},
            model_refs={},
            model_registry_root=None,
        )


def test_model_training_must_precede_first_decision(tmp_path):
    version = register(
        "future-model",
        b"fixture",
        training_snapshot_id="future-fixture",
        training_as_of="2025-01-03T00:00:00Z",
        code_hash=None,
        root=tmp_path / "models",
    )
    with pytest.raises(ContextError, match="after the first decision"):
        build_as_of_context(
            decision_ts=datetime.fromisoformat("2025-01-04T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars"},
            model_refs={"future": version.as_ref()},
            model_registry_root=tmp_path / "models",
        )


def test_model_training_cutoff_must_not_be_nat(tmp_path):
    version = register(
        "unknown-cutoff-model",
        b"fixture",
        training_snapshot_id="fixture",
        training_as_of="NaT",
        code_hash=None,
        root=tmp_path / "models",
    )
    with pytest.raises(ContextError, match="training_as_of"):
        build_as_of_context(
            decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars"},
            model_refs={"ranker": version.as_ref()},
            model_registry_root=tmp_path / "models",
        )


def test_tampered_model_bytes_are_rejected(tmp_path):
    version = register(
        "tampered-bytes",
        b"original",
        training_snapshot_id="fixture",
        training_as_of="2025-01-01T00:00:00Z",
        code_hash=None,
        root=tmp_path / "models",
    )
    assert version.artifact_path is not None
    from pathlib import Path

    Path(version.artifact_path).write_bytes(b"tampered")
    with pytest.raises(ContextError, match="artifact was modified"):
        build_as_of_context(
            decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars"},
            model_refs={"ranker": version.as_ref()},
            model_registry_root=tmp_path / "models",
        )


def test_mismatched_model_reference_is_rejected(tmp_path):
    ref = _model_ref(tmp_path)
    forged = replace(ref, digest="0" * 16)
    with pytest.raises(ContextError, match="reference does not match"):
        build_as_of_context(
            decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars"},
            model_refs={"ranker": forged},
            model_registry_root=tmp_path / "models",
        )


def test_tampered_model_provenance_is_rejected(tmp_path):
    ref = _model_ref(tmp_path)
    manifest = tmp_path / "models" / ref.name / "manifest.jsonl"
    row = json.loads(manifest.read_text())
    row["hyperparameters"]["nested"]["depth"] = 99
    manifest.write_text(json.dumps(row) + "\n")
    with pytest.raises(ContextError, match="provenance digest mismatch"):
        build_as_of_context(
            decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            bars=_bars(),
            bars_snapshot_id="bars-fixture",
            required_features={"bars"},
            model_refs={"ranker": ref},
            model_registry_root=tmp_path / "models",
        )


@pytest.mark.parametrize(
    "scores, message",
    [
        (pd.Series([1.0, 2.0], index=["A", "A"]), "duplicate"),
        (pd.Series({"A": float("nan")}), "finite"),
        (pd.Series({"OUTSIDE": 1.0}), "outside"),
        (pd.Series({"A": 1.0 + 2.0j}), "real numeric"),
        (pd.Series({"A": True}), "real numeric"),
        (pd.Series({"A": "1.0"}), "real numeric"),
    ],
)
def test_invalid_scores_fail_closed(scores, message):
    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=_bars(),
        bars_snapshot_id="bars-fixture",
        required_features={"bars"},
        model_refs={},
        model_registry_root=None,
    )

    class Invalid:
        required_features = frozenset({"bars"})
        required_models = {}

        def score(self, context):
            return scores

    with pytest.raises(ContextError, match=message):
        score_context(Invalid(), context)


def test_context_defensively_copies_frames_and_nested_model_metadata(tmp_path):
    bars = _bars()
    news = _news()
    ref = _model_ref(tmp_path)
    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=bars,
        bars_snapshot_id="bars-fixture",
        news=news,
        news_snapshot_id="news-fixture",
        required_features={"bars", "news"},
        model_refs={"ranker": ref},
        model_registry_root=tmp_path / "models",
    )
    bars.loc[:, "adj_close"] = -1.0
    news.loc[:, "headline"] = "mutated source"
    read_bars = context.features["bars"].frame
    read_bars.loc[:, "adj_close"] = -2.0
    read_news = context.features["news"].frame
    read_news.loc[:, "headline"] = "mutated read"
    read_model = context.models["ranker"]
    read_model.version.hyperparameters["nested"]["depth"] = 999
    read_model.version.eval_report["fixture"]["verified"] = False

    assert set(context.features["news"].frame["headline"]) == {"visible"}
    assert context.features["bars"].frame["adj_close"].tolist() == [10.0, 20.0]
    assert context.models["ranker"].version.hyperparameters["nested"]["depth"] == 1
    assert context.models["ranker"].version.eval_report["fixture"]["verified"] is True


def test_context_defensively_copies_nested_frame_object_cells():
    decision = datetime.fromisoformat("2025-01-02T00:00:00+00:00")
    nested = {"sentences": ["original"]}
    news = _news().iloc[[0]].copy()
    news["body"] = pd.Series([nested], dtype="object")
    view = AsOfView(
        kind="news",
        as_of=decision,
        snapshot_id="news-fixture",
        frame=news,
    )
    context = AsOfContext(
        decision_ts=decision,
        first_decision_ts=decision,
        universe=("A",),
        features={"news": view},
        models={},
    )

    nested["sentences"].append("source mutation")
    first_read = context.features["news"].frame
    first_read.iloc[0]["body"]["sentences"].append("read mutation")

    assert context.features["news"].frame.iloc[0]["body"] == {"sentences": ["original"]}


@pytest.mark.parametrize("tamper", ["bytes", "provenance"])
def test_direct_context_construction_rejects_unverified_model_handle(tamper):
    import hashlib

    artifact = b"verified"
    digest = hashlib.sha256(artifact).hexdigest()[:16]
    hyperparameters = {"nested": {"depth": 1}}
    provenance = compute_provenance_digest(
        digest=digest,
        training_snapshot_id="fixture",
        training_as_of="2025-01-01T00:00:00Z",
        code_hash="fixture-code",
        hyperparameters=hyperparameters,
        seed=1,
        eval_report={"ok": True},
    )
    version = ModelVersion(
        name="direct",
        version=1,
        digest=digest,
        created_at="",
        training_snapshot_id="fixture",
        training_as_of="2025-01-01T00:00:00Z",
        code_hash="fixture-code",
        hyperparameters=hyperparameters,
        seed=1,
        eval_report={"ok": True},
        provenance_digest=provenance,
    )
    if tamper == "bytes":
        handle = ModelHandle(version=version, artifact_bytes=b"forged")
    else:
        handle = ModelHandle(
            version=replace(version, hyperparameters={"nested": {"depth": 99}}),
            artifact_bytes=artifact,
        )
    bars = _bars().loc[[pd.Timestamp("2025-01-02T00:00:00Z")]]
    view = AsOfView(
        kind="bars",
        as_of=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        snapshot_id="bars-fixture",
        frame=bars,
    )
    with pytest.raises(ValueError, match="model (artifact|provenance)"):
        AsOfContext(
            decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
            universe=("A", "B"),
            features={"bars": view},
            models={"direct": handle},
        )


@pytest.mark.parametrize(
    "kind, frame",
    [
        ("bars", _bars()),
        ("news", _news()),
    ],
)
def test_direct_context_construction_rejects_future_bearing_view(kind, frame):
    decision = datetime.fromisoformat("2025-01-02T00:00:00+00:00")
    view = AsOfView(
        kind=kind,
        as_of=decision,
        snapshot_id=f"{kind}-fixture",
        frame=frame,
    )
    with pytest.raises(ValueError, match="future"):
        AsOfContext(
            decision_ts=decision,
            first_decision_ts=decision,
            universe=("A", "B"),
            features={kind: view},
            models={},
        )


@pytest.mark.parametrize(
    "kind, frame, message",
    [
        ("news", _news().drop(columns="knowable_at"), "requires knowable_at"),
        (
            "news",
            _news().iloc[[0]].assign(knowable_at=pd.to_datetime(["NaT"], utc=True)),
            "must not be null",
        ),
        (
            "bars",
            _bars().iloc[[0]].set_axis(
                pd.DatetimeIndex([pd.NaT], tz="UTC", name="timestamp"), axis="index"
            ),
            "must not contain NaT",
        ),
    ],
)
def test_direct_context_construction_rejects_unknown_temporal_values(kind, frame, message):
    decision = datetime.fromisoformat("2025-01-02T00:00:00+00:00")
    view = AsOfView(
        kind=kind,
        as_of=decision,
        snapshot_id=f"{kind}-fixture",
        frame=frame,
    )

    with pytest.raises(ValueError, match=message):
        AsOfContext(
            decision_ts=decision,
            first_decision_ts=decision,
            universe=("A", "B"),
            features={kind: view},
            models={},
        )


def test_score_snapshots_declared_model_pins_once(tmp_path):
    ref = _model_ref(tmp_path)
    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=_bars(),
        bars_snapshot_id="bars-fixture",
        required_features={"bars"},
        model_refs={"ranker": ref},
        model_registry_root=tmp_path / "models",
    )

    class ChangingDeclaration:
        required_features = frozenset({"bars"})

        def __init__(self):
            self.reads = 0

        @property
        def required_models(self):
            self.reads += 1
            if self.reads > 1:
                raise RuntimeError("model declaration was read more than once")
            return {"ranker": ref}

        def score(self, context):
            return pd.Series({"A": 1.0})

    strategy = ChangingDeclaration()

    assert score_context(strategy, context).to_dict() == {"A": 1.0}
    assert strategy.reads == 1


def test_legacy_model_adapter_rejects_bound_handle_changed_after_construction(tmp_path):
    ref = _model_ref(tmp_path)
    version, artifact = get_version_with_bytes(ref.name, ref.version, root=tmp_path / "models")
    loaded = LoadedStrategy(
        config=StrategyConfig(
            name="legacy-model",
            universe=["A", "B"],
            execution=ExecutionContract(rebalance_frequency="1d"),
            construction="equal_weight_positive",
            needs_model=True,
            model_ref=ref,
            feature_lookback=0,
        ),
        construct_fn=equal_weight_positive,
        model_signal_fn=lambda view, params, model: pd.Series({"A": 1.0}),
        model_handle=ModelHandle(version=version, artifact_bytes=artifact),
    )
    context = build_as_of_context(
        decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        first_decision_ts=datetime.fromisoformat("2025-01-02T00:00:00+00:00"),
        universe=("A", "B"),
        bars=_bars(),
        bars_snapshot_id="bars-fixture",
        required_features={"bars"},
        model_refs={ref.name: ref},
        model_registry_root=tmp_path / "models",
    )
    loaded.model_handle = ModelHandle(version=version, artifact_bytes=b"changed-after-load")

    with pytest.raises(ContextError, match="bound model handle changed"):
        score_context(LegacyStrategyAdapter(loaded), context)


def test_exercise_verifies_snapshot_payload_before_claiming_pass(tmp_path):
    manifest, store, record = _exercise_manifest(tmp_path)
    part = next((store.data_dir / record.data_path).rglob("*.parquet"))
    frame = pd.read_parquet(part)
    frame.loc[frame.index[0], "adj_close"] += 1.0
    frame.to_parquet(part, index=False)

    with pytest.raises(ValueError, match="verification"):
        run_exercise(manifest, tmp_path / "evidence" / "result.json")


def test_exercise_refuses_to_write_inside_read_only_input_store(tmp_path):
    manifest, store, _ = _exercise_manifest(tmp_path)

    with pytest.raises(ValueError, match="outside the read-only data store"):
        run_exercise(manifest, store.data_dir / "result.json")


def test_exercise_refuses_non_pilot_data_instead_of_relabelling_it(tmp_path):
    manifest, _, _ = _exercise_manifest(tmp_path, tier=DataTier.SYNTHETIC_FIXTURE)

    with pytest.raises(ValueError, match="pilot_real_proxy"):
        run_exercise(manifest, tmp_path / "evidence" / "result.json")
