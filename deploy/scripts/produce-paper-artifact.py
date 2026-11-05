#!/usr/bin/env python3
"""Trusted CI preparation/packaging; never adopt, activate or execute application code."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Never

ALIASES = frozenset('.claude/skills/' + name for name in (
    'author-a-strategy', 'forage-inspirations', 'interpret-results', 'leap-hypotheses',
    'operating-algua', 'report-experiments', 'run-the-research-loop',
))
BUILDER = 'deploy/scripts/build-paper-release.py'
SELF = 'deploy/scripts/produce-paper-artifact.py'
WORKFLOW = '.github/workflows/paper-application-artifact.yml'


def require(value: Any, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(root: Path, *args: str, data: str | None = None, strip: bool = True) -> str:
    env = {'PATH': '/usr/bin:/bin:/usr/local/bin', 'HOME': '/nonexistent',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'core.hooksPath',
           'GIT_CONFIG_VALUE_0': '/dev/null', 'GIT_CONFIG_KEY_1': 'core.fsmonitor',
           'GIT_CONFIG_VALUE_1': 'false', 'GIT_TERMINAL_PROMPT': '0'}
    result = subprocess.run(['git', '-C', str(root), *args], input=data, env=env,
                            capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, 'trusted_git_command_failed')
    return result.stdout.strip() if strip else result.stdout


def files(root: Path, *, skip_git: bool = True):
    """Prune candidate metadata BEFORE descent; never open its config, hooks or objects."""
    require(root.is_dir() and not root.is_symlink(), 'tree_root')
    for base, dirs, names in os.walk(root, topdown=True, followlinks=False):
        if skip_git and Path(base) == root:
            dirs[:] = [name for name in dirs if name != '.git']
            names[:] = [name for name in names if name != '.git']
        for name in sorted(dirs + names):
            path = Path(base) / name
            require(name != '.git' or not skip_git, 'nested_git_metadata')
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), 'unsafe_tree_entry')
            if stat.S_ISREG(info.st_mode):
                yield path.relative_to(root).as_posix(), path


def load(path: Path) -> dict:
    require(stat.S_ISREG(path.lstat().st_mode), 'json_regular_file')
    require(path.stat().st_size <= 8 * 1024 * 1024, 'json_bound')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, 'duplicate_json_key')
            out[key] = value
        return out
    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))


def prepare(repository: Path, source: str, recipe: str, target: Path,
            context: Path, base_image: str) -> dict:
    require(re.fullmatch('[0-9a-f]{40}', source) and re.fullmatch('[0-9a-f]{40}', recipe),
            'exact_source_and_recipe_commits')
    require(git(repository, 'rev-parse', 'HEAD') == recipe, 'recipe_checkout_mismatch')
    main = git(repository, 'rev-parse', 'refs/remotes/origin/main')
    git(repository, 'merge-base', '--is-ancestor', source, main)
    git(repository, 'merge-base', '--is-ancestor', recipe, main)
    for name in (BUILDER, SELF, WORKFLOW):
        require(git(repository, 'show', recipe + ':' + name, strip=False) ==
                (repository / name).read_text(), 'recipe_file_drift')
    require(not target.exists() and not context.exists(), 'preparation_exists')
    target.mkdir()
    git(target, 'init', '--bare', '--quiet', '--initial-branch=main', '--template=')
    git(target, 'fetch', '--quiet', '--depth=1', '--no-tags', str(repository), source)
    git(target, 'update-ref', 'refs/heads/main', source)
    (target / 'FETCH_HEAD').unlink()
    record = {'schema': 'algua-paper-ci-source/v1', 'source_commit': source,
              'recipe_commit': recipe, 'verified_main': main,
              'builder_sha256': sha(repository / BUILDER),
              'packager_sha256': sha(repository / SELF), 'base_image': base_image}
    context.write_bytes(canonical(record) + b'\n')
    return record


def reconstructed_checkout(source: Path, commit: str, output: Path) -> None:
    output.mkdir()
    git(output, 'init', '--quiet', '--initial-branch=main', '--template=')
    for key, value in [('core.hooksPath', '/dev/null'), ('core.fsmonitor', 'false'),
                       ('core.logAllRefUpdates', 'false')]:
        git(output, 'config', key, value)
    git(output, 'fetch', '--quiet', '--depth=1', '--no-tags', str(source), commit)
    git(output, 'sparse-checkout', 'init', '--no-cone')
    git(output, 'sparse-checkout', 'set', '--no-cone', '--stdin',
        data='/*\n' + ''.join('!/' + name + '\n' for name in sorted(ALIASES)))
    git(output, 'checkout', '--quiet', '--no-track', '-B', 'main', commit)
    (output / '.git/FETCH_HEAD').unlink()


def package(release: Path, descriptor: Path, source: Path, context: Path, output: Path) -> dict:
    record, spec = load(context), load(descriptor)
    require(set(spec) == {'path', 'commit', 'lock_sha256', 'files', 'digest'}, 'release_shape')
    require(spec['commit'] == record['source_commit'], 'source_commit_mismatch')
    payload = {key: spec[key] for key in ('commit', 'lock_sha256', 'files')}
    require(hashlib.sha256(canonical(payload)).hexdigest() == spec['digest'], 'release_digest')
    materialized = dict(files(release))
    require({name: sha(path) for name, path in materialized.items()} == spec['files'],
            'release_inventory_mismatch')
    require(spec['files']['uv.lock'] == spec['lock_sha256'], 'lock_mismatch')
    profile = load(release / 'application-runtime.json')
    require(profile['commit'] == spec['commit'] and
            profile['builder_sha256'] == record['builder_sha256'], 'builder_source_mismatch')
    require(sha(Path(__file__)) == record['packager_sha256'], 'packager_source_mismatch')
    require(not output.exists(), 'package_exists')
    with TemporaryDirectory(prefix='paper-ci-git-') as temporary:
        clean = Path(temporary) / 'checkout'
        reconstructed_checkout(source, spec['commit'], clean)
        for name, path in files(clean):
            require(name in materialized and sha(path) == sha(materialized[name]),
                    'tracked_source_mismatch')
        metadata = dict(files(clean / '.git', skip_git=False))
        output.mkdir()
        archive = output / 'application.tar.gz'
        with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
            directories = {'release', 'release/.git'}
            for prefix, entries in [('release', materialized), ('release/.git', metadata)]:
                for name in entries:
                    parent = Path(prefix) / Path(name).parent
                    directories.update(str(path) for path in (parent, *parent.parents)
                                       if str(path) != '.')
            for name in sorted(directories, key=lambda item: (item.count('/'), item)):
                info = tarfile.TarInfo(name)
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                info.uid, info.gid = os.getuid(), os.getgid()
                tar.addfile(info)
            for prefix, entries in [('release', materialized), ('release/.git', metadata)]:
                for name, path in sorted(entries.items()):
                    info = tar.gettarinfo(str(path), arcname=prefix + '/' + name)
                    executable = prefix == 'release' and path.stat().st_mode & 0o111
                    info.mode = 0o755 if executable else 0o644
                    info.uname = info.gname = ''
                    with path.open('rb') as stream:
                        tar.addfile(info, stream)
        shutil.copyfile(descriptor, output / 'release-spec.json')
        provenance = {**record, 'schema': 'algua-paper-ci-artifact/v1',
                      'application_digest': spec['digest'], 'trusted': False,
                      'adoption_approved': False, 'external_base_compatibility': 'UNVERIFIED',
                      'declared_external_base': profile.get('external_base_python'),
                      'git_metadata': 'reconstructed; candidate Git never read or executed',
                      'git_metadata_digest': hashlib.sha256(canonical(
                          {name: sha(path) for name, path in metadata.items()})).hexdigest()}
        (output / 'provenance.json').write_bytes(canonical(provenance) + b'\n')
        (output / 'SHA256SUMS').write_text(''.join(
            sha(output / name) + '  ' + name + '\n'
            for name in ('application.tar.gz', 'release-spec.json', 'provenance.json')))
    return provenance


def main() -> int:
    class Parser(argparse.ArgumentParser):
        def error(self, message: str) -> Never:
            raise ValueError('invalid_arguments')
    try:
        parser = Parser()
        commands = parser.add_subparsers(dest='command', required=True)
        prep = commands.add_parser('prepare')
        for name in ('repository', 'input', 'context'):
            prep.add_argument('--' + name, type=Path, required=True)
        for name in ('source-sha', 'recipe-sha', 'base-image'):
            prep.add_argument('--' + name, required=True)
        pack = commands.add_parser('package')
        for name in ('release', 'descriptor', 'input', 'context', 'output'):
            pack.add_argument('--' + name, type=Path, required=True)
        args = parser.parse_args()
        if args.command == 'prepare':
            prepare(args.repository, args.source_sha, args.recipe_sha, args.input,
                    args.context, args.base_image)
        else:
            package(args.release, args.descriptor, args.input, args.context, args.output)
        print(json.dumps({'ok': True, 'trusted': False}))
        return 0
    except Exception as exc:
        print(json.dumps({'ok': False, 'code': str(exc) if isinstance(exc, ValueError)
                          else 'artifact_producer_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
