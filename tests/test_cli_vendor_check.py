import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import algua
from algua.cli.main import app
from tests._sharadar_fixtures import sample_tables, write_csvs, write_tables

runner = CliRunner()
REPO_ROOT = Path(algua.__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _tmp_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))


def _invoke(paths, out, *extra):
    return runner.invoke(app, [
        "data", "vendor-check", "--vendor", "sharadar",
        "--sep", str(paths["sep"]), "--actions", str(paths["actions"]),
        "--tickers", str(paths["tickers"]), "--report-out", str(out), *extra])


def test_vendor_check_passes_and_writes_private_report(tmp_path):
    paths = write_csvs(tmp_path / "in")
    out = tmp_path / "private" / "report.json"
    res = _invoke(paths, out)
    assert res.exit_code == 0, res.stdout
    body = json.loads(res.stdout)
    assert body["ok"] is True and body["passed"] is True and body["vendor"] == "sharadar"
    assert body["report_out"] == str(out.resolve())
    full = json.loads(out.read_text())
    assert full["passed"] is True and "findings" in full["checks"][0]
    assert oct(out.stat().st_mode & 0o777) == "0o600"


def test_vendor_check_failing_sample_exits_1(tmp_path):
    sep, actions, tickers = sample_tables()
    actions = actions[actions["action"] != "bankruptcyliquidation"]
    paths = write_tables(tmp_path / "in", sep, actions, tickers)
    out = tmp_path / "report.json"
    res = _invoke(paths, out)
    assert res.exit_code == 1
    assert json.loads(res.stdout)["passed"] is False
    assert out.exists()


def test_vendor_check_with_previous_sep_reports_revisions(tmp_path):
    paths = write_csvs(tmp_path / "in")
    res = _invoke(paths, tmp_path / "r.json", "--previous-sep", str(paths["sep"]))
    assert res.exit_code == 0, res.stdout
    assert json.loads(res.stdout)["checks"][-1]["name"] == "revisions"


def test_report_out_inside_repo_refused(tmp_path):
    paths = write_csvs(tmp_path / "in")
    out = REPO_ROOT / "vendor-check-report.json"
    res = _invoke(paths, out)
    assert res.exit_code == 1
    assert "outside the repository" in json.loads(res.stdout)["error"]
    assert not out.exists()


def test_report_out_existing_refused(tmp_path):
    paths = write_csvs(tmp_path / "in")
    out = tmp_path / "report.json"
    out.write_text("keep me")
    res = _invoke(paths, out)
    assert res.exit_code == 1
    assert "already exists" in json.loads(res.stdout)["error"]
    assert out.read_text() == "keep me"


def test_unknown_vendor_refused(tmp_path):
    paths = write_csvs(tmp_path / "in")
    res = runner.invoke(app, [
        "data", "vendor-check", "--vendor", "acme",
        "--sep", str(paths["sep"]), "--actions", str(paths["actions"]),
        "--tickers", str(paths["tickers"]), "--report-out", str(tmp_path / "r.json")])
    assert res.exit_code == 1
    assert not (tmp_path / "r.json").exists()


def test_stdout_contains_no_input_prices(tmp_path):
    paths = write_csvs(tmp_path / "in")
    sep, _, _ = sample_tables()
    # Make the adjusted check produce findings (which carry values) to prove they stay private.
    sep_bad = sep.copy()
    sep_bad.loc[0, "closeadj"] = 123.456
    paths = write_tables(tmp_path / "bad", sep_bad, *sample_tables()[1:])
    res = _invoke(paths, tmp_path / "r.json")
    assert res.exit_code == 0, res.stdout
    values = set(sep_bad[["close", "closeunadj", "closeadj"]].to_numpy().ravel())
    for v in values:
        assert repr(float(v)) not in res.stdout
    full = json.loads((tmp_path / "r.json").read_text())
    adjusted = next(c for c in full["checks"] if c["name"] == "adjusted_close")
    assert adjusted["findings"] and "findings" not in res.stdout
