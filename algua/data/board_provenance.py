"""Bounded, exact-snapshot provenance read model for the strategy board."""
from __future__ import annotations

import json
from typing import Any

from algua.data.manifest import SnapshotManifest
from algua.provenance.research import ResearchProvenanceError
from algua.provenance.snapshot_evidence import project_snapshot_record as project_snapshot_record

__all__ = ["SnapshotProvenanceReader", "project_snapshot_record"]


def _wrapper(status: str, reason: str | None, value: dict[str, Any] | None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": value}


class SnapshotProvenanceReader:
    """Resolve only an exact run-bound manifest ID; never infer a provider or newer snapshot."""

    def __init__(self, manifest: SnapshotManifest) -> None:
        self._manifest = manifest
        self._loaded = False
        self._source_unavailable = False
        self._payloads: list[dict[str, Any]] = []

    def resolve(self, snapshot_id: str) -> dict[str, Any]:
        self._load_payloads()
        if self._source_unavailable:
            return _wrapper("UNAVAILABLE", "source_unavailable", None)
        matches = [
            payload
            for payload in self._payloads
            if payload.get("snapshot_id") == snapshot_id
        ]
        if not matches:
            return _wrapper("UNAVAILABLE", "snapshot_not_found", None)
        if self._conflicting(matches):
            return _wrapper("INVALID", "conflicting_snapshot_records", None)
        return project_snapshot_record(snapshot_id, matches[0])

    def capture(self, snapshot_id: str) -> dict[str, Any] | None:
        """Validated, exact record for detached run capture; legacy absence stays unknown."""
        evidence = self.resolve(snapshot_id)
        if evidence["status"] == "UNAVAILABLE" and evidence["reason"] == "provenance_absent":
            return None
        if evidence["status"] != "VALID":
            raise ResearchProvenanceError(evidence["reason"], "cannot capture bars provenance")
        return next(p for p in self._payloads if p.get("snapshot_id") == snapshot_id)

    def _load_payloads(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = self._manifest.path.read_bytes() if self._manifest.path.exists() else b""
            committed = SnapshotManifest._committed_prefix(raw).decode("utf-8")
            for line in committed.split("\n"):
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    self._source_unavailable = True
                    self._payloads.clear()
                    return
                self._payloads.append(payload)
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._source_unavailable = True
            self._payloads.clear()

    @staticmethod
    def _conflicting(payloads: list[dict[str, Any]]) -> bool:
        first = payloads[0]
        return any(payload != first for payload in payloads[1:])
