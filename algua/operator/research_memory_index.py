"""Read-only discovery of retained attempt metadata and verified public archive readback."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from algua.contracts.idea import AttemptOutcome
from algua.operator.campaign_memory_schema import CYCLE, memory_reference, validate_payload
from algua.operator.research_memory_checkpoint import load_checkpoint, validate_retained_payload
from algua.operator.research_memory_projection import MemoryLimits
from algua.registry.read_snapshot import registry_snapshot
from algua.tracking.bounded_local_read import ReadBudget
from algua.tracking.research_archive import LocalResearchArchive

MAX_INDEX_LIMIT = 100


def validate_research_cycle(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(CYCLE, value) is None:
        raise ValueError("invalid retained research cycle identifier")
    return value


def _entry(row: sqlite3.Row) -> dict:
    if (type(row["id"]) is not int or row["id"] < 1
            or type(row["idea_id"]) is not int or row["idea_id"] < 1
            or row["outcome"] not in AttemptOutcome
            or memory_reference(row["evidence_ref"]) is None):
        raise ValueError("retained research index metadata invalid")
    cycle_id = validate_research_cycle(row["run_stamp"])
    stamp = row["outcome_at"]
    if stamp is not None:
        if not isinstance(stamp, str) or len(stamp) > 64:
            raise ValueError("retained research index timestamp invalid")
        try:
            parsed = datetime.fromisoformat(stamp)
        except ValueError as exc:
            raise ValueError("retained research index timestamp invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("retained research index timestamp invalid")
    return {"attempt_id": row["id"], "evidence_id": f"idea_attempts:{row['id']}",
            "idea_id": row["idea_id"], "research_cycle_id": cycle_id,
            "outcome": row["outcome"], "outcome_at": stamp,
            "archive_reference": row["evidence_ref"]}


def list_retained_research(database: Path, *, limit: int = 20) -> dict:
    """Newest terminal attempt references, not verified archives, cycles or independent trials.

    Read only a private bounded DB/WAL copy. Never migrate, bootstrap an archive, or serialize
    claim credentials, outcome free text or controller requests. Repeated cycles stay explicit.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_INDEX_LIMIT:
        raise ValueError("retained research limit must be between 1 and 100")
    with registry_snapshot(database, max_bytes=MemoryLimits().max_database_bytes,
                           timeout_seconds=5, label="retained research registry") as snapshot:
        rows = snapshot.connection.execute(
            "SELECT id,idea_id,run_stamp,outcome,outcome_at,evidence_ref FROM idea_attempts "
            "WHERE outcome IS NOT NULL AND evidence_ref LIKE 'mlflow:%/public-evidence.json%' "
            "ORDER BY id DESC LIMIT ?", (limit + 1,),
        ).fetchall()
        entries = [_entry(row) for row in rows[:limit]]
    return {"schema_version": "retained-research-index/v1", "metadata_verified": False,
            "evidence_mode": "UNVERIFIED_WORKER", "authority": "none", "association": "cycle_only",
            "count": len(entries), "limit": limit, "has_more": len(rows) > limit,
            "attempts": entries}


def read_retained_research(
    run: str, *, database: Path, data_dir: Path, tracking_uri: str, tracking_backend: str,
) -> dict:
    """The existing show payload, validated against its checkpoint and archive without writes."""
    validate_research_cycle(run)
    metadata = load_checkpoint(data_dir / "research-cycles", run, database=str(database.resolve()),
                               budget=ReadBudget(256 * 1024))
    archive = LocalResearchArchive(tracking_uri, backend=tracking_backend, existing_only=True)
    payload = archive.read(metadata["research_memory"]["receipt"])
    validate_payload(payload, run)
    return validate_retained_payload(payload, metadata=metadata, cycle_id=run)
