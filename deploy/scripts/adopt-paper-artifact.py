#!/usr/bin/env python3
"""Explicit owner-approved file adoption only; no artifact code, release or activation."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import ModuleType

API = 'https://api.github.com/repos/its-nix/algua'
WORKFLOW = '.github/workflows/paper-application-artifact.yml'
KEYS = {'schema', 'approval_ref', 'repository_id', 'run_id', 'run_attempt', 'artifact_id',
        'artifact_sha256', 'recipe_commit', 'source_commit', 'application_digest',
        'provenance_sha256', 'base', 'destination'}
BASE_KEYS = {'approval_ref', 'ci_image', 'python_path', 'python_sha256', 'stdlib_path',
             'stdlib_py_digest', 'os_release_sha256', 'machine', 'libc'}


def require(ok, code):
    if not ok:
        raise ValueError(code)


def controlled(path):
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid == 0
                and not info.st_mode & 0o022, 'root_control_required')


def support():
    path = Path(__file__).with_name('paper_archive.py')
    controlled(path)
    module = ModuleType('paper_archive')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, token=None):
    headers = {'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2026-03-10'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
    try:
        return opener.open(urllib.request.Request(url, headers=headers), timeout=30)
    except urllib.error.HTTPError as response:
        if response.code == 302:
            return response
        raise ValueError('github_http_error') from None


def api(path, token):
    with request(API + path, token) as response:
        require(response.status == 200, 'github_http_status')
        raw = response.read(1024**2 + 1)
        require(len(raw) <= 1024**2, 'api_size')
        return json.loads(raw)


def check_base(base, archive):
    require(set(base) == BASE_KEYS and 1 <= len(base['approval_ref']) <= 200, 'base_approval')
    binary, stdlib = Path(base['python_path']), Path(base['stdlib_path'])
    require(all(path.is_absolute() and path.resolve() == path for path in (binary, stdlib)),
            'base_path')
    controlled(binary)
    controlled(stdlib)
    require(binary.is_file() and stdlib.is_dir(), 'base_missing')
    require(archive.sha(binary) == base['python_sha256'], 'base_python_mismatch')
    sources = {}
    for path in sorted(stdlib.rglob('*')):
        controlled(path)
        require(path.is_dir() or stat.S_ISREG(path.lstat().st_mode), 'base_entry')
        if path.suffix == '.py' and 'site-packages' not in path.relative_to(stdlib).parts:
            sources[path.relative_to(stdlib).as_posix()] = archive.sha(path)
    require(hashlib.sha256(archive.canonical(sources)).hexdigest()
            == base['stdlib_py_digest'], 'base_stdlib_mismatch')
    os_release = Path('/etc/os-release').resolve()
    controlled(os_release)
    require(archive.sha(os_release) == base['os_release_sha256']
            and os.uname().machine == base['machine']
            and os.confstr('CS_GNU_LIBC_VERSION') == base['libc'], 'base_os_mismatch')


def download_timeout(_signum, _frame):
    raise ValueError('download_bound')


def fetch_zip(req, token, path, archive):
    run = api(f"/actions/runs/{req['run_id']}/attempts/{req['run_attempt']}", token)
    artifact = api(f"/actions/artifacts/{req['artifact_id']}", token)
    require(run['id'] == req['run_id'] and run['run_attempt'] == req['run_attempt']
            and run['status'] == 'completed' and run['conclusion'] == 'success'
            and run['event'] == 'workflow_dispatch' and run['head_branch'] == 'main'
            and run['head_sha'] == req['recipe_commit']
            and run['path'].split('@')[0] == WORKFLOW
            and run['repository']['id'] == req['repository_id'], 'run_identity')
    associated = artifact['workflow_run']
    name = f"paper-application-{req['source_commit']}-{req['run_id']}-{req['run_attempt']}"
    require(artifact['id'] == req['artifact_id'] and artifact['name'] == name
            and artifact['expired'] is False and artifact['size_in_bytes'] <= archive.MAX_ZIP
            and artifact['digest'] == 'sha256:' + req['artifact_sha256']
            and associated['id'] == req['run_id']
            and associated['repository_id'] == associated['head_repository_id']
            == req['repository_id'] and associated['head_sha'] == req['recipe_commit'],
            'artifact_identity')
    with request(f"{API}/actions/artifacts/{req['artifact_id']}/zip", token) as response:
        require(response.status == 302, 'artifact_redirect')
        location = response.headers['Location']
    target = urllib.parse.urlsplit(location)
    require(target.scheme == 'https' and not target.username and not target.password
            and target.port in {None, 443} and not target.fragment
            and (target.hostname.endswith('.blob.core.windows.net')
                 or target.hostname.endswith('.githubusercontent.com')), 'storage_redirect')
    started, size = time.monotonic(), 0
    previous = signal.signal(signal.SIGALRM, download_timeout)
    timer = signal.setitimer(signal.ITIMER_REAL, 300)
    try:
        with request(location) as response, path.open('xb') as stream:
            require(response.status == 200, 'storage_http_status')
            while True:
                require(time.monotonic() - started < 300, 'download_bound')
                chunk = response.read1(64 * 1024)
                size += len(chunk)
                require(size <= archive.MAX_ZIP and time.monotonic() - started <= 300,
                        'download_bound')
                if not chunk:
                    break
                stream.write(chunk)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        remaining = max(0.000001, timer[0] - (time.monotonic() - started)) if timer[0] else 0
        signal.setitimer(signal.ITIMER_REAL, remaining, timer[1])
    require(archive.sha(path) == req['artifact_sha256'], 'artifact_checksum')


def adopt(request_path, token=None):
    require(os.geteuid() == 0, 'root_operator_required')
    controlled(request_path)
    archive = support()
    approval = archive.read_raw(request_path, 64 * 1024)
    req = archive.parse_json(approval)
    require(set(req) == KEYS and req['schema'] == 'algua-paper-adoption/v1'
            and 1 <= len(req['approval_ref']) <= 200, 'approval_shape')
    for key in ('repository_id', 'run_id', 'run_attempt', 'artifact_id'):
        require(type(req[key]) is int and req[key] > 0, 'identity_type')
    for key in ('recipe_commit', 'source_commit'):
        require(re.fullmatch('[0-9a-f]{40}', req[key]), 'commit_type')
    for key in ('artifact_sha256', 'application_digest', 'provenance_sha256'):
        require(re.fullmatch('[0-9a-f]{64}', req[key]), 'digest_type')
    destination = Path(req['destination'])
    require(destination.is_absolute() and destination.parent.resolve() == destination.parent
            and re.fullmatch('/[A-Za-z0-9/._-]+', str(destination)), 'destination_path')
    controlled(destination.parent)
    require(not destination.exists() and not destination.is_symlink(), 'destination_exists')
    check_base(req['base'], archive)
    stage = Path(tempfile.mkdtemp(prefix='.paper-adopt-', dir=destination.parent))
    stage.chmod(0o700)
    try:
        download = stage / 'download.zip'
        fetch_zip(req, token, download, archive)
        root, spec, provenance = archive.unpack(download, stage)
        require(archive.sha(stage / 'provenance.json') == req['provenance_sha256'],
                'provenance_digest')
        require(provenance['schema'] == 'algua-paper-ci-artifact/v1'
                and spec['commit'] == provenance['source_commit'] == req['source_commit']
                and spec['digest'] == provenance['application_digest'] == req['application_digest']
                and provenance['recipe_commit'] == req['recipe_commit']
                and provenance['base_image'] == req['base']['ci_image']
                and provenance['trusted'] is False, 'approved_provenance')
        profile = archive.read_json(root / 'application-runtime.json', 64 * 1024)
        expected = {key: req['base'][name] for key, name in
                    [('path', 'python_path'), ('sha256', 'python_sha256'),
                     ('stdlib', 'stdlib_path'), ('stdlib_py_digest', 'stdlib_py_digest')]}
        require(profile['external_base_python'] == expected
                and profile['commit'] == req['source_commit']
                and profile['builder_sha256'] == provenance['builder_sha256'], 'base_profile')
        download.unlink()
        (stage / 'application.tar.gz').unlink()
        (stage / 'SHA256SUMS').unlink()
        spec['path'] = str(destination / 'release')
        (stage / 'release-spec.json').write_bytes(archive.canonical(spec) + b'\n')
        receipt = {'schema': 'algua-paper-adoption-receipt/v1', 'approval_ref': req['approval_ref'],
                   'request_sha256': hashlib.sha256(approval).hexdigest(),
                   'artifact_id': req['artifact_id'],
                   'run_id': req['run_id'], 'run_attempt': req['run_attempt'],
                   'artifact_sha256': req['artifact_sha256'], 'recipe_commit': req['recipe_commit'],
                   'source_commit': req['source_commit'],
                   'base_approval_ref': req['base']['approval_ref'],
                   'application_digest': spec['digest'], 'release_approved': False,
                   'activated': False, 'approval_minted': False}
        (stage / 'adoption.json').write_bytes(archive.canonical(receipt) + b'\n')
        root.chmod(0o555)
        for name in ('release-spec.json', 'provenance.json', 'adoption.json'):
            (stage / name).chmod(0o444)
        stage.chmod(0o555)
        from algua.primitives.no_replace import rename_noreplace
        rename_noreplace(stage, destination)
        return receipt
    finally:
        if stage.exists():
            for base, _dirs, _files in os.walk(stage, topdown=False):
                Path(base).chmod(0o700)
            shutil.rmtree(stage)


def main():
    try:
        require(os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site,
                'trusted_root_isolated_operator_required')
        controlled(Path(__file__).absolute())
        controlled(Path(sys.executable).resolve())
        root = Path(__file__).absolute().parents[2]
        for path in (root / 'algua').rglob('*'):
            controlled(path)
        sys.path.insert(0, str(root))
        require(len(sys.argv) in {2, 3}, 'usage_request_optional_token_fd')
        require(len(sys.argv) == 2 or sys.argv[2].isdigit(), 'token_fd')
        token = os.read(int(sys.argv[2]), 4097).decode().strip() if len(sys.argv) == 3 else None
        require(token is None or len(token) <= 4096, 'token_bound')
        print(json.dumps({'ok': True, **adopt(Path(sys.argv[1]), token)}))
        return 0
    except Exception as exc:
        code = str(exc)
        print(json.dumps({'ok': False, 'code': code if re.fullmatch('[a-z_]{1,80}', code)
                          else 'artifact_adoption_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
