"""Run the actual Bash admission adapter with a failed CLI, never a model or registry."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / '.opencode/scripts/run-research-loop.sh'
LIMIT = 1024 * 1024
SECRET = 'SYNTHETIC_PRIVATE_START_RESPONSE'


def _diagnostic(tmp_path):
    return tmp_path / 'data/research-cycles/diagnostic.start-error.txt'


def _start(tmp_path, raw, *, code=1):
    cycles = tmp_path / 'data/research-cycles'
    if not cycles.is_symlink():
        cycles.mkdir(parents=True, exist_ok=True)
    response = tmp_path / 'mock-response'
    response.write_bytes(raw)
    source = DRIVER.read_text()
    adapter = source[source.index('  CLAIM_ARGS=('):source.index('  N_CLAIMED=')]
    values = {
        'AUTH_DB': str(tmp_path / 'unused.db'), 'AUTH_DATA_DIR': str(tmp_path / 'data'),
        'STAMP': 'diagnostic', 'N_HYPOTHESES': '1', 'TIMEOUT': '10m', 'WORKER_LIMIT': '1',
        'CPU_SECONDS': '600', 'MEMORY_MB': '4096', 'FILE_MB': '512', 'MAX_COST': '',
        'CATEGORY': '', 'CAMPAIGN': '', 'CHOOSE_CAMPAIGN': '0',
    }
    command = 'set -euo pipefail\n' + '\n'.join(
        f'{key}={shlex.quote(value)}' for key, value in values.items()) + '\n'
    mock = ('import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes());'
            ' raise SystemExit(int(sys.argv[2]))')
    command += 'AUTH_CLI=(' + shlex.join([sys.executable, '-c', mock, str(response), str(code)])
    command += ')\n' + adapter.replace('python3 -c', shlex.quote(sys.executable) + ' -c')
    return subprocess.run(['bash', '-c', command], cwd=ROOT, capture_output=True,
                          text=True, timeout=15)


def _assert_redacted(result):
    assert result.returncode == 1
    assert result.stdout == ''
    assert SECRET not in result.stderr
    envelope = json.loads(next(line for line in result.stderr.splitlines()
                               if line.startswith('{')))
    assert envelope['error'] == 'cycle-start failed; inspect private artifacts'
    assert envelope['phase'] == 'cycle_start'


@pytest.mark.parametrize('raw', [
    json.dumps({'ok': False, 'error': SECRET, 'code': 'invalid_input',
                'claimed': [{'claim_token': SECRET}]}).encode(),
    ('malformed response\n' + SECRET).encode(),
])
def test_failed_private_response_preserves_cause_without_echo(tmp_path, raw):
    result = _start(tmp_path, raw)
    _assert_redacted(result)
    path = _diagnostic(tmp_path)
    assert path.read_bytes() == raw
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_uid == os.getuid()
    assert not (path.parent / 'diagnostic.choice').exists()


def test_successful_claim_response_is_never_saved(tmp_path):
    raw = json.dumps({'ok': True, 'claimed': [{'id': 1, 'claim_token': SECRET}]}).encode()
    result = _start(tmp_path, raw, code=0)
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert not _diagnostic(tmp_path).exists()


@pytest.mark.parametrize('size', [LIMIT, LIMIT + 1])
def test_private_response_byte_limit(tmp_path, size):
    raw = SECRET.encode() + b'x' * (size - len(SECRET))
    result = _start(tmp_path, raw)
    _assert_redacted(result)
    path = _diagnostic(tmp_path)
    if size == LIMIT:
        assert path.read_bytes() == raw
    else:
        assert not path.exists()
        assert 'private cycle-start response not saved' in result.stderr


@pytest.mark.parametrize('kind', ['existing', 'symlink', 'dangling', 'directory'])
def test_private_response_never_overwrites_existing_path(tmp_path, kind):
    path = _diagnostic(tmp_path)
    path.parent.mkdir(parents=True)
    target = tmp_path / 'untouched'
    target.write_bytes(b'original private evidence')
    if kind == 'existing':
        path.write_bytes(b'first failure')
    elif kind == 'directory':
        path.mkdir()
    else:
        path.symlink_to(target if kind == 'symlink' else tmp_path / 'absent')
    before = path.lstat()
    result = _start(tmp_path, SECRET.encode())
    _assert_redacted(result)
    assert 'private cycle-start response not saved' in result.stderr
    assert path.lstat() == before
    assert target.read_bytes() == b'original private evidence'
    if kind == 'existing':
        assert path.read_bytes() == b'first failure'


@pytest.mark.parametrize('kind', ['symlink', 'writable'])
def test_private_response_refuses_unsafe_cycle_directory(tmp_path, kind):
    path = _diagnostic(tmp_path)
    path.parent.parent.mkdir()
    if kind == 'symlink':
        target = tmp_path / 'other'
        target.mkdir()
        path.parent.symlink_to(target, target_is_directory=True)
    else:
        path.parent.mkdir(mode=0o777)
        path.parent.chmod(0o777)
    result = _start(tmp_path, SECRET.encode())
    _assert_redacted(result)
    assert not path.exists()
    assert 'private cycle-start response not saved' in result.stderr
