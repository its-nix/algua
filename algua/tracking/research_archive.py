"""Public worker evidence in the existing local MLflow store; never promotion authority."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from algua.tracking.uri import sqlite_tracking_uri

_EXPERIMENT = "algua-research-memory"
_ARTIFACT = "public-evidence.json"
_MAX_BYTES = 16 * 1024 * 1024


class LocalResearchArchive:
    """Idempotent publication under the caller's existing cycle lock.

    This bounded increment supports local mlflow-sqlite only. Other backends must refuse
    cleanup rather than pretend retention succeeded. MLflow remains operational mutable evidence;
    the receipt's SHA detects later changes but grants no gate, trial or investment authority.
    """

    def __init__(self, tracking_uri: str, *, backend: str = "mlflow-sqlite") -> None:
        uri = sqlite_tracking_uri(tracking_uri)
        if (backend != "mlflow-sqlite" or not uri.startswith("sqlite:///")
                or any(c in uri[len("sqlite:///"):] for c in "?#")
                or uri[len("sqlite:///"):] in ("", ":memory:")):
            raise ValueError("research memory requires the configured local MLflow SQLite store")
        database = Path(uri[len("sqlite:///"):]).resolve()
        self.database = database
        self.tracking_uri = "sqlite:///" + str(database)
        self.artifact_root = database.parent / (database.stem + ".artifacts") / _EXPERIMENT
        self._client: Any = None
        self._experiment_id: str | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            from mlflow.tracking import MlflowClient
            self._client = MlflowClient(tracking_uri=self.tracking_uri)
        return self._client

    @property
    def experiment_id(self) -> str:
        if self._experiment_id is None:
            existing = self.client.get_experiment_by_name(_EXPERIMENT)
            if existing is None:
                self._experiment_id = self.client.create_experiment(
                    _EXPERIMENT, artifact_location=self.artifact_root.as_uri())
            else:
                if (existing.lifecycle_stage != "active"
                        or existing.artifact_location != self.artifact_root.as_uri()):
                    raise ValueError("research memory experiment location is incompatible")
                self._experiment_id = existing.experiment_id
        return self._experiment_id

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(payload, sort_keys=True, allow_nan=False,
                         separators=(",", ":"), ensure_ascii=False).encode()
        if len(raw) > _MAX_BYTES:
            raise ValueError("research memory artifact exceeds its byte bound")
        cycle_id = payload["research_cycle_id"]
        if not isinstance(cycle_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}",
                                                      cycle_id) is None:
            raise ValueError("research memory cycle identity is malformed")
        digest = hashlib.sha256(raw).hexdigest()
        matches = self.client.search_runs(
            [self.experiment_id], filter_string=f"tags.algua_cycle_id = '{cycle_id}'",
            max_results=2)
        if len(matches) > 1:
            raise ValueError("research memory has conflicting cycle publications")
        if matches:
            run = matches[0]
            if (run.data.tags.get("archive_sha256") != digest
                    or run.data.tags.get("evidence_mode") != "UNVERIFIED_WORKER"
                    or run.info.status not in ("RUNNING", "FINISHED")):
                raise ValueError("research memory cycle publication is immutable")
        else:
            run = self.client.create_run(self.experiment_id, tags={
                "algua_cycle_id": cycle_id, "archive_sha256": digest,
                "evidence_mode": "UNVERIFIED_WORKER", "kind": "research_memory",
            })
        receipt = {
            "schema_version": "research-memory-receipt/v1", "research_cycle_id": cycle_id,
            "tracking_uri": self.tracking_uri, "run_id": run.info.run_id, "sha256": digest,
            "reference": f"mlflow:{run.info.run_id}/{_ARTIFACT}#sha256={digest}",
        }
        present = self.client.list_artifacts(run.info.run_id)
        if any(item.path != _ARTIFACT or item.is_dir for item in present):
            raise ValueError("research memory contains unexpected artifacts")
        if not present:
            with tempfile.TemporaryDirectory(prefix="algua-memory-publish-") as directory:
                path = Path(directory) / _ARTIFACT
                path.write_bytes(raw)
                self.client.log_artifact(run.info.run_id, str(path))
        self.read(receipt)
        if run.info.status != "FINISHED":
            self.client.set_terminated(run.info.run_id, status="FINISHED")
        return receipt

    def read(self, receipt: dict[str, Any]) -> dict[str, Any]:
        keys = {"schema_version", "research_cycle_id", "tracking_uri", "run_id", "sha256",
                "reference"}
        if (set(receipt) != keys or receipt.get("schema_version") != "research-memory-receipt/v1"
                or receipt.get("tracking_uri") != self.tracking_uri
                or not isinstance(receipt.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]) is None
                or receipt.get("reference") != (
                    f"mlflow:{receipt.get('run_id')}/{_ARTIFACT}#sha256={receipt['sha256']}")):
            raise ValueError("research memory receipt is malformed")
        run = self.client.get_run(receipt["run_id"])
        if (run.info.experiment_id != self.experiment_id
                or run.data.tags.get("archive_sha256") != receipt["sha256"]
                or run.data.tags.get("algua_cycle_id") != receipt.get("research_cycle_id")
                or run.data.tags.get("evidence_mode") != "UNVERIFIED_WORKER"):
            raise ValueError("research memory receipt does not match its stored cycle")
        uri = urlsplit(run.info.artifact_uri)
        if uri.scheme != "file" or not Path(unquote(uri.path)).resolve().is_relative_to(
            self.artifact_root.resolve()
        ):
            raise ValueError("research memory artifact location is unsupported")
        with tempfile.TemporaryDirectory(prefix="algua-memory-read-") as directory:
            path = Path(self.client.download_artifacts(run.info.run_id, _ARTIFACT, directory))
            if path.stat().st_size > _MAX_BYTES:
                raise ValueError("research memory artifact exceeds its byte bound")
            raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
            raise ValueError("research memory artifact digest mismatch")
        payload: dict[str, Any] = json.loads(raw)
        if (payload.get("schema_version") != "research-memory/v1"
                or payload.get("research_cycle_id") != receipt["research_cycle_id"]
                or payload.get("evidence_mode") != "UNVERIFIED_WORKER"
                or payload.get("authority") != "none"):
            raise ValueError("research memory artifact envelope is malformed")
        return payload
