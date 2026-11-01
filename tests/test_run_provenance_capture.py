"""Mutation/refusal controls use synthetic bars and trusted test callbacks only."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from algua.backtest.engine import run
from algua.backtest.errors import BacktestError
from algua.backtest.run_inputs import capture_run_inputs
from algua.data.serve import StoreBackedProvider
from algua.primitives.timeparse import utc
from algua.strategies.loader import load_strategy
from tests.test_run_provenance import COSTS, END, NAME, START, snapshot


@pytest.mark.parametrize("fees,slippage", [(0.0, 0.0), (0.0012, 0.0034)])
def test_costs_are_effective_capture_not_post_run_config(tmp_path, monkeypatch, fees, slippage):
    store, rec = snapshot(tmp_path, monkeypatch)
    strategy = load_strategy(NAME)
    strategy = replace(strategy, config=strategy.config.model_copy(update={
        "execution": replace(strategy.execution, fees=fees, slippage=slippage),
    }))
    provider = StoreBackedProvider(store, rec.snapshot_id)
    baseline = run(strategy, provider, utc(START), utc(END))
    original_signal = strategy.signal_fn
    def mutate_config(view, params):
        strategy.config.execution = replace(strategy.execution, fees=0.1, slippage=0.2)
        return original_signal(view, params)
    strategy.signal_fn = mutate_config
    strategy.signal_panel_fn = None
    mutated = run(strategy, provider, utc(START), utc(END))
    assert mutated.execution_costs == COSTS | {"fees": fees, "slippage": slippage}
    assert mutated.metrics == baseline.metrics
    assert mutated.returns.equals(baseline.returns)


def test_capture_detaches_metadata_before_fetch_and_returns_separate_copies(tmp_path, monkeypatch):
    store, rec = snapshot(tmp_path, monkeypatch)
    strategy = load_strategy(NAME)
    raw = rec.to_dict()
    expected = json.loads(json.dumps(raw))
    class MutatingProvider(StoreBackedProvider):
        @property
        def bars_provenance(self):
            return raw

        def get_bars(self, *args):
            raw["symbols"].append("AFTER_CAPTURE")
            raw["source_metadata"]["research_provenance"] = "changed during fetch"
            return super().get_bars(*args)

    bundle = capture_run_inputs(strategy, MutatingProvider(store, rec.snapshot_id),
                                strategy.universe, utc(START), utc(END), include_provenance=True)
    first = bundle.provenance(None)
    assert first["bars_provenance"] == expected
    first["bars_provenance"]["symbols"].append("CONSUMER")
    first["execution_costs"]["fees"] = 10.0
    assert bundle.provenance(None)["bars_provenance"] == expected
    assert bundle.execution_costs() == COSTS


def test_legacy_metadata_is_unknown_even_with_labeled_newer_snapshot(tmp_path, monkeypatch):
    store, legacy = snapshot(tmp_path, monkeypatch, declared=False)
    snapshot(tmp_path, monkeypatch)
    result = run(load_strategy(NAME), StoreBackedProvider(store, legacy.snapshot_id),
                 utc(START), utc(END))
    assert result.snapshot_id == legacy.snapshot_id
    assert result.bars_provenance is None
    assert result.execution_costs == COSTS  # actual run, not a historical inferred cost


@pytest.mark.parametrize("corruption", ["malformed", "hash", "conflict", "verified_pit"])
def test_bad_exact_manifest_never_creates_a_research_run(tmp_path, monkeypatch, corruption):
    from typer.testing import CliRunner

    from algua.cli.main import app

    store, rec = snapshot(tmp_path, monkeypatch)
    raw = rec.to_dict()
    if corruption == "malformed":
        raw["source_metadata"]["research_provenance"] = "not-json"
    elif corruption == "hash":
        raw["content_hash"] = "different"
    elif corruption == "verified_pit":
        envelope = json.loads(raw["source_metadata"]["research_provenance"])
        envelope.update(data_tier="verified_pit", limitations=[])
        raw["source_metadata"]["research_provenance"] = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"))
    text = json.dumps(raw) + "\n"
    if corruption == "conflict":
        text += json.dumps(raw | {"content_hash": "different"}) + "\n"
    store.manifest.path.write_text(text)
    output = CliRunner().invoke(app, ["backtest", "run", NAME, "--snapshot", rec.snapshot_id,
                                    "--start", START, "--end", END])
    assert output.exit_code == 1, output.stdout
    assert json.loads(output.stdout)["ok"] is False
    from algua.registry.db import registry_conn
    from algua.registry.store import SqliteStrategyRepository
    with registry_conn() as conn:
        assert SqliteStrategyRepository(conn).list_runs() == []


def test_legacy_strategy_rejects_bars_identity_drift(tmp_path, monkeypatch):
    store, rec = snapshot(tmp_path, monkeypatch)
    class DriftingProvider(StoreBackedProvider):
        def get_bars(self, *args):
            bars = super().get_bars(*args)
            self.snapshot_id = "changed"
            return bars
    with pytest.raises(BacktestError, match="snapshot_id changed"):
        run(load_strategy(NAME), DriftingProvider(store, rec.snapshot_id), utc(START), utc(END))


@pytest.mark.parametrize("surface", ["capture", "run", "walk_forward", "sweep"])
@pytest.mark.parametrize("corruption", [
    "hash", "verified_pit", "malformed", "provider", "coverage",
])
def test_shared_capture_validates_optional_metadata(tmp_path, monkeypatch, surface, corruption):
    from algua.backtest.sweep import sweep
    from algua.backtest.walkforward import walk_forward

    store, rec = snapshot(tmp_path, monkeypatch)
    raw = rec.to_dict()
    if corruption == "hash":
        raw["content_hash"] = "corrupt"
    elif corruption == "malformed":
        raw["source_metadata"]["research_provenance"] = "not-json"
    elif corruption == "provider":
        raw["provider"] = "different"
    elif corruption == "coverage":
        raw["start"] = "2025-01-01"
    else:
        envelope = json.loads(raw["source_metadata"]["research_provenance"])
        envelope.update(data_tier="verified_pit", limitations=[])
        raw["source_metadata"]["research_provenance"] = json.dumps(
            envelope, sort_keys=True, separators=(",", ":"))

    class OptionalMetadataProvider(StoreBackedProvider):
        @property
        def bars_provenance(self):
            return raw

        def get_bars(self, *args):
            pytest.fail("invalid metadata must be rejected before any fetch")

    strategy = load_strategy(NAME)
    provider = OptionalMetadataProvider(store, rec.snapshot_id)
    with pytest.raises((BacktestError, ValueError)):
        if surface == "capture":
            capture_run_inputs(strategy, provider, strategy.universe, utc(START), utc(END),
                               include_provenance=True)
        elif surface == "run":
            run(strategy, provider, utc(START), utc(END))
        elif surface == "walk_forward":
            walk_forward(strategy, provider, utc(START), utc(END), windows=2)
        else:
            sweep(strategy, provider, utc(START), utc(END), grid={}, windows=2)
