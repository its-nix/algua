"""Focused real Git/archive checks; no workflow dispatch or application execution."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'producer', ROOT / 'deploy/scripts/produce-paper-artifact.py')
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


def commit(repo, message):
    producer.git(repo, 'add', '.')
    producer.git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                 'commit', '-qm', message)
    return producer.git(repo, 'rev-parse', 'HEAD')


def world(path):
    recipe = path / 'recipe'
    recipe.mkdir()
    producer.git(recipe, 'init', '-q', '-b', 'main', '--template=')
    (recipe / 'uv.lock').write_text('fixture lock\n')
    (recipe / 'runtime.py').write_text('MARKER = "source fixture"\n')
    (recipe / '.claude/skills').mkdir(parents=True)
    for name in producer.ALIASES:
        (recipe / name).symlink_to('../../.opencode/skills/' + Path(name).name)
    source = commit(recipe, 'source')
    for name in (producer.BUILDER, producer.SELF, producer.WORKFLOW):
        target = recipe / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    trusted = commit(recipe, 'trusted recipe')
    producer.git(recipe, 'update-ref', 'refs/remotes/origin/main', trusted)
    with (recipe / '.git/config').open('a') as stream:
        stream.write('\n[http]\n extraheader = AUTHORIZATION: fixture-token-not-for-build\n')
    return recipe, source, trusted


def test_prepare_requires_exact_main_ancestry_and_sanitizes_checkout_metadata(tmp_path):
    recipe, source, trusted = world(tmp_path)
    producer.git(recipe, 'checkout', '-qb', 'unmerged')
    (recipe / 'unmerged.txt').write_text('not eligible\n')
    unmerged = commit(recipe, 'unmerged')
    producer.git(recipe, 'checkout', '-q', 'main')
    target, context = tmp_path / 'input.git', tmp_path / 'context.json'
    with pytest.raises(ValueError, match='trusted_git_command_failed'):
        producer.prepare(recipe, unmerged, trusted, target, context, 'fixture-base@sha256:x')
    assert not target.exists() and not context.exists()
    result = producer.prepare(recipe, source, trusted, target, context, 'fixture-base@sha256:x')
    assert result['source_commit'] == source and result['recipe_commit'] == trusted
    assert result['verified_main'] == trusted
    assert producer.git(target, 'rev-list', '--all') == source
    assert producer.git(target, 'for-each-ref', '--format=%(refname)') == 'refs/heads/main'
    assert 'fixture-token' not in (target / 'config').read_text()
    assert not (target / 'FETCH_HEAD').exists()


@pytest.mark.skipif(sys.platform != 'linux' or os.geteuid() != 0,
                    reason='disposable Linux ownership fixture; no actual artifact adoption')
def test_real_archive_reconstructs_git_and_existing_consumer_never_executes_fsmonitor():
    directory = Path('/paper-producer-fixture-' + uuid4().hex)
    directory.mkdir(mode=0o755)
    try:
        recipe, source, trusted = world(directory)
        bare, context = directory / 'input.git', directory / 'context.json'
        producer.prepare(recipe, source, trusted, bare, context, 'fixture-base@sha256:x')
        release = directory / 'candidate'
        release.mkdir()
        for name in ('uv.lock', 'runtime.py'):
            (release / name).write_text(producer.git(recipe, 'show', source + ':' + name,
                                                   strip=False))
        (release / '.venv/bin').mkdir(parents=True)
        (release / '.venv/bin/algua').write_text('#!/bin/sh\nexit 0\n')
        (release / '.venv/bin/algua').chmod(0o755)
        profile = {'commit': source, 'builder_sha256': producer.sha(recipe / producer.BUILDER),
                   'external_base_python': {'path': '/fixture/base', 'self_contained': False}}
        (release / 'application-runtime.json').write_text(json.dumps(profile))
        inventory = {p.relative_to(release).as_posix(): producer.sha(p)
                     for p in release.rglob('*') if p.is_file()}
        payload = {'commit': source, 'lock_sha256': inventory['uv.lock'], 'files': inventory}
        spec = {'path': str(release), **payload,
                'digest': producer.hashlib.sha256(producer.canonical(payload)).hexdigest()}
        descriptor = directory / 'release.json'
        descriptor.write_text(json.dumps(spec))
        marker = directory / 'MUST-NOT-EXECUTE'
        attack = directory / 'attack.sh'
        attack.write_text('#!/bin/sh\ntouch ' + str(marker) + '\n')
        attack.chmod(0o755)
        (release / '.git/hooks').mkdir(parents=True)
        (release / '.git/config').write_text('[core]\n fsmonitor = ' + str(attack) + '\n')
        shutil.copyfile(attack, release / '.git/hooks/post-checkout')
        (release / '.git/objects').symlink_to('/must-not-be-traversed')
        output = directory / 'package'
        result = producer.package(release, descriptor, bare, context, output)
        assert result['trusted'] is False and result['adoption_approved'] is False
        assert not marker.exists()
        assert (output / 'release-spec.json').read_bytes() == descriptor.read_bytes()
        for line in (output / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split('  ')
            assert producer.sha(output / name) == digest
        adopted = directory / 'fixture-adoption'
        adopted.mkdir(mode=0o755)
        with tarfile.open(output / 'application.tar.gz') as tar:
            tar.extractall(adopted, filter='data')
        root = adopted / 'release'
        assert os.access(root / '.venv/bin/algua', os.X_OK)
        assert not (root / '.git/hooks/post-checkout').exists()
        config = (root / '.git/config').read_text()
        assert 'fsmonitor = false' in config and 'hooksPath = /dev/null' in config
        assert str(attack) not in config
        module_spec = importlib.util.spec_from_file_location('consumer',
                            ROOT / 'deploy/scripts/release-paper.py')
        consumer = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(consumer)
        spec['path'] = str(root)
        assert consumer.release(spec, 1001) == root
        assert not marker.exists()
    finally:
        shutil.rmtree(directory)


def test_workflow_is_opt_in_read_only_and_recipe_pinned():
    import yaml

    text = (ROOT / producer.WORKFLOW).read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'workflow_dispatch'}
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['artifact']
    assert job['if'] == "github.ref == 'refs/heads/main'"
    checkout = job['steps'][0]
    assert checkout['with']['ref'] == '${{ github.workflow_sha }}'
    assert checkout['with']['persist-credentials'] == 'false'
    assert '${{ secrets.' not in text and 'self-hosted' not in text
