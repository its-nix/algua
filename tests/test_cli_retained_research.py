"""Public list -> verified show with actual temporary capture, without main strategy rows."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from algua.cli.main import main
from algua.contracts.idea import AttemptOutcome
from algua.registry.db import connect
from algua.registry.idea_attempts import IdeaAttemptsRepository
from algua.registry.store import SqliteStrategyRepository
from algua.tracking.research_archive import LocalResearchArchive
from tests.test_cli_research_memory import cli_memory as cli_memory


def invoke(capsys, *args):
    with pytest.raises(SystemExit) as stopped:
        main(["research", "memory", *args])
    return stopped.value.code, json.loads(capsys.readouterr().out)


def capture(cli_memory, capsys):
    authority, cycle, worker, source, _ = cli_memory
    code, _ = invoke(capsys, "seed", "--run", cycle.cycle_id, "--worker-root", str(worker))
    assert code == 0
    conn = connect(source)
    SqliteStrategyRepository(conn).record_run(
        "backtest", "synthetic-retained", config={"params": {"n": 3}},
        metrics={"total_return_is": -0.25})
    conn.close()
    code, payload = invoke(capsys, "capture", "--run", cycle.cycle_id, "--worker-root", str(worker),
                           "--worker-exit", "0", "--source-commit", "b" * 40)
    assert code == 0
    row = cycle.rows()[0]
    IdeaAttemptsRepository(authority).record_outcome(
        row["idea_id"], token=row["claim_token"], outcome=AttemptOutcome.INTEGRITY_FAIL,
        reason="synthetic qualification limit", evidence_ref=payload["receipt"]["reference"])
    return payload["receipt"]


def test_actual_main_list_and_show_after_prune_do_not_bootstrap_or_open_authority(
    cli_memory, monkeypatch, capsys,
):
    authority, cycle, worker, _, _ = cli_memory
    capture(cli_memory, capsys)
    assert SqliteStrategyRepository(authority).list_strategies() == []
    before = list(authority.iterdump())
    shutil.rmtree(worker)

    def forbidden(*args, **kwargs):
        raise AssertionError("read must not open/migrate authority")

    monkeypatch.setattr("algua.cli.research_memory_cmd.registry_conn", forbidden)
    original = LocalResearchArchive.__init__

    def existing_only(self, *args, **kwargs):
        assert kwargs.get("existing_only") is True
        original(self, *args, **kwargs)

    monkeypatch.setattr(LocalResearchArchive, "__init__", existing_only)
    code, index = invoke(capsys, "list", "--limit", "1")
    assert code == 0 and index["count"] == 1
    assert index["attempts"][0]["research_cycle_id"] == cycle.cycle_id
    code, detail = invoke(capsys, "show", "--run", cycle.cycle_id)
    assert code == 0, detail
    assert detail["authority"] == "none" and detail["evidence_mode"] == "UNVERIFIED_WORKER"
    assert detail["worker_exit"] == 0
    assert detail["evaluations"][0]["metrics"]["total_return_is"] == -0.25
    assert detail["evaluations"][0]["source_ref"].startswith(f"scratch:{cycle.cycle_id}:runs:")
    assert list(authority.iterdump()) == before


@pytest.mark.parametrize("args", [["list", "--limit", "0"], ["list", "--limit", "101"],
                                  ["show", "--run", "../escape"]])
def test_invalid_inputs_are_json_before_store_bootstrap(cli_memory, monkeypatch, capsys, args):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid input reached archive construction")

    monkeypatch.setattr(LocalResearchArchive, "__init__", forbidden)
    code, payload = invoke(capsys, *args)
    assert code != 0 and payload["ok"] is False


@pytest.mark.parametrize("fault", ["checkpoint", "malformed-checkpoint", "archive"])
def test_changed_checkpoint_or_archive_refuses_verified_detail(cli_memory, capsys, fault):
    _, cycle, _, _, tracking = cli_memory
    receipt = capture(cli_memory, capsys)
    if fault == "checkpoint":
        value = json.loads(cycle.path.read_text())
        value["request"]["database"] = "/different/authority.db"
        cycle.path.write_text(json.dumps(value))
    elif fault == "malformed-checkpoint":
        cycle.path.write_text('{"request":')
    else:
        archive = LocalResearchArchive(f"sqlite:///{tracking}")
        uri = archive.client.get_run(receipt["run_id"]).info.artifact_uri
        target = Path(unquote(urlsplit(uri).path)) / "public-evidence.json"
        target.write_bytes(b"corrupted")
    code, payload = invoke(capsys, "show", "--run", cycle.cycle_id)
    assert code != 0 and payload["ok"] is False
