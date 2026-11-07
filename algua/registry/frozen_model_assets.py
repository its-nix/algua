"""Package and read the one supported frozen model profile from fixed bundle paths."""
from __future__ import annotations

import hashlib
import os
import stat
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
from algua.registry.frozen_source import FrozenFile


def pack_model(handle: ModelHandle) -> tuple[FrozenModelAsset, tuple[FrozenFile, ...]]:
    raw, provenance = bytes(handle.artifact_bytes), portable_model_provenance(handle)
    asset = FrozenModelAsset(handle.version.as_ref(), hashlib.sha256(raw).hexdigest(),
                             hashlib.sha256(provenance).hexdigest())
    restored = unpack_model(asset, raw, provenance)
    validate_proxy_model(restored)
    return asset, (FrozenFile(MODEL_ARTIFACT, "100644", raw),
                   FrozenFile(MODEL_PROVENANCE, "100644", provenance))


def _read_file(root: Path, relative: str, limit: int) -> bytes:
    """Walk trusted fixed paths with no symlink following, including directory components."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parts = relative.split("/")
        for component in parts[:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError("frozen model file is not a bounded regular file")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                content = handle.read(limit + 1)
            if len(content) != info.st_size or len(content) > limit:
                raise ValueError("frozen model file size changed during capture")
            return content
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def read_bundle_model(bundle_root: Path, asset: FrozenModelAsset) -> ModelHandle:
    try:
        artifact = _read_file(bundle_root, MODEL_ARTIFACT, MAX_MODEL_BYTES)
        provenance = _read_file(bundle_root, MODEL_PROVENANCE, MAX_PROVENANCE_BYTES)
    except OSError as exc:
        raise ValueError("frozen model asset is missing or unsafe") from exc
    handle = unpack_model(asset, artifact, provenance)
    validate_proxy_model(handle)
    return handle
