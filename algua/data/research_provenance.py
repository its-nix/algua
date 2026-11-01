from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from algua.contracts.canonical import canonical_json as _canonical_json

RESEARCH_PROVENANCE_KEY = "research_provenance"
SCHEMA_VERSION = "pilot-provenance/v1"
MAX_ENVELOPE_CHARS = 4096

PILOT_PROXY_LIMITATIONS = frozenset(
    {
        "adjusted_close_vendor_revisable",
        "corporate_actions_unverified",
        "delisted_names_absent",
        "event_timing_unavailable",
        "historical_market_cap_unavailable",
        "point_in_time_universe_unavailable",
        "survivorship_biased_selection",
    }
)
SYNTHETIC_LIMITATION = "synthetic_not_market_data"
LIMITATION_VOCABULARY = PILOT_PROXY_LIMITATIONS | {SYNTHETIC_LIMITATION}

_UNIVERSE_METHOD = re.compile(r"^[a-z0-9][a-z0-9._/:+\-]{0,159}$")
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_FIELDS = {
    "schema_version", "data_tier", "universe_method", "limitations",
    "coverage_start", "coverage_end", "provider",
}


class DataTier(StrEnum):
    PILOT_REAL_PROXY = "pilot_real_proxy"
    VERIFIED_PIT = "verified_pit"
    SYNTHETIC_FIXTURE = "synthetic_fixture"


class ResearchProvenanceError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class ProvenanceDeclaration:
    data_tier: DataTier
    universe_method: str
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchProvenance:
    data_tier: DataTier
    universe_method: str
    limitations: tuple[str, ...]
    coverage_start: str
    coverage_end: str
    provider: str


def declaration_from_options(
    data_tier: str | None,
    universe_method: str | None,
    limitations: list[str] | None,
) -> ProvenanceDeclaration | None:
    if data_tier is None and universe_method is None and not limitations:
        return None
    if data_tier is None or universe_method is None:
        raise ResearchProvenanceError(
            "research_provenance_incomplete_declaration",
            "--data-tier and --universe-method must be provided together",
        )
    try:
        tier = DataTier(data_tier)
    except ValueError as exc:
        raise ResearchProvenanceError(
            "research_provenance_malformed", f"unknown data tier {data_tier!r}"
        ) from exc
    if tier is DataTier.VERIFIED_PIT:
        raise ResearchProvenanceError(
            "verified_pit_evidence_required", "no verified-PIT evidence verifier exists"
        )
    declaration = ProvenanceDeclaration(tier, universe_method, tuple(limitations or ()))
    _validate_declaration(declaration)
    return declaration


def build_envelope(
    declaration: ProvenanceDeclaration,
    *,
    provider: str,
    coverage_start: str,
    coverage_end: str,
) -> ResearchProvenance:
    _validate_declaration(declaration)
    if declaration.data_tier is DataTier.VERIFIED_PIT:
        raise ResearchProvenanceError(
            "verified_pit_evidence_required", "no verified-PIT evidence verifier exists"
        )
    limitations = set(declaration.limitations)
    if declaration.data_tier is DataTier.PILOT_REAL_PROXY:
        limitations.update(PILOT_PROXY_LIMITATIONS)
    value = ResearchProvenance(
        data_tier=declaration.data_tier,
        universe_method=declaration.universe_method,
        limitations=tuple(sorted(limitations)),
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        provider=provider,
    )
    _validate_value(value)
    return value


def encode_envelope(value: ResearchProvenance) -> str:
    _validate_value(value)
    return _canonical_json(_as_payload(value))


def parse_envelope(raw: object) -> ResearchProvenance:
    if not isinstance(raw, str) or len(raw) > MAX_ENVELOPE_CHARS:
        raise ResearchProvenanceError(
            "research_provenance_malformed", "envelope must be a bounded JSON string"
        )
    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_raise_bad_constant,
        )
    except (json.JSONDecodeError, ResearchProvenanceError) as exc:
        if isinstance(exc, ResearchProvenanceError):
            raise
        raise ResearchProvenanceError(
            "research_provenance_malformed", "envelope is not valid JSON"
        ) from exc
    if not isinstance(parsed, dict) or set(parsed) != _FIELDS:
        raise ResearchProvenanceError(
            "research_provenance_malformed", "envelope must contain exactly the v1 fields"
        )
    if parsed["schema_version"] != SCHEMA_VERSION:
        raise ResearchProvenanceError(
            "research_provenance_unknown_schema",
            f"expected {SCHEMA_VERSION!r}",
        )
    if not all(
        isinstance(parsed[field], str)
        for field in ("data_tier", "universe_method", "coverage_start", "coverage_end", "provider")
    ) or not isinstance(parsed["limitations"], list):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "envelope fields have invalid JSON types"
        )
    if not all(isinstance(item, str) for item in parsed["limitations"]):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "limitations must contain only strings"
        )
    try:
        tier = DataTier(parsed["data_tier"])
    except ValueError as exc:
        raise ResearchProvenanceError(
            "research_provenance_malformed", "data_tier is outside the v1 vocabulary"
        ) from exc
    value = ResearchProvenance(
        data_tier=tier,
        universe_method=parsed["universe_method"],
        limitations=tuple(parsed["limitations"]),
        coverage_start=parsed["coverage_start"],
        coverage_end=parsed["coverage_end"],
        provider=parsed["provider"],
    )
    _validate_value(value)
    if raw != _canonical_json(parsed):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "envelope is not canonical JSON"
        )
    return value


def decode_research_provenance(
    source_metadata: Mapping[str, str] | None,
) -> ResearchProvenance | None:
    if RESEARCH_PROVENANCE_KEY not in (source_metadata or {}):
        return None
    return parse_envelope((source_metadata or {})[RESEARCH_PROVENANCE_KEY])


def _validate_declaration(value: ProvenanceDeclaration) -> None:
    if not isinstance(value.data_tier, DataTier):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "data_tier must be a DataTier value"
        )
    if not isinstance(value.universe_method, str) or not _UNIVERSE_METHOD.fullmatch(
        value.universe_method
    ):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "universe_method has invalid syntax"
        )
    if not isinstance(value.limitations, tuple) or not all(
        isinstance(item, str) for item in value.limitations
    ):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "limitations must be a tuple of strings"
        )
    unknown = set(value.limitations) - LIMITATION_VOCABULARY
    if unknown or len(set(value.limitations)) != len(value.limitations):
        raise ResearchProvenanceError(
            "research_provenance_tier_limitations", "limitations are duplicated or unknown"
        )
    if value.data_tier is DataTier.PILOT_REAL_PROXY and SYNTHETIC_LIMITATION in value.limitations:
        raise ResearchProvenanceError(
            "research_provenance_tier_limitations", "proxy data cannot be synthetic"
        )
    if (
        value.data_tier is DataTier.SYNTHETIC_FIXTURE
        and SYNTHETIC_LIMITATION not in value.limitations
    ):
        raise ResearchProvenanceError(
            "research_provenance_tier_limitations", "synthetic limitation is required"
        )


def _validate_value(value: ResearchProvenance) -> None:
    _validate_declaration(
        ProvenanceDeclaration(value.data_tier, value.universe_method, value.limitations)
    )
    if value.limitations != tuple(sorted(value.limitations)):
        raise ResearchProvenanceError(
            "research_provenance_tier_limitations", "limitations must be sorted"
        )
    limitations = set(value.limitations)
    if value.data_tier is DataTier.PILOT_REAL_PROXY and not PILOT_PROXY_LIMITATIONS <= limitations:
        raise ResearchProvenanceError(
            "research_provenance_tier_limitations", "proxy limitations are incomplete"
        )
    if value.data_tier is DataTier.VERIFIED_PIT and limitations & {
        SYNTHETIC_LIMITATION,
        "point_in_time_universe_unavailable",
        "survivorship_biased_selection",
        "delisted_names_absent",
    }:
        raise ResearchProvenanceError(
            "research_provenance_tier_limitations", "verified PIT has contradictory limitations"
        )
    if not isinstance(value.provider, str) or not _PROVIDER.fullmatch(value.provider):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "provider has invalid syntax"
        )
    try:
        start = date.fromisoformat(value.coverage_start)
        end = date.fromisoformat(value.coverage_end)
    except (TypeError, ValueError) as exc:
        raise ResearchProvenanceError(
            "research_provenance_malformed", "coverage dates must be ISO dates"
        ) from exc
    if (
        start.isoformat() != value.coverage_start
        or end.isoformat() != value.coverage_end
        or start > end
    ):
        raise ResearchProvenanceError(
            "research_provenance_malformed", "coverage dates are non-canonical or reversed"
        )


def _as_payload(value: ResearchProvenance) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "data_tier": value.data_tier.value,
        "universe_method": value.universe_method,
        "limitations": list(value.limitations),
        "coverage_start": value.coverage_start,
        "coverage_end": value.coverage_end,
        "provider": value.provider,
    }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ResearchProvenanceError(
                "research_provenance_malformed", f"duplicate key {key!r}"
            )
        value[key] = item
    return value


def _raise_bad_constant(value: str) -> None:
    raise ResearchProvenanceError(
        "research_provenance_malformed", f"invalid JSON constant {value!r}"
    )
