#!/usr/bin/env python3
"""Assemble one product with a build-time authority policy; NEVER adopt or authorize it."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Never


def _helper():
    path = Path(__file__).with_name('build-paper-release.py')
    spec = importlib.util.spec_from_file_location('application_materializer', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assemble_policy(root: Path, *, development: bool) -> dict[str, str]:
    """Replace every application copy, remove alternatives and verify exact installed bytes."""
    source = root / 'algua/registry'
    name = 'signer_anchor_dev.py' if development else 'signer_anchor_installed.py'
    policy = (source / name).read_bytes()
    registries = [source, *root.glob('.venv/lib/python*/site-packages/algua/registry')]
    if len(registries) != 2:
        raise ValueError('exactly_one_installed_package_required')
    lock = (root / 'uv.lock').read_bytes()
    for registry in registries:
        (registry.parents[1] / 'uv.lock').write_bytes(lock)
        (registry / 'signer_anchor.py').write_bytes(policy)
        for alternate in ('signer_anchor_dev.py', 'signer_anchor_installed.py'):
            (registry / alternate).unlink()
    # Cached bytecode and the source git object database can retain the development loader.
    # They are not needed by the installed noneditable application.
    for cache in list(root.rglob('__pycache__')):
        shutil.rmtree(cache)
    shutil.rmtree(root / '.git', ignore_errors=True)
    if development:
        shutil.copytree(root / 'approvers', registries[1].parents[1] / 'approvers')
    else:
        shutil.rmtree(root / 'approvers', ignore_errors=True)
    for path in root.rglob('signer_anchor*'):
        if path.name != 'signer_anchor.py' or path.read_bytes() != policy:
            raise ValueError('authority_policy_separation_failed')
    return {str(p.relative_to(root) / 'signer_anchor.py'): hashlib.sha256(policy).hexdigest()
            for p in registries}


def build(repository: Path, commit: str, output: Path, descriptor: Path,
          *, development: bool = False) -> dict:
    helper = _helper()
    helper.require(sys.platform == 'linux', 'linux_build_required')
    helper.require(not descriptor.exists(), 'descriptor_exists')
    helper.require(not descriptor.resolve().is_relative_to(output.resolve()),
                   'descriptor_inside_output')
    with TemporaryDirectory(prefix='algua-authority-build-') as private:
        # Reuse dependency materialization, never its paper descriptor as live authority.
        helper.build(repository, commit, output, Path(private) / 'application.json')
    policy_files = assemble_policy(output, development=development)
    profile = 'algua-development/v1' if development else 'algua-installed-live/v1'
    if not development:
        template = output / 'deploy/scripts/algua-live-entry'
        template.write_text(template.read_text().replace('@COMMIT@', commit))
    runtime = json.loads((output / 'application-runtime.json').read_text())
    runtime.update(profile=profile, trusted_or_approved=False,
                   authority_policy_files=policy_files,
                   startup='Python -I -S; explicit site-packages; no .pth execution',
                   installed_acceptance='BLOCKED: runtime/UID/isolation/outage review required')
    (output / 'application-runtime.json').write_bytes(helper.canonical(runtime) + b'\n')
    files = helper.inventory(output)
    payload = {'schema': profile, 'commit': commit, 'files': files,
               'authority_policy_files': policy_files, 'trusted_or_approved': False}
    result = {**payload, 'digest': hashlib.sha256(helper.canonical(payload)).hexdigest()}
    with descriptor.open('x') as stream:
        json.dump(result, stream, sort_keys=True)
        stream.write('\n')
    return result


def main() -> int:
    try:
        class Parser(argparse.ArgumentParser):
            def error(self, message: str) -> Never:
                raise ValueError('invalid_arguments')

        parser = Parser(description=__doc__)
        parser.add_argument('--repository', type=Path, required=True)
        parser.add_argument('--commit', required=True)
        parser.add_argument('--output', type=Path, required=True)
        parser.add_argument('--descriptor', type=Path, required=True)
        parser.add_argument('--development', action='store_true')
        args = parser.parse_args()
        result = build(args.repository, args.commit, args.output, args.descriptor,
                       development=args.development)
        print(json.dumps({'ok': True, 'trusted': False, 'digest': result['digest'],
                          'installed_acceptance': 'blocked'}))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc), 'code': 'authority_build_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
