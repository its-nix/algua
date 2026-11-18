import csv
import hashlib
import io
import json
import os
import stat
from pathlib import Path

import pytest

import algua
from algua.data.importers.sharadar_tables import TICKERS_COLUMNS, read_tickers
from algua.data.sharadar_metadata import (
    SCHEMA,
    MetadataPrepareError,
    prepare_metadata,
    publish_metadata,
)

HEAD = (
    "table,permaticker,ticker,name,exchange,isdelisted,category,firstpricedate,"
    "lastpricedate,currency,siccode\n"
)
MIXED = (
    HEAD
    + "SEP,900001,zza,NA,NYSE,N,Domestic,2020-01-02,2020-01-10,USD,3674\n"
    + "SF1,900001,zza,NA,NYSE,N,Domestic,,,NULL,\n"
    + "sep,900009,zza,Other,NASDAQ,Y,ADR,2020-01-02,,NA, \n"
    + "SFP,900002,ZZB,Name,NYSE,N,X,2020-01-02,2020-01-03,USD,100\n"
)
OLD = (
    "table,permaticker,ticker,name,exchange,isdelisted,category,firstpricedate,"
    "lastpricedate\n"
    "SEP,1,ZZA,Name,NYSE,N,X,2020-01-02,2020-01-10\n"
)
OPTIONALS = (
    "currency",
    "location",
    "secfilings",
    "cusips",
    "figi",
    "relatedtickers",
    "lastupdated",
    "siccode",
    "sicsector",
    "sicindustry",
)


def _write(tmp_path: Path, text: str, name: str = "T.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _doc(art):
    return json.loads(art.body)


def test_sep_and_sf1_same_identity_stay_separate_rows(tmp_path):
    doc = _doc(prepare_metadata(_write(tmp_path, MIXED)))
    assert doc["row_count"] == 4
    assert [row["table"] for row in doc["rows"]] == ["SEP", "SF1", "sep", "SFP"]
    sep, sf1 = doc["rows"][0], doc["rows"][1]
    assert sep["permaticker"] == sf1["permaticker"] == "900001"
    assert sep["ticker"] == sf1["ticker"] == "zza"
    assert sep["lastpricedate"] == "2020-01-10"
    assert sf1["lastpricedate"] is None and sf1["firstpricedate"] is None
    assert isinstance(sep["permaticker"], str)
    assert sep["isdelisted"] == "N" and doc["rows"][2]["isdelisted"] == "Y"
    assert doc["verified_pit"] is False
    assert doc["status"] == "unqualified"
    assert doc["coverage"] == doc["completeness"] == "unverified"
    assert not {"intervals", "membership", "aliases", "qualified"} & set(doc)


def test_raw_text_null_and_literal_sentinels_are_preserved(tmp_path):
    header = list(TICKERS_COLUMNS) + list(OPTIONALS)
    cells = [
        "SEP",
        " 900001 ",
        "  zza  ",
        "Café, Name\nstill",
        "NULL",
        "n",
        " Domestic ",
        "2020-01-02",
        "",
        " NA ",
        "null",
        "N/A",
        "None",
        "nan",
        "ZZOLD",
        "2020-01-03",
        "3674",
        " ",
        "Manufacturing",
    ]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerow(cells)
    doc = _doc(prepare_metadata(_write(tmp_path, buf.getvalue())))
    row = doc["rows"][0]
    assert row["permaticker"] == " 900001 "
    assert row["ticker"] == "  zza  "
    assert row["name"] == "Café, Name\nstill"
    assert row["exchange"] == "NULL"
    assert row["isdelisted"] == "n"
    assert row["category"] == " Domestic "
    assert row["lastpricedate"] is None
    assert row["currency"] == " NA "
    assert row["location"] == "null"
    assert row["secfilings"] == "N/A"
    assert row["cusips"] == "None"
    assert row["figi"] == "nan"
    assert row["relatedtickers"] == "ZZOLD"
    assert row["sicsector"] == " "
    assert row["sicindustry"] == "Manufacturing"
    assert all(isinstance(value, str) for value in row.values() if value is not None)
    assert set(row) == set(doc["source_columns"]) == set(header)


def test_old_export_missing_optionals_distinguishes_absent_from_null(tmp_path):
    doc = _doc(prepare_metadata(_write(tmp_path, OLD)))
    assert doc["source_columns"] == list(TICKERS_COLUMNS)
    assert set(doc["rows"][0]) == set(TICKERS_COLUMNS)
    for name in OPTIONALS:
        assert name not in doc["source_columns"]
        assert name not in doc["rows"][0]
    assert doc["rows"][0]["name"] == "Name"
    assert doc["verified_pit"] is False


def test_present_empty_optional_is_null_and_absent_optional_is_omitted(tmp_path):
    doc = _doc(prepare_metadata(_write(tmp_path, MIXED)))
    sf1 = doc["rows"][1]
    assert "currency" in doc["source_columns"] and "siccode" in doc["source_columns"]
    assert sf1["currency"] == "NULL"
    assert sf1["siccode"] is None
    assert "figi" not in doc["source_columns"] and "figi" not in sf1
    assert doc["rows"][2]["currency"] == "NA"
    assert doc["rows"][2]["siccode"] == " "


def test_digest_binds_exact_captured_bytes(tmp_path, monkeypatch):
    raw = MIXED.replace("\n", "\r\n").encode()
    path = tmp_path / "T.csv"
    path.write_bytes(raw)
    real_open = os.open
    opened: list[str] = []

    def tracking(target, *args, **kwargs):
        opened.append(os.fspath(target))
        return real_open(target, *args, **kwargs)

    monkeypatch.setattr("algua.data.sharadar_identity.os.open", tracking)
    monkeypatch.setattr(
        Path, "read_bytes", lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("reread"))
    )
    art = prepare_metadata(path)
    assert art.tickers_sha256 == hashlib.sha256(raw).hexdigest()
    assert art.artifact_sha256 == hashlib.sha256(art.body).hexdigest()
    assert _doc(art)["inputs"]["tickers_sha256"] == art.tickers_sha256
    assert opened.count(os.fspath(path)) == 1
    path.write_bytes(b"mutated")
    assert art.tickers_sha256 == hashlib.sha256(raw).hexdigest()
    assert _doc(art)["rows"][0]["ticker"] == "zza"


def test_leading_bom_is_not_part_of_the_first_header_but_is_in_the_hash(tmp_path):
    raw = b"\xef\xbb\xbf" + OLD.encode()
    path = tmp_path / "T.csv"
    path.write_bytes(raw)
    art = prepare_metadata(path)
    doc = _doc(art)
    assert art.tickers_sha256 == hashlib.sha256(raw).hexdigest()
    assert doc["source_columns"][0] == "table"
    assert doc["rows"][0]["table"] == "SEP"
    assert "\ufeff" not in art.body.decode()


@pytest.mark.parametrize(
    "payload,match",
    [
        ((HEAD + "SEP,1,ZZLEAK,Name,NYSE,N,X,2020-01-02\n").encode(), "malformed row"),
        (
            (HEAD + "SEP,1,ZZLEAK,Name,NYSE,N,X,2020-01-02,2020-01-10,EXTRA\n").encode(),
            "malformed row",
        ),
        ((HEAD + '"ZZLEAK').encode(), "malformed row"),
        ((HEAD + "\n").encode(), "malformed row"),
        (
            b"table,permaticker,ticker,SECRETHEAD,SECRETHEAD,name,exchange,isdelisted,category,"
            b"firstpricedate,lastpricedate\nSEP,1,ZZLEAK,a,b,Name,NYSE,N,X,2020-01-02,2020-01-10\n",
            "duplicate headers",
        ),
        (b"table,ticker\nSEP,ZZLEAK\n", "missing required columns"),
        (b"", "missing required columns"),
        (b"\xff\xfeZZLEAK", "not valid UTF-8"),
    ],
)
def test_malformed_inputs_use_fixed_text(tmp_path, payload, match):
    path = tmp_path / "T.csv"
    path.write_bytes(payload)
    with pytest.raises(MetadataPrepareError, match=match) as exc:
        prepare_metadata(path)
    assert "ZZLEAK" not in str(exc.value)
    assert "SECRETHEAD" not in str(exc.value)


def test_row_and_size_limits_do_not_echo_cells(tmp_path, monkeypatch):
    path = _write(tmp_path, MIXED)
    monkeypatch.setattr("algua.data.sharadar_metadata.MAX_ROWS", 1)
    with pytest.raises(MetadataPrepareError, match="row limit") as exc:
        prepare_metadata(path)
    assert "zza" not in str(exc.value) and "900001" not in str(exc.value)
    monkeypatch.setattr("algua.data.sharadar_metadata.MAX_TICKERS_BYTES", 8)
    with pytest.raises(MetadataPrepareError, match="size limit") as exc:
        prepare_metadata(path)
    assert "zza" not in str(exc.value)


def test_symlink_input_is_refused_without_its_text(tmp_path):
    target = _write(tmp_path, MIXED.replace("zza", "ZZLEAK"), name="real.csv")
    link = tmp_path / "link.csv"
    os.symlink(target, link)
    with pytest.raises(MetadataPrepareError) as exc:
        prepare_metadata(link)
    assert "ZZLEAK" not in str(exc.value)


def test_unexpected_failure_is_fixed_text(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "algua.data.sharadar_metadata._parse_csv",
        lambda _data: (_ for _ in ()).throw(RuntimeError("ZZLEAK")),
    )
    with pytest.raises(MetadataPrepareError, match="preparation failed") as exc:
        prepare_metadata(_write(tmp_path, OLD))
    assert "ZZLEAK" not in str(exc.value)


def test_legacy_read_tickers_still_projects_sep_rows(tmp_path):
    path = _write(tmp_path, MIXED)
    frame = read_tickers(path)
    assert list(frame.columns) == list(TICKERS_COLUMNS)
    assert frame["table"].tolist() == ["SEP"]
    assert frame["ticker"].tolist() == ["ZZA"]
    assert frame["permaticker"].tolist() == [900001]
    assert frame["permaticker"].dtype == "int64"
    assert bool(frame["isdelisted"].iloc[0]) is False
    assert frame["name"].tolist() == ["NA"]
    prepared = _doc(prepare_metadata(path))
    assert [row["table"] for row in prepared["rows"]] == ["SEP", "SF1", "sep", "SFP"]
    assert prepared["rows"][0]["ticker"] == "zza"
    assert "currency" in prepared["source_columns"]
    assert "currency" not in frame.columns


def _layout(tmp_path):
    main = tmp_path / "main"
    admin = main / ".git" / "worktrees" / "wt"
    admin.mkdir(parents=True)
    other = tmp_path / "other-wt"
    other.mkdir()
    (other / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")
    (admin / "commondir").write_text("../..\n", encoding="utf-8")
    (admin / "gitdir").write_text(f"{other / '.git'}\n", encoding="utf-8")
    return main, admin, other


def _publish(out, root):
    return publish_metadata(out, b"{}", repo_root=root)


def test_output_refuses_every_linked_checkout_and_prefix_lookalikes(tmp_path):
    main, _admin, other = _layout(tmp_path)
    for blocked in (other / "out.json", main / "nested" / "out.json", main / "out.json"):
        with pytest.raises(MetadataPrepareError, match="outside the repository"):
            _publish(blocked, other)
        assert not blocked.exists()
    assert not (main / "nested").exists()
    out = _publish(tmp_path / "safe" / "out.json", other)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    _publish(tmp_path / "main-extra" / "out.json", other)
    with pytest.raises(MetadataPrepareError, match="already exists"):
        _publish(out, other)


def test_running_worktree_refuses_a_sibling_inside_the_main_repo():
    root = Path(algua.__file__).resolve().parents[1]
    with pytest.raises(MetadataPrepareError, match="outside the repository"):
        _publish(root / "out.json", root)
    assert not (root / "out.json").exists()


def test_git_pointer_spelled_through_an_alias_still_matches_by_inode(tmp_path):
    main, admin, other = _layout(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path)
    # pointers spell the checkouts through a symlink; the output uses the real path
    (other / ".git").write_text(f"gitdir: {alias / 'main' / '.git' / 'worktrees' / 'wt'}\n")
    (admin / "commondir").write_text(f"{alias / 'main' / '.git'}\n")
    (admin / "gitdir").write_text(f"{alias / 'other-wt' / '.git'}\n")
    for blocked in (main / "out.json", other / "out.json"):
        with pytest.raises(MetadataPrepareError, match="outside the repository"):
            _publish(blocked, other)
    # a symlinked output spelling is refused by the O_NOFOLLOW walk
    with pytest.raises(MetadataPrepareError, match="real directories"):
        _publish(alias / "main" / "out.json", other)
    assert not (main / "out.json").exists()


def test_case_variant_output_inside_a_checkout_is_refused(tmp_path):
    root = tmp_path / "Repo"
    root.mkdir()
    if not (tmp_path / "repo").exists():
        pytest.skip("case-sensitive filesystem")
    with pytest.raises(MetadataPrepareError, match="outside the repository"):
        _publish(tmp_path / "repo" / "sub" / "out.json", root)
    assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    "breakage",
    [
        "git_symlink",
        "commondir_symlink",
        "worktrees_symlink",
        "entry_unreadable",
        "entry_missing_gitdir",
        "commondir_binary",
        "gitdir_symlink",
        "git_fifo",
    ],
)
def test_malformed_git_layout_fails_closed_with_fixed_text(tmp_path, breakage):
    main, admin, other = _layout(tmp_path)
    decoy = tmp_path / "decoy"
    decoy.write_text("gitdir: /nowhere\n")
    if breakage == "git_symlink":
        (other / ".git").unlink()
        (other / ".git").symlink_to(decoy)
    elif breakage == "commondir_symlink":
        (admin / "commondir").unlink()
        (admin / "commondir").symlink_to(decoy)
    elif breakage == "worktrees_symlink":
        real = main / ".git" / "wt-real"
        (main / ".git" / "worktrees").rename(real)
        (main / ".git" / "worktrees").symlink_to(real)
        # the running root is main so worktrees is read directly
        other = main
    elif breakage == "entry_unreadable":
        (admin / "gitdir").chmod(0)
        if os.access(admin / "gitdir", os.R_OK):
            pytest.skip("permissions not enforced")
    elif breakage == "entry_missing_gitdir":
        (admin / "gitdir").unlink()
    elif breakage == "commondir_binary":
        (admin / "commondir").write_bytes(b"\xff\xfeSECRETCELL")
    elif breakage == "gitdir_symlink":
        (admin / "gitdir").unlink()
        (admin / "gitdir").symlink_to(decoy)
    elif breakage == "git_fifo":
        (other / ".git").unlink()
        os.mkfifo(other / ".git")
    out = tmp_path / "safe" / "out.json"
    with pytest.raises(MetadataPrepareError) as exc:
        _publish(out, other)
    assert "SECRET" not in str(exc.value) and "codec" not in str(exc.value)
    assert not out.exists()


def test_absent_git_entry_and_absent_worktrees_are_root_only(tmp_path):
    bare = tmp_path / "plain"
    bare.mkdir()
    _publish(tmp_path / "o1" / "out.json", bare)
    (bare / ".git").mkdir()
    _publish(tmp_path / "o2" / "out.json", bare)
    with pytest.raises(MetadataPrepareError, match="outside the repository"):
        _publish(bare / "out.json", bare)


def test_parent_swapped_after_discovery_cannot_redirect_the_write(tmp_path, monkeypatch):
    from algua.data import sharadar_metadata_paths as mod

    main, _admin, other = _layout(tmp_path)
    parent = tmp_path / "stage"
    real = mod._discover

    def swap(*args, **kwargs):
        ids = real(*args, **kwargs)
        parent.mkdir()
        parent.rmdir()
        parent.symlink_to(main)
        return ids

    monkeypatch.setattr(mod, "_discover", swap)
    with pytest.raises(MetadataPrepareError, match="real directories"):
        _publish(parent / "out.json", other)
    assert not (main / "out.json").exists()


def _cli():
    """Import the app. This interpreter's CPython build has no ``os.waitid``; the command
    under test does not use it, so a missing symbol is stubbed only to let the import finish."""
    if not hasattr(os, "waitid"):
        os.waitid = lambda *_args, **_kwargs: None
    from typer.testing import CliRunner

    from algua.cli.main import app

    return CliRunner(), app


def test_csv_field_overflow_is_a_fixed_parse_error(tmp_path):
    limit = csv.field_size_limit()
    path = tmp_path / "T.csv"
    path.write_bytes((HEAD + '"ZZLEAK' + ("x" * 80)).encode())
    try:
        csv.field_size_limit(32)
        with pytest.raises(MetadataPrepareError, match="could not be parsed") as exc:
            prepare_metadata(path)
    finally:
        csv.field_size_limit(limit)
    assert "ZZLEAK" not in str(exc.value)


def test_cli_success_is_safe_json_and_private_output_does_not_overwrite(tmp_path):
    runner, app = _cli()
    src = _write(tmp_path, OLD.replace("Name", "ZZLEAK"))
    out = tmp_path / "priv" / "meta.json"
    args = ["data", "sharadar", "prepare-metadata", "--tickers", str(src), "--out", str(out)]
    res = runner.invoke(app, args)
    assert res.exit_code == 0, res.stdout
    payload = json.loads(res.stdout)
    assert set(payload) == {
        "ok",
        "schema",
        "status",
        "row_count",
        "tickers_sha256",
        "artifact_sha256",
        "artifact_path",
    }
    assert payload["ok"] is True
    assert payload["schema"] == SCHEMA
    assert payload["status"] == "unqualified"
    assert payload["row_count"] == 1
    assert payload["tickers_sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert payload["artifact_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert payload["artifact_path"] == os.path.abspath(out)
    assert "ZZLEAK" not in res.stdout
    assert "verified_pit" not in payload
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.parent.stat().st_mode) == 0o700
    doc = json.loads(out.read_bytes())
    assert doc["verified_pit"] is False and doc["rows"][0]["name"] == "ZZLEAK"
    first = out.read_bytes()
    again = runner.invoke(app, args)
    assert again.exit_code == 1
    assert json.loads(again.stdout)["ok"] is False
    assert "ZZLEAK" not in again.stdout
    assert out.read_bytes() == first


def test_cli_parser_and_checkout_errors_are_json_and_write_nothing(tmp_path):
    runner, app = _cli()
    src = _write(tmp_path, HEAD + "SEP,1,ZZLEAK,Name,NYSE,N,X,2020-01-02\n")
    out = tmp_path / "meta.json"
    res = runner.invoke(
        app, ["data", "sharadar", "prepare-metadata", "--tickers", str(src), "--out", str(out)]
    )
    assert res.exit_code == 1
    body = json.loads(res.stdout)
    assert body["ok"] is False
    assert "ZZLEAK" not in res.stdout
    assert "Traceback" not in res.stdout
    assert not out.exists()
    root = Path(algua.__file__).resolve().parents[1]
    inside = root / ".tickers-metadata-test-output.json"
    try:
        refused = runner.invoke(
            app,
            [
                "data",
                "sharadar",
                "prepare-metadata",
                "--tickers",
                str(_write(tmp_path, OLD)),
                "--out",
                str(inside),
            ],
        )
        assert refused.exit_code == 1
        assert json.loads(refused.stdout)["ok"] is False
        assert not inside.exists()
    finally:
        inside.unlink(missing_ok=True)


def test_kernel_alias_to_checkout_descendant_is_refused_via_dotdot_chain(tmp_path, monkeypatch):
    main, _admin, other = _layout(tmp_path)
    nested = main / "nested"
    nested.mkdir()
    (tmp_path / "safe" / "alias").mkdir(parents=True)
    real_open = os.open

    def aliased(path, flags, *args, **kwargs):
        if path == "alias" and kwargs.get("dir_fd") is not None:
            return real_open(nested, flags)  # bind-mount-like: not a checkout, below one
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", aliased)
    with pytest.raises(MetadataPrepareError, match="outside the repository"):
        _publish(tmp_path / "safe" / "alias" / "new" / "out.json", other)
    assert list(nested.iterdir()) == []
    assert sorted(p.name for p in main.iterdir()) == [".git", "nested"]


def test_listed_worktree_whose_root_is_gone_refuses(tmp_path):
    _main, admin, other = _layout(tmp_path)
    (admin / "gitdir").write_text(f"{tmp_path / 'gone' / '.git'}\n", encoding="utf-8")
    out = tmp_path / "safe" / "out.json"
    with pytest.raises(MetadataPrepareError, match="outside every worktree"):
        _publish(out, other)
    assert not out.exists()


def test_cli_invalid_utf8_pointer_is_one_fixed_error(tmp_path, monkeypatch):
    runner, app = _cli()
    _main, admin, other = _layout(tmp_path)
    (admin / "commondir").write_bytes(b"\xff\xfeSECRETCELL")
    (other / "algua").mkdir()
    monkeypatch.setattr(algua, "__file__", str(other / "algua" / "__init__.py"))
    out = tmp_path / "safe" / "meta.json"
    res = runner.invoke(
        app,
        [
            "data",
            "sharadar",
            "prepare-metadata",
            "--tickers",
            str(_write(tmp_path, OLD)),
            "--out",
            str(out),
        ],
    )
    assert res.exit_code == 1
    body = json.loads(res.stdout)
    assert body["ok"] is False
    assert "could not confirm output is outside every worktree" in json.dumps(body)
    assert "SECRET" not in res.stdout and "codec" not in res.stdout and "utf" not in res.stdout
    assert not out.exists() and not out.parent.exists()


@pytest.mark.parametrize("which", ["gitdir", "common"])
def test_referenced_git_admin_dir_that_is_a_symlink_is_refused(tmp_path, which):
    main, admin, other = _layout(tmp_path)
    if which == "gitdir":
        link = tmp_path / "admin-link"
        link.symlink_to(admin)
        (other / ".git").write_text(f"gitdir: {link}\n", encoding="utf-8")
    else:
        link = tmp_path / "common-link"
        link.symlink_to(main / ".git")
        (admin / "commondir").write_text(f"{link}\n", encoding="utf-8")
    out = tmp_path / "safe" / "out.json"
    with pytest.raises(MetadataPrepareError, match="outside every worktree"):
        _publish(out, other)
    assert not out.exists() and not out.parent.exists()
