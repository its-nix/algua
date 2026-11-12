"""No new model spending on unchanged clean zero-yield input after two attempts."""
import pytest

from algua.operator.leap_progress import context_key, ready, record_result


def test_repeated_empty_passes_wait_for_changed_inputs_and_do_not_refute_ideas(tmp_path):
    key = context_key({'notes': ['a'], 'coverage': {'sessions': 504}, 'code': 'v1'})
    assert ready(tmp_path, key)
    record_result(tmp_path, key, clean=True, imported=0)
    assert ready(tmp_path, key)
    record_result(tmp_path, key, clean=True, imported=0)
    assert not ready(tmp_path, key)
    changed = context_key({'notes': ['b'], 'coverage': {'sessions': 504}, 'code': 'v1'})
    assert ready(tmp_path, changed)
    record_result(tmp_path, key, clean=True, imported=1)
    assert ready(tmp_path, key)
    assert list(tmp_path.glob('*.db')) == []


def test_failed_worker_is_not_a_clean_exhaustion_and_corrupt_state_refuses(tmp_path):
    key = context_key({'source': 'fixture'})
    record_result(tmp_path, key, clean=False, imported=0)
    assert ready(tmp_path, key)
    (tmp_path / 'leap-progress.json').write_text('bad')
    with pytest.raises(ValueError, match='leap_progress'):
        ready(tmp_path, key)


def test_actual_launcher_gate_skips_model_on_third_identical_context(tmp_path, monkeypatch):
    import json
    import os
    import shlex
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / '.opencode/scripts/leap.sh').read_text()
    block = source[source.index('# Two clean empty passes'):source.index('echo "Creating worktree')]
    binary = tmp_path / 'bin'
    binary.mkdir()
    uv = binary / 'uv'
    uv.write_text(f'#!{sys.executable}\nimport os,sys\n'
                  "i=sys.argv.index('python')\n"
                  "os.execv(sys.executable,[sys.executable,*sys.argv[i+1:]])\n")
    uv.chmod(0o700)
    monkeypatch.delenv('ALGUA_RESEARCH_PROFILE', raising=False)
    values = dict(REPO_ROOT=str(root), AUTH_DATA_DIR=str(tmp_path), INSPIRATIONS_JSON='["source"]',
                  DEPTH_JSON='{}', REFUTED_JSON='[]', SCORECARD_BY_CATEGORY='{}',
                  CATEGORIES_FILE=str(root / '.opencode/categories.txt'), FORCE='0',
                  STAMP='fixture',
                  DIGEST=str(tmp_path / 'leap-runs.jsonl'))
    script = 'set -euo pipefail\n' + '\n'.join(
        f'{k}={shlex.quote(v)}' for k,v in values.items()) + '\n' + block
    script += '\nprintf "KEY=%s\\nWOULD_CALL_MODEL\\n" "$LEAP_CONTEXT_KEY"\n'
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH']}
    def run():
        result = subprocess.run(['bash', '-c', script], cwd=root, env=env,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout
    first = run()
    key = first.split('KEY=')[1].splitlines()[0]
    record_result(tmp_path, key, clean=True, imported=0)
    assert 'WOULD_CALL_MODEL' in run()
    record_result(tmp_path, key, clean=True, imported=0)
    assert 'WOULD_CALL_MODEL' not in run()
    row = json.loads((tmp_path / 'leap-runs.jsonl').read_text())
    assert row['outcome'] == 'unchanged_inputs' and row['model_called'] is False


@pytest.mark.parametrize('import_rc,body,counts', [
    ('0', '{"ok":true,"imported":[],"critic_errors":0}', True),
    ('1', '{"ok":false,"imported":[]}', False),
    ('0', '{"ok":true,"imported":[],"critic_errors":1}', False),
])
def test_actual_result_adapter_never_counts_failed_import_as_clean(
        tmp_path, import_rc, body, counts):
    import os
    import shlex
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = (root / '.opencode/scripts/leap.sh').read_text()
    block = source[source.index('# Preserve failed-run uncertainty'):
                   source.index('# --- Per-venue yield')]
    binary = tmp_path / 'bin'
    binary.mkdir()
    uv = binary / 'uv'
    uv.write_text(f'#!{sys.executable}\nimport os,sys\n'
                  "i=sys.argv.index('python')\n"
                  "os.execv(sys.executable,[sys.executable,*sys.argv[i+1:]])\n")
    uv.chmod(0o700)
    key = context_key({'fixture': 'result'})
    values = dict(REPO_ROOT=str(root), AUTH_DATA_DIR=str(tmp_path), LEAP_CONTEXT_KEY=key,
                  IMPORTED_JSON='[]', IMPORT_OUT=body, IMPORT_RC=import_rc, rc='0',
                  timed_out='0', rate_limited='0', IMPORT_PARSE_ERROR='0')
    script = 'set -euo pipefail\n' + '\n'.join(
        f'{k}={shlex.quote(v)}' for k,v in values.items()) + '\n' + block
    env = {**os.environ, 'PATH': str(binary) + os.pathsep + os.environ['PATH']}
    p = subprocess.run(['bash','-c',script],env=env,cwd=root,capture_output=True,text=True)
    assert p.returncode == 0, p.stderr
    assert (tmp_path / 'leap-progress.json').exists() is counts
