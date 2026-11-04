"""Public worker evidence in the existing local MLflow store; never promotion authority."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import unquote, urlsplit

from algua.registry.read_snapshot import registry_snapshot
from algua.tracking.bounded_local_read import LocalReadError, ReadBudget, read_local_file
from algua.tracking.uri import sqlite_tracking_uri

_EXPERIMENT = "algua-research-memory"
_ARTIFACT = "public-evidence.json"
_MAX_BYTES = 16 * 1024 * 1024
# Separate metadata DB+WAL source-size preflight per lookup; not an actual-I/O byte ceiling.
_MAX_STORE_BYTES = 128 * 1024 * 1024
# MLflow 3.16.0, mlflow/utils/validation.py::_RUN_ID_REGEX / _validate_run_id.
# Preserve Unicode word characters and .match/$ terminator semantics exactly.
_RUN_ID = re.compile(r"^[a-zA-Z0-9][\w\-]{0,255}$")


def valid_run_id(value: object) -> bool:
    """The pinned MLflow ID vocabulary, without client initialization or source I/O."""
    return isinstance(value, str) and _RUN_ID.match(value) is not None


class ArchiveReadError(ValueError):
    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate archive JSON key")
        value[key] = item
    return value


def _constant(value: str) -> NoReturn:
    raise ValueError("nonfinite archive JSON constant")


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite archive JSON number")
    return number


class LocalResearchArchive:
    """Idempotent publication under the caller's existing cycle lock.

    This bounded increment supports local mlflow-sqlite only. Other backends must refuse
    cleanup rather than pretend retention succeeded. MLflow remains operational mutable evidence;
    the receipt's SHA detects later changes but grants no gate, trial or investment authority.
    """

    def __init__(self, tracking_uri: str, *, backend: str = "mlflow-sqlite",
                 existing_only: bool = False) -> None:
        uri = sqlite_tracking_uri(tracking_uri)
        if (backend != "mlflow-sqlite" or not uri.startswith("sqlite:///")
                or any(c in uri[len("sqlite:///"):] for c in "?#")
                or uri[len("sqlite:///"):] in ("", ":memory:")):
            raise ArchiveReadError("archive_store_unavailable",
                                   "research memory requires the configured local "
                                   "MLflow SQLite store")
        if type(existing_only) is not bool:
            raise ValueError("existing_only must be a boolean")
        self.existing_only = existing_only
        database = Path(uri[len("sqlite:///"):]).resolve()
        self.database = database
        self.tracking_uri = "sqlite:///" + str(database)
        self.artifact_root = database.parent / (database.stem + ".artifacts") / _EXPERIMENT
        self._client: Any = None
        self._experiment_id: str | None = None

    @property
    def client(self) -> Any:
        if self.existing_only:
            raise ArchiveReadError("archive_store_unavailable",
                                   "existing-only research memory cannot initialize MLflowClient")
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
        if self.existing_only:
            raise ArchiveReadError("archive_store_unavailable",
                                   "existing-only research memory cannot publish")
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

    def _metadata(self, run_id: str) -> tuple[str, str, dict[str, str]]:
        """Query only a private existing SQLite snapshot; source DB/WAL/SHM stay untouched.

        MLflowClient construction can create/migrate tables and the default experiment. Neither
        read mode uses it. Schema head comes from the installed MLflow migration definition;
        publication alone keeps the existing client. Each lookup preflights DB+WAL at 128MiB.
        Concurrent source growth can exceed that copying amount before snapshot refusal; this is
        not a strict actual-I/O ceiling. The caller's batch deadline covers copies/imports and
        teardown may overhang. SQLite queries additionally have a five-second progress deadline.
        """
        try:
            sizes = [self.database, Path(str(self.database) + "-wal")]
            if sum(path.stat().st_size for path in sizes if path.exists()) > _MAX_STORE_BYTES:
                raise ArchiveReadError("source_bytes_exceeded",
                                       "research memory store exceeds its source-size preflight")
            from mlflow.store.db.utils import _get_latest_schema_revision
            from mlflow.store.tracking.sqlalchemy_store import DEFAULT_WORKSPACE_NAME

            with registry_snapshot(self.database, max_bytes=_MAX_STORE_BYTES,
                                   timeout_seconds=5, label="research archive store") as snapshot:
                conn = snapshot.connection
                required = {
                    "alembic_version": {"version_num"},
                    "experiments": {"experiment_id", "name", "workspace", "artifact_location",
                                    "lifecycle_stage"},
                    "runs": {"run_uuid", "experiment_id", "artifact_uri"},
                    "tags": {"run_uuid", "key", "value"},
                }
                for table, columns in required.items():
                    schema = conn.execute("SELECT type FROM sqlite_master WHERE name=?",
                                          (table,)).fetchone()
                    actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                    if schema is None or schema[0] != "table" or not columns <= actual:
                        raise ValueError("incompatible existing archive schema")
                versions = conn.execute(
                    "SELECT version_num FROM alembic_version LIMIT 2").fetchall()
                if len(versions) != 1 or versions[0][0] != _get_latest_schema_revision():
                    raise ValueError("incompatible existing archive schema version")
                if conn.execute("SELECT 1 FROM experiments WHERE workspace IS NOT NULL "
                                "AND workspace!=? LIMIT 1", (DEFAULT_WORKSPACE_NAME,)).fetchone():
                    raise ValueError("workspace-scoped archive store is unsupported")
                experiments = conn.execute(
                    "SELECT experiment_id,artifact_location,lifecycle_stage FROM experiments "
                    "WHERE name=? LIMIT 2", (_EXPERIMENT,)).fetchall()
                runs = conn.execute("SELECT experiment_id,artifact_uri FROM runs "
                                    "WHERE run_uuid=? LIMIT 2", (run_id,)).fetchall()
                if len(experiments) != 1 or len(runs) != 1:
                    raise ValueError("existing archive experiment or run is unavailable")
                experiment, run = experiments[0], runs[0]
                if (experiment["lifecycle_stage"] != "active"
                        or experiment["artifact_location"] != self.artifact_root.as_uri()):
                    raise ArchiveReadError("receipt_invalid",
                                           "research memory experiment location is incompatible")
                if run["experiment_id"] != experiment["experiment_id"]:
                    raise ArchiveReadError("receipt_invalid",
                                           "research memory receipt does not match "
                                           "its stored cycle")
                tags = conn.execute("SELECT key,value FROM tags WHERE run_uuid=? AND key IN "
                                    "(?,?,?) LIMIT 4", (run_id, "archive_sha256", "algua_cycle_id",
                                                        "evidence_mode")).fetchall()
                if len(tags) != 3 or len({row["key"] for row in tags}) != 3:
                    raise ArchiveReadError("receipt_invalid",
                                           "research memory receipt does not match "
                                           "its stored cycle")
                return (str(experiment["experiment_id"]), run["artifact_uri"],
                        {row["key"]: row["value"] for row in tags})
        except ArchiveReadError:
            raise
        except (OSError, sqlite3.Error, ValueError) as exc:
            raise ArchiveReadError("archive_store_unavailable",
                                   "research memory existing archive store is unavailable") from exc

    def read(self, receipt: dict[str, Any], *, budget: ReadBudget | None = None) -> dict[str, Any]:
        keys = {"schema_version", "research_cycle_id", "tracking_uri", "run_id", "sha256",
                "reference"}
        if (not isinstance(receipt, dict) or set(receipt) != keys
                or receipt.get("schema_version") != "research-memory-receipt/v1"
                or receipt.get("tracking_uri") != self.tracking_uri
                or not valid_run_id(receipt.get("run_id"))
                or not isinstance(receipt.get("research_cycle_id"), str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}",
                                receipt["research_cycle_id"]) is None
                or not isinstance(receipt.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]) is None
                or receipt.get("reference") != (
                    f"mlflow:{receipt.get('run_id')}/{_ARTIFACT}#sha256={receipt['sha256']}")):
            raise ArchiveReadError("receipt_invalid", "research memory receipt is malformed")
        _, artifact_uri, tags = self._metadata(receipt["run_id"])
        if (tags.get("archive_sha256") != receipt["sha256"]
                or tags.get("algua_cycle_id") != receipt["research_cycle_id"]
                or tags.get("evidence_mode") != "UNVERIFIED_WORKER"):
            raise ArchiveReadError("receipt_invalid",
                                   "research memory receipt does not match its stored cycle")
        try:
            if not isinstance(artifact_uri, str):
                raise ValueError("invalid artifact URI type")
            uri = urlsplit(artifact_uri)
        except ValueError as exc:
            raise ArchiveReadError("artifact_location_unsupported",
                                   "research memory artifact location is unsupported") from exc
        if (uri.scheme != "file" or uri.netloc or uri.query or uri.fragment
                or not Path(unquote(uri.path)).is_absolute()):
            raise ArchiveReadError("artifact_location_unsupported",
                                   "research memory artifact location is unsupported")
        try:
            raw = read_local_file(Path(unquote(uri.path)) / _ARTIFACT, root=self.artifact_root,
                                  max_bytes=_MAX_BYTES, budget=budget,
                                  expected_sha256=receipt["sha256"])
        except LocalReadError as exc:
            raise ArchiveReadError(exc.reason, str(exc)) from exc
        try:
            payload: dict[str, Any] = json.loads(raw, object_pairs_hook=_object,
                                               parse_constant=_constant, parse_float=_float)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ArchiveReadError("artifact_payload_invalid",
                                   "research memory artifact envelope is malformed") from exc
        if (not isinstance(payload, dict) or payload.get("schema_version") != "research-memory/v1"
                or payload.get("research_cycle_id") != receipt["research_cycle_id"]
                or payload.get("evidence_mode") != "UNVERIFIED_WORKER"
                or payload.get("authority") != "none"):
            raise ArchiveReadError("artifact_payload_invalid",
                                   "research memory artifact envelope is malformed")
        return payload
