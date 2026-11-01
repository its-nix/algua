"""Validated ASCII v1 envelopes retain their original encoding and snapshot identities."""
from __future__ import annotations

import ast
import itertools
import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from algua.contracts.canonical import canonical_json
from algua.provenance.research import (
    LIMITATION_VOCABULARY,
    PILOT_PROXY_LIMITATIONS,
    RESEARCH_PROVENANCE_KEY,
    SCHEMA_VERSION,
    SYNTHETIC_LIMITATION,
    DataTier,
    ResearchProvenance,
    ResearchProvenanceError,
    encode_envelope,
    parse_envelope,
)
from algua.provenance.snapshot import Dataset, Kind, SnapshotMetadata, compute_snapshot_id


def value(tier):
    limits = (tuple(sorted(PILOT_PROXY_LIMITATIONS)) if tier is DataTier.PILOT_REAL_PROXY else
              (SYNTHETIC_LIMITATION,) if tier is DataTier.SYNTHETIC_FIXTURE else ())
    return ResearchProvenance(tier, "boundary/v1", limits, "2000-02-29", "2026-10-30", "yfinance")


def original_encoding(envelope):
    return canonical_json({"schema_version": SCHEMA_VERSION, **asdict(envelope)})


def snapshot_identity(envelope, raw):
    metadata = SnapshotMetadata(
        Dataset.BARS, envelope.provider, ("AAA", "BBB"), "2000-02-29", "2026-10-31",
        "2026-11-01T00:00:00+00:00", "encoding-equivalence", kind=Kind.BARS,
        timeframe="1d", adjustment="none", source_metadata={RESEARCH_PROVENANCE_KEY: raw},
    )
    return compute_snapshot_id(metadata, "0123456789abcdef" * 4)


@pytest.mark.parametrize("tier,accepted", [
    (DataTier.PILOT_REAL_PROXY, 1), (DataTier.VERIFIED_PIT, 16),
    (DataTier.SYNTHETIC_FIXTURE, 128),
])
def test_every_tier_limitation_combination_retains_encoding(tier, accepted):
    vocabulary = sorted(LIMITATION_VOCABULARY)
    seen = rejected = 0
    for flags in itertools.product((False, True), repeat=len(vocabulary)):
        envelope = replace(value(tier), limitations=tuple(
            item for item, included in zip(vocabulary, flags, strict=True) if included))
        expected = original_encoding(envelope)
        try:
            actual = encode_envelope(envelope)
        except ResearchProvenanceError:
            with pytest.raises(ResearchProvenanceError):
                parse_envelope(expected)
            rejected += 1
            continue
        assert actual.encode("ascii") == expected.encode("ascii")
        assert parse_envelope(actual) == envelope
        assert snapshot_identity(envelope, actual) == snapshot_identity(envelope, expected)
        seen += 1
    assert seen == accepted
    assert seen + rejected == 256


@pytest.mark.parametrize("tier", list(DataTier))
@pytest.mark.parametrize("provider", [
    "a", "a" + "abcdefghijklmnopqrstuvwxyz0123456789._-" + "z" * 24, "9" * 64,
])
@pytest.mark.parametrize("method", ["a", "a" + "abcdefghijklmnopqrstuvwxyz0123456789._/:+-" * 3,
                                    "z" * 160])
@pytest.mark.parametrize("coverage", [
    ("0001-01-01", "9999-12-31"), ("2000-02-29", "2000-02-29"),
    ("2024-10-31", "2026-10-30"),
])
def test_ascii_alphabets_lengths_and_date_boundaries_match(tier, provider, method, coverage):
    envelope = replace(value(tier), provider=provider, universe_method=method,
                       coverage_start=coverage[0], coverage_end=coverage[1])
    assert encode_envelope(envelope) == original_encoding(envelope)
    assert parse_envelope(encode_envelope(envelope)) == envelope


@pytest.mark.parametrize("tier,golden", [
    (DataTier.PILOT_REAL_PROXY, "7d68cbc8f658dc30"),
    (DataTier.VERIFIED_PIT, "5dda74adb24b8fbe"),
    (DataTier.SYNTHETIC_FIXTURE, "315d41e523093f92"),
])
def test_snapshot_identity_goldens_from_original_encoder(tier, golden):
    envelope = value(tier)
    assert snapshot_identity(envelope, encode_envelope(envelope)) == golden


@pytest.mark.parametrize("field,bad", [
    ("provider", "café"), ("provider", "ｙfinance"),
    ("universe_method", "e\u0301/v1"), ("universe_method", "é/v1"),
    ("coverage_start", "２０００-02-29"), ("coverage_end", "2026-10-３０"),
    ("limitations", ("synthetic_not_market_data", "café")),
])
def test_non_ascii_values_remain_invalid_before_encoding(field, bad):
    envelope = replace(value(DataTier.SYNTHETIC_FIXTURE), **{field: bad})
    with pytest.raises(ResearchProvenanceError):
        encode_envelope(envelope)
    with pytest.raises(ResearchProvenanceError):
        parse_envelope(original_encoding(envelope))


def test_public_encoding_aliases_are_preserved():
    from algua.data import research_provenance as public

    assert public.encode_envelope is encode_envelope
    assert public.parse_envelope is parse_envelope
    assert public.ResearchProvenance is ResearchProvenance


def test_provenance_module_has_only_stdlib_or_own_package_imports():
    root = Path(__file__).resolve().parents[1] / "algua/provenance"
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert all(name.split(".")[0] in sys.stdlib_module_names
                       or name == "algua.provenance" or name.startswith("algua.provenance.")
                       for name in modules), (path.name, modules)
