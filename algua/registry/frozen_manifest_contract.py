"""Pure canonical outer descriptor for a recoverable frozen planner."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from algua.contracts.canonical import FROZEN_WIRE, _utf8_nfc, canonical_json
from algua.contracts.frozen_model import FrozenModelAsset
from algua.contracts.planner import PLANNER_PROTOCOL_VERSION
from algua.contracts.strategy_interface import LEGACY_INTERFACE, StrategyInterface
from algua.registry.artifact_contract import (
    _HEX32,
    _OID,
    DESCRIPTOR_VERSION,
    MAX_MANIFEST_BYTES,
    PLANNER_BOUNDARY_VERSION,
    BundleDescriptor,
    _digest,
    _require_digest,
)
from algua.registry.environment_contract import EnvironmentDescriptor


@dataclass(frozen=True)
class FrozenManifest:
    source_ref: str
    code_hash: str
    config_hash: str
    dependency_hash: str
    resolved_config: dict[str, Any]
    universe_name: str | None
    bundle: BundleDescriptor
    environment: EnvironmentDescriptor
    strategy_interface: StrategyInterface = LEGACY_INTERFACE
    model_asset: FrozenModelAsset | None = None

    def __post_init__(self) -> None:
        if ((self.model_asset is None and self.strategy_interface != LEGACY_INTERFACE)
                or (self.model_asset is not None
                    and (not isinstance(self.model_asset, FrozenModelAsset)
                         or self.strategy_interface != 'context_v1'))):
            raise ValueError("unsupported frozen model/interface profile")
        _require_digest(self.source_ref, "source ref", _OID)
        _require_digest(self.code_hash, "code hash", _HEX32)
        _require_digest(self.config_hash, "config hash", _HEX32)
        _require_digest(self.dependency_hash, "dependency hash")
        if not isinstance(self.resolved_config, dict):
            raise ValueError("resolved config must be an object")
        if self.universe_name is not None:
            if not isinstance(self.universe_name, str):
                raise ValueError("universe name must be a string or null")
            # Retain the canonical-JSON form so the ledger projection cannot disagree with it.
            object.__setattr__(
                self, "universe_name", _utf8_nfc(self.universe_name, "universe name"))
        if not isinstance(self.bundle, BundleDescriptor) or not isinstance(
            self.environment, EnvironmentDescriptor,
        ):
            raise ValueError("frozen manifest bundle and environment must be typed descriptors")
        if self.environment.key.dependency_hash != self.dependency_hash:
            raise ValueError("environment dependency hash disagrees")
        normalized = json.loads(canonical_json(self.resolved_config))
        object.__setattr__(self, "resolved_config", normalized)

    def to_dict(self) -> dict[str, Any]:
        model = self.model_asset
        result = {
            "descriptor_version": 2 if model is not None else DESCRIPTOR_VERSION,
            "source_kind": "frozen",
            "source_ref": self.source_ref,
            "identity": {
                "code_hash": self.code_hash,
                "config_hash": self.config_hash,
                "dependency_hash": self.dependency_hash,
            },
            "resolved_config": self.resolved_config,
            "universe_name": self.universe_name,
            "bundle": self.bundle.to_dict(),
            "environment": self.environment.to_dict(),
            "assets": [] if model is None else [model.to_dict()],
            "planner_protocol_version": 2 if model is not None else PLANNER_PROTOCOL_VERSION,
            "planner_boundary_version": 2 if model is not None else PLANNER_BOUNDARY_VERSION,
            "frozen_wire": (
                FROZEN_WIRE if model is None else {'name': 'frozen-planner', 'version': 2}),
        }
        if model is not None:
            result['strategy_interface'] = self.strategy_interface
        return result

    @property
    def json(self) -> str:
        raw = canonical_json(self.to_dict())
        if len(raw.encode()) > MAX_MANIFEST_BYTES:
            raise ValueError("frozen manifest exceeds the canonical size bound")
        return raw

    @property
    def digest(self) -> str:
        _ = self.json
        return _digest("algua.frozen-manifest", self.to_dict())
