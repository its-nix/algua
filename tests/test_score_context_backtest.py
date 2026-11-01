from __future__ import annotations

import hashlib
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import algua.strategies.momentum as momentum_family
from algua.backtest._sample import SyntheticProvider
from algua.backtest.engine import run, simulate
from algua.backtest.errors import BacktestError
from algua.backtest.run_inputs import capture_run_inputs
from algua.backtest.sweep import _override, sweep
from algua.backtest.walkforward import walk_forward
from algua.contracts.model_types import (
    ModelHandle,
    ModelRef,
    ModelVersion,
    compute_provenance_digest,
)
from algua.contracts.types import ExecutionContract
from algua.data.news_schema import explode_news_symbols, to_news_schema
from algua.portfolio.construction import get_construction_policy
from algua.strategies.base import (
    LoadedStrategy,
    StrategyConfig,
    config_hash,
    strategy_config_hash,
)
from algua.strategies.loader import _loaded_for_test, load_strategy, load_tradable_strategy

_FAMILY_PATH = Path(momentum_family.__path__[0])


class _BarsProvider(SyntheticProvider):
    snapshot_id = "task2-bars-snapshot"


class _NewsProvider:
    snapshot_id = "task2-news-snapshot"

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls = 0

    def get_news(
        self, symbols: list[str], end: datetime  # noqa: ARG002 - protocol fixture
    ) -> pd.DataFrame:
        self.calls += 1
        return self.frame[self.frame["symbol"].isin(symbols)].copy()


class _DriftingNewsProvider(_NewsProvider):
    def __init__(self, frame: pd.DataFrame) -> None:
        super().__init__(frame)
        self.current_snapshot = "news-primary"

    @property
    def snapshot_id(self) -> str:
        return self.current_snapshot

    def get_news(self, symbols: list[str], end: datetime) -> pd.DataFrame:
        frame = super().get_news(symbols, end)
        self.current_snapshot = "news-revised"
        return frame


class _AliasedBarsProvider(_BarsProvider):
    def __init__(self, frame: pd.DataFrame) -> None:
        super().__init__(seed=0)
        self.frame = frame
        self.calls = 0

    def get_bars(self, symbols, start, end, timeframe):  # noqa: ANN001, ARG002
        self.calls += 1
        return self.frame


class _DriftOnSecondBarsFetch(SyntheticProvider):
    def __init__(self, seed: int = 17) -> None:
        super().__init__(seed=seed)
        self.calls = 0
        self.current_snapshot = "snapshot-primary"

    @property
    def snapshot_id(self) -> str:
        return self.current_snapshot

    def get_bars(self, symbols, start, end, timeframe):  # noqa: ANN001
        self.calls += 1
        if self.calls == 2:
            self.current_snapshot = "snapshot-benchmark"
        return super().get_bars(symbols, start, end, timeframe)


def _score_aaa(context) -> pd.Series:  # noqa: ANN001
    return pd.Series({"AAA": 1.0})


class _ChangingSnapshotProvider(SyntheticProvider):
    def __init__(self, seed: int = 0) -> None:
        super().__init__(seed=seed)
        self.snapshot_reads = 0

    @property
    def snapshot_id(self) -> str:
        self.snapshot_reads += 1
        return f"changing-snapshot-{self.snapshot_reads}"


class _ExplodingSnapshotProvider(SyntheticProvider):
    @property
    def snapshot_id(self) -> str:
        raise RuntimeError("snapshot metadata must not be read by legacy simulate")


class _PinnedThenExplodingProvider(SyntheticProvider):
    def __init__(self, seed: int = 0, *, max_snapshot_reads: int = 2) -> None:
        super().__init__(seed=seed)
        self.snapshot_reads = 0
        self.max_snapshot_reads = max_snapshot_reads

    @property
    def snapshot_id(self) -> str:
        self.snapshot_reads += 1
        if self.snapshot_reads > self.max_snapshot_reads:
            raise RuntimeError("verified snapshot metadata was read again")
        return "run-pinned-snapshot"


def _model(*, training_as_of: str = "2023-12-31T00:00:00+00:00") -> tuple[ModelRef, ModelHandle]:
    artifact = b"task2-context-model"
    digest = hashlib.sha256(artifact).hexdigest()[:16]
    provenance = compute_provenance_digest(
        digest=digest,
        training_snapshot_id="training-snapshot",
        training_as_of=training_as_of,
        code_hash="training-code",
        hyperparameters={"scale": 0.25},
        seed=7,
        eval_report={"status": "fixture"},
    )
    version = ModelVersion(
        name="task2-model",
        version=1,
        digest=digest,
        created_at="2024-01-01T00:00:00+00:00",
        training_snapshot_id="training-snapshot",
        training_as_of=training_as_of,
        code_hash="training-code",
        hyperparameters={"scale": 0.25},
        seed=7,
        eval_report={"status": "fixture"},
        provenance_digest=provenance,
    )
    return version.as_ref(), ModelHandle(version=version, artifact_bytes=artifact)


def _config(**overrides: Any) -> StrategyConfig:
    fields: dict[str, Any] = {
        "name": "context-score",
        "universe": ["AAA", "BBB"],
        "execution": ExecutionContract(
            rebalance_frequency="1d", decision_lag_bars=1, max_weight_per_symbol=1.0
        ),
        "params": {},
        "construction": "equal_weight_positive",
        "feature_lookback": 0,
    }
    fields.update(overrides)
    return StrategyConfig(**fields)


def test_context_interface_binds_combined_modalities_without_churning_legacy_identity() -> None:
    legacy = StrategyConfig(
        name="s",
        universe=["A", "B"],
        execution=ExecutionContract(rebalance_frequency="1d"),
        params={"lookback": 10},
        construction="top_k_equal_weight",
        construction_params={"top_k": 2},
    )
    assert config_hash(_loaded_for_test(legacy)) == "e2c60b0fcf5b163f0731e4f7ef9c73b3"

    ref, handle = _model()
    config = _config(
        needs_news=True,
        needs_model=True,
        model_ref=ref,
    )
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        model_handle=handle,
        construct_fn=get_construction_policy(config.construction),
    )

    assert strategy.required_features == frozenset({"bars", "news"})
    assert strategy.required_models == {ref.name: ref}
    assert config_hash(strategy) != config_hash(_loaded_for_test(legacy))
    assert config_hash(strategy) != strategy_config_hash(config)
    assert "strategy_interface" not in config.model_dump(mode="json")
    assert strategy.authored_signal is strategy.score_fn

    with pytest.raises(ValueError, match="signal_panel.*context_v1"):
        LoadedStrategy(
            config=config,
            strategy_interface="context_v1",
            score_fn=lambda context: pd.Series({"AAA": 1.0}),
            signal_panel_fn=lambda bars, params: pd.DataFrame(),
            model_handle=handle,
            construct_fn=get_construction_policy(config.construction),
        )


def test_strategy_interface_vocabulary_is_centralized() -> None:
    from algua.contracts.strategy_interface import (
        CONTEXT_INTERFACE_V1,
        LEGACY_INTERFACE,
        SUPPORTED_STRATEGY_INTERFACES,
        uses_context_interface,
    )

    assert SUPPORTED_STRATEGY_INTERFACES == frozenset({"legacy", "context_v1"})
    assert LEGACY_INTERFACE == "legacy"
    assert CONTEXT_INTERFACE_V1 == "context_v1"
    assert uses_context_interface(CONTEXT_INTERFACE_V1)
    assert not uses_context_interface(LEGACY_INTERFACE)


def test_loaded_strategy_docstring_distinguishes_legacy_and_context_interfaces() -> None:
    doc = LoadedStrategy.__doc__ or ""
    assert "legacy" in doc
    assert "context_v1" in doc
    assert "simultaneous modalities" in doc


def test_loader_binds_authored_context_score_and_verified_model(monkeypatch, tmp_path) -> None:
    from algua.models import register

    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path))
    artifact = b"task2-loader-model"
    version = register(
        "task2-loader-model",
        artifact,
        training_snapshot_id="training-snapshot",
        training_as_of="2023-12-31T00:00:00+00:00",
        code_hash="training-code",
        hyperparameters={"scale": 0.25},
        seed=7,
        eval_report={"status": "fixture"},
        root=tmp_path / "models",
    )
    ref = version.as_ref()
    name = "tmp_task2_context_loader"
    dotted = f"algua.strategies.momentum.{name}"
    path = _FAMILY_PATH / f"{name}.py"
    path.write_text(
        "import pandas as pd\n"
        "from algua.contracts.model_types import ModelRef\n"
        "from algua.contracts.types import ExecutionContract\n"
        "from algua.strategies.base import StrategyConfig\n"
        f"MODEL_REF = ModelRef(**{ref.as_dict()!r})\n"
        "CONFIG = StrategyConfig(\n"
        f"    name={name!r}, universe=['AAA', 'BBB'],\n"
        "    execution=ExecutionContract(rebalance_frequency='1d'),\n"
        "    construction='equal_weight_positive',\n"
        "    needs_news=True, needs_model=True, model_ref=MODEL_REF, feature_lookback=0)\n"
        "STRATEGY_INTERFACE = 'context_v1'\n"
        "def score(context):\n"
        "    return pd.Series({'AAA': 1.0})\n"
    )
    sys.modules.pop(dotted, None)
    try:
        module = importlib.import_module(dotted)
        loaded = load_strategy(name)
        assert loaded.score_fn is module.score
        assert loaded.authored_signal is module.score
        assert loaded.model_handle is not None
        assert loaded.model_handle.version.as_ref() == ref
        assert loaded.model_handle.artifact_bytes == artifact
        from algua.registry.approvals import closure_module_names

        assert dotted in closure_module_names(loaded)
    finally:
        path.unlink(missing_ok=True)
        sys.modules.pop(dotted, None)


def test_canonical_backtest_scores_bars_news_and_model_then_fills_next_bar() -> None:
    provider = _BarsProvider(seed=4)
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 12, tzinfo=UTC)
    bars = provider.get_bars(["AAA", "BBB"], start, end, "1d")
    sessions = bars.index.unique().sort_values()
    news = to_news_schema(
        explode_news_symbols(
            pd.DataFrame(
                [
                    {
                        "source": "fixture",
                        "article_id": "known-on-second-session",
                        "symbols": ["AAA"],
                        "published_at": sessions[1],
                        "knowable_at": sessions[1],
                        "headline": "synthetic fixture news",
                    }
                ]
            )
        )
    )
    ref, handle = _model(training_as_of="2024-01-01T00:00:00+00:00")
    config = _config(
        needs_news=True,
        needs_model=True,
        model_ref=ref,
    )
    observed: list[tuple[pd.Timestamp, int, pd.Timestamp, str, str]] = []

    def score(context) -> pd.Series:
        visible_news = context.features["news"].frame
        visible_bars = context.features["bars"].frame
        assert context.models[ref.name].artifact_bytes == handle.artifact_bytes
        observed.append(
            (
                pd.Timestamp(context.decision_ts),
                len(visible_news),
                visible_bars.index.max(),
                context.features["bars"].snapshot_id,
                context.features["news"].snapshot_id,
            )
        )
        return pd.Series({"AAA": 1.0}) if len(visible_news) else pd.Series({"BBB": 1.0})

    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=score,
        model_handle=handle,
        construct_fn=get_construction_policy(config.construction),
    )

    _, executed, _ = simulate(
        strategy,
        provider,
        start,
        end,
        news_provider=_NewsProvider(news),
    )

    assert observed[0] == (
        sessions[0], 0, sessions[0], "task2-bars-snapshot", "task2-news-snapshot"
    )
    assert observed[1] == (
        sessions[1], 1, sessions[1], "task2-bars-snapshot", "task2-news-snapshot"
    )
    assert executed.loc[sessions[0]].to_dict() == {"AAA": 0.0, "BBB": 0.0}
    assert executed.loc[sessions[1]].to_dict() == {"AAA": 0.0, "BBB": 0.95}
    assert executed.loc[sessions[2]].to_dict() == {"AAA": 0.95, "BBB": 0.0}


def test_context_strategy_is_explicitly_refused_by_tradable_loader() -> None:
    name = "tmp_task2_context_not_tradable"
    dotted = f"algua.strategies.momentum.{name}"
    path = _FAMILY_PATH / f"{name}.py"
    path.write_text(
        "import pandas as pd\n"
        "from algua.contracts.types import ExecutionContract\n"
        "from algua.strategies.base import StrategyConfig\n"
        "CONFIG = StrategyConfig(\n"
        f"    name={name!r}, universe=['AAA'],\n"
        "    execution=ExecutionContract(rebalance_frequency='1d'),\n"
        "    construction='equal_weight_positive',\n"
        "    feature_lookback=0)\n"
        "STRATEGY_INTERFACE = 'context_v1'\n"
        "def score(context):\n"
        "    return pd.Series({'AAA': 1.0})\n"
    )
    sys.modules.pop(dotted, None)
    try:
        with pytest.raises(ValueError, match="context_v1.*research backtest"):
            load_tradable_strategy(name)
    finally:
        path.unlink(missing_ok=True)
        sys.modules.pop(dotted, None)


@pytest.mark.parametrize(
    ("scores", "message"),
    [
        (pd.Series([1.0, float("nan")], index=["AAA", "BBB"]), "finite"),
        (pd.Series([1.0, 2.0], index=["AAA", "AAA"]), "duplicate"),
        (pd.Series({"OUTSIDE": 1.0}), "outside"),
        (pd.Series({"AAA": True}), "real numeric"),
    ],
)
def test_context_backtest_refuses_invalid_score_vectors(
    scores: pd.Series, message: str
) -> None:
    config = _config()
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: scores,
        construct_fn=get_construction_policy(config.construction),
    )
    with pytest.raises(BacktestError, match=message):
        simulate(
            strategy,
            _BarsProvider(seed=2),
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 12, tzinfo=UTC),
        )


def test_context_backtest_refuses_missing_required_modality_and_snapshot() -> None:
    ref, handle = _model()
    combined = _config(
        needs_news=True,
        needs_model=True,
        model_ref=ref,
    )
    strategy = LoadedStrategy(
        config=combined,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        model_handle=handle,
        construct_fn=get_construction_policy(combined.construction),
    )
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 12, tzinfo=UTC)
    with pytest.raises(BacktestError, match="needs_news"):
        simulate(strategy, _BarsProvider(seed=2), start, end)

    bars_only = _config()
    no_snapshot_strategy = LoadedStrategy(
        config=bars_only,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        construct_fn=get_construction_policy(bars_only.construction),
    )
    with pytest.raises(BacktestError, match="pinned bars snapshot_id"):
        simulate(no_snapshot_strategy, SyntheticProvider(seed=2), start, end)


def test_context_backtest_pins_snapshot_even_when_warmup_skips_every_decision() -> None:
    config = _config(
        execution=ExecutionContract(
            rebalance_frequency="1d",
            decision_lag_bars=1,
            max_weight_per_symbol=1.0,
            warmup_bars=100,
        )
    )
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        construct_fn=get_construction_policy(config.construction),
    )

    with pytest.raises(BacktestError, match="pinned bars snapshot_id"):
        simulate(
            strategy,
            SyntheticProvider(seed=2),
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 12, tzinfo=UTC),
        )


def test_context_backtest_refuses_snapshot_identity_drift_across_fetch() -> None:
    config = _config()
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        construct_fn=get_construction_policy(config.construction),
    )

    with pytest.raises(BacktestError, match="bars snapshot_id changed during fetch"):
        simulate(
            strategy,
            _ChangingSnapshotProvider(seed=2),
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 12, tzinfo=UTC),
        )


def test_context_backtest_refuses_sidecar_identity_drift_across_fetch() -> None:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 12, tzinfo=UTC)
    sessions = _BarsProvider(seed=2).get_bars(["AAA", "BBB"], start, end, "1d").index
    news = to_news_schema(
        explode_news_symbols(
            pd.DataFrame(
                [{
                    "source": "fixture",
                    "article_id": "drifting-sidecar",
                    "symbols": ["AAA"],
                    "published_at": sessions[0],
                    "knowable_at": sessions[0],
                    "headline": "drifting sidecar fixture",
                }]
            )
        )
    )
    config = _config(needs_news=True)
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=_score_aaa,
        construct_fn=get_construction_policy(config.construction),
    )

    with pytest.raises(BacktestError, match="news snapshot_id changed during fetch"):
        simulate(
            strategy,
            _BarsProvider(seed=2),
            start,
            end,
            news_provider=_DriftingNewsProvider(news),
        )


def test_legacy_simulate_does_not_read_optional_provider_snapshot_metadata() -> None:
    strategy = _loaded_for_test(_config(name="legacy-score"))

    simulate(
        strategy,
        _ExplodingSnapshotProvider(seed=2),
        datetime(2024, 1, 2, tzinfo=UTC),
        datetime(2024, 1, 12, tzinfo=UTC),
    )


def test_context_run_stamps_verified_snapshot_without_reread_or_decisions() -> None:
    provider = _PinnedThenExplodingProvider(seed=2)
    config = _config(
        execution=ExecutionContract(
            rebalance_frequency="1d",
            decision_lag_bars=1,
            max_weight_per_symbol=1.0,
            warmup_bars=100,
        )
    )
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: pytest.fail("warmup should skip every score call"),
        construct_fn=get_construction_policy(config.construction),
    )

    result = run(
        strategy,
        provider,
        datetime(2024, 1, 2, tzinfo=UTC),
        datetime(2024, 1, 12, tzinfo=UTC),
    )

    assert result.snapshot_id == "run-pinned-snapshot"
    assert provider.snapshot_reads == 2


@pytest.mark.parametrize("surface", ["override", "validate", "sequential", "parallel", "cli"])
@pytest.mark.parametrize("key", ["pick", "typo"])
def test_context_signal_sweep_refused_before_effects(surface, key, monkeypatch) -> None:
    import json

    from typer.testing import CliRunner

    from algua.backtest.sweep import validate_sweep_grid
    from algua.cli.main import app
    from algua.evaluation import sweep_run

    sweep_module = importlib.import_module("algua.backtest.sweep")
    config = _config(params={"pick": "AAA"})
    calls = []

    def score(context):
        calls.append("score")
        return pd.Series({config.params["pick"]: 1.0})

    strategy = LoadedStrategy(
        config=config, strategy_interface="context_v1", score_fn=score,
        construct_fn=get_construction_policy(config.construction),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("unsupported grid reached provider/worker/trial/holdout/evidence")

    for target in ["capture_run_inputs", "_run_combos", "ProcessPoolExecutor", "walk_forward"]:
        monkeypatch.setattr(sweep_module, target, forbidden)
    for target in ["registry_conn", "record_search_breadth", "record_sweep_run", "record_tracking"]:
        monkeypatch.setattr(sweep_run, target, forbidden)
    monkeypatch.setenv("ALGUA_SWEEP_CPU_BUDGET", "2" if surface == "parallel" else "1")
    start, end = datetime(2024, 1, 2, tzinfo=UTC), datetime(2024, 6, 28, tzinfo=UTC)
    message = "context_v1.*signal parameter.*unsupported"
    if surface == "cli":
        monkeypatch.setattr(
            sweep_run, "resolve_eval_inputs", lambda *a, **kw: (strategy, None, start, end)
        )
        result = CliRunner().invoke(
            app, ["backtest", "sweep", "fixture", "--demo", "--param", f"{key}=AAA,BBB", "--track"]
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert "context_v1" in str(payload) and "unsupported" in str(payload)
    else:
        with pytest.raises(ValueError, match=message):
            if surface == "override":
                _override(strategy, {key: "BBB"})
            elif surface == "validate":
                validate_sweep_grid(strategy, {key: ["AAA", "BBB"]})
            else:
                sweep(strategy, None, start, end, grid={key: ["AAA", "BBB"]})
    assert calls == []
    assert strategy.config.params == {"pick": "AAA"}


def test_supported_sweep_overrides_change_actual_decisions() -> None:
    from algua.backtest.sweep import validate_sweep_grid
    from algua.contracts.strategy_context import AsOfContext, AsOfView
    from algua.portfolio.overlays import OverlaySpec, resolve_overlays

    ts = pd.date_range("2024-01-02", periods=2, tz="UTC", name="timestamp")
    bars = pd.DataFrame(
        {"symbol": ["AAA", "BBB", "AAA", "BBB"], "adj_close": [10., 20., 8., 20.]},
        index=ts.repeat(2),
    )
    context = AsOfContext(
        decision_ts=ts[-1].to_pydatetime(), first_decision_ts=ts[0].to_pydatetime(),
        universe=("AAA", "BBB"),
        features={"bars": AsOfView(
            kind="bars", as_of=ts[-1].to_pydatetime(), snapshot_id="fixture", frame=bars
        )}, models={},
    )
    config = _config(
        params={"pick": "AAA"}, construction="top_k_equal_weight",
        construction_params={"top_k": 1}, feature_lookback=2,
        overlays=[OverlaySpec(
            policy="trailing_stop", params={"lookback": 2, "stop_pct": 0.1, "cooldown_bars": 0}
        )],
    )
    strategy = LoadedStrategy(
        config=config, strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 2., "BBB": 1.}),
        construct_fn=get_construction_policy(config.construction),
        overlay_fns=resolve_overlays(config.overlays, feature_lookback=2),
    )
    _, trials = validate_sweep_grid(
        strategy, {"construction.top_k": [1, 2], "overlay.0.stop_pct": [0.1, 0.3]}
    )
    weights = [trial.target_weights_context(context) for trial in trials]
    assert weights[0]["AAA"] == 0.0
    assert weights[1]["AAA"] == pytest.approx(0.95)
    assert weights[2]["AAA"] == 0.0 and weights[2]["BBB"] == pytest.approx(0.5)
    assert weights[3]["AAA"] == weights[3]["BBB"] == pytest.approx(0.475)
    assert len({config_hash(trial) for trial in trials}) == 4
    assert all(trial.score_fn is strategy.score_fn for trial in trials)
    assert strategy.config.construction_params == {"top_k": 1}
    legacy = LoadedStrategy(
        config=_config(params={"pick": "AAA"}),
        signal_fn=lambda view, params: pd.Series({params["pick"]: 1.}),
        construct_fn=get_construction_policy("equal_weight_positive"),
    )
    _, legacy_trials = validate_sweep_grid(legacy, {"pick": ["AAA", "BBB"]})
    assert list(legacy_trials[0].signal(bars).index) == ["AAA"]
    assert list(legacy_trials[1].signal(bars).index) == ["BBB"]
    assert config_hash(legacy_trials[0]) != config_hash(legacy_trials[1])


def test_sweep_runs_bars_and_news_context_with_verified_snapshot_identity() -> None:
    provider = _PinnedThenExplodingProvider(seed=3, max_snapshot_reads=3)
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 6, 28, tzinfo=UTC)
    sessions = provider.get_bars(["AAA", "BBB"], start, end, "1d").index.unique()
    news = to_news_schema(
        explode_news_symbols(
            pd.DataFrame(
                [
                    {
                        "source": "fixture",
                        "article_id": "sweep-news",
                        "symbols": ["AAA"],
                        "published_at": sessions[5],
                        "knowable_at": sessions[5],
                        "headline": "synthetic sweep fixture",
                    }
                ]
            )
        )
    )
    config = _config(
        params={"bias": 1.0}, needs_news=True,
        construction="top_k_equal_weight", construction_params={"top_k": 2},
    )
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        construct_fn=get_construction_policy(config.construction),
    )

    result = sweep(
        strategy,
        provider,
        start,
        end,
        grid={"construction.top_k": [1]},
        windows=2,
        news_provider=_NewsProvider(news),
    )

    assert result.snapshot_id == "run-pinned-snapshot"
    assert result.news_snapshot == "task2-news-snapshot"
    assert result.n_combos == 1
    assert provider.snapshot_reads == 3


def test_sweep_retains_context_model_lane_refusal() -> None:
    ref, handle = _model()
    config = _config(params={"bias": 1.0}, needs_model=True, model_ref=ref)
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        model_handle=handle,
        construct_fn=get_construction_policy(config.construction),
    )

    with pytest.raises(BacktestError, match="needs_model.*sweep/walk-forward"):
        sweep(
            strategy,
            _BarsProvider(seed=3),
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 6, 28, tzinfo=UTC),
            grid={"construction.top_k": [1]},
        )


def test_context_backtest_refuses_future_training_and_tampered_bound_bytes() -> None:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 12, tzinfo=UTC)
    future_ref, future_handle = _model(training_as_of="2024-01-03T00:00:00+00:00")
    future_config = _config(
        needs_model=True,
        model_ref=future_ref,
    )
    future_strategy = LoadedStrategy(
        config=future_config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        model_handle=future_handle,
        construct_fn=get_construction_policy(future_config.construction),
    )
    with pytest.raises(BacktestError, match="AFTER the first decision bar"):
        simulate(future_strategy, _BarsProvider(seed=2), start, end)

    ref, handle = _model()
    tampered_config = _config(
        needs_model=True,
        model_ref=ref,
    )
    tampered_strategy = LoadedStrategy(
        config=tampered_config,
        strategy_interface="context_v1",
        score_fn=lambda context: pd.Series({"AAA": 1.0}),
        model_handle=handle,
        construct_fn=get_construction_policy(tampered_config.construction),
    )
    tampered_strategy.model_handle = ModelHandle(
        version=handle.version, artifact_bytes=b"tampered-after-load"
    )
    with pytest.raises(BacktestError, match="artifact bytes"):
        simulate(tampered_strategy, _BarsProvider(seed=2), start, end)


@pytest.mark.parametrize("surface", ["simulate", "run", "walk_forward", "sweep"])
def test_run_surfaces_sever_provider_consumer_and_nested_sidecar_aliases(
    surface: str, monkeypatch
) -> None:
    monkeypatch.setenv("ALGUA_SWEEP_CPU_BUDGET", "1")
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 6, 28, tzinfo=UTC)
    source_bars = _BarsProvider(seed=9).get_bars(["AAA", "BBB"], start, end, "1d")
    bars_provider = _AliasedBarsProvider(source_bars)
    sessions = source_bars.index.unique().sort_values()
    news = to_news_schema(
        explode_news_symbols(
            pd.DataFrame(
                [{
                    "source": "fixture",
                    "article_id": "nested-alias",
                    "symbols": ["AAA"],
                    "published_at": sessions[0],
                    "knowable_at": sessions[0],
                    "headline": "nested alias fixture",
                }]
            )
        )
    )
    news["metadata"] = [[{"tags": ["original"]}]]
    news_provider = _NewsProvider(news)
    observed_prices: list[float] = []
    observed_tags: list[list[str]] = []

    def score(context) -> pd.Series:  # noqa: ANN001
        bars_view = context.features["bars"].frame
        news_view = context.features["news"].frame
        observed_prices.append(
            float(bars_view.loc[bars_view["symbol"] == "AAA", "adj_close"].iloc[-1])
        )
        observed_tags.append(list(news_view["metadata"].iloc[0][0]["tags"]))
        # Mutate both a consumer copy and the provider-owned aliases after capture. Neither may
        # alter the authoritative run inputs seen by a later decision.
        news_view["metadata"].iloc[0][0]["tags"].append("consumer")
        bars_provider.frame.loc[bars_provider.frame["symbol"] == "AAA", "adj_close"] = -999.0
        news_provider.frame["metadata"].iloc[0][0]["tags"].append("provider")
        return pd.Series({"AAA": 1.0})

    config = _config(needs_news=True)
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=score,
        construct_fn=get_construction_policy(config.construction),
    )
    if surface == "simulate":
        simulate(strategy, bars_provider, start, end, news_provider=news_provider)
    elif surface == "run":
        run(strategy, bars_provider, start, end, news_provider=news_provider)
    elif surface == "walk_forward":
        walk_forward(
            strategy, bars_provider, start, end, windows=2, news_provider=news_provider
        )
    else:
        sweep(
            strategy,
            bars_provider,
            start,
            end,
            grid={},
            windows=2,
            news_provider=news_provider,
        )

    assert bars_provider.calls == 1
    assert news_provider.calls == 1
    assert len(set(observed_prices)) > 1  # the captured market series still evolves normally
    assert all(price != -999.0 for price in observed_prices)
    assert observed_tags and all(tags == ["original"] for tags in observed_tags)


def test_walk_forward_uses_one_bars_fetch_for_decisions_and_benchmark() -> None:
    config = _config()
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=_score_aaa,
        construct_fn=get_construction_policy(config.construction),
    )
    provider = _DriftOnSecondBarsFetch()

    result = walk_forward(
        strategy,
        provider,
        datetime(2024, 1, 2, tzinfo=UTC),
        datetime(2024, 6, 28, tzinfo=UTC),
        windows=2,
    )

    assert provider.calls == 1
    assert provider.snapshot_id == "snapshot-primary"
    assert result.snapshot_id == "snapshot-primary"
    assert result.market_returns is not None


def test_capture_freezes_bars_before_later_fetch_and_identity_callbacks() -> None:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 1, 3, tzinfo=UTC)
    source_bars = _BarsProvider(seed=4).get_bars(["AAA", "BBB"], start, end, "1d")
    source_bars["metadata"] = [[{"tags": ["original"]}]] * len(source_bars)
    bars_provider = _AliasedBarsProvider(source_bars)

    class MutatingNewsProvider:
        def __init__(self) -> None:
            self.identity_reads = 0

        @property
        def snapshot_id(self) -> str:
            self.identity_reads += 1
            if self.identity_reads == 2:
                source_bars["metadata"].iloc[0][0]["tags"].append("identity-getter")
            return "news-stable"

        def get_news(self, symbols, as_of):  # noqa: ANN001, ARG002
            source_bars.loc[:, "adj_close"] = -999.0
            source_bars["metadata"].iloc[0][0]["tags"].append("sidecar-fetch")
            return pd.DataFrame()

    config = _config(needs_news=True)
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=_score_aaa,
        construct_fn=get_construction_policy(config.construction),
    )

    bundle = capture_run_inputs(
        strategy,
        bars_provider,
        config.universe,
        start,
        end,
        news_provider=MutatingNewsProvider(),
        include_provenance=True,
    )

    captured = bundle.bars()
    assert (captured["adj_close"] >= 0).all()
    assert captured["metadata"].iloc[0][0]["tags"] == ["original"]


def test_capture_catches_bars_identity_drift_during_later_sidecar_fetch() -> None:
    class DriftingBarsProvider(_BarsProvider):
        current_snapshot = "bars-primary"

        @property
        def snapshot_id(self) -> str:
            return self.current_snapshot

    bars_provider = DriftingBarsProvider(seed=5)

    class DriftingNewsProvider(_NewsProvider):
        def get_news(self, symbols: list[str], end: datetime) -> pd.DataFrame:
            bars_provider.current_snapshot = "bars-revised"
            return super().get_news(symbols, end)

    config = _config(needs_news=True)
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=_score_aaa,
        construct_fn=get_construction_policy(config.construction),
    )

    with pytest.raises(BacktestError, match="bars snapshot_id changed during fetch"):
        capture_run_inputs(
            strategy,
            bars_provider,
            config.universe,
            datetime(2024, 1, 2, tzinfo=UTC),
            datetime(2024, 1, 3, tzinfo=UTC),
            news_provider=DriftingNewsProvider(
                pd.DataFrame({"symbol": pd.Series(dtype="object")})
            ),
            include_provenance=True,
        )


def test_sweep_captures_bars_and_sidecars_once_for_every_combo(monkeypatch) -> None:
    monkeypatch.setenv("ALGUA_SWEEP_CPU_BUDGET", "1")
    start = datetime(2024, 1, 2, tzinfo=UTC)
    end = datetime(2024, 6, 28, tzinfo=UTC)
    seed_provider = _BarsProvider(seed=12)
    sessions = seed_provider.get_bars(["AAA", "BBB"], start, end, "1d").index.unique()
    news = to_news_schema(
        explode_news_symbols(
            pd.DataFrame(
                [{
                    "source": "fixture",
                    "article_id": "shared-sweep-sidecar",
                    "symbols": ["AAA"],
                    "published_at": sessions[0],
                    "knowable_at": sessions[0],
                    "headline": "shared sweep fixture",
                }]
            )
        )
    )
    news_provider = _NewsProvider(news)
    provider = _DriftOnSecondBarsFetch(seed=12)
    config = _config(
        params={"bias": 1.0}, needs_news=True,
        construction="top_k_equal_weight", construction_params={"top_k": 2},
    )
    strategy = LoadedStrategy(
        config=config,
        strategy_interface="context_v1",
        score_fn=_score_aaa,
        construct_fn=get_construction_policy(config.construction),
    )

    result = sweep(
        strategy,
        provider,
        start,
        end,
        grid={"construction.top_k": [1, 2]},
        windows=2,
        news_provider=news_provider,
    )

    assert result.n_combos == 2
    assert result.snapshot_id == "snapshot-primary"
    assert result.news_snapshot == "task2-news-snapshot"
    assert provider.calls == 1
    assert news_provider.calls == 1
