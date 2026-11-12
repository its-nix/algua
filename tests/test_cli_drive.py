"""CLI surface of the Drive ideation backend: steering, inbox intake, idea publish."""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.knowledge.drive import tables
from tests._drive_fake import FakeDrive

runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("ALGUA_KNOWLEDGE_DIR", str(tmp_path / "kb"))
    monkeypatch.setenv("ALGUA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ALGUA_DB_PATH", str(tmp_path / "data" / "algua.db"))
    monkeypatch.delenv("ALGUA_DRIVE_FOLDER_ID", raising=False)
    yield


@pytest.fixture
def drive(monkeypatch):
    fake = FakeDrive()
    fake.seed(*tables.CATEGORIES, tables.CATEGORY_HEADER, [{"slug": "momentum"}])
    monkeypatch.setenv("ALGUA_DRIVE_FOLDER_ID", "F")
    monkeypatch.setattr(tables, "client_for", lambda _s: fake)
    return fake


def _json(r):
    return json.loads(r.output)


def test_cli_export_disabled_without_folder(tmp_path):
    r = runner.invoke(app, ["research", "steering", "export", "--to", str(tmp_path / "s")])
    assert r.exit_code == 1
    assert _json(r) == {"ok": False, "error": "drive_disabled", "code": "drive_disabled"}


def test_cli_export_writes_snapshot(tmp_path, drive):
    r = runner.invoke(app, ["research", "steering", "export", "--to", str(tmp_path / "s")])
    assert r.exit_code == 0, r.output
    assert _json(r)["categories"] == 1
    assert (tmp_path / "s" / "categories.txt").exists()


def test_cli_drive_error_is_a_json_envelope(tmp_path, drive):
    drive.fail["read_tab"] = 1
    r = runner.invoke(app, ["research", "steering", "export", "--to", str(tmp_path / "s")])
    assert r.exit_code == 1
    body = _json(r)
    assert body["ok"] is False and body["error"] == "drive_unavailable"


def test_cli_inbox_intake(drive):
    drive.seed(*tables.INBOX, tables.INBOX_HEADER, [{"idea": "buy quiet small caps",
                                                     "category": "momentum"}])
    r = runner.invoke(app, ["research", "inbox", "intake"])
    assert r.exit_code == 0, r.output
    body = _json(r)
    assert body["ok"] is True and len(body["taken"]) == 1
    assert drive.rows(*tables.INSPIRATIONS)[0]["category"] == "momentum"
