"""Write safety of the Drive client (final review I1/I2/I3/I5): no duplicate rows from retries, a
renamed required header is an error, owner columns survive rewrites, and quota-friendly I/O."""
from __future__ import annotations

import json

import pytest

from algua.knowledge.drive import DriveError
from tests.test_drive_client import SHEET, FakeTransport, _client


class SheetSim:
    """A tiny in-memory Sheets/Drive server: one spreadsheet, real A1 writes."""

    def __init__(self, values: list[list[str]], *, files: int = 1):
        self.values = [list(r) for r in values]
        self.files = files
        self.ops: list[str] = []
        self.fail: dict[str, int] = {}  # op -> HTTP status returned once

    def __call__(self, method, url, body):
        if "drive/v3/files" in url:
            self.ops.append("find")
            return 200, {"files": [{"id": f"{SHEET}{i}", "name": "S"}
                                   for i in range(self.files)]}
        if url.endswith("fields=sheets.properties.title"):
            return 200, {"sheets": [{"properties": {"title": "t"}}]}
        op = ("append" if ":append" in url else "clear" if ":clear" in url
              else "update" if "values:batchUpdate" in url
              else "write" if method == "PUT" else "read")
        self.ops.append(op)
        if op in self.fail:
            return self.fail.pop(op), {"error": "x"}
        data = json.loads(body) if body else {}
        if op == "read":
            return 200, {"values": self.values}
        if op == "append":
            self.values += data["values"]
        elif op == "write":
            for i, row in enumerate(data["values"]):
                while len(self.values) <= i:
                    self.values.append([])
                self.values[i] = list(row)
        elif op == "update":
            for d in data["data"]:
                a1 = d["range"].split("!")[1]
                col, r = ord(a1[0]) - 65, int(a1[1:]) - 1
                row = self.values[r]
                while len(row) <= col:
                    row.append("")
                row[col] = d["values"][0][0]
        elif op == "clear":
            self.values = []
        return 200, {}


def _c(tmp_path, sim):
    return _client(tmp_path, FakeTransport(sim))


def test_append_is_not_retried_after_a_5xx(tmp_path):
    sim = SheetSim([["id"]])
    sim.fail["append"] = 503
    with pytest.raises(DriveError) as exc:
        _c(tmp_path, sim).append_rows("S", "t", [{"id": "a"}])
    assert exc.value.code == "drive_unavailable"
    assert sim.ops.count("append") == 1  # the server may have committed it: never send twice


def test_append_is_retried_after_a_429(tmp_path):
    sim = SheetSim([["id"]])
    sim.fail["append"] = 429  # a rate-limited request was not processed
    _c(tmp_path, sim).append_rows("S", "t", [{"id": "a"}])
    assert sim.values == [["id"], ["a"]]


def test_two_spreadsheets_with_one_name_is_a_schema_error(tmp_path):
    with pytest.raises(DriveError) as exc:
        _c(tmp_path, SheetSim([["id"]], files=2)).read_tab("S", "t", [])
    assert exc.value.code == "drive_schema" and "2 spreadsheets named 'S'" in str(exc.value)


def test_renamed_required_header_raises_instead_of_adding_a_column(tmp_path):
    sim = SheetSim([["id", "Idea"], ["r1", "buy dips"]])
    with pytest.raises(DriveError) as exc:
        _c(tmp_path, sim).ensure_header("S", "t", ["id", "idea", "status"],
                                        required=["id", "idea"])
    assert exc.value.code == "drive_schema" and "missing header idea" in str(exc.value)
    assert sim.values[0] == ["id", "Idea"]


def test_ensure_header_writes_empty_tab_and_adds_optional_columns(tmp_path):
    sim = SheetSim([])
    _c(tmp_path, sim).ensure_header("S", "t", ["id", "idea"], required=["id"])
    assert sim.values == [["id", "idea"]]
    sim2 = SheetSim([["id", "mine"]])
    _c(tmp_path, sim2).ensure_header("S", "t", ["id", "idea"], required=["id"])
    assert sim2.values[0] == ["id", "mine", "idea"]


def test_replace_tab_keeps_owner_columns_and_never_clears(tmp_path):
    sim = SheetSim([["key", "my notes", "kind"], ["a", "keep", "blog"], ["b", "x", "paper"]])
    _c(tmp_path, sim).replace_tab("S", "t", ["key", "kind"],
                                  [{"key": "a", "kind": "blog", "my notes": "keep"}])
    assert "clear" not in sim.ops
    assert sim.values == [["key", "my notes", "kind"], ["a", "keep", "blog"], ["", "", ""]]


def test_header_is_read_once_for_many_writes(tmp_path):
    sim = SheetSim([["id", "status"], ["a", ""], ["b", ""]])
    c = _c(tmp_path, sim)
    for i in range(5):
        c.append_rows("S", "t", [{"id": f"n{i}"}])
        c.update_cells("S", "t", 2, {"status": f"s{i}"})
    assert sim.ops.count("read") == 1


def test_429_backoff_outlasts_a_one_minute_quota_window():
    from algua.knowledge.drive import client as mod
    assert sum(mod._BACKOFF * 2 ** i for i in range(mod._ATTEMPTS - 1)) >= 60


def test_drive_secret_files_are_gitignored():
    """Review I6: the consent output and the OAuth client file must never be committed to this
    public repository, wherever an operator runs the consent script from."""
    import subprocess
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    for name in ("drive.json", "client_secret.json", "client_secret_123.apps.json",
                 "scripts/drive.json"):
        proc = subprocess.run(["git", "check-ignore", "-q", name], cwd=repo)
        assert proc.returncode == 0, f"{name} is not gitignored"
