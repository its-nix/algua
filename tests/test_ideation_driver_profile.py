"""Run the actual ideation prompt adapters without launching an agent."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from algua.operator.research_memory_checkpoint import canonical
from tests.test_research_profile import configured as configured
from tests.test_research_profile import profile

ROOT = Path(__file__).resolve().parents[1]
DRIVERS = [ROOT / '.opencode/scripts' / name for name in ('forage.sh', 'leap.sh')]


def _run_adapter(tmp_path, driver, *, snapshot_id=None, configured_path=None, data_dir=None):
    source = driver.read_text()
    block = source[source.index('# --- Optional verified research inputs'):
                   source.index('# --- Agent invocation')]
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    calls = tmp_path / 'calls'
    uv = bindir / 'uv'
    uv.write_text(f'''#!{sys.executable}
import sys
from pathlib import Path
from algua.operator import research_profile
Path({str(calls)!r}).write_text('called')
research_profile.SNAPSHOT_ID = {snapshot_id!r}
args = sys.argv[1:]
index = args.index('-c')
code = args[index + 1]
sys.argv = ['-c', *args[index + 2:]]
exec(compile(code, '<driver-profile>', 'exec'))
''')
    uv.chmod(0o700)
    values = {'GOAL': 'original goal', 'REPO_ROOT': str(ROOT),
              'AUTH_DATA_DIR': str(data_dir or tmp_path / 'missing-data')}
    command = 'set -euo pipefail\n' + '\n'.join(
        f'{key}={shlex.quote(value)}' for key, value in values.items()) + '\n' + block
    command += '\nprintf "%s" "$GOAL"'
    env = {k: v for k, v in os.environ.items() if k != 'ALGUA_RESEARCH_PROFILE'}
    env['PATH'] = str(bindir) + os.pathsep + env['PATH']
    if configured_path is not None:
        env['ALGUA_RESEARCH_PROFILE'] = str(configured_path)
    result = subprocess.run(['bash', '-c', command], cwd=ROOT, capture_output=True,
                            text=True, env=env, timeout=30)
    return result, calls


@pytest.mark.parametrize('driver', DRIVERS)
def test_unconfigured_ideation_profile_preserves_goal_without_reading(tmp_path, driver):
    result, calls = _run_adapter(tmp_path, driver)
    assert result.returncode == 0 and result.stdout == 'original goal'
    assert result.stderr == '' and not calls.exists()


@pytest.mark.parametrize('driver', DRIVERS)
def test_ideation_prompt_receives_verified_exact_research_inputs(configured, tmp_path, driver):
    store, record, path, _ = configured
    receipt = profile.load_research_profile(store.data_dir)
    result, calls = _run_adapter(tmp_path, driver, snapshot_id=record.snapshot_id,
                                configured_path=path, data_dir=store.data_dir)
    assert result.returncode == 0, result.stderr
    assert calls.exists()
    assert canonical(receipt).decode() in result.stdout
    assert 'MSFT' not in receipt['symbols'] and len(receipt['symbols']) == 300
    assert 'outside the listed symbols' in result.stdout
    assert 'UNTRUSTED DATA' in result.stdout and 'no authority' in result.stdout
    assert 'next-bar' in result.stdout and 'qualification' in result.stdout
    assert str(path) not in result.stdout and str(store.data_dir) not in result.stdout


@pytest.mark.parametrize('driver', DRIVERS)
def test_invalid_ideation_profile_fails_before_agent_without_private_errors(tmp_path, driver):
    path = tmp_path / 'PRIVATE_SENTINEL.json'
    path.write_text(json.dumps({'invalid': 'PRIVATE_SENTINEL'}))
    result, calls = _run_adapter(tmp_path, driver, configured_path=path)
    assert result.returncode != 0 and calls.exists()
    assert 'profile verification refused' in result.stderr
    assert 'PRIVATE_SENTINEL' not in result.stdout + result.stderr
    assert 'Traceback' not in result.stderr
