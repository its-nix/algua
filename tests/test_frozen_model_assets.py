"""Portable frozen model assets; synthetic trained inputs, never trading qualification."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from algua.contracts.canonical import canonical_json
from algua.contracts.model_types import ModelHandle
from tests.test_trained_model_context import trained as trained


def test_pack_roundtrip_keeps_pin_and_bytes(trained):
    from algua.registry.frozen_model_assets import pack_model, unpack_model

    version, raw = trained[-2:]
    asset, files = pack_model(ModelHandle(version, raw))
    contents = {item.path: item.data for item in files}
    restored = unpack_model(asset, contents['_algua/model/artifact.json'],
                            contents['_algua/model/provenance.json'])
    assert restored.version.as_ref() == version.as_ref()
    assert restored.artifact_bytes == raw
    assert restored.version.artifact_path is None


@pytest.mark.parametrize('change', ['bytes', 'provenance', 'pin', 'inner_digest'])
def test_swapped_or_changed_content_is_not_a_portable_model(trained, change):
    from algua.registry.frozen_model_assets import pack_model, unpack_model

    version, artifact = trained[-2:]
    asset, files = pack_model(ModelHandle(version, artifact))
    provenance = files[1].data
    if change == 'bytes':
        artifact += b' '
    elif change == 'provenance':
        raw = json.loads(provenance)
        raw['eval_report']['mode'] = 'other'
        provenance = canonical_json(raw).encode()
        asset = replace(asset, provenance_sha256=hashlib.sha256(provenance).hexdigest())
    elif change == 'pin':
        asset = replace(asset, ref=replace(asset.ref, version=asset.ref.version + 1))
    else:
        artifact += b' '
        asset = replace(asset, artifact_sha256=hashlib.sha256(artifact).hexdigest())
    with pytest.raises(ValueError, match='mismatch|pin|provenance'):
        unpack_model(asset, artifact, provenance)


@pytest.mark.parametrize('field,value', [('seed', True), ('version', True),
                                       ('hyperparameters', []), ('extra', 1)])
def test_portable_metadata_refuses_coercions_and_unknown_fields(trained, field, value):
    from algua.registry.frozen_model_assets import pack_model, unpack_model

    asset, files = pack_model(ModelHandle(trained[-2], trained[-1]))
    raw = json.loads(files[1].data)
    raw[field] = value
    provenance = canonical_json(raw).encode()
    asset = replace(asset, provenance_sha256=hashlib.sha256(provenance).hexdigest())
    with pytest.raises(ValueError):
        unpack_model(asset, files[0].data, provenance)


def test_duplicate_metadata_keys_refuse_even_with_matching_outer_hash(trained):
    from algua.registry.frozen_model_assets import pack_model, unpack_model

    asset, files = pack_model(ModelHandle(trained[-2], trained[-1]))
    provenance = b'{"seed":0,' + files[1].data[1:]
    asset = replace(asset, provenance_sha256=hashlib.sha256(provenance).hexdigest())
    with pytest.raises(ValueError, match='duplicate'):
        unpack_model(asset, files[0].data, provenance)


@pytest.mark.parametrize('part,limit', [(0, 64 * 1024), (1, 1024 * 1024)])
def test_asset_size_is_bounded_before_parsing(trained, part, limit):
    from algua.registry.frozen_model_assets import pack_model, unpack_model

    asset, files = pack_model(ModelHandle(trained[-2], trained[-1]))
    content = [file.data for file in files]
    content[part] = b'x' * (limit + 1)
    with pytest.raises(ValueError, match='size'):
        unpack_model(asset, *content)


@pytest.mark.parametrize('unsafe', ['file_link', 'directory_link', 'fifo', 'oversize', 'missing'])
def test_bundle_reader_never_follows_unsafe_asset_paths(trained, tmp_path, unsafe):
    import os

    from algua.registry.frozen_model_assets import pack_model, read_bundle_model

    asset, files = pack_model(ModelHandle(trained[-2], trained[-1]))
    root = tmp_path / 'bundle'
    for file in files:
        path = root / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file.data)
    restored = read_bundle_model(root, asset)
    assert restored.version.as_ref() == asset.ref
    path = root / files[0].path
    if unsafe == 'directory_link':
        directory = path.parent
        moved = tmp_path / 'external'
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        path.unlink()
        if unsafe == 'file_link':
            outside = tmp_path / 'outside'
            outside.write_bytes(files[0].data)
            path.symlink_to(outside)
        elif unsafe == 'fifo':
            os.mkfifo(path)
        elif unsafe == 'oversize':
            path.write_bytes(b'x' * (64 * 1024 + 1))
    with pytest.raises(ValueError):
        read_bundle_model(root, asset)
