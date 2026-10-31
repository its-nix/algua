from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.contracts import ProviderBars
from algua.data.manifest import SnapshotManifest
from algua.data.models import Dataset, Kind, SnapshotMetadata, SnapshotRecord
from algua.data.refresh import refresh_bars
from algua.data.research_provenance import (
    PILOT_PROXY_LIMITATIONS,
    DataTier,
    ProvenanceDeclaration,
    ResearchProvenance,
    ResearchProvenanceError,
    decode_research_provenance,
    encode_envelope,
    parse_envelope,
)
from algua.data.store import DataStore


def _bars(symbols: tuple[str, ...] = ("AAPL", "MSFT")) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        for day, close in (("2026-01-02", 100.0), ("2026-01-05", 101.0)):
            rows.append(
                {
                    "ts": f"{day}T00:00:00+00:00",
                    "symbol": symbol,
                    "open": close - 1,
                    "high": close + 1,
                    "low": close - 2,
                    "close": close,
                    "adj_close": close - 0.5,
                    "volume": 1000.0,
                }
            )
    return pd.DataFrame(rows)


def _declaration(method: str = "dated-candidate-proxy/v1") -> ProvenanceDeclaration:
    return ProvenanceDeclaration(
        data_tier=DataTier.PILOT_REAL_PROXY,
        universe_method=method,
    )


def _ingest(store: DataStore, **overrides: object) -> SnapshotRecord:
    kwargs: dict[str, object] = {
        "provider": "yfinance",
        "symbols": ["AAPL", "MSFT"],
        "start": "2026-01-01",
        "end": "2026-01-06",
        "as_of": "2026-01-07T00:00:00+00:00",
        "source": "pilot",
        "frame": _bars(),
        "provenance": _declaration(),
    }
    kwargs.update(overrides)
    return store.ingest_bars(**kwargs)  # type: ignore[arg-type]


def test_envelope_is_canonical_and_round_trips_actual_tier() -> None:
    value = ResearchProvenance(
        data_tier=DataTier.SYNTHETIC_FIXTURE,
        universe_method="fixture/v1",
        limitations=("synthetic_not_market_data",),
        coverage_start="2026-01-02",
        coverage_end="2026-01-05",
        provider="fixture",
    )

    raw = encode_envelope(value)

    assert raw == (
        '{"coverage_end":"2026-01-05","coverage_start":"2026-01-02",'
        '"data_tier":"synthetic_fixture","limitations":["synthetic_not_market_data"],'
        '"provider":"fixture","schema_version":"pilot-provenance/v1",'
        '"universe_method":"fixture/v1"}'
    )
    assert parse_envelope(raw) == value
    assert decode_research_provenance({"research_provenance": raw}) == value
    assert decode_research_provenance({}) is None
    assert decode_research_provenance(None) is None

    verified = ResearchProvenance(
        data_tier=DataTier.VERIFIED_PIT,
        universe_method="verified-membership/v1",
        limitations=(),
        coverage_start="2026-01-02",
        coverage_end="2026-01-05",
        provider="fixture",
    )
    assert parse_envelope(encode_envelope(verified)).data_tier is DataTier.VERIFIED_PIT


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        '{"schema_version":"pilot-provenance/v2"}',
        '{ "coverage_end":"2026-01-05" }',
        '{"coverage_end":"2026-01-05","coverage_end":"2026-01-05"}',
    ],
)
def test_malformed_or_unknown_envelopes_fail_closed(raw: str) -> None:
    with pytest.raises(ResearchProvenanceError):
        parse_envelope(raw)


def test_typed_declaration_refuses_raw_string_tier(tmp_path) -> None:
    declaration = ProvenanceDeclaration(  # type: ignore[arg-type]
        data_tier="pilot_real_proxy",
        universe_method="dated-candidate-proxy/v1",
    )
    with pytest.raises(ResearchProvenanceError, match="research_provenance_malformed"):
        _ingest(DataStore(tmp_path / "data"), provenance=declaration)


def test_proxy_required_limitations_are_added_and_verified_pit_write_is_refused(tmp_path) -> None:
    store = DataStore(tmp_path / "data")
    rec = _ingest(store)
    decoded = decode_research_provenance(rec.metadata.source_metadata)

    assert decoded is not None
    assert decoded.data_tier is DataTier.PILOT_REAL_PROXY
    assert decoded.limitations == tuple(sorted(PILOT_PROXY_LIMITATIONS))

    with pytest.raises(ResearchProvenanceError, match="verified_pit_evidence_required"):
        _ingest(
            store,
            provenance=ProvenanceDeclaration(
                data_tier=DataTier.VERIFIED_PIT,
                universe_method="verified-membership/v1",
            ),
        )
    assert len(store.list_snapshots()) == 1


def test_declared_bars_bind_observed_coverage_symbols_identity_and_dedup(tmp_path) -> None:
    store = DataStore(tmp_path / "data")
    first = _ingest(store)
    again = _ingest(store)
    changed = _ingest(store, provenance=_declaration("dated-candidate-proxy/v2"))

    decoded = decode_research_provenance(first.metadata.source_metadata)
    assert decoded is not None
    assert (decoded.coverage_start, decoded.coverage_end) == ("2026-01-02", "2026-01-05")
    assert again == first
    assert changed.content_hash == first.content_hash
    assert changed.snapshot_id != first.snapshot_id
    assert store.get_snapshot(first.snapshot_id) == first
    assert len(store.list_snapshots()) == 2

    reloaded = DataStore(tmp_path / "data").get_snapshot(first.snapshot_id)
    assert reloaded.snapshot_id == first.snapshot_id
    assert decode_research_provenance(reloaded.metadata.source_metadata) == decoded


def test_refresh_reuses_declared_snapshot_without_fetching_or_relabeling(tmp_path) -> None:
    store = DataStore(tmp_path / "data")
    declared = _ingest(store)

    class UnusedProvider:
        name = "yfinance"

        def get_bars(self, _request: object) -> ProviderBars:
            raise AssertionError("matching declared snapshot must be reused")

    reused, refreshed = refresh_bars(
        store,
        UnusedProvider(),  # type: ignore[arg-type]
        symbols=["AAPL", "MSFT"],
        start="2026-01-01",
        end="2026-01-06",
        require_bar_on="2026-01-05",
        min_rows={"AAPL": 2, "MSFT": 2},
    )

    assert refreshed is False
    assert reused == declared
    assert decode_research_provenance(reused.metadata.source_metadata).data_tier is (
        DataTier.PILOT_REAL_PROXY
    )


def test_declared_bars_refuse_missing_requested_symbol_before_commit(tmp_path) -> None:
    store = DataStore(tmp_path / "data")

    with pytest.raises(ResearchProvenanceError, match="research_provenance_symbol_mismatch"):
        _ingest(store, frame=_bars(("AAPL",)))

    assert store.list_snapshots() == []


def test_reserved_metadata_injection_and_direct_manifest_bypass_fail_closed(tmp_path) -> None:
    store = DataStore(tmp_path / "data")
    source = tmp_path / "opaque.csv"
    source.write_text("x\n1\n", encoding="utf-8")

    with pytest.raises(ResearchProvenanceError, match="research_provenance_reserved_key"):
        store.ingest_file(
            dataset=Dataset.BARS,
            provider="local",
            symbols=["AAPL"],
            start="2026-01-02",
            end="2026-01-03",
            as_of="2026-01-04T00:00:00+00:00",
            source="fixture",
            file_path=source,
            source_metadata={"research_provenance": "{}"},
        )

    metadata = SnapshotMetadata(
        dataset=Dataset.BARS,
        provider="local",
        symbols=("AAPL",),
        start="2026-01-02",
        end="2026-01-03",
        as_of="2026-01-04T00:00:00+00:00",
        source="fixture",
        kind=Kind.BARS,
        source_metadata={"research_provenance": "{}"},
    )
    rec = SnapshotRecord(
        snapshot_id="bypass",
        metadata=metadata,
        row_count=1,
        content_hash="hash",
        data_path=Path("snapshots/bars/bypass"),
        created_at="2026-01-04T00:00:00+00:00",
        storage_format="parquet_dataset",
    )
    manifest = SnapshotManifest(tmp_path / "direct-manifest.jsonl")
    with pytest.raises(ResearchProvenanceError):
        manifest.append_if_absent(rec)
    assert not manifest.path.exists()

    with pytest.raises(ResearchProvenanceError, match="research_provenance_reserved_key"):
        store._ingest_parquet(
            metadata=metadata,
            frame=pd.DataFrame({"symbol": ["AAPL"]}),
            filename="bars.parquet",
        )


def test_manifest_loader_refuses_non_string_reserved_value() -> None:
    rec = SnapshotRecord(
        snapshot_id="raw",
        metadata=SnapshotMetadata(
            dataset=Dataset.BARS,
            provider="local",
            symbols=("AAPL",),
            start="2026-01-02",
            end="2026-01-03",
            as_of="2026-01-04T00:00:00+00:00",
            source="fixture",
            kind=Kind.BARS,
        ),
        row_count=1,
        content_hash="hash",
        data_path=Path("snapshots/bars/raw"),
        created_at="2026-01-04T00:00:00+00:00",
    )
    payload = rec.to_dict()
    payload["source_metadata"] = {"research_provenance": {"data_tier": "pilot_real_proxy"}}

    with pytest.raises(ResearchProvenanceError, match="research_provenance_malformed"):
        SnapshotRecord.from_dict(payload)


@pytest.mark.parametrize(
    ("declaration_args", "reason"),
    [
        (["--data-tier", "pilot_real_proxy"], "research_provenance_incomplete_declaration"),
        (
            ["--data-tier", "verified_pit", "--universe-method", "pit/v1"],
            "verified_pit_evidence_required",
        ),
        (
            ["--data-tier", "synthetic_fixture", "--universe-method", "fixture/v1"],
            "research_provenance_tier_limitations",
        ),
    ],
)
def test_cli_validates_declaration_before_provider_fetch(
    monkeypatch, tmp_path, declaration_args: list[str], reason: str
) -> None:
    from algua.cli import data_cmd

    fetched = False

    class ExplodingProvider:
        def get_bars(self, _request: object) -> object:
            nonlocal fetched
            fetched = True
            raise AssertionError("provider must not be called")

    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(data_cmd, "_bar_provider", lambda _name: ExplodingProvider())

    args = [
        "data", "ingest-bars", "--provider", "fake", "--symbols", "AAPL",
        "--start", "2026-01-02", "--end", "2026-01-03", *declaration_args,
    ]
    result = CliRunner().invoke(app, args)

    assert result.exit_code == 1
    assert fetched is False
    payload = json.loads(result.stdout)
    assert payload["code"] == "invalid_input"
    assert reason in payload["error"]


def test_cli_ingest_bars_persists_declared_provenance(monkeypatch, tmp_path) -> None:
    from algua.cli import data_cmd

    class FakeProvider:
        def get_bars(self, _request: object) -> ProviderBars:
            return ProviderBars(frame=_bars(("AAPL",)), source_metadata={"provider": "fake"})

    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(data_cmd, "_bar_provider", lambda _name: FakeProvider())

    result = CliRunner().invoke(
        app,
        [
            "data",
            "ingest-bars",
            "--provider",
            "fake",
            "--symbols",
            "AAPL",
            "--start",
            "2026-01-01",
            "--end",
            "2026-01-06",
            "--data-tier",
            "pilot_real_proxy",
            "--universe-method",
            "dated-candidate-proxy/v1",
        ],
    )

    assert result.exit_code == 0, result.stdout
    metadata = json.loads(result.stdout)["snapshot"]["source_metadata"]
    provenance = decode_research_provenance(metadata)
    assert provenance is not None
    assert provenance.data_tier is DataTier.PILOT_REAL_PROXY
    assert (provenance.coverage_start, provenance.coverage_end) == (
        "2026-01-02",
        "2026-01-05",
    )
