"""Recover model bytes from a verified bundle without importing authority or store layers."""
from __future__ import annotations

import json
from pathlib import Path

from algua.contracts.canonical import canonical_json
from algua.contracts.frozen_model import (
    MAX_MODEL_BYTES,
    MAX_PROVENANCE_BYTES,
    MODEL_ARTIFACT,
    MODEL_PROVENANCE,
    FrozenModelAsset,
    unpack_model,
)
from algua.contracts.model_types import ModelHandle
from algua.primitives.bounded_file import read_relative_regular


def bundle_model(bundle_root: Path) -> ModelHandle:
    """The fixed model stamp and files belong to the enclosing inventory-verified bundle."""
    raw = read_relative_regular(bundle_root, '_algua/protocol.json', 256 * 1024)
    stamp = json.loads(raw)
    if (canonical_json(stamp).encode() != raw or type(stamp) is not dict
            or set(stamp) != {'descriptor_version', 'planner_boundary_version',
                             'planner_protocol_version', 'frozen_wire',
                             'strategy_interface', 'model_asset'}
            or stamp['strategy_interface'] != 'context_v1'
            or any(type(stamp[key]) is not int or stamp[key] != 2
                   for key in ('descriptor_version', 'planner_boundary_version',
                               'planner_protocol_version'))
            or stamp['frozen_wire'] != {'name': 'frozen-planner', 'version': 2}):
        raise ValueError('unsupported frozen model bundle profile')
    asset = FrozenModelAsset.from_dict(stamp['model_asset'])
    return unpack_model(asset,
        read_relative_regular(bundle_root, MODEL_ARTIFACT, MAX_MODEL_BYTES),
        read_relative_regular(bundle_root, MODEL_PROVENANCE, MAX_PROVENANCE_BYTES))
