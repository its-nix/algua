import json
import os
import stat
from pathlib import Path

import pytest

from algua.data.sharadar_identity import (
    IdentityCompileError,
    compile_identity_artifact,
    write_private_new,
)

T_HEAD = "table,permaticker,ticker,name,exchange,isdelisted,category,firstpricedate,lastpricedate\n"
A_HEAD = "date,action,ticker,name,value,contraticker,contraname\n"
TICKERS = (T_HEAD + "SEP,900001,ZZNEW,ZZ One,NYSE,N,X,2020-01-02,2020-01-10\n"
                    "SEP,900002,ZZTWO,ZZ Two,NYSE,N,X,2020-01-02,2020-01-10\n"
                    "SF1,900001,ZZNEW,ZZ One,NYSE,N,X,,\n")


def _pair(date, ticker, old, new):
    return (f"{date},tickerchangefrom,{ticker},n,,{old},\n"
            f"{date},tickerchangeto,{ticker},n,,{new},\n")


def _files(tmp_path, tickers=TICKERS, actions=""):
    t, a = tmp_path / "T.csv", tmp_path / "A.csv"
    t.write_text(tickers)
    a.write_text(A_HEAD + actions)
    return t, a


def _doc(art):
    return json.loads(art.body)


def test_compiles_identities_and_pair_without_inference(tmp_path):
    t, a = _files(tmp_path, actions=_pair("2020-01-06", "ZZNEW", "ZZOLD", "ZZMID")
                  + "2020-01-07,split,ZZTWO,n,2,,\n")
    art = compile_identity_artifact(t, a)
    doc = _doc(art)
    assert (art.identity_count, art.event_count) == (2, 1)
    assert doc["identities"][0] == {"stable_key": "sharadar:permaticker:900001",
                                    "permaticker": 900001, "current_storage_ticker": "ZZNEW"}
    # current ticker (ZZNEW) differs from the event's new symbol (ZZMID): kept as given
    assert doc["ticker_change_events"] == [{"stable_key": "sharadar:permaticker:900001",
        "effective_date": "2020-01-06", "from_ticker": "ZZOLD", "to_ticker": "ZZMID"}]
    assert doc["coverage"] == doc["completeness"] == "unverified"
    assert "verified_pit" not in art.body.decode()
    assert not {"first", "last", "intervals", "alias"} & {k.lower() for k in doc}
    assert doc["inputs"]["tickers_sha256"] == art.tickers_sha256


def test_multi_rename_chain_may_end_off_current_ticker(tmp_path):
    acts = (_pair("2021-03-01", "ZZNEW", "ZZB", "ZZC") + _pair("2020-01-06", "ZZNEW", "ZZA", "ZZB"))
    t, a = _files(tmp_path, actions=acts)
    evs = _doc(compile_identity_artifact(t, a))["ticker_change_events"]
    assert [(e["effective_date"], e["from_ticker"], e["to_ticker"]) for e in evs] == [
        ("2020-01-06", "ZZA", "ZZB"), ("2021-03-01", "ZZB", "ZZC")]


def test_deterministic_and_inputs_unchanged(tmp_path):
    t, a = _files(tmp_path, actions=_pair("2020-01-06", "ZZNEW", "ZZA", "ZZB"))
    before = (t.read_bytes(), a.read_bytes())
    assert compile_identity_artifact(t, a).body == compile_identity_artifact(t, a).body
    assert (t.read_bytes(), a.read_bytes()) == before


@pytest.mark.parametrize("actions,why", [
    ("2020-01-06,tickerchangefrom,ZZNEW,n,,ZZA,\n", "unpaired"),
    ("2020-01-06,tickerchangeto,ZZNEW,n,,ZZA,\n", "unpaired"),
    (_pair("2020-01-06", "ZZNEW", "ZZA", "ZZA"), "self"),
    (_pair("2020-01-06", "ZZGONE", "ZZA", "ZZB"), "unmapped"),
    (_pair("2020-01-06", "ZZNEW", "ZZA", "ZZB") * 2, "duplicate"),
    ("2020-01-06,tickerchangefrom,ZZNEW,n,,,\n2020-01-06,tickerchangeto,ZZNEW,n,,ZZB,\n",
     "missing contra"),
    (_pair("2020-01-06", "ZZNEW", "ZZA", "ZZB") + _pair("2020-02-06", "ZZNEW", "ZZQ", "ZZC"),
     "contradictory chain"),
    # same dated pair on two events with different content for one ticker/date
    (_pair("2020-01-06", "ZZNEW", "ZZA", "ZZB") + _pair("2020-01-06", "ZZNEW", "ZZB", "ZZC"),
     "same-date conflict"),
])
def test_malformed_or_contradictory_events_refuse(tmp_path, actions, why):
    t, a = _files(tmp_path, actions=actions)
    with pytest.raises(IdentityCompileError):
        compile_identity_artifact(t, a)


@pytest.mark.parametrize("rows", [
    "SEP,900001,ZZNEW,A,NYSE,N,X,,\nSEP,900002,ZZNEW,B,NYSE,N,X,,\n",   # reused/ambiguous ticker
    "SEP,900001,ZZNEW,A,NYSE,N,X,,\nSEP,900001,ZZOTH,A,NYSE,N,X,,\n",   # duplicate permaticker
    "SEP,0,ZZNEW,A,NYSE,N,X,,\n",                                        # non-positive
    "SEP,-5,ZZNEW,A,NYSE,N,X,,\n",
    "SEP,900001,,A,NYSE,N,X,,\n",                                        # empty ticker
    "SEP,abc,ZZNEW,A,NYSE,N,X,,\n",                                      # malformed
    "SF1,900001,ZZNEW,A,NYSE,N,X,,\n",                                   # no SEP identities
])
def test_bad_identities_refuse(tmp_path, rows):
    t, a = _files(tmp_path, tickers=T_HEAD + rows)
    with pytest.raises(IdentityCompileError):
        compile_identity_artifact(t, a)


def test_reader_errors_do_not_leak_vendor_text(tmp_path):
    t, a = _files(tmp_path, actions="SECRETDATE,tickerchangefrom,ZZSECRET,n,,ZZA,\n")
    with pytest.raises(IdentityCompileError) as exc:
        compile_identity_artifact(t, a)
    assert "SECRET" not in str(exc.value)


def test_write_private_new_modes_no_overwrite_no_symlink(tmp_path):
    root = Path("/nonexistent-repo-root")
    out = tmp_path / "newdir" / "sub" / "id.json"
    got = write_private_new(out, b"{}", repo_root=root)
    assert stat.S_IMODE(got.stat().st_mode) == 0o600
    assert stat.S_IMODE(got.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(got.parent.parent.stat().st_mode) == 0o700
    assert not [p for p in got.parent.iterdir() if p != got]
    with pytest.raises(IdentityCompileError):
        write_private_new(out, b"other", repo_root=root)
    assert got.read_bytes() == b"{}"
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "link.json"
    os.symlink(victim, link)
    with pytest.raises(IdentityCompileError):
        write_private_new(link, b"x", repo_root=root)
    dangling = tmp_path / "dangling.json"
    os.symlink(tmp_path / "nowhere", dangling)
    with pytest.raises(IdentityCompileError):
        write_private_new(dangling, b"x", repo_root=root)
    assert victim.read_text() == "keep" and not (tmp_path / "nowhere").exists()


def test_write_refuses_inside_repo(tmp_path):
    with pytest.raises(IdentityCompileError):
        write_private_new(tmp_path / "x" / "o.json", b"{}", repo_root=tmp_path)
    assert not (tmp_path / "x").exists()


def test_cli_stdout_has_only_safe_summary(tmp_path):
    from typer.testing import CliRunner

    from algua.cli.main import app
    t, a = _files(tmp_path, actions=_pair("2020-01-06", "ZZNEW", "ZZOLD", "ZZMID"))
    out = tmp_path / "priv" / "ids.json"
    res = CliRunner().invoke(app, ["data", "sharadar", "compile-identities", "--tickers", str(t),
                                   "--actions", str(a), "--out", str(out)])
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert payload["ok"] and payload["identity_count"] == 2 and payload["event_count"] == 1
    for leak in ("ZZ", "9000", "2020-01"):
        assert leak not in res.stdout.replace(str(tmp_path), "")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    again = CliRunner().invoke(app, ["data", "sharadar", "compile-identities", "--tickers",
                                     str(t), "--actions", str(a), "--out", str(out)])
    assert again.exit_code == 1 and json.loads(again.stdout)["ok"] is False
    (tmp_path / "b").mkdir()
    bad = _files(tmp_path / "b", tickers=T_HEAD + "SEP,1,ZZLEAK,A,NYSE,maybe,X,,\n")
    res = CliRunner().invoke(app, ["data", "sharadar", "compile-identities", "--tickers",
        str(bad[0]), "--actions", str(bad[1]), "--out", str(tmp_path / "o2.json")])
    assert res.exit_code == 1 and "ZZLEAK" not in res.stdout
    assert not (tmp_path / "o2.json").exists()
