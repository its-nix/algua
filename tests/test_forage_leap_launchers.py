"""Verification for the forage launcher (ideation engine spec 2026-09-08 §5) and the leap
launcher (§6): both are TRUSTED DRIVERS wrapping a sandboxed agent, and what these tests
pin is the privilege story (what the agent may reach) plus the driver's own authority-side step
list — the two things a refactor can silently weaken. Also carries the systemd units and the
sources-registry seed check for both stages.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FORAGE = REPO / ".opencode" / "scripts" / "forage.sh"
LEAP = REPO / ".opencode" / "scripts" / "leap.sh"


@pytest.mark.parametrize("driver", [LEAP, FORAGE])
@pytest.mark.parametrize("agent_exit", [0, 1, 3, 124])
def test_agent_exit_survives_the_logging_pipeline(tmp_path, driver, agent_exit):
    source = driver.read_text()
    start = source.index('run_start="$(date +%s)"')
    end = source.index('wall_s=', start)
    script = (
        'set -euo pipefail\nGOAL=fixture\n'
        f'PROMPT_FILE={shlex.quote(str(tmp_path / "prompt"))}\n'
        f'RUN_LOG={shlex.quote(str(tmp_path / "log"))}\n'
        f'AGENT_CMD=(bash -c "exit {agent_exit}")\n'
        + source[start:end] + '\nprintf "%s" "$rc"\n'
    )
    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True,
                            timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == str(agent_exit)


def _run_leap_memory_context(tmp_path, response, *, memory_exit=0, dry_run=False):
    """Execute the actual context/GOAL and digest adapters; never enter the agent seam."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    response_path = tmp_path / "memory-response.json"
    response_path.write_text(response)
    calls = tmp_path / "calls.jsonl"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    uv = bindir / "uv"
    uv.write_text(f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with Path({str(calls)!r}).open('a') as stream: stream.write(json.dumps(args)+'\\n')
if 'python' in args:
    i=args.index('python'); os.execv(sys.executable,[sys.executable,*args[i+1:]])
if 'prompt-context' in args:
    sys.stdout.write(Path({str(response_path)!r}).read_text()); raise SystemExit({memory_exit})
print(json.dumps({{'by_category':{{}}}}) if 'scorecard' in args else '[]')
''')
    uv.chmod(0o700)
    source = LEAP.read_text()
    context = source[source.index('_read_json() {'):source.index('# --- Agent invocation')]
    start = source.index('echo "Appending run digest to ${DIGEST}..."')
    digest = source[start:source.index('\necho\n', start)]
    values = {'REPO_ROOT': str(REPO), 'AUTH_DB': str(tmp_path / 'unused.db'),
              'AUTH_DATA_DIR': str(tmp_path),
              'CATEGORIES_FILE': str(REPO / '.opencode/categories.txt'),
              'LEAP_MAX_IDEAS': '3', 'DRY_RUN': str(int(dry_run)), 'STAMP': 'fixture-leap',
              'DIGEST': str(tmp_path / 'digest.jsonl'), 'DEPTH_JSON': '{}',
              'IMPORTED_JSON': '[]', 'SKIPPED_JSON': '[]', 'CRITIC_ROWS': '0',
              'EXHAUSTED_JSON': '[]', 'rc': '0', 'timed_out': '0', 'wall_s': '0',
              'rate_limited': '0', 'IMPORT_PARSE_ERROR': '0',
              'INSPIRATIONS_JSON': '[]', 'REFUTED_JSON': '[]', 'NEGATIVE_JSON': '[]',
              'SCORECARD_BY_CATEGORY': '{}'}
    command = 'set -euo pipefail\n' + '\n'.join(
        f'{key}={shlex.quote(value)}' for key, value in values.items()) + '\n'
    goal_path = tmp_path / 'goal.txt'
    command += context + f'\nprintf "%s" "$GOAL" > {shlex.quote(str(goal_path))}\n' + digest
    env = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
    result = subprocess.run(['bash', '-c', command], cwd=REPO, capture_output=True,
                            text=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr
    return {'goal': goal_path.read_text(),
            'digest': json.loads((tmp_path / 'digest.jsonl').read_text()),
            'calls': [json.loads(line) for line in calls.read_text().splitlines()]
                     if calls.exists() else [], 'stderr': result.stderr}


def test_leap_advisory_memory_failure_continues_without_fake_metrics(tmp_path):
    result = _run_leap_memory_context(tmp_path, '{"ok":false,"error":"PRIVATE_SENTINEL"}',
                                     memory_exit=1)
    assert 'refuted' in result['goal'].lower()  # Existing context remains available.
    assert 'PRIVATE_SENTINEL' not in result['goal'] + result['stderr']
    summary = result['digest']['public_research_memory_context']
    assert summary['status'] == 'read_error' and summary['snapshot_sha256'] is None
    assert summary['receipt_refs'] == [] and summary['observation_count'] == 0
    assert 'read_error' in result['goal'] and 'not zero trials' in result['goal']
    assert sum('prompt-context' in call for call in result['calls']) == 1


def test_leap_invalid_memory_response_is_unavailable_without_worker_text(tmp_path):
    raw = '{"ok":true,"public_research_memory":{"metrics":"PRIVATE_SENTINEL"}}'
    result = _run_leap_memory_context(tmp_path, raw)
    assert result['digest']['public_research_memory_context']['status'] == 'read_error'
    assert 'PRIVATE_SENTINEL' not in result['goal'] + result['stderr']
    assert 'read_error' in result['goal']


def test_leap_dry_context_does_not_query_archives(tmp_path):
    result = _run_leap_memory_context(tmp_path, 'PRIVATE_SENTINEL', dry_run=True)
    assert not any('prompt-context' in call for call in result['calls'])
    assert result['digest']['public_research_memory_context']['status'] == 'not_requested'


def test_leap_idle_gates_do_not_read_archives(tmp_path):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    marker = tmp_path / 'unexpected-memory-read'
    uv = bindir / 'uv'
    uv.write_text(f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
if 'prompt-context' in sys.argv:
    Path({str(marker)!r}).touch(); raise SystemExit(9)
if 'depth' in sys.argv:
    print(json.dumps({{'below_refill':os.environ['FIXTURE_DEPTH']=='below',
                      'open_unclaimed':0,'refill_at':3}}))
else: print('[]')
''')
    uv.chmod(0o700)
    for depth in ['above', 'below']:
        env = {**os.environ, 'PATH': str(bindir) + os.pathsep + os.environ['PATH'],
               'FIXTURE_DEPTH': depth, 'ALGUA_DATA_DIR': str(tmp_path / 'data')}
        result = subprocess.run(['bash', str(LEAP)], cwd=REPO, env=env,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stderr
        assert 'nothing to do' in result.stdout
        assert not marker.exists()


def _dry(script, *args):
    return subprocess.run(["bash", str(script), "--dry-run", *args], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout


def test_forage_dry_run_is_sandboxed_web_search_only_no_registry():
    """Forage reaches the web and NOTHING else; the registry is out of reach by capability.

    The agent definition denies `bash` outright, so forage runs no `algua` command at all -- the
    registry is unreachable rather than merely undriven. The four authority env vars are stripped
    from the child on top of that, so even an inherited value cannot leak in.
    """
    out = _dry(FORAGE, "--categories", "momentum,seasonality", "--max-notes", "4",
               "--timeout", "10m")
    assert "DRY RUN" in out
    assert "run_agent.sh" in out and "--mode forage" in out
    # No registry path VALUE reaches the agent (an `ALGUA_DB_PATH=...` assignment would be a leak;
    # the `-u ALGUA_DB_PATH` UNSET directive asserted below is the opposite of that).
    assert "ALGUA_DB_PATH=" not in out.split("would run:")[1]
    # The agent CHILD must have these four stripped even though the driver's own environment (and
    # its later accept/propose/digest calls) legitimately needs them.
    assert ("env -u ALGUA_DB_PATH -u ALGUA_KNOWLEDGE_DIR -u ALGUA_DATA_DIR "
            "-u ALGUA_MLFLOW_TRACKING_URI") in out
    assert "research inspirations accept" in out          # trusted driver lands the notes
    assert "categories: momentum,seasonality" in out and "max notes: 4" in out
    assert "forage/" in out and "--timeout 10m" in out


def test_forage_has_no_sandbox_bypass_escape_hatch():
    """The FORAGE_MCP bypass is gone, and setting it must not resurrect one.

    Under Codex, attaching the paper-search MCP server required
    `--dangerously-bypass-approvals-and-sandbox` -- dropping the OS wall to gain a tool. OpenCode
    configures MCP declaratively in `opencode.json`, so the capability no longer costs a wall. A
    flag whose only purpose was to disable a safety wall must not survive the migration, and a
    stale `FORAGE_MCP=1` in an operator's environment must change nothing.
    """
    env = {**os.environ, "FORAGE_MCP": "1"}
    out = subprocess.run(["bash", str(FORAGE), "--dry-run"], cwd=REPO, capture_output=True,
                         text=True, check=True, env=env).stdout
    assert "--dangerously-bypass-approvals-and-sandbox" not in out
    assert "NO OS WALL" not in out
    assert "run_agent.sh" in out and "--mode forage" in out


def test_leap_dry_run_is_sandboxed_no_web_scratch_db_then_import():
    out = _dry(LEAP, "--max-ideas", "5", "--timeout", "10m", "--force")
    assert "run_agent.sh" in out and "--mode leap" in out
    assert "--dangerously-bypass" not in out
    assert ".leap-scratch/data/algua.db" in out             # ALGUA_DB_PATH -> scratch copy
    assert "research idea import --from" in out            # trusted driver imports
    assert "research inspirations write-yield" in out       # scorecard -> _sources.yaml
    assert "max ideas: 5" in out and "leap/" in out


def test_leap_dry_run_prints_every_planned_driver_step():
    # The dry run is the ONLY cheap check that the driver still does its whole authority-side
    # step list (seed -> agent -> import -> yield -> digest) in the right order; each line here
    # is one step that would otherwise be droppable without any test noticing.
    out = _dry(LEAP, "--max-ideas", "5", "--timeout", "10m", "--force")
    assert "DRY RUN" in out
    assert "depth gate: skipped (--force)" in out
    assert "would create worktree: " in out and "on branch leap/" in out
    assert "max ideas: 5" in out
    assert "would seed scratch from: " in out
    assert "would pre-warm env: " in out
    assert "would run: " in out and "run_agent.sh" in out and "--timeout 10m" in out
    assert "would import via: uv run algua research idea import --from" in out
    assert "--seeded-max-id" in out and "--critic-file" in out
    assert ("would write yield via: uv run algua research inspirations write-yield "
            "--from-scorecard -") in out
    assert "would append digest to: " in out and "leap-runs.jsonl" in out
    # Order matters: nothing authoritative may be planned before the agent's run.
    assert out.index("would run: ") < out.index("would import via: ")
    assert out.index("would import via: ") < out.index("would write yield via: ")


def test_leap_dry_run_without_force_still_gates_on_pool_depth():
    out = _dry(LEAP, "--max-ideas", "5")
    assert "would check depth: " in out and "research idea depth" in out


def test_leap_rejects_unknown_argument():
    proc = subprocess.run(["bash", str(LEAP), "--bogus"], cwd=REPO, capture_output=True, text=True)
    assert proc.returncode == 2


def test_leap_units_every_two_hours_at_half_past_and_disjoint_from_paper():
    from tests.test_operator_layer import _fire_minutes, _oncalendar
    leap = _fire_minutes(_oncalendar("algua-leap.timer"))
    paper = _fire_minutes(_oncalendar("algua-paper.timer"))
    assert leap == {30} and not (leap & paper)
    tmr = (REPO / "deploy/systemd/algua-leap.timer").read_text()
    assert "OnCalendar=*-*-* 00/2:30:00 UTC" in tmr


def test_leap_units_shaped_and_installed():
    svc = (REPO / "deploy/systemd/algua-leap.service").read_text()
    assert "Type=oneshot" in svc and "leap.sh" in svc
    assert "TimeoutStartSec=2100" in svc          # > LEAP_TIMEOUT (25m) + prewarm
    tmr = (REPO / "deploy/systemd/algua-leap.timer").read_text()
    assert "Persistent=true" in tmr and "WantedBy=timers.target" in tmr
    installer = (REPO / "deploy/systemd/install-user-units.sh").read_text()
    assert "algua-leap.service" in installer and "algua-leap.timer" in installer


# --- Leap fix round 1 (review findings) -----------------------------------------------------------


def test_leap_dry_run_scratch_mlflow_tracking_uri_not_authority():
    # Without an explicit ALGUA_MLFLOW_TRACKING_URI in the agent child's `env` prefix, the agent
    # would inherit the unit's EnvironmentFile= (authority) tracking URI — a needless authority-path
    # leak into the sandbox. The `would run:` line is the agent invocation itself, so this pins the
    # var lives there, scoped under .leap-scratch, never the bare/authority value.
    out = _dry(LEAP, "--max-ideas", "5", "--timeout", "10m", "--force")
    run_line = out.split("would run: ", 1)[1].splitlines()[0]
    assert "ALGUA_MLFLOW_TRACKING_URI=" in run_line
    mlflow_val = next(
        tok for tok in run_line.split() if tok.startswith("ALGUA_MLFLOW_TRACKING_URI="))
    val = mlflow_val.split("=", 1)[1]
    assert val.endswith("/.leap-scratch/mlruns")


def _extract_import_capture_block() -> str:
    # The IMPORT_OUT capture (stdout-only) plus the `_import_field` fail-loud parsing, extracted
    # verbatim from leap.sh via literal start/end markers — the same "run the ACTUAL launcher code,
    # not a reimplementation" technique test_research_run_digest.py uses for run-research-loop.sh's
    # heredocs, applied here to a plain shell block instead of a python heredoc.
    src = LEAP.read_text(encoding="utf-8")
    start = 'echo "Importing survivors via: ${IMPORT_CMD[*]}"'
    end = "CRITIC_ROWS=\"$(_import_field critic_rows '0')\""
    start_idx = src.index(start)
    end_idx = src.index(end, start_idx) + len(end)
    return src[start_idx:end_idx]


_IMPORT_CAPTURE_SRC = _extract_import_capture_block()


def _fake_uv_bin(tmp_path: Path, *, stdout: str, stderr: str = "", exit_code: int = 0) -> Path:
    bindir = tmp_path / "fakebin-uv"
    bindir.mkdir(exist_ok=True)
    fake_uv = bindir / "uv"
    script = "#!/usr/bin/env bash\n"
    if stderr:
        script += f"cat >&2 <<'ERR'\n{stderr}\nERR\n"
    script += f"cat <<'OUT'\n{stdout}\nOUT\n"
    script += f"exit {exit_code}\n"
    fake_uv.write_text(script, encoding="utf-8")
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


def _run_import_capture(tmp_path: Path, fake_uv_bindir: Path) -> dict:
    run_log = tmp_path / "run.log"
    script = tmp_path / "run_import_capture.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'REPO_ROOT={tmp_path!s}\n'
        f'AUTH_DATA_DIR={tmp_path!s}\n'
        f'RUN_LOG={run_log!s}\n'
        "IMPORT_CMD=(uv run algua research idea import --from x --run y --max 1"
        " --seeded-max-id 0 --critic-file z)\n"
        f"{_IMPORT_CAPTURE_SRC}\n"
        'echo "RESULT_IMPORTED=${IMPORTED_JSON}"\n'
        'echo "RESULT_SKIPPED=${SKIPPED_JSON}"\n'
        'echo "RESULT_CRITIC=${CRITIC_ROWS}"\n'
        'echo "RESULT_PARSE_ERROR=${IMPORT_PARSE_ERROR}"\n',
        encoding="utf-8",
    )
    env = {**os.environ, "PATH": f"{fake_uv_bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env,
                          timeout=30, check=True)
    result: dict = {"stdout": proc.stdout, "stderr": proc.stderr, "run_log": run_log}
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_"):
            key, _, val = line.partition("=")
            result[key] = val
    return result


def test_leap_import_stderr_noise_never_corrupts_the_parsed_imported_list(tmp_path):
    # The bug this closes: folding stderr into the captured JSON (`2>&1`) meant ANY stderr line (a
    # `uv` resolve notice, a Python warning) silently turned IMPORTED_JSON into "[]" with rc 0 —
    # mark-used would then never run, and the run looked healthy. A stderr line ahead of clean JSON
    # on stdout must not affect parsing at all.
    payload = '{"ok": true, "imported": [123, 456], "skipped": [], "critic_rows": 1, "ceiling": 5}'
    fake_uv = _fake_uv_bin(tmp_path, stdout=payload,
                           stderr="warning: resolved uv.lock in 4ms (fake noise)")
    result = _run_import_capture(tmp_path, fake_uv)
    assert json.loads(result["RESULT_IMPORTED"]) == [123, 456]
    assert json.loads(result["RESULT_CRITIC"]) == 1
    assert result["RESULT_PARSE_ERROR"] == "0"
    assert (tmp_path / 'research-ready').is_file()
    # The noise must still be visible somewhere (the run log or the terminal), not swallowed.
    assert "fake noise" in result["run_log"].read_text(encoding="utf-8")


def test_leap_import_output_not_json_fails_loudly_and_flags_the_digest(tmp_path):
    fake_uv = _fake_uv_bin(tmp_path, stdout="not json at all")
    result = _run_import_capture(tmp_path, fake_uv)
    assert json.loads(result["RESULT_IMPORTED"]) == []
    assert result["RESULT_PARSE_ERROR"] == "1"
    assert "WARNING: import output was not JSON" in result["stderr"]
    # Printed exactly once, not once per field (imported/skipped/critic_rows).
    assert result["stderr"].count("WARNING: import output was not JSON") == 1
    assert not (tmp_path / 'research-ready').exists()


def test_empty_or_failed_import_does_not_wake_research(tmp_path):
    for case, payload, code in [('empty', '{"ok": true, "imported": []}', 0),
                                ('failed', '{"ok": false, "imported": [1]}', 1)]:
        directory = tmp_path / case
        directory.mkdir()
        _run_import_capture(directory, _fake_uv_bin(directory, stdout=payload, exit_code=code))
        assert not (directory / 'research-ready').exists()


def test_leap_seeded_max_id_read_and_backup_share_one_python_invocation():
    # The seed watermark (authority's max idea id BEFORE the agent runs) must be read in the SAME
    # python invocation that performs the sqlite backup, so the race window between "read the
    # watermark" and "seed the scratch copy" is as tight as possible; and the comment must name the
    # REAL safety net (research idea import's own collision re-check), not just the read timing.
    src = LEAP.read_text(encoding="utf-8")
    m = re.search(
        r"seeding scratch registry.*?<<'PY'\n(.*?)\nPY\n", src, re.DOTALL)
    assert m, "could not find the scratch-seeding python heredoc in leap.sh"
    body = m.group(1)
    assert "SELECT COALESCE(MAX(id),0) FROM ideas" in body
    assert "src.backup(dst)" in body
    assert "collision" in src  # the corrected comment documents the actual safety net


def test_leap_dry_run_seeded_max_id_is_a_placeholder_not_a_premature_read():
    # A dry run must not need (or claim) a live watermark value — the value is only meaningful once
    # the scratch registry is actually seeded, which a dry run never does.
    out = _dry(LEAP, "--max-ideas", "5", "--timeout", "10m", "--force")
    assert "would import via: uv run algua research idea import --from" in out
    assert "--seeded-max-id <read at seed time>" in out


_HEREDOC_RE = re.compile(r"<<'PY'[^\n]*\n(.*?)\n^PY$", re.DOTALL | re.MULTILINE)


def _leap_heredocs() -> list[str]:
    return _HEREDOC_RE.findall(LEAP.read_text(encoding="utf-8"))


# Heredoc 0 = the combined seed-watermark-read + sqlite-backup step; heredoc 1 = the mark-used /
# mark-exhausted inspiration bookkeeping (what the exhausted-section tests below exercise); heredoc
# 2 = the digest append. Keep these indices in sync when adding a heredoc to leap.sh.
_EXHAUSTED_SRC = _leap_heredocs()[1]


def _fake_algua_bin(tmp_path: Path) -> Path:
    # A fake `uv` intercepting exactly the two `uv run algua research inspirations ...` calls the
    # extracted heredoc makes (mark-used, mark-exhausted), so this test never shells out to the
    # real CLI / touches the real vault. `research idea show` is not reached (imported_json is
    # always "[]" below, so the mark-used loop never runs).
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    fake_uv = bindir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$*\" == *mark-exhausted* || \"$*\" == *mark-used* ]]; then\n"
        "  echo '{\"ok\": true}'\n"
        "  exit 0\n"
        "fi\n"
        "echo \"unexpected fake-uv invocation: $*\" >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


def _run_exhausted_block(tmp_path: Path, report_text: str | None) -> subprocess.CompletedProcess:
    report_path = tmp_path / "leap-report.md"
    if report_text is not None:
        report_path.write_text(report_text, encoding="utf-8")
    bindir = _fake_algua_bin(tmp_path)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
    return subprocess.run(
        [sys.executable, "-", "[]", str(report_path), str(tmp_path)],
        input=_EXHAUSTED_SRC, capture_output=True, text=True, env=env, timeout=30)


def test_leap_exhausted_section_accepts_any_heading_depth(tmp_path):
    for hashes in ("##", "###", "####"):
        proc = _run_exhausted_block(
            tmp_path, f"{hashes} Exhausted inspirations\n- 2026-09-07-index-add-crowding\n")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == ["2026-09-07-index-add-crowding"]
        assert 'note: no "Exhausted inspirations" section' not in proc.stderr


def test_leap_exhausted_section_absent_vs_present_but_empty(tmp_path):
    # Absent (no heading at all) gets a note distinguishing it from a deliberate empty list.
    absent = _run_exhausted_block(tmp_path, "some other report content, no heading at all\n")
    assert absent.returncode == 0, absent.stderr
    assert json.loads(absent.stdout) == []
    assert 'note: no "Exhausted inspirations" section in leap-report.md' in absent.stderr

    # Present but empty: no such note (the agent deliberately judged nothing spent).
    empty = _run_exhausted_block(tmp_path, "## Exhausted inspirations\n\n## Something else\n")
    assert empty.returncode == 0, empty.stderr
    assert json.loads(empty.stdout) == []
    assert 'note: no "Exhausted inspirations" section' not in empty.stderr


# --- Vault placement (final fix wave): the seed lives in deploy/, the vault is runtime state ------


def test_vault_inspirations_dir_is_git_ignored_and_the_seed_is_tracked():
    assert "kb/inspirations/" in (REPO / ".gitignore").read_text()
    assert (REPO / "deploy/kb/inspirations/_sources.yaml").exists()
    tracked = subprocess.run(["git", "ls-files", "kb/inspirations"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    assert tracked.strip() == ""


def test_installer_dry_run_would_seed_the_sources_registry_when_absent(tmp_path):
    installer = REPO / "deploy/systemd/install-user-units.sh"
    env = {**os.environ, "ALGUA_KNOWLEDGE_DIR": str(tmp_path / "kb")}
    out = subprocess.run(["bash", str(installer), "--dry-run"], cwd=REPO, capture_output=True,
                         text=True, check=True, env=env).stdout
    assert "would seed sources registry: " in out
    assert str(tmp_path / "kb" / "inspirations" / "_sources.yaml") in out
    assert not (tmp_path / "kb").exists()          # a dry run writes nothing


def test_installer_never_overwrites_an_existing_sources_registry(tmp_path):
    installer = REPO / "deploy/systemd/install-user-units.sh"
    dest = tmp_path / "kb" / "inspirations" / "_sources.yaml"
    dest.parent.mkdir(parents=True)
    dest.write_text("venues: []  # human-curated\n")
    env = {**os.environ, "ALGUA_KNOWLEDGE_DIR": str(tmp_path / "kb")}
    out = subprocess.run(["bash", str(installer), "--dry-run"], cwd=REPO, capture_output=True,
                         text=True, check=True, env=env).stdout
    assert "already present" in out and "would seed sources registry" not in out
    assert dest.read_text() == "venues: []  # human-curated\n"


def test_forage_seeds_the_sources_registry_when_the_vault_has_none(tmp_path):
    # A vault relocated via ALGUA_KNOWLEDGE_DIR self-heals at forage startup — copy-if-absent,
    # never over an existing registry.
    kb = tmp_path / "kb"
    env = {**os.environ, "ALGUA_KNOWLEDGE_DIR": str(kb)}
    out = subprocess.run(["bash", str(FORAGE), "--dry-run"], cwd=REPO, capture_output=True,
                         text=True, check=True, env=env).stdout
    assert "would seed sources registry: " in out
    assert not kb.exists()

    dest = kb / "inspirations" / "_sources.yaml"
    dest.parent.mkdir(parents=True)
    dest.write_text("venues: []\n")
    out = subprocess.run(["bash", str(FORAGE), "--dry-run"], cwd=REPO, capture_output=True,
                         text=True, check=True, env=env).stdout
    assert "seed sources registry" not in out
    assert dest.read_text() == "venues: []\n"


# --- Forage fix round 2 (final fix wave) ---------------------------------------------------------


def _extract_block(script: Path, start: str, end: str) -> str:
    src = script.read_text(encoding="utf-8")
    start_idx = src.index(start)
    end_idx = src.index(end, start_idx) + len(end)
    return src[start_idx:end_idx]


_ACCEPT_CAPTURE_SRC = _extract_block(
    FORAGE,
    'echo "Landing foraged notes via: ${ACCEPT_CMD[*]}"',
    "REJECTED_JSON=\"$(_accept_field rejected '[]')\"")


def _run_accept_capture(tmp_path: Path, fake_uv_bindir: Path) -> dict:
    run_log = tmp_path / "run.log"
    script = tmp_path / "run_accept_capture.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"REPO_ROOT={tmp_path!s}\n"
        f"RUN_LOG={run_log!s}\n"
        "ACCEPT_CMD=(uv run algua research inspirations accept --from x --run y --max 1)\n"
        f"{_ACCEPT_CAPTURE_SRC}\n"
        'echo "RESULT_ACCEPTED=${ACCEPTED_JSON}"\n'
        'echo "RESULT_REJECTED=${REJECTED_JSON}"\n'
        'echo "RESULT_PARSE_ERROR=${ACCEPT_PARSE_ERROR}"\n',
        encoding="utf-8",
    )
    env = {**os.environ, "PATH": f"{fake_uv_bindir}{os.pathsep}{os.environ.get('PATH', '')}"}
    proc = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env,
                          timeout=30, check=True)
    result: dict = {"stdout": proc.stdout, "stderr": proc.stderr, "run_log": run_log}
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT_"):
            key, _, val = line.partition("=")
            result[key] = val
    return result


def test_forage_accept_stderr_noise_never_corrupts_the_accepted_list(tmp_path):
    # Folding stderr into the captured JSON (`2>&1`) meant ANY stderr line (a `uv` resolve notice,
    # a Python warning) silently turned ACCEPTED_JSON into "[]" with rc 0 — the digest then said
    # the run foraged nothing while the vault had the notes. Same bug leap.sh already fixed.
    payload = ('{"ok": true, "accepted": ["2026-09-08-a-note"], '
               '"rejected": [{"file": "x.md", "reasons": ["bad filename: x.md"]}]}')
    fake_uv = _fake_uv_bin(tmp_path, stdout=payload,
                           stderr="warning: resolved uv.lock in 4ms (fake noise)")
    result = _run_accept_capture(tmp_path, fake_uv)
    assert json.loads(result["RESULT_ACCEPTED"]) == ["2026-09-08-a-note"]
    assert json.loads(result["RESULT_REJECTED"])[0]["file"] == "x.md"
    assert result["RESULT_PARSE_ERROR"] == "0"
    assert "fake noise" in result["run_log"].read_text(encoding="utf-8")


def test_forage_accept_output_not_json_fails_loudly_and_flags_the_digest(tmp_path):
    fake_uv = _fake_uv_bin(tmp_path, stdout="not json at all")
    result = _run_accept_capture(tmp_path, fake_uv)
    assert json.loads(result["RESULT_ACCEPTED"]) == []
    assert result["RESULT_PARSE_ERROR"] == "1"
    assert "WARNING: accept output was not JSON" in result["stderr"]
    assert result["stderr"].count("WARNING: accept output was not JSON") == 1


def test_forage_digest_records_the_accept_parse_error_flag():
    src = FORAGE.read_text(encoding="utf-8")
    assert '"accept_parse_error": accept_parse_error == "1"' in src


# forage.sh heredoc 0 = the seen-hash reader; 1 = the sources-registry slice; 2 = the
# proposed-venue validator/proposer (extracted here); 3 = the digest append. Keep these indices in
# sync when adding a heredoc to forage.sh.
_PROPOSED_SRC = _HEREDOC_RE.findall(FORAGE.read_text(encoding="utf-8"))[2]


def test_forage_proposed_venues_block_emits_only_json_on_stdout(tmp_path):
    # PROPOSED_JSON is a command substitution of this block's stdout. A progress line printed on
    # stdout ("proposed venue: X") made the whole capture unparseable, so the digest row's
    # `proposed` list came back empty even on a run that really did add a venue.
    report = tmp_path / "forage-report.md"
    report.write_text("## Proposed venues\n"
                      "- key: blog/goodone kind: blog url: https://g/x categories: [momentum]\n"
                      "- key: BADKEY kind: blog url: https://g/y categories: [momentum]\n")
    cats = tmp_path / "categories.txt"
    cats.write_text("momentum\n")
    bindir = tmp_path / "fakebin-propose"
    bindir.mkdir()
    fake_uv = bindir / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\necho '{\"ok\": true}'\nexit 0\n", encoding="utf-8")
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"}

    proc = subprocess.run(
        [sys.executable, "-", str(report), str(cats), str(tmp_path)],
        input=_PROPOSED_SRC, capture_output=True, text=True, env=env, timeout=30)

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["blog/goodone"]      # stdout is PURE JSON
    assert "proposed venue: blog/goodone" in proc.stderr    # the progress line still shows
    assert "BADKEY" in proc.stderr


def test_forage_seen_hash_list_is_trimmed_to_the_newest_300():
    assert "hashes[-300:]" in FORAGE.read_text(encoding="utf-8")


def test_forage_help_covers_the_env_block():
    out = subprocess.run(["bash", str(FORAGE), "-h"], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    assert "Env: FORAGE_MAX_NOTES" in out and "FORAGE_TIMEOUT" in out


# --- Leap fix round 2 (final fix wave) -----------------------------------------------------------


def test_leap_reads_every_non_exhausted_note_not_only_fresh():
    # `mark-used` flips a note to `used` the first time it feeds a hypothesis, but a note usually
    # holds more than one leap. Reading `--status fresh` starved leap of material after one pass.
    src = LEAP.read_text(encoding="utf-8")
    assert "--exclude-status exhausted --limit 20 --rare-first" in src
    # The only `--status fresh` read is the owner-idea depth-gate bypass (spec 2026-11-12 §6.4):
    # an owner idea already leapt once must not keep bypassing the gate every firing.
    fresh_lines = [ln for ln in src.splitlines() if "--status fresh" in ln]
    assert len(fresh_lines) == 1 and "inspirations list --status fresh" in fresh_lines[0]
    assert "--source-kind human" in src.split("--status fresh", 1)[1].splitlines()[1]


def test_leap_dry_run_prints_the_material_gate():
    out = _dry(LEAP, "--max-ideas", "5", "--force")
    assert ("would check material: uv run algua research inspirations list "
            "--exclude-status exhausted --limit 1") in out
    # The material gate is planned AFTER the (cheaper) depth gate and BEFORE any worktree.
    assert out.index("depth gate: skipped") < out.index("would check material: ")
    assert out.index("would check material: ") < out.index("would create worktree: ")


def test_leap_with_an_empty_vault_exits_zero_and_creates_no_worktree(tmp_path):
    # --force clears the depth gate; the vault is a fresh empty dir, so the material gate must
    # stop the run before the flock, the worktree, the uv sync and the codex call.
    runs_before = set((REPO / ".runs").glob("leap-*")) if (REPO / ".runs").exists() else set()
    env = {**os.environ, "ALGUA_KNOWLEDGE_DIR": str(tmp_path / "empty-kb"),
           "ALGUA_DATA_DIR": str(tmp_path / "data")}
    proc = subprocess.run(["bash", str(LEAP), "--force"], cwd=REPO, capture_output=True,
                          text=True, timeout=180, env=env)
    assert proc.returncode == 0, proc.stderr
    assert "no fresh material (0 non-exhausted inspirations); nothing to do" in proc.stdout
    runs_after = set((REPO / ".runs").glob("leap-*")) if (REPO / ".runs").exists() else set()
    assert runs_after == runs_before


# --- Unit shape + operator docs (final fix wave) --------------------------------------------------


def test_forage_service_is_installable_like_the_other_oneshot_units():
    # Without [Install], `systemctl enable algua-forage.service` fails and the installer's
    # multi-user.target -> default.target rewrite has nothing to rewrite. Mirrors
    # algua-mergeback-drain.service / algua-leap.service.
    svc = (REPO / "deploy/systemd/algua-forage.service").read_text()
    assert "[Install]\nWantedBy=multi-user.target" in svc


def test_leap_timer_and_readme_tell_the_truth_about_the_shared_minute():
    # Leap fires at :30 — the merge-back drainer's own minute. The old comments claimed the grid
    # was disjoint from the drainer, which it is not; what is true is that leap takes no
    # operator.lock, so sharing the minute is harmless.
    tmr = (REPO / "deploy/systemd/algua-leap.timer").read_text()
    assert "SHARES the merge-back drainer's :30 minute" in tmr
    assert "leap does NOT" in tmr and "operator.lock" in tmr
    readme = (REPO / "deploy/systemd/README.md").read_text()
    assert "shares the merge-back drainer's `:30` minute" in readme
    assert "leap\ntakes no `operator.lock`" in readme


def test_env_example_documents_the_driver_timeouts():
    env = (REPO / "deploy/systemd/algua.env.example").read_text()
    for line in ("# LEAP_TIMEOUT=25m", "# FORAGE_TIMEOUT=20m", "# SYNC_TIMEOUT=5m"):
        assert line in env


# --- Drive ideation backend (spec 2026-11-12 §4, §6.4): intake -> snapshot -> leap -> publish ---

def _dry_drive(script, *args):
    env = {**os.environ, "ALGUA_DRIVE_FOLDER_ID": "x"}
    return subprocess.run(["bash", str(script), "--dry-run", *args], cwd=REPO,
                          capture_output=True, text=True, check=True, env=env).stdout


def test_leap_dry_run_drive_mode_prints_intake_export_publish_in_order():
    out = _dry_drive(LEAP, "--max-ideas", "5")
    assert out.index("would intake owner inbox via: uv run algua research inbox intake") \
        < out.index("would export steering snapshot via: uv run algua research steering export") \
        < out.index("would check depth: ") \
        < out.index("would publish via: uv run algua research idea publish")


def test_leap_dry_run_without_drive_is_unchanged():
    env = {k: v for k, v in os.environ.items() if k != "ALGUA_DRIVE_FOLDER_ID"}
    out = subprocess.run(["bash", str(LEAP), "--dry-run", "--max-ideas", "5"], cwd=REPO,
                         capture_output=True, text=True, check=True, env=env).stdout
    assert "inbox intake" not in out and "steering export" not in out
    assert "idea publish" not in out


def test_forage_dry_run_drive_mode_uses_snapshot_paths():
    out = _dry_drive(FORAGE, "--categories", "momentum")
    line = [ln for ln in out.splitlines() if ln.startswith("would read steering from: ")][0]
    assert "/.runs/steering-forage/categories.txt" in line
    assert "/.runs/steering-forage/inspirations/_sources.yaml" in line
    assert "would seed sources registry" not in out


def test_snapshot_dir_is_outside_agent_workdir():
    out = _dry_drive(LEAP, "--max-ideas", "5")
    snap = out.split("steering export --to ")[1].split()[0]
    workdir = out.split("would create worktree: ")[1].split()[0]
    assert not snap.startswith(workdir.rstrip("/") + "/")
    assert "/.runs/" in snap


def test_leap_human_ideas_bypass_the_depth_gate_in_source():
    src = LEAP.read_text()
    assert "--source-kind human" in src and "depth gate bypassed: fresh owner ideas" in src
    assert "--found-since" in src  # review I7: the bypass is age-bounded


def test_research_loop_publishes_after_its_digest():
    src = (REPO / ".opencode/scripts/run-research-loop.sh").read_text()
    tail = src.split("append_digest completed", 1)[1]
    assert "research idea publish" in tail
