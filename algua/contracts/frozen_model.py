"""Portable frozen model identity and bytes-only verification, without acquisition authority."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from algua.contracts.canonical import canonical_json
from algua.contracts.model_types import (
    ModelHandle,
    ModelRef,
    ModelVersion,
    compute_provenance_digest,
    normalize_as_of,
)

MODEL_ARTIFACT = "_algua/model/artifact.json"
MODEL_PROVENANCE = "_algua/model/provenance.json"
MAX_MODEL_BYTES = 64 * 1024
MAX_PROVENANCE_BYTES = 1024 * 1024
_REF_KEYS = frozenset({"name", "version", "digest", "training_as_of", "provenance_digest"})
_VERSION_KEYS = _REF_KEYS | {
    "created_at", "training_snapshot_id", "code_hash", "hyperparameters", "seed", "eval_report",
}


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value) is not None


def _object(value: Any, keys: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("frozen model metadata has unknown or missing fields")
    return value


def parse_model_ref(value: Any) -> ModelRef:
    raw = _object(value, _REF_KEYS)
    if (type(raw["name"]) is not str or not raw["name"].strip()
            or type(raw["version"]) is not int or raw["version"] < 1
            or not _hex(raw["digest"], 16) or not _hex(raw["provenance_digest"], 16)
            or type(raw["training_as_of"]) is not str):
        raise ValueError("frozen model reference has invalid types or values")
    stamp = normalize_as_of(raw["training_as_of"])
    if stamp is None or stamp != stamp:
        raise ValueError("frozen model training cutoff is invalid")
    return ModelRef(**raw)


@dataclass(frozen=True)
class FrozenModelAsset:
    ref: ModelRef
    artifact_sha256: str
    provenance_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, ModelRef):
            raise ValueError("frozen model reference must be typed")
        parse_model_ref(self.ref.as_dict())
        if not _hex(self.artifact_sha256, 64) or not _hex(self.provenance_sha256, 64):
            raise ValueError("frozen model asset hashes must be full SHA256")

    def to_dict(self) -> dict[str, Any]:
        return {"ref": self.ref.as_dict(), "artifact_sha256": self.artifact_sha256,
                "provenance_sha256": self.provenance_sha256}

    @classmethod
    def from_dict(cls, value: Any) -> FrozenModelAsset:
        raw = _object(value, frozenset({"ref", "artifact_sha256", "provenance_sha256"}))
        return cls(parse_model_ref(raw["ref"]), raw["artifact_sha256"], raw["provenance_sha256"])


def portable_model_provenance(handle: ModelHandle) -> bytes:
    version = handle.version
    raw = {key: getattr(version, key) for key in _VERSION_KEYS}
    return canonical_json(raw).encode("utf-8")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate frozen model metadata key")
        result[key] = value
    return result


def unpack_model(asset: FrozenModelAsset, artifact: bytes, provenance: bytes) -> ModelHandle:
    """Verify portable bytes/pin/provenance; numerical profile validation belongs to the caller."""
    if (type(artifact) is not bytes or not 0 < len(artifact) <= MAX_MODEL_BYTES
            or type(provenance) is not bytes or not 0 < len(provenance) <= MAX_PROVENANCE_BYTES):
        raise ValueError("frozen model asset size or byte type is invalid")
    if (hashlib.sha256(artifact).hexdigest() != asset.artifact_sha256
            or hashlib.sha256(provenance).hexdigest() != asset.provenance_sha256):
        raise ValueError("frozen model asset SHA256 mismatch")
    try:
        text = provenance.decode("utf-8")
        raw = _object(json.loads(text, object_pairs_hook=_unique), _VERSION_KEYS)
        if canonical_json(raw) != text:
            raise ValueError("frozen model provenance is not canonical")
        ref = parse_model_ref({key: raw[key] for key in _REF_KEYS})
        if ref != asset.ref:
            raise ValueError("frozen model provenance does not match its pin")
        if (type(raw["created_at"]) is not str or not raw["created_at"]
                or type(raw["hyperparameters"]) is not dict or type(raw["eval_report"]) is not dict
                or (raw["seed"] is not None and type(raw["seed"]) is not int)
                or any(raw[key] is not None and type(raw[key]) is not str
                       for key in ("training_snapshot_id", "code_hash"))):
            raise ValueError("frozen model provenance has invalid field types")
        version = ModelVersion(**raw, artifact_path=None)
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid frozen model provenance") from exc
    if hashlib.sha256(artifact).hexdigest()[:16] != ref.digest:
        raise ValueError("frozen model bytes do not match pinned digest")
    expected = compute_provenance_digest(
        digest=version.digest, training_snapshot_id=version.training_snapshot_id,
        training_as_of=version.training_as_of, code_hash=version.code_hash,
        hyperparameters=version.hyperparameters, seed=version.seed, eval_report=version.eval_report,
    )
    if expected != ref.provenance_digest:
        raise ValueError("frozen model provenance does not reproduce pinned digest")
    return ModelHandle(version, artifact)
