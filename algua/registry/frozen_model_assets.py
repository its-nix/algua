"""Package and read the one supported frozen model profile from fixed bundle paths."""
from __future__ import annotations

import hashlib
from pathlib import Path

from algua.contracts.frozen_model import (
    MAX_MODEL_BYTES,
    MAX_PROVENANCE_BYTES,
    MODEL_ARTIFACT,
    MODEL_PROVENANCE,
    FrozenModelAsset,
    portable_model_provenance,
)
from algua.contracts.frozen_model import unpack_model as unpack_model
from algua.contracts.model_types import ModelHandle
from algua.features.price_linear_context import validate_proxy_model
from algua.primitives.bounded_file import read_relative_regular as _read_file
from algua.registry.frozen_source import FrozenFile


def pack_model(handle: ModelHandle) -> tuple[FrozenModelAsset, tuple[FrozenFile, ...]]:
    raw, provenance = bytes(handle.artifact_bytes), portable_model_provenance(handle)
    asset = FrozenModelAsset(handle.version.as_ref(), hashlib.sha256(raw).hexdigest(),
                             hashlib.sha256(provenance).hexdigest())
    restored = unpack_model(asset, raw, provenance)
    validate_proxy_model(restored)
    return asset, (FrozenFile(MODEL_ARTIFACT, "100644", raw),
                   FrozenFile(MODEL_PROVENANCE, "100644", provenance))


def read_bundle_model(bundle_root: Path, asset: FrozenModelAsset) -> ModelHandle:
    try:
        artifact = _read_file(bundle_root, MODEL_ARTIFACT, MAX_MODEL_BYTES)
        provenance = _read_file(bundle_root, MODEL_PROVENANCE, MAX_PROVENANCE_BYTES)
    except OSError as exc:
        raise ValueError("frozen model asset is missing or unsafe") from exc
    handle = unpack_model(asset, artifact, provenance)
    validate_proxy_model(handle)
    return handle
