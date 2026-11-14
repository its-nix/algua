"""Pure version/profile checks shared by the wire, child and planner supervisor."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from algua.contracts.frozen_model import FrozenModelAsset, parse_model_ref
from algua.live.frozen_wire_json import WireError, expect_object, is_hex


def wire_tag(version: int) -> dict[str, Any]:
    if type(version) is not int or version not in (1, 2):
        raise WireError("bad_wire", repr(version))
    return {"name": "frozen-planner", "version": version}


def wire_version(value: Any, *, expected: int | None = None) -> int:
    body = expect_object(value, frozenset({"name", "version"}), "wire")
    version = body["version"]
    if (type(version) is not int or version not in (1, 2)
            or body["name"] != "frozen-planner" or (expected is not None and version != expected)):
        raise WireError("bad_wire", repr(value))
    return version


def model_fields(config: dict[str, Any], snapshot: Any) -> dict[str, Any]:
    if type(snapshot) is not str or not snapshot or snapshot.strip() != snapshot:
        raise WireError("bad_model_profile", "model profile requires a pinned bars_snapshot_id")
    if (config.get("needs_model") is not True or config.get("needs_news") is not False
            or config.get("needs_fundamentals") is not False):
        raise WireError("bad_model_profile", "only the bars + pinned model profile is supported")
    try:
        ref = parse_model_ref(config.get("model_ref"))
    except (TypeError, ValueError) as exc:
        raise WireError("bad_model_profile", str(exc)) from exc
    return {"bars_snapshot_id": snapshot, "model_ref": ref.as_dict()}


def model_extension(config_json: str, snapshot: Any) -> dict[str, Any]:
    return model_fields(json.loads(config_json), snapshot)


def protocol_profile(stamp: Any) -> int:
    if type(stamp) is not dict:
        raise WireError("bad_protocol", "the stamp is not an object")
    version = wire_version(stamp.get("frozen_wire"))
    keys = {"descriptor_version", "planner_boundary_version",
            "planner_protocol_version", "frozen_wire"}
    if version == 2:
        keys |= {"strategy_interface", "model_asset"}
    expect_object(stamp, frozenset(keys), "protocol")
    if any(type(stamp[key]) is not int or stamp[key] != version
           for key in ("descriptor_version", "planner_boundary_version",
                       "planner_protocol_version")):
        raise WireError("bad_protocol", "mixed or unsupported protocol versions")
    if version == 2:
        if stamp["strategy_interface"] != "context_v1":
            raise WireError("bad_protocol", "model profile requires context_v1")
        try:
            FrozenModelAsset.from_dict(stamp["model_asset"])
        except (TypeError, ValueError) as exc:
            raise WireError("bad_protocol", str(exc)) from exc
    return version


@dataclass(frozen=True)
class WireIdentity:
    strategy_name: str
    deployment_id: int
    artifact_id: int
    manifest_digest: str
    bundle_digest: str
    environment_digest: str
    protocol_version: int = 1

    def __post_init__(self) -> None:
        wire_tag(self.protocol_version)
        if not isinstance(self.strategy_name, str) or not self.strategy_name:
            raise WireError("bad_identity", "strategy_name must be a non-empty string")
        for name in ("deployment_id", "artifact_id"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise WireError("bad_identity", f"{name} must be a positive integer")
        for name in ("manifest_digest", "bundle_digest", "environment_digest"):
            if not is_hex(getattr(self, name), 64):
                raise WireError("bad_identity", f"{name} must be 64 lowercase hex chars")


