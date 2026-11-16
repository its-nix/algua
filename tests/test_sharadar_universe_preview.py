"""Synthetic-only tests for stage-1 bar preparation and the stage-2 private universe preview."""
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from algua.calendar.market_calendar import MarketCalendar
from algua.data.sharadar_bars_prep import prepare_bars
from algua.data.sharadar_identity import IdentityCompileError, compile_identity_artifact
from algua.data.sharadar_universe import FROZEN_RULES_SHA256, compute_universe_preview
from algua.data.store import DataStore

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "deploy/research/us-liquid-common-v1.json"
T_HEAD = "table,permaticker,ticker,name,exchange,isdelisted,category,firstpricedate,lastpricedate\n"
A_HEAD = "date,action,ticker,name,value,contraticker,contraname\n"
S_HEAD = "ticker,date,open,high,low,close,volume,closeadj,closeunadj,lastupdated\n"
SESS = MarketCalendar("XNYS").sessions_in_range(date(2023, 1, 3), date(2024, 2, 29))
LAST, END = SESS[-1], date(2024, 3, 1)
IDS = {"ZZA": 900001, "ZZB": 900002, "ZZC": 900003}
SID = {k: f"SHARADAR:PERMATICKER:{p}" for k, p in IDS.items()}


def _build(tmp_path, *, vol=None, skip=None, extra=()):
    vol = {"ZZA": 2_000_000, "ZZB": 2_000_000, "ZZC": 2_000_000, **(vol or {})}
    skip = skip or {}
    t, a, s = tmp_path / "T.csv", tmp_path / "A.csv", tmp_path / "S.csv"
    t.write_text(T_HEAD + "".join(f"SEP,{p},{k},n,NYSE,N,X,,\n" for k, p in IDS.items())
        + "".join(f"SEP,{p},{k},n,NYSE,N,X,,\n" for k, p in extra))
    a.write_text(A_HEAD)
    s.write_text(S_HEAD + "".join(
        f"{k},{d},10,10,10,10,{vol[k]},10,10,{d}\n"
        for k in IDS for d in SESS if d not in skip.get(k, ())))
    art = compile_identity_artifact(t, a)
    ident = tmp_path / "ident.json"
    ident.write_bytes(art.body)
    store = DataStore(tmp_path / "data")
    prep = prepare_bars(s, t, a, ident, as_of="2024-03-02T00:00:00+00:00", store=store)
    return store, ident, prep, art


def _evidence(tmp_path, ident, prep, *, absent=None, cert_from="2023-01-01", omit=None,
              currency="USD", cert_known="2023-01-01", extra=()):
    absent = absent or {}
    start = {"known_from": "2023-01-01", "end_exclusive": None}
    secs = [{
        "stable_key": f"sharadar:permaticker:{p}",
        "episodes": [{"start": "2023-01-03", **start}],
        "listing_status_certified": [{"start": cert_from, **start, "known_from": cert_known}],
        "eligibility": [{"start": "2023-01-01", **start, "issuer_domicile": "US",
                         "venue": "XNYS", "instrument": "ordinary_common_stock",
                         "currency": currency}],
        "certified_absent_sessions": [str(d) for d in absent.get(k, ())]}
        for k, p in [*IDS.items(), *extra] if k != omit]
    doc = {"schema": "algua.sharadar.eligibility_evidence.v1",
           "identity_artifact_sha256": hashlib.sha256(ident.read_bytes()).hexdigest(),
           "bars_content_hash": prep.content_hash, "rules_sha256": FROZEN_RULES_SHA256,
           "inventory": {"complete_from": "2023-01-01",
                         "complete_through_exclusive": "2024-12-31"},
           "securities": secs}
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(doc))
    return p


def _run(store, ident, prep, ev):
    return compute_universe_preview(store=store, snapshot_id=prep.snapshot_id, identities=ident,
                                    rules=RULES, evidence=ev, start=LAST, end=END, out=None,
                                    repo_root=ROOT)


def _members(result):
    return {i["symbol"] for i in json.loads(result.body)["intervals"]}


def test_stage1_binds_hashes_and_stable_ids(tmp_path):
    store, _, prep, art = _build(tmp_path)
    assert (prep.tickers_sha256, prep.actions_sha256) == (art.tickers_sha256, art.actions_sha256)
    assert set(store.read_bars(prep.snapshot_id)["symbol"]) == set(SID.values())
    meta = store.get_snapshot(prep.snapshot_id).metadata.source_metadata
    assert meta["stable_id_transform"] == "upper(sharadar:permaticker:N)"
    assert "verified_pit" not in json.dumps(meta)


def test_stage1_refuses_inputs_not_matching_compiler_hashes(tmp_path):
    store, ident, _, _ = _build(tmp_path)
    (tmp_path / "A.csv").write_text(A_HEAD + "\n")
    with pytest.raises(IdentityCompileError):
        prepare_bars(tmp_path / "S.csv", tmp_path / "T.csv", tmp_path / "A.csv", ident,
                     as_of="2024-03-02T00:00:00+00:00", store=store)


def test_exact_boundary_selected_and_output_unqualified(tmp_path):
    store, ident, prep, _ = _build(tmp_path)  # 10 * 2,000,000 == 20,000,000 exactly
    r = _run(store, ident, prep, _evidence(tmp_path, ident, prep))
    doc = json.loads(r.body)
    assert doc["verified_pit"] is False and doc["qualified"] is False
    assert doc["evidence_status"] == "declared_input_unverified"
    assert _members(r) == set(SID.values()) and r.refused_dates == 0


def test_just_below_liquidity_excluded(tmp_path):
    store, ident, prep, _ = _build(tmp_path, vol={"ZZB": 1_999_999})
    r = _run(store, ident, prep, _evidence(tmp_path, ident, prep))
    assert _members(r) == {SID["ZZA"], SID["ZZC"]}


def test_certified_absence_in_window_excludes(tmp_path):
    gap = SESS[-5]
    store, ident, prep, _ = _build(tmp_path, skip={"ZZB": {gap}})
    r = _run(store, ident, prep, _evidence(tmp_path, ident, prep, absent={"ZZB": [gap]}))
    assert _members(r) == {SID["ZZA"], SID["ZZC"]}


def test_uncertified_missing_bar_refuses_date(tmp_path):
    store, ident, prep, _ = _build(tmp_path, skip={"ZZB": {SESS[-5]}})
    with pytest.raises(IdentityCompileError):  # sole date refused: nothing exported
        _run(store, ident, prep, _evidence(tmp_path, ident, prep))


def test_history_lower_bound_passes_with_unknown_older_prefix(tmp_path):  # case (a)
    store, ident, prep, _ = _build(tmp_path, skip={"ZZC": set(SESS[:20])})
    r = _run(store, ident, prep, _evidence(tmp_path, ident, prep))  # 271 >= 252 counted
    assert SID["ZZC"] in _members(r)


def test_short_history_with_unknown_prefix_refuses_never_excludes(tmp_path):  # case (b)
    store, ident, prep, _ = _build(tmp_path, skip={"ZZC": set(SESS[:60])})  # 231 counted
    with pytest.raises(IdentityCompileError):
        _run(store, ident, prep, _evidence(tmp_path, ident, prep))


def test_short_history_with_fully_accounted_prefix_is_excluded(tmp_path):  # case (c)
    pre = set(SESS[:60])
    store, ident, prep, _ = _build(tmp_path, skip={"ZZC": pre})
    r = _run(store, ident, prep, _evidence(tmp_path, ident, prep, absent={"ZZC": sorted(pre)}))
    assert _members(r) == {SID["ZZA"], SID["ZZB"]}


def test_missing_episode_without_listing_certification_is_unknown(tmp_path):
    store, ident, prep, _ = _build(tmp_path)
    ev = _evidence(tmp_path, ident, prep, omit="ZZC")  # no entry at all -> unknown, not excluded
    with pytest.raises(IdentityCompileError):
        _run(store, ident, prep, ev)


def test_known_exclusion_non_usd_yields_empty_computed_date(tmp_path):
    store, ident, prep, _ = _build(tmp_path)
    r = _run(store, ident, prep, _evidence(tmp_path, ident, prep, currency="CAD"))
    assert r.computed_dates == 1 and _members(r) == set()


def test_evidence_must_bind_bars_hash(tmp_path):
    store, ident, prep, _ = _build(tmp_path)
    ev = _evidence(tmp_path, ident, prep)
    doc = json.loads(ev.read_text())
    doc["bars_content_hash"] = "0" * 64
    ev.write_text(json.dumps(doc))
    with pytest.raises(IdentityCompileError):
        _run(store, ident, prep, ev)


def test_identity_without_bars_omitted_from_evidence_refuses(tmp_path):
    extra = [("ZZD", 900004)]  # in the artifact, no SEP rows at all
    store, ident, prep, _ = _build(tmp_path, extra=extra)
    with pytest.raises(IdentityCompileError):
        _run(store, ident, prep, _evidence(tmp_path, ident, prep))  # evidence lacks ZZD
    ok = _evidence(tmp_path, ident, prep, extra=extra)
    doc = json.loads(ok.read_text())
    doc["securities"][-1]["episodes"] = []  # certified not listed in the window
    ok.write_text(json.dumps(doc))
    assert _members(_run(store, ident, prep, ok)) == set(SID.values())


def test_listing_certification_not_yet_known_is_unknown(tmp_path):
    store, ident, prep, _ = _build(tmp_path, extra=[("ZZD", 900004)])
    ev = _evidence(tmp_path, ident, prep, extra=[("ZZD", 900004)])
    doc = json.loads(ev.read_text())
    doc["securities"][-1]["episodes"] = []
    doc["securities"][-1]["listing_status_certified"][0]["known_from"] = "2030-01-01"
    ev.write_text(json.dumps(doc))
    with pytest.raises(IdentityCompileError):  # not known by t: unknown listing status
        _run(store, ident, prep, ev)
