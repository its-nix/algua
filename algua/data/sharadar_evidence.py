"""Parse + validate the explicit dated eligibility/coverage evidence for the universe preview.

The evidence is supplied input, never derived from current vendor metadata or earliest price. Any
malformed, unpinned or mismatched file refuses with fixed text (no values). Dates are ISO strings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from algua.data.sharadar_identity import IdentityCompileError

SCHEMA = "algua.sharadar.eligibility_evidence.v1"
_ELIG_FIELDS = ("issuer_domicile", "venue", "instrument", "currency")


def stable_id(stable_key: str) -> str:
    """The ONE explicit transform: compiler key `sharadar:permaticker:N` -> DataStore-canonical
    upper-case ASCII `SHARADAR:PERMATICKER:N`. Used by every stage, incl. the ASCII tie key."""
    return stable_key.upper()


def _d(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError
    return parsed


def _opt(value: object) -> date | None:
    return None if value is None else _d(value)


@dataclass(frozen=True)
class Episode:
    start: date
    end: date | None  # exclusive
    known_from: date


@dataclass(frozen=True)
class Eligibility:
    start: date
    end: date | None  # exclusive
    known_from: date
    fields: tuple[str | None, ...]  # domicile, venue, instrument, currency; None = unknown


@dataclass(frozen=True)
class SecurityEvidence:
    episodes: tuple[Episode, ...]
    eligibility: tuple[Eligibility, ...]
    absent: frozenset[date]
    # dated ranges where the security's listing status (ALL episodes) is certified complete;
    # outside them a missing episode is UNKNOWN listing status, never "not listed"
    listing_certified: tuple[Episode, ...]


@dataclass(frozen=True)
class Evidence:
    inventory_from: date
    inventory_to: date  # exclusive
    securities: dict[str, SecurityEvidence]  # keyed by canonical stable ID


def _overlap(items: list[tuple[date, date | None]]) -> bool:
    items = sorted(items, key=lambda x: x[0])
    return any(a[1] is None or a[1] > b[0] for a, b in zip(items, items[1:], strict=False))


def parse_evidence(data: bytes, *, identity_sha256: str, bars_content_hash: str, rules_sha256: str,
                   known_ids: frozenset[str]) -> Evidence:
    try:
        doc = json.loads(data)
        if (doc["schema"] != SCHEMA or doc["identity_artifact_sha256"] != identity_sha256
                or doc["bars_content_hash"] != bars_content_hash
                or doc["rules_sha256"] != rules_sha256):
            raise IdentityCompileError("evidence is not bound to these identities/bars/rules")
        inv = doc["inventory"]
        lo, hi = _d(inv["complete_from"]), _d(inv["complete_through_exclusive"])
        if lo >= hi:
            raise ValueError
        out: dict[str, SecurityEvidence] = {}
        for row in doc["securities"]:
            if row["stable_key"] != str(row["stable_key"]).lower():
                raise ValueError  # compiler's lowercase key; the upper transform is explicit
            sid = stable_id(row["stable_key"])
            if sid in out or sid not in known_ids:
                raise ValueError
            eps = tuple(Episode(_d(e["start"]), _opt(e["end_exclusive"]), _d(e["known_from"]))
                        for e in row["episodes"])
            els = tuple(Eligibility(_d(e["start"]), _opt(e["end_exclusive"]), _d(e["known_from"]),
                                    tuple(_field(e.get(k)) for k in _ELIG_FIELDS))
                        for e in row["eligibility"])
            cert = tuple(Episode(_d(e["start"]), _opt(e["end_exclusive"]), _d(e["known_from"]))
                         for e in row["listing_status_certified"])
            absent = frozenset(_d(x) for x in row["certified_absent_sessions"])
            for a in (*eps, *cert):
                if a.end is not None and a.end <= a.start:
                    raise ValueError
            if any(x.end is not None and x.end <= x.start for x in els):
                raise ValueError
            if (_overlap([(e.start, e.end) for e in eps])
                    or _overlap([(e.start, e.end) for e in els])):
                raise ValueError
            out[sid] = SecurityEvidence(tuple(sorted(eps, key=lambda e: e.start)),
                                        tuple(sorted(els, key=lambda e: e.start)), absent,
                                        tuple(sorted(cert, key=lambda e: e.start)))
        return Evidence(lo, hi, out)
    except IdentityCompileError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError):
        raise IdentityCompileError("eligibility evidence is malformed") from None


def _field(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError
    return value
