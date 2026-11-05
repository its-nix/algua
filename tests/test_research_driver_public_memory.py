"""Execute actual Bash parser/claim branches without a research worker or model call."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

import pytest

from tests import test_research_driver_campaign_choice as driver
from tests.test_research_driver_campaign_choice import driver_pool as driver_pool


@pytest.mark.parametrize("args,expected", [
    (["--choose-campaign"], "1 1"),
    (["--campaign", "fixture.json"], "1 1"),
    (["--choose-campaign", "--no-public-memory-context"], "0 0"),
    ([], "0 0"),
])
def test_campaign_defaults_forward_memory_and_keep_explicit_optout(tmp_path, args, expected):
    source = driver.DRIVER.read_text()
    parser = source[source.index("while [[ $#"):source.index("\nREPO_ROOT=")]
    command = driver._preamble(tmp_path, PUBLIC_MEMORY_CONTEXT="0",
        RESEARCH_PUBLIC_MEMORY_CONTEXT="0") + "set -- " + shlex.join(args) + "\n" + parser
    command += '\nprintf "%s %s" "$PUBLIC_MEMORY_CONTEXT" "$RESEARCH_PUBLIC_MEMORY_CONTEXT"'
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected


def _start(tmp_path, monkeypatch, *args):
    # Substitute only the chooser child, letting the new fixed memory reader use real Popen.
    fixture = driver.FIXTURE_CLI.replace(
        "class FixtureChild:\n",
        "original_popen = campaign_choice.subprocess.Popen\n"
        "original_killpg = campaign_choice.os.killpg\n\n"
        "class FixtureChild:\n"
        "    def __new__(cls, command, **kwargs):\n"
        "        if '--workdir' not in command:\n"
        "            return original_popen(command, **kwargs)\n"
        "        return super().__new__(cls)\n")
    fixture = fixture.replace(
        "campaign_choice.os.killpg = lambda *args: None",
        "campaign_choice.os.killpg = lambda pid, sig: (\n"
        "    None if pid == 1 else original_killpg(pid, sig))")
    monkeypatch.setattr(driver, "FIXTURE_CLI", fixture)
    return driver._driver_start(
        tmp_path, *args, without_memory=False, REPO_ROOT=str(driver.ROOT),
        PYTHON=sys.executable, PUBLIC_MEMORY_CONTEXT="0",
        AUTH_TRACKING_BACKEND="mlflow-sqlite",
        AUTH_TRACKING_URI=f"sqlite:///{tmp_path / 'authority-tracking.db'}")


def test_driver_rejects_memory_without_campaign_before_any_call(
        driver_pool, tmp_path, monkeypatch):
    result = _start(tmp_path, monkeypatch, "--public-memory-context")
    assert result.returncode == 2
    assert "requires --choose-campaign or --campaign" in result.stderr
    assert not driver._calls(tmp_path)
    assert driver_pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0


def test_driver_forwards_opt_in_with_trusted_tracking_configuration(
        driver_pool, tmp_path, monkeypatch):
    monkeypatch.setenv("ALGUA_TRACKING_BACKEND", "noop")
    monkeypatch.setenv("ALGUA_MLFLOW_TRACKING_URI", "unsupported://worker-routing")
    result = _start(tmp_path, monkeypatch, "--choose-campaign", "--public-memory-context")
    marker, claimed = driver._started(result)
    assert marker and [idea["id"] for idea in claimed] == [3]
    calls = driver._calls(tmp_path)
    assert len(calls) == 1
    snapshot = calls[0]["menu"]["request"]["context"]["public_research_memory"]
    assert snapshot["status"] == "unavailable" and snapshot["authority"] == "none"
    assert not (tmp_path / "authority-tracking.db").exists()


def test_dry_run_memory_campaign_performs_no_claim_archive_or_model_call(tmp_path):
    source = driver.DRIVER.read_text()
    parser = source[source.index("while [[ $#"):source.index("\nREPO_ROOT=")]
    start = source.index('if [[ "${DRY_RUN}" -eq 1 ]]; then\n  echo "would claim')
    end = source.index("\n# Everything the agent reads/writes", start)
    marker = tmp_path / "must-not-call"
    forbidden = tmp_path / "forbidden-cli"
    forbidden.write_text("#!/bin/sh\nprintf called > " + shlex.quote(str(marker)) + "\nexit 99\n")
    forbidden.chmod(0o700)
    preamble = driver._preamble(tmp_path, DRY_RUN="0", PUBLIC_MEMORY_CONTEXT="0")
    command = (preamble + f"AUTH_CLI=({shlex.quote(str(forbidden))})\n"
               + "set -- --choose-campaign --public-memory-context --dry-run\n"
               + parser + source[start:end])
    command = command.replace("python3 -c", shlex.quote(sys.executable) + " -c")
    result = subprocess.run(["bash", "-c", command], cwd=driver.ROOT, env=os.environ.copy(),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith("would claim 3 ideas from ")
    assert not marker.exists() and not (tmp_path / "data").exists()


def test_legacy_driver_preserves_menu_without_memory_work(driver_pool, tmp_path, monkeypatch):
    result = _start(tmp_path, monkeypatch, "--choose-campaign", "--no-public-memory-context")
    _, claimed = driver._started(result)
    assert [idea["id"] for idea in claimed] == [3]
    assert "public_research_memory" not in driver._calls(tmp_path)[0]["menu"]["request"]["context"]
    assert not (tmp_path / "authority-tracking.db").exists()


def test_campaign_default_admits_and_decodes_memory_without_extra_flags(
    driver_pool, tmp_path, monkeypatch,
):
    result = _start(tmp_path, monkeypatch, "--choose-campaign")
    _, claimed = driver._started(result)
    assert [idea["id"] for idea in claimed] == [3]
    snapshot = driver._calls(tmp_path)[0]["menu"]["request"]["context"]["public_research_memory"]
    assert snapshot["selection_protocol"] == "recent_completed_attempts_desc/v1"


def test_empty_default_campaign_admits_without_chooser_or_prompt_decode(
    driver_pool, tmp_path, monkeypatch,
):
    result = _start(tmp_path, monkeypatch, "--choose-campaign", "--category", "empty-category")
    marker, claimed = driver._started(result)
    assert marker == "campaign" and claimed == []
    assert driver._calls(tmp_path) == []
    assert driver_pool.execute("SELECT COUNT(*) FROM idea_attempts").fetchone()[0] == 0
