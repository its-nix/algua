"""Stage 2: PRIVATE PREVIEW of the frozen `us-liquid-common/v1` daily universe (unqualified).

Computes per-XNYS-session membership from one frozen stage-1 bars snapshot plus explicit dated
eligibility evidence. It never infers historical domicile/venue/currency/instrument/listing episode
from current metadata or earliest price. Any unknown required input REFUSES that date (no silent
drop, no rank-1001 replacement, no prior membership carried over). Output is a private export; it is
not imported into the store, publishes no universe, and is never `verified_pit` or qualified.
"""
from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Context, Decimal, Inexact, localcontext
from pathlib import Path

import numpy as np

from algua.calendar.market_calendar import MarketCalendar
from algua.contracts.canonical import canonical_json
from algua.data.models import Dataset
from algua.data.sharadar_bars_prep import load_identity_artifact
from algua.data.sharadar_evidence import Episode, SecurityEvidence, parse_evidence
from algua.data.sharadar_identity import (
    IdentityCompileError,
    _capture,
    _sanitized,
    write_private_new,
)
from algua.data.store import DataStore

SCHEMA = "algua.sharadar.universe_preview.v1"
FROZEN_RULES_SHA256 = "38d880b7b6079fd460d48e5bb144b14c74a0089f55fff37e7cfc1ecee867c7b2"
MATERIALIZER_REV = "sharadar-universe-preview/1"
_EXACT = Context(prec=400, traps=[Inexact])
VALID, ABSENT, UNKNOWN, INVALID = 0, 1, 2, 3


@dataclass(frozen=True)
class UniversePreview:
    body: bytes
    artifact_sha256: str
    path: Path | None
    computed_dates: int
    refused_dates: int
    interval_count: int
    hashes: dict[str, str]


def _in(a: date, lo: date, hi: date | None) -> bool:
    return lo <= a and (hi is None or a < hi)


class _Sec:
    """Per-security classified session codes with prefix counts (index = global session index)."""

    def __init__(self, ev: SecurityEvidence, n: int) -> None:
        self.ev = ev
        self.code = np.full(n, UNKNOWN, dtype=np.int8)
        self.close: dict[int, str] = {}
        self.vol: dict[int, str] = {}
        self.dv: dict[int, Decimal] = {}
        self.cum: dict[int, np.ndarray] = {}

    def finish(self) -> None:
        for k in (VALID, UNKNOWN, INVALID):
            self.cum[k] = np.concatenate(([0], np.cumsum(self.code == k)))

    def count(self, kind: int, lo: int, hi: int) -> int:  # inclusive indices
        return int(self.cum[kind][hi + 1] - self.cum[kind][lo])

    def dollar_volume(self, i: int) -> Decimal:
        if i not in self.dv:
            self.dv[i] = Decimal(self.close[i]) * Decimal(self.vol[i])
        return self.dv[i]


def _episode_at(eps: tuple[Episode, ...], t: date) -> tuple[Episode | None, bool]:
    """(known episode containing t, an episode containing t exists but is not yet known)."""
    unknown = False
    for e in eps:
        if _in(t, e.start, e.end):
            if e.known_from <= t:
                return e, False
            unknown = True
    return None, unknown


@_sanitized("universe preview failed")
def compute_universe_preview(*, store: DataStore, snapshot_id: str, identities: Path,
                             rules: Path, evidence: Path, start: date, end: date,
                             out: Path | None, repo_root: Path) -> UniversePreview:
    rules_bytes = _capture(rules, 1 << 20)
    cfg = json.loads(rules_bytes)
    rules_sha = hashlib.sha256(canonical_json(cfg).encode("utf-8")).hexdigest()
    if rules_sha != FROZEN_RULES_SHA256 or cfg.get("rule_id") != "us-liquid-common/v1":
        raise IdentityCompileError("rules are not the frozen us-liquid-common/v1 configuration")
    ident = load_identity_artifact(identities)
    rec = store.get_snapshot(snapshot_id)
    if (rec.dataset != Dataset.BARS or rec.metadata.provider != "sharadar"
            or rec.metadata.timeframe != "1d" or rec.metadata.adjustment != "none"):
        raise IdentityCompileError("snapshot is not a stage-1 Sharadar 1d raw bars snapshot")
    ev_bytes = _capture(evidence, 256 << 20)
    ev = parse_evidence(ev_bytes, identity_sha256=ident.sha256, bars_content_hash=rec.content_hash,
                        rules_sha256=rules_sha, known_ids=ident.ids)
    if start >= end:
        raise IdentityCompileError("start must be before end")

    bars = store.read_bars(snapshot_id)
    if not set(bars["symbol"].unique()) <= ident.ids:
        raise IdentityCompileError("snapshot has symbols that are not artifact stable IDs")
    cal = MarketCalendar(cfg["calendar"])
    first_bar = bars.index.min().date()
    sessions = cal.sessions_in_range(min(first_bar, ev.inventory_from, start), end)
    pos = {d: i for i, d in enumerate(sessions)}
    eval_dates = [d for d in sessions if start <= d < end]
    if not eval_dates:
        raise IdentityCompileError("no XNYS sessions in the requested range")
    n = len(sessions)

    secs: dict[str, _Sec] = {}
    contradict: dict[str, set[int]] = {}
    for sid, sev in ev.securities.items():
        sec = _Sec(sev, n)
        for d in sev.absent:
            if d in pos:
                sec.code[pos[d]] = ABSENT
        secs[sid] = sec
    for sid, grp in bars.groupby("symbol", sort=False):
        found = secs.get(str(sid))
        if found is None:
            raise IdentityCompileError("snapshot symbol has no evidence entry")
        s = found
        bad: set[int] = set()
        for ts, close, vol in zip(grp.index, grp["close"], grp["volume"], strict=True):
            d = ts.date()
            if d not in pos:
                raise IdentityCompileError("snapshot has a bar on a non-XNYS-session date")
            i = pos[d]
            ok = (math.isfinite(close) and close > 0 and math.isfinite(vol) and vol >= 0
                  and s.code[i] == UNKNOWN)  # a certified absence plus a bar is a contradiction
            s.code[i] = VALID if ok else INVALID
            if ok:
                s.close[i], s.vol[i] = str(float(close)), str(float(vol))
            e, _ = _episode_at(s.ev.episodes, d)
            if e is None:
                bad.add(i)
        contradict[str(sid)] = bad
    for s in secs.values():
        s.finish()

    cap = int(cfg["selection"]["maximum_securities"])
    hist_min = int(cfg["history_floor"]["minimum_valid_observed_sessions"])
    win = int(cfg["liquidity"]["sessions"])
    price_min = Decimal(str(cfg["price"]["minimum_USD_inclusive"]))
    liq_min = Decimal(str(cfg["liquidity"]["minimum_USD_inclusive"]))
    elig = cfg["eligibility"]
    want = (elig["issuer_domicile"], None, "ordinary_common_stock", elig["currency"])
    venues = set(elig["listing_venues"])

    members_by_date: dict[date, list[str]] = {}
    refused: dict[date, Counter[str]] = {}
    with localcontext(_EXACT):
        for t in eval_dates:
            ti = pos[t]
            why: Counter[str] = Counter()
            if not (ev.inventory_from <= t < ev.inventory_to):
                why["unknown_universe_inventory"] += 1
            ranked: list[tuple[Decimal, str]] = []
            for sid in sorted(secs):
                if why.get("unknown_universe_inventory"):
                    break
                s = secs[sid]
                e, e_unknown = _episode_at(s.ev.episodes, t)
                if e_unknown:
                    why["episode_not_known_by_t"] += 1
                    continue
                if e is None:
                    if not any(_in(t, c.start, c.end) and c.known_from <= t
                               for c in s.ev.listing_certified):
                        why["unknown_listing_status"] += 1
                    elif ti in contradict.get(sid, ()):
                        why["bar_outside_listing_episode"] += 1
                    continue
                cur = next((x for x in s.ev.eligibility
                            if _in(t, x.start, x.end) and x.known_from <= t), None)
                if cur is None or any(f is None for f in cur.fields):
                    why["eligibility_unknown"] += 1
                    continue
                dom, venue, inst, ccy = cur.fields
                if (dom, inst, ccy) != (want[0], want[2], want[3]) or venue not in venues:
                    continue  # known economic/instrument exclusion
                # Counted observations lie in ONE known continuous episode e. A count >= floor
                # is a certified lower bound even if the older bar prefix is unknown; an unknown
                # prefix with a count below the floor cannot be excluded, so it refuses the date.
                lo = bisect_left(sessions, e.start)
                prefix_unknown = lo == 0 and e.start < sessions[0]
                if s.count(INVALID, lo, ti):
                    why["invalid_or_duplicate_bar"] += 1
                    continue
                wlo = ti - win + 1
                if wlo >= lo:
                    if s.count(UNKNOWN, wlo, ti):
                        why["unknown_expected_bar_not_certified_absent"] += 1
                        continue
                    if s.count(VALID, wlo, ti) != win:
                        continue  # certified absence inside the trailing window
                if s.count(VALID, lo, ti) < hist_min:
                    if prefix_unknown or s.count(UNKNOWN, lo, ti):
                        why["history_floor_undecidable_unknown_prefix"] += 1
                    continue
                if Decimal(s.close[ti]) < price_min:
                    continue
                dvs = sorted(s.dollar_volume(i) for i in range(ti - win + 1, ti + 1))
                median = (dvs[win // 2 - 1] + dvs[win // 2]) / 2
                if median >= liq_min:
                    ranked.append((median, sid))
            if why:
                refused[t] = why
                continue
            ranked.sort(key=lambda r: (-r[0], r[1]))
            members_by_date[t] = sorted(sid for _, sid in ranked[:cap])

    if not members_by_date:
        raise IdentityCompileError("every requested date was refused; nothing to export")
    intervals: list[dict[str, str | None]] = []
    openm: dict[str, date] = {}
    for t in eval_dates:
        cur_members = set(members_by_date.get(t, ()))
        for sid in [k for k in openm if k not in cur_members]:
            intervals.append({"symbol": sid, "add_date": openm.pop(sid).isoformat(),
                              "drop_date": t.isoformat()})
        for sid in cur_members:
            openm.setdefault(sid, t)
    intervals += [{"symbol": sid, "add_date": a.isoformat(), "drop_date": None}
                  for sid, a in openm.items()]
    intervals.sort(key=lambda r: (r["symbol"], r["add_date"]))
    hashes = {"rules_sha256": rules_sha, "identity_artifact_sha256": ident.sha256,
              "evidence_sha256": hashlib.sha256(ev_bytes).hexdigest(),
              "bars_content_hash": rec.content_hash}
    doc = {
        "schema": SCHEMA, "status": "private_preview_unqualified", "verified_pit": False,
        "qualified": False,
        "evidence_status": "declared_input_unverified",
        "historical_eligibility_and_coverage": "unverified",
        "stable_id_transform": "upper(sharadar:permaticker:N); tie key = transformed id",
         "authoritative_universe": False, "rule_id": cfg["rule_id"],
        "calendar": cfg["calendar"], "materializer_rev": MATERIALIZER_REV,
        "snapshot_id": snapshot_id, "hashes": hashes,
        "range": {"start": start.isoformat(), "end_exclusive": end.isoformat()},
        "notes": ["refused dates have no membership; prior membership never stands in",
                  "drop_date null means still selected at the last computed session of the range",
                  "not imported into the store; protected PIT verification not performed"],
        "computed_dates": [d.isoformat() for d in sorted(members_by_date)],
        "daily_selected_count": {d.isoformat(): len(m)
                                 for d, m in sorted(members_by_date.items())},
        "refused_dates": {d.isoformat(): dict(sorted(c.items()))
                          for d, c in sorted(refused.items())},
        "shortfall_dates": sum(1 for m in members_by_date.values() if len(m) < cap),
        "intervals": intervals,
    }
    body = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = write_private_new(out, body, repo_root=repo_root) if out is not None else None
    return UniversePreview(body, hashlib.sha256(body).hexdigest(), path, len(members_by_date),
                           len(refused), len(intervals), hashes)
