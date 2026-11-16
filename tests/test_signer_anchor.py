"""Synthetic authority tests; no enrolled production keys, registry or venue access."""
from __future__ import annotations

import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from algua.registry import live_gate
from algua.registry import signer_anchor_installed as installed

REPO = Path(__file__).resolve().parents[1]


def _builder():
    spec = importlib.util.spec_from_file_location(
        'live_builder', REPO / 'deploy/scripts/build-live-artifact.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _artifact(tmp_path):
    root = tmp_path / 'release'
    for base in ('algua/registry', '.venv/lib/python3.12/site-packages/algua/registry'):
        target = root / base
        target.mkdir(parents=True)
        for path in (REPO / 'algua/registry').glob('signer_anchor*.py'):
            shutil.copyfile(path, target / path.name)
        (target / '__pycache__').mkdir()
        (target / '__pycache__/signer_anchor_dev.pyc').write_bytes(b'dev')
    (root / 'uv.lock').write_bytes(b'synthetic-locked-dependencies')
    (root / 'approvers').mkdir()
    (root / 'approvers/allowed_signers').write_bytes(b'synthetic public enrollment')
    return root


@pytest.mark.parametrize('development', [False, True])
def test_build_time_policy_separation(tmp_path, development):
    root = _artifact(tmp_path)
    policy = 'signer_anchor_dev.py' if development else 'signer_anchor_installed.py'
    expected = (REPO / 'algua/registry' / policy).read_bytes()
    files = _builder().assemble_policy(root, development=development)
    assert len(files) == 2
    assert set(files.values()) == {hashlib.sha256(expected).hexdigest()}
    assert not list(root.rglob('signer_anchor_dev*'))
    assert not list(root.rglob('signer_anchor_installed*'))
    assert not list(root.rglob('__pycache__'))
    for filename in files:
        assert (root / filename).read_bytes() == expected
    assert (root / '.venv/lib/python3.12/site-packages/uv.lock').read_bytes() == (
        root / 'uv.lock').read_bytes()


def test_installed_artifact_direct_import_has_no_development_escape(tmp_path):
    root = _artifact(tmp_path)
    _builder().assemble_policy(root, development=False)
    origin = root / 'algua/registry/signer_anchor.py'
    script = '''
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('strict', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert str(module.ALLOWED_SIGNERS_PATH) == '/etc/algua/authority/allowed_signers'
for path in (pathlib.Path('approvers/allowed_signers'), pathlib.Path('/tmp/allowed_signers')):
    try:
        with module.open_anchor(path):
            raise AssertionError('override accepted')
    except module.AnchorError:
        pass
try:
    module.require_enrollment_allowed()
except module.AnchorError:
    pass
else:
    raise AssertionError('enrollment accepted')
'''
    env = {**os.environ, 'ALGUA_ALLOWED_SIGNERS_PATH': '/tmp/evil',
           'ALGUA_AUTHORITY_MODE': 'development', 'PYTHONPATH': '/tmp/evil', 'PATH': '/tmp/evil'}
    result = subprocess.run([sys.executable, '-I', '-S', '-c', script, str(origin)],
                            cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('mode,uid,directory', [
    (stat.S_IFREG | 0o666, 0, False), (stat.S_IFREG | 0o644, 1000, False),
    (stat.S_IFDIR | 0o777, 0, True), (stat.S_IFIFO | 0o644, 0, False),
    (stat.S_IFLNK | 0o644, 0, False), (stat.S_IFREG | 0o600, 0, False),
])
def test_unsafe_descriptor_refused(monkeypatch, mode, uid, directory):
    monkeypatch.setattr(installed.os, 'fstat', lambda fd: SimpleNamespace(st_mode=mode, st_uid=uid))
    with pytest.raises(installed.AnchorError):
        installed._check_fd(123, directory=directory)


def test_acl_refused(monkeypatch):
    monkeypatch.setattr(installed.os, 'fstat', lambda fd: SimpleNamespace(
        st_mode=stat.S_IFREG | 0o644, st_uid=0))
    monkeypatch.setattr(installed.os, 'getxattr', lambda *args: b'extended acl', raising=False)
    with pytest.raises(installed.AnchorError, match='ACL'):
        installed._check_fd(123, directory=False)


@pytest.mark.parametrize('content', [b'', b'x' * 33])
def test_empty_and_oversized_refused(tmp_path, content):
    path = tmp_path / 'anchor'
    path.write_bytes(content)
    with path.open('rb') as stream, pytest.raises(installed.AnchorError):
        installed._read_bounded(stream.fileno(), 32)


def _synthetic_authority(monkeypatch, tmp_path, content=b'test anchor'):
    directory = tmp_path / 'authority'
    directory.mkdir()
    (directory / 'allowed_signers').write_bytes(content)
    (directory / 'installed.json').write_text(json.dumps({
        'schema': 'algua-authority/v1',
        'allowed_signers_sha256': hashlib.sha256(content).hexdigest()}))
    real_open = os.open

    def open_test_root(path, flags, *, dir_fd=None):
        if path == '/':
            return real_open(directory, flags)
        if path in ('etc', 'algua', 'authority'):
            return os.dup(dir_fd)
        return real_open(path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(installed.os, 'open', open_test_root)
    monkeypatch.setattr(installed, '_check_fd', lambda *args, **kwargs: None)
    return directory


@pytest.mark.parametrize('manifest', [
    '{}', 'null', '[]', '42', '{',
    '{"schema":"algua-authority/v1","allowed_signers_sha256":"bad"}',
    '{"schema":"algua-authority/v1","schema":"algua-authority/v1"}',
    'x' * 1025,
])
def test_manifest_failures(monkeypatch, tmp_path, manifest):
    directory = _synthetic_authority(monkeypatch, tmp_path)
    (directory / 'installed.json').write_text(manifest)
    with pytest.raises(installed.AnchorError):
        installed._read_authority()


def test_manifest_binds_exact_bytes_and_mixed_rotation_refuses(monkeypatch, tmp_path):
    directory = _synthetic_authority(monkeypatch, tmp_path)
    assert installed._read_authority() == b'test anchor'
    (directory / 'allowed_signers').write_bytes(b'replacement')
    with pytest.raises(installed.AnchorError, match='hash mismatch'):
        installed._read_authority()


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux sealed memfd contract')
def test_sealed_snapshot_real_ssh_and_descriptor_tampering(monkeypatch, tmp_path):
    key = tmp_path / 'synthetic'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
                   check=True, capture_output=True)
    content = ('test namespaces="algua-go-live" ' + key.with_suffix('.pub').read_text()).encode()
    payload = tmp_path / 'payload'
    payload.write_text('synthetic authority only')
    subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign', '-n', 'algua-go-live',
                    '-f', str(key), str(payload)], check=True, capture_output=True)
    signature = payload.with_suffix('.sig').read_bytes()
    monkeypatch.setattr(installed, '_check_process', lambda: None)
    monkeypatch.setattr(installed, '_check_runtime', lambda: None)
    monkeypatch.setattr(installed, '_read_authority', lambda: content)
    monkeypatch.setattr(live_gate, 'signer_anchor', installed)
    with installed.open_anchor(installed.ALLOWED_SIGNERS_PATH) as snapshot:
        fd, = snapshot.pass_fds
        duplicate = os.dup(fd)
        try:
            for operation in (lambda: os.write(duplicate, b'evil'),
                              lambda: os.ftruncate(duplicate, 0),
                              lambda: snapshot.path.write_bytes(b'evil'),
                              lambda: fcntl.fcntl(duplicate, fcntl.F_ADD_SEALS, 0)):
                with pytest.raises(OSError) as failure:
                    operation()
                assert failure.value.errno in (errno.EPERM, errno.EACCES)
            assert snapshot.path.read_bytes() == content
        finally:
            os.close(duplicate)
    assert live_gate.verify_signature(installed.ALLOWED_SIGNERS_PATH,
                                      payload.read_text(), signature) == 'test'
    assert live_gate.verify_signature(installed.ALLOWED_SIGNERS_PATH,
                                      'tampered', signature) is None
    assert live_gate.verify_signature(installed.ALLOWED_SIGNERS_PATH,
                                      payload.read_text(), signature, namespace='wrong') is None


def test_namespace_and_both_ssh_calls_use_one_snapshot(monkeypatch, tmp_path):
    anchor = tmp_path / 'signers'
    original = b'test namespaces="algua-go-live" ssh-ed25519 synthetic\n'
    anchor.write_bytes(original)
    seen = []

    def run(args, **kwargs):
        assert args[0] == '/usr/bin/ssh-keygen'
        seen.append(Path(args[args.index('-f') + 1]).read_bytes())
        anchor.write_bytes(b'changed during verification')
        return SimpleNamespace(returncode=0, stdout=b'test\n')

    monkeypatch.setattr(live_gate.subprocess, 'run', run)
    assert live_gate.verify_signature(anchor, 'payload', b'sig') == 'test'
    assert seen == [original, original]


@pytest.fixture
def disposable_installed_artifact(tmp_path):
    """Only opt in inside a disposable Linux container; never touch host authority paths."""
    if (sys.platform != 'linux' or os.geteuid() != 0
            or os.environ.get('ALGUA_DISPOSABLE_AUTHORITY_TEST') != '1'):
        pytest.skip('requires explicitly disposable root Linux container')
    import uuid

    authority = Path('/etc/algua/authority')
    assert not authority.exists(), 'refusing to touch existing authority'
    release = Path('/opt/algua/releases') / (uuid.uuid4().hex + 'a' * 8)
    release.mkdir(parents=True, mode=0o755)
    authority.mkdir(parents=True, mode=0o755)
    try:
        shutil.copytree(REPO / 'algua', release / 'algua',
                        ignore=shutil.ignore_patterns('__pycache__'))
        site = release / '.venv/lib/python3.12/site-packages'
        site.mkdir(parents=True)
        shutil.copytree(release / 'algua', site / 'algua')
        shutil.copyfile(REPO / 'uv.lock', release / 'uv.lock')
        _builder().assemble_policy(release, development=False)
        key = tmp_path / 'synthetic-installed'
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
                       check=True, capture_output=True)
        anchor = ('test namespaces="algua-go-live" ' + key.with_suffix('.pub').read_text()).encode()
        (authority / 'allowed_signers').write_bytes(anchor)
        (authority / 'installed.json').write_text(json.dumps({
            'schema': 'algua-authority/v1',
            'allowed_signers_sha256': hashlib.sha256(anchor).hexdigest()}))
        payload = tmp_path / 'installed-payload'
        payload.write_text('unchanged synthetic payload')
        subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign', '-n', 'algua-go-live',
                        '-f', str(key), str(payload)], check=True, capture_output=True)
        yield release, site, authority, payload.with_suffix('.sig').read_text()
    finally:
        shutil.rmtree(release)
        shutil.rmtree(authority)


def _unprivileged(script, *, paths, cwd='/', env=None):
    import ctypes

    def drop_privileges():
        assert ctypes.CDLL(None).prctl(38, 1, 0, 0, 0) == 0  # PR_SET_NO_NEW_PRIVS
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)

    program = f'import sys; sys.dont_write_bytecode=True; sys.path[:0]={paths!r};\n' + script
    return subprocess.run([str(Path(sys._base_executable).resolve()), '-I', '-S', '-c', program],
                          preexec_fn=drop_privileges, cwd=cwd, env=env,
                          text=True, capture_output=True,
                          timeout=60)


def test_installed_artifact_real_signature_and_refusal_as_runtime_uid(
    disposable_installed_artifact,
):
    release, site, authority, signature = disposable_installed_artifact
    program = f'''
from algua.registry.live_gate import verify_signature, ALLOWED_SIGNERS_PATH
assert verify_signature(ALLOWED_SIGNERS_PATH, 'unchanged synthetic payload',
                        {signature!r}.encode()) == 'test'
print('verified')
'''
    # Direct source and installed-package imports both use the assembled mandatory policy.
    for path in (release, site):
        result = _unprivileged(program, paths=[str(path)])
        assert result.returncode == 0, result.stderr
    (authority / 'installed.json').write_text('{}')
    result = _unprivileged(program, paths=[str(site)])
    assert result.returncode != 0 and 'SignatureError' in result.stderr
    attempts = '''
import os
from pathlib import Path
root=Path('/etc/algua/authority')
for operation in (lambda: (root/'allowed_signers').write_text('evil'),
                  lambda: (root/'allowed_signers').unlink(),
                  lambda: os.rename(root, root.with_name('replaced'))):
    try:
        operation()
    except PermissionError:
        pass
    else:
        raise AssertionError('runtime replaced authority')
'''
    result = _unprivileged(attempts, paths=[])
    assert result.returncode == 0, result.stderr


def test_installed_cli_enrollment_refuses_json_without_mutation(disposable_installed_artifact):
    release, site, authority, _ = disposable_installed_artifact
    before = (authority / 'allowed_signers').read_bytes()
    deps = str(Path(pytest.__file__).parents[1])
    script = '''
from algua.cli.main import main
main(['registry', 'enroll-approver', '--name', 'synthetic', '--pubkey', 'ssh-ed25519 synthetic'])
'''
    # Existing vectorbt imports need a cache locator. This disposable synthetic cache is
    # test-only; installed cache/executable-runtime acceptance remains a documented blocker.
    from tempfile import TemporaryDirectory

    with TemporaryDirectory(prefix='algua-test-jit-') as cache:
        os.chown(cache, 65534, 65534)
        result = _unprivileged(script, paths=[str(site), deps],
                               env={**os.environ, 'NUMBA_CACHE_DIR': cache})
    assert result.returncode != 0
    assert result.stdout, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope['ok'] is False and 'installed enrollment refused' in envelope['error']
    assert (authority / 'allowed_signers').read_bytes() == before


def test_installed_coordination_ignores_development_lock_path(monkeypatch):
    from algua.operator import deployment_lock

    monkeypatch.setattr(deployment_lock, 'signer_anchor', installed)
    monkeypatch.setenv('ALGUA_OPERATOR_LOCK_PATH', '/tmp/evil')
    fixed = Path('/var/lib/algua-live/operator.lock')
    assert deployment_lock._operator_lock_path(lambda: Path('/tmp/evil')) == fixed
    assert deployment_lock._operator_lock_path() == fixed


def test_development_coordination_retains_existing_resolver():
    from algua.operator.deployment_lock import _operator_lock_path

    assert _operator_lock_path(lambda: Path('/test/checkout/.git/operator.lock')) == (
        Path('/test/checkout/.git/operator.lock'))


def test_installed_cli_lock_run_uses_same_transition_lock(monkeypatch):
    from contextlib import contextmanager

    from typer.testing import CliRunner

    from algua.cli import operator_cmd
    from algua.cli.main import app
    from algua.operator import deployment_lock

    seen = []

    @contextmanager
    def capture(path, **kwargs):
        seen.append(path)
        yield

    monkeypatch.setattr(deployment_lock, 'signer_anchor', installed)
    monkeypatch.setattr(operator_cmd, 'operator_run_lock', capture)
    monkeypatch.setattr(operator_cmd, '_resolve_git_dir', lambda: Path('/tmp/evil'))
    monkeypatch.setattr(operator_cmd, '_run_locked_command',
                        lambda argv: SimpleNamespace(returncode=0))
    result = CliRunner().invoke(app, ['operator', 'lock-run', '--', 'synthetic-no-op'])
    assert result.exit_code == 0, result.stdout
    assert seen == [Path('/var/lib/algua-live/operator.lock')]


@pytest.mark.parametrize('component', ['etc', 'algua', 'authority', 'allowed_signers',
                                       'installed.json'])
def test_symlink_at_each_authority_component_refuses(monkeypatch, tmp_path, component):
    root = tmp_path / 'root'
    authority = root / 'etc/algua/authority'
    authority.mkdir(parents=True)
    (authority / 'allowed_signers').write_bytes(b'synthetic')
    (authority / 'installed.json').write_text('{}')
    selected = next(path for path in root.rglob('*') if path.name == component)
    moved = selected.with_name(selected.name + '-real')
    selected.rename(moved)
    selected.symlink_to(moved, target_is_directory=moved.is_dir())
    real_open = os.open

    def open_test_root(path, flags, *, dir_fd=None):
        return real_open(root if path == '/' else path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(installed.os, 'open', open_test_root)
    monkeypatch.setattr(installed, '_check_fd', lambda *args, **kwargs: None)
    with pytest.raises(OSError):
        installed._read_authority()


@pytest.mark.parametrize('mode', ['unit', 'missing', 'conflicting'])
def test_live_service_mode_preflight_uses_actual_unit_argv(monkeypatch, mode):
    """Exercise the real CLI mode guard, stopping before registry, data or venue access."""
    import configparser
    import shlex

    from typer.testing import CliRunner

    from algua.cli import live_cmd
    from algua.cli.main import app

    unit = configparser.ConfigParser(interpolation=None)
    unit.read(REPO / 'deploy/systemd/algua-live.service')
    command = shlex.split(unit['Service']['ExecStart'])
    entry = '/usr/local/libexec/algua-live-entry'
    assert command[:5] == [entry, 'operator', 'lock-run', '--', entry]
    args = command[5:]
    assert args[:2] == ['live', 'run-all']
    if mode == 'missing':
        args = [value for value in args if value != '--refresh']
    elif mode == 'conflicting':
        args += ['--snapshot', 'synthetic-no-read']
    reached = []

    def stop_after_mode_selection(max_drawdown, disabled):
        reached.append((max_drawdown, disabled))
        raise ValueError('synthetic stop after mode selection')

    def refuse_effects():
        raise AssertionError('unit preflight must not reach registry or venue effects')

    monkeypatch.setattr(live_cmd, 'resolve_drawdown_breaker', stop_after_mode_selection)
    monkeypatch.setattr(live_cmd, 'registry_conn', refuse_effects)
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope['ok'] is False
    if mode == 'unit':
        assert reached == [(None, False)], envelope
        assert envelope['error'] == 'synthetic stop after mode selection'
    else:
        assert reached == []
        assert 'pass exactly one of --snapshot <id> or --refresh' in envelope['error']
