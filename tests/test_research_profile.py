"""Pinned proxy profile validates real store bytes; no researcher or provider is launched."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from algua.data.research_provenance import DataTier, ProvenanceDeclaration
from algua.data.store import DataStore
from algua.operator import research_profile as profile
from algua.operator.research_context import cycle_context

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configured(tmp_path, monkeypatch):
    symbols = profile.midcap_symbols(ROOT)
    rows = [{"ts": stamp, "symbol": symbol, "open": 20.0, "high": 21.0,
             "low": 19.0, "close": 20.0, "adj_close": 20.0, "volume": 2_000_000.0}
            for stamp in pd.to_datetime(["2024-11-01", "2026-11-06"], utc=True)
            for symbol in [*symbols, "AAON"]]
    store = DataStore(tmp_path / "data")
    record = store.ingest_bars(provider="yfinance", symbols=[*symbols, "AAON"],
        start="2024-11-01", end="2026-11-08", as_of="2026-11-08T12:00:00+00:00",
        source="SYNTHETIC_FIXTURE", frame=pd.DataFrame(rows),
        provenance=ProvenanceDeclaration(DataTier.PILOT_REAL_PROXY, "fixture-current-members"))
    monkeypatch.setattr(profile, "SNAPSHOT_ID", record.snapshot_id)
    descriptor = {"schema_version": "midcap-research-profile/v1",
                  "snapshot_id": record.snapshot_id, "content_hash": record.content_hash,
                  "start": "2024-11-01", "end": "2026-11-08",
                  "symbols_sha256": profile.symbols_digest(symbols)}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(descriptor))
    monkeypatch.setenv("ALGUA_RESEARCH_PROFILE", str(path))
    return store, record, path, descriptor


def test_unconfigured_context_unchanged_and_does_not_read_data(tmp_path, monkeypatch):
    monkeypatch.delenv("ALGUA_RESEARCH_PROFILE", raising=False)
    assert profile.load_research_profile(tmp_path) is None
    assert "research_profile" not in cycle_context(tmp_path)
    assert not tmp_path.joinpath("manifest.jsonl").exists()


def test_exact_config_symbols_exclude_extra_snapshot_member(configured):
    store, record, _, descriptor = configured
    receipt = profile.load_research_profile(store.data_dir)
    assert receipt["snapshot_id"] == record.snapshot_id
    assert receipt["content_hash"] == record.content_hash
    assert receipt["symbols_sha256"] == descriptor["symbols_sha256"]
    assert len(receipt["symbols"]) == 300 and "AAON" not in receipt["symbols"]
    assert receipt["data_tier"] == "pilot_real_proxy"
    assert len(receipt["limitations"]) == 7
    assert receipt["universe_mode"] == "static" and receipt["qualification_eligible"] is False
    assert cycle_context(store.data_dir)["research_profile"] == receipt


@pytest.mark.parametrize("key,value", [
    ("snapshot_id", "other"), ("start", "2024-11-02"), ("end", "2026-11-09"),
    ("symbols_sha256", "0" * 64), ("content_hash", "0" * 64),
    ("extra", "unknown"),
])
def test_incomplete_or_drifted_profile_refuses(configured, key, value):
    store, _, path, descriptor = configured
    path.write_text(json.dumps(descriptor | {key: value}))
    with pytest.raises(ValueError, match="research_profile:"):
        profile.load_research_profile(store.data_dir)
    descriptor.pop("start")
    path.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError, match="research_profile:"):
        profile.load_research_profile(store.data_dir)


def test_profile_duplicate_fields_refuse(configured):
    store, _, path, descriptor = configured
    path.write_text(json.dumps(descriptor)[:-1] + ',"start":"2024-11-01"}')
    with pytest.raises(ValueError, match="research_profile:"):
        profile.load_research_profile(store.data_dir)


def test_payload_change_refuses_even_with_unchanged_manifest(configured):
    store, record, _, _ = configured
    leaf = next((store.data_dir / record.data_path).rglob("*.parquet"))
    frame = pd.read_parquet(leaf)
    frame.loc[0, "adj_close"] = 23.0
    frame.to_parquet(leaf, index=False)
    with pytest.raises(ValueError, match="research_profile:payload"):
        profile.load_research_profile(store.data_dir)


def test_universe_is_parsed_without_importing_strategy(tmp_path):
    target = tmp_path / profile.UNIVERSE_MODULE
    target.parent.mkdir(parents=True)
    target.write_text('raise RuntimeError("must not execute")\n'
                      'CONFIG=StrategyConfig(universe="A B".split())')
    with pytest.raises(ValueError, match="research_profile:universe"):
        profile.midcap_symbols(tmp_path)


def test_missing_snapshot_refuses_with_fixed_profile_error(configured, tmp_path):
    with pytest.raises(ValueError, match="research_profile:payload"):
        profile.load_research_profile(tmp_path / "missing-data")
