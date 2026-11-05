"""Synthetic operator adoption only: no GitHub fetch or artifact execution."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tarfile
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'linux' or os.geteuid() != 0,
    reason='disposable root-owned Linux fixture, never production adoption')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def outer(package):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name in ('application.tar.gz', 'release-spec.json', 'provenance.json', 'SHA256SUMS'):
            archive.write(package / name, name)
    return output.getvalue()


@pytest.fixture
def case():
    directory = Path('/paper/adoption-fixture-' + uuid4().hex)
    directory.mkdir(mode=0o755)
    try:
        for name in ('adopt-paper-artifact.py', 'paper_archive.py'):
            shutil.copyfile(ROOT / 'deploy/scripts' / name, directory / name)
        adopter = module('adopter', directory / 'adopt-paper-artifact.py')
        archive = adopter.support()
        producer = module('producer', ROOT / 'deploy/scripts/produce-paper-artifact.py')
        base = directory / 'base'
        base.mkdir()
        binary = base / 'python'
        binary.write_text('#!/bin/sh\necho MUST_NOT_EXECUTE\nexit 99\n')
        binary.chmod(0o755)
        stdlib = base / 'stdlib'
        stdlib.mkdir()
        (stdlib / 'fixture.py').write_text('raise RuntimeError("MUST_NOT_IMPORT")\n')
        base_request = {'approval_ref': 'synthetic-base-owner-decision', 'ci_image': 'fixture-base',
            'python_path': str(binary), 'python_sha256': archive.sha(binary),
            'stdlib_path': str(stdlib), 'stdlib_py_digest': producer.hashlib.sha256(
                archive.canonical({'fixture.py': archive.sha(stdlib / 'fixture.py')})).hexdigest(),
            'os_release_sha256': archive.sha(Path('/etc/os-release').resolve()),
            'machine': os.uname().machine, 'libc': os.confstr('CS_GNU_LIBC_VERSION')}
        recipe = directory / 'recipe'
        recipe.mkdir()
        producer.git(recipe, 'init', '-q', '-b', 'main', '--template=')
        (recipe / 'uv.lock').write_text('synthetic lock\n')
        (recipe / 'runtime.py').write_text('raise RuntimeError("MUST_NOT_EXECUTE")\n')
        (recipe / '.claude/skills').mkdir(parents=True)
        for name in producer.ALIASES:
            (recipe / name).symlink_to('../../.opencode/skills/' + Path(name).name)
        for name in (producer.BUILDER, producer.SELF, producer.WORKFLOW):
            target = recipe / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        producer.git(recipe, 'add', '.')
        producer.git(recipe, '-c', 'user.name=Fixture', '-c', 'user.email=x@example.invalid',
                     'commit', '-qm', 'synthetic approved source and recipe')
        source = producer.git(recipe, 'rev-parse', 'HEAD')
        producer.git(recipe, 'update-ref', 'refs/remotes/origin/main', source)
        bare, context = directory / 'input.git', directory / 'context.json'
        producer.prepare(recipe, source, source, bare, context, 'fixture-base')
        release = directory / 'candidate'
        producer.reconstructed_checkout(bare, source, release)
        (release / '.venv/bin').mkdir(parents=True)
        (release / '.venv/bin/algua').write_text('#!/bin/sh\nexit 99\n')
        (release / '.venv/bin/algua').chmod(0o755)
        profile = {'commit': source, 'builder_sha256': producer.sha(recipe / producer.BUILDER),
            'external_base_python': {key: base_request[value] for key, value in
                [('path', 'python_path'), ('sha256', 'python_sha256'),
                 ('stdlib', 'stdlib_path'), ('stdlib_py_digest', 'stdlib_py_digest')]}}
        (release / 'application-runtime.json').write_text(json.dumps(profile))
        inventory = {name: archive.sha(path) for name, path in producer.files(release)}
        payload = {'commit': source, 'lock_sha256': inventory['uv.lock'], 'files': inventory}
        descriptor = directory / 'descriptor.json'
        descriptor.write_bytes(archive.canonical({'path': str(release), **payload,
            'digest': producer.hashlib.sha256(archive.canonical(payload)).hexdigest()}))
        package = directory / 'package'
        provenance = producer.package(release, descriptor, bare, context, package)
        request = {'schema': 'algua-paper-adoption/v1', 'approval_ref': 'fixture-exact-artifact',
            'repository_id': 123, 'run_id': 234, 'run_attempt': 2, 'artifact_id': 345,
            'artifact_sha256': '', 'recipe_commit': source, 'source_commit': source,
            'application_digest': provenance['application_digest'],
            'provenance_sha256': archive.sha(package / 'provenance.json'),
            'base': base_request, 'destination': str(directory / 'adopted')}
        yield directory, adopter, archive, producer, package, request
    finally:
        for current, _dirs, _files in os.walk(directory, topdown=False):
            Path(current).chmod(0o700)
        shutil.rmtree(directory)


def network(monkeypatch, case, *, wrong_run=False, wrong_digest=False):
    directory, adopter, archive, producer, package, req = case
    data = outer(package)
    req['artifact_sha256'] = producer.hashlib.sha256(data).hexdigest()
    run = {'id': 999 if wrong_run else req['run_id'], 'run_attempt': req['run_attempt'],
        'status': 'completed', 'conclusion': 'success', 'event': 'workflow_dispatch',
        'head_branch': 'main', 'head_sha': req['recipe_commit'], 'path': adopter.WORKFLOW,
        'repository': {'id': req['repository_id']}}
    artifact = {'id': req['artifact_id'], 'name':
        f"paper-application-{req['source_commit']}-{req['run_id']}-{req['run_attempt']}",
        'expired': False, 'size_in_bytes': len(data), 'digest': 'sha256:' +
        ('0' * 64 if wrong_digest else req['artifact_sha256']), 'workflow_run': {
            'id': req['run_id'], 'repository_id': req['repository_id'],
            'head_repository_id': req['repository_id'], 'head_sha': req['recipe_commit']}}
    calls = []

    class Response(io.BytesIO):
        def __init__(self, body=b'', status=200, headers=None):
            super().__init__(body)
            self.status, self.headers = status, headers or {}

    def response(url, token=None):
        calls.append((url, token))
        if url.endswith('/zip'):
            return Response(status=302, headers={
                'Location': 'https://fixture.blob.core.windows.net/object?signature=fixture'})
        if url.startswith('https://fixture.blob.'):
            return Response(data)
        return Response(json.dumps(artifact if '/artifacts/' in url else run).encode())

    monkeypatch.setattr(adopter, 'request', response)
    approval = directory / 'approval.json'
    approval.write_text(json.dumps(req))
    return approval, calls


def test_verified_synthetic_adoption_preserves_consumer_descriptor_without_artifact_execution(
        case, monkeypatch):
    directory, adopter, archive, _producer, _package, req = case
    approval, calls = network(monkeypatch, case)
    import subprocess
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: pytest.fail('artifact execution'))
    result = adopter.adopt(approval, 'synthetic-private-token')
    destination = Path(req['destination'])
    spec = archive.read_json(destination / 'release-spec.json', 8 * 1024**2)
    assert set(spec) == {'path', 'commit', 'lock_sha256', 'files', 'digest'}
    assert spec['path'] == str(destination / 'release')
    assert spec['digest'] == req['application_digest']
    assert result['activated'] is result['release_approved'] is result['approval_minted'] is False
    assert all(token == 'synthetic-private-token' for url, token in calls
               if url.startswith(adopter.API))
    assert [token for url, token in calls if url.startswith('https://fixture.blob.')] == [None]
    assert all(p.stat().st_uid == 0 and not p.stat().st_mode & 0o022
               for p in destination.rglob('*'))
    assert not list(directory.glob('.paper-adopt-*'))


@pytest.mark.parametrize('failure', ['run', 'digest', 'base', 'existing', 'race'])
def test_identity_base_and_no_clobber_refusals(case, monkeypatch, failure):
    directory, adopter, _archive, _producer, _package, req = case
    approval, _calls = network(monkeypatch, case, wrong_run=failure == 'run',
                              wrong_digest=failure == 'digest')
    destination = Path(req['destination'])
    if failure == 'base':
        Path(req['base']['python_path']).write_text('different base\n')
    if failure == 'existing':
        destination.mkdir()
        (destination / 'preserve').write_text('existing')
    if failure == 'race':
        import algua.primitives.no_replace as primitive
        original = primitive.rename_noreplace
        def racing(source, target):
            target.mkdir()
            (target / 'preserve').write_text('racing writer')
            original(source, target)
        monkeypatch.setattr(primitive, 'rename_noreplace', racing)
    with pytest.raises((ValueError, FileExistsError)):
        adopter.adopt(approval)
    if failure in {'existing', 'race'}:
        assert (destination / 'preserve').is_file()
        assert list(destination.iterdir()) == [destination / 'preserve']
    else:
        assert not destination.exists()
    assert not list(directory.glob('.paper-adopt-*'))


@pytest.mark.parametrize('kind', ['duplicate', 'traversal', 'symlink', 'hardlink', 'special'])
def test_unsafe_archive_members_refuse_without_publication(case, monkeypatch, kind):
    directory, adopter, _archive, producer, package, req = case
    with tarfile.open(package / 'application.tar.gz', 'w:gz') as stream:
        member = tarfile.TarInfo('release/../escape' if kind == 'traversal' else 'release')
        member.type = {'symlink': tarfile.SYMTYPE, 'hardlink': tarfile.LNKTYPE,
                       'special': tarfile.FIFOTYPE}.get(kind, tarfile.DIRTYPE)
        member.linkname = '/untrusted'
        stream.addfile(member)
        if kind == 'duplicate':
            stream.addfile(member)
    (package / 'SHA256SUMS').write_text(''.join(
        producer.sha(package / name) + '  ' + name + '\n'
        for name in ('application.tar.gz', 'provenance.json', 'release-spec.json')))
    approval, _calls = network(monkeypatch, case)
    with pytest.raises(ValueError, match='tar_'):
        adopter.adopt(approval)
    assert not Path(req['destination']).exists() and not (directory / 'escape').exists()
    assert not list(directory.glob('.paper-adopt-*'))


def test_helper_ignores_timestamp_valid_poisoned_bytecode(case):
    import py_compile

    directory, adopter, _archive, _producer, _package, _req = case
    helper = directory / 'paper_archive.py'
    info = helper.stat()
    marker = directory / 'POISONED_CACHE_EXECUTED'
    poison = directory / 'poison.py'
    payload = f'from pathlib import Path\nPath({str(marker)!r}).write_text("poisoned")\n'
    poison.write_text(payload + '#' * (info.st_size - len(payload.encode())))
    os.utime(poison, ns=(info.st_atime_ns, info.st_mtime_ns))
    cache = Path(importlib.util.cache_from_source(str(helper)))
    cache.parent.mkdir(exist_ok=True)
    py_compile.compile(str(poison), cfile=str(cache), doraise=True)
    os.chown(cache, 1001, 1001)
    adopter.support()
    assert not marker.exists()


def test_runtime_owned_native_stdlib_entry_refuses_before_download(case, monkeypatch):
    directory, adopter, _archive, _producer, _package, req = case
    dynamic = Path(req['base']['stdlib_path']) / 'lib-dynload'
    dynamic.mkdir()
    extension = dynamic / 'fixture.so'
    extension.write_bytes(b'opaque native fixture, never loaded')
    os.chown(extension, 1001, 1001)
    approval, calls = network(monkeypatch, case)
    with pytest.raises(ValueError, match='root_control_required'):
        adopter.adopt(approval)
    assert calls == [] and not Path(req['destination']).exists()
    assert not list(directory.glob('.paper-adopt-*'))


def test_approval_rewrite_during_fetch_cannot_reattribute_original_request(case, monkeypatch):
    _directory, adopter, _archive, producer, _package, req = case
    approval, _calls = network(monkeypatch, case)
    original_sha = producer.sha(approval)
    original_ref = req['approval_ref']
    original = adopter.request

    def rewrite(url, token=None):
        if url.startswith('https://fixture.blob.'):
            changed = dict(req, approval_ref='different-later-owner-request')
            approval.write_text(json.dumps(changed))
        return original(url, token)

    monkeypatch.setattr(adopter, 'request', rewrite)
    result = adopter.adopt(approval)
    assert producer.sha(approval) != original_sha
    assert result['request_sha256'] == original_sha
    assert result['approval_ref'] == original_ref


def test_dribbling_download_hits_deadline_and_removes_private_stage(case, monkeypatch):
    import signal
    from types import SimpleNamespace

    directory, adopter, _archive, _producer, _package, req = case
    approval, _calls = network(monkeypatch, case)
    original = adopter.request
    elapsed = [0.0]

    class Dribble(io.BytesIO):
        status = 200
        progress_reads = 0

        def read(self, amount=-1):
            elapsed[0] += 601  # a full-chunk read can outlive the intended wall budget
            return b''

        def read1(self, amount=-1):
            assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
            self.progress_reads += 1
            elapsed[0] += 17  # successful small reads continually reset a socket timeout
            return b'x'

    response = Dribble()
    monkeypatch.setattr(adopter, 'time', SimpleNamespace(monotonic=lambda: elapsed[0]))
    monkeypatch.setattr(adopter, 'request', lambda url, token=None: response
        if url.startswith('https://fixture.blob.') else original(url, token))
    with pytest.raises(ValueError, match='download_bound'):
        adopter.adopt(approval)
    assert 0 < response.progress_reads <= 18 and elapsed[0] <= 330
    assert response.closed and not Path(req['destination']).exists()
    assert not list(directory.glob('.paper-adopt-*'))
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
