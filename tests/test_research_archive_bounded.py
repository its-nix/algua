"""Real local archive files and MLflow metadata; fixture evidence grants no gate authority."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from algua.tracking.research_archive import LocalResearchArchive

MIB = 1024 * 1024


@pytest.fixture
def archive_case(tmp_path):
    archive = LocalResearchArchive(f"sqlite:///{tmp_path / 'tracking.db'}")
    payload = {"schema_version": "research-memory/v1", "research_cycle_id": "fixture-bounded",
               "evidence_mode": "UNVERIFIED_WORKER", "authority": "none",
               "evaluations": [{"kind": "backtest", "metrics": {"total_return_is": -0.2}}]}
    receipt = archive.publish(payload)
    uri = archive.client.get_run(receipt["run_id"]).info.artifact_uri
    artifact = Path(unquote(urlsplit(uri).path)) / "public-evidence.json"
    return archive, payload, receipt, artifact


def test_oversized_real_artifact_refuses_before_any_download(archive_case, monkeypatch):
    archive, _, receipt, artifact = archive_case
    with artifact.open("r+b") as stream:
        stream.truncate(16 * MIB + 1)
    downloads = []
    download = archive.client.download_artifacts

    def observed(*args, **kwargs):
        downloads.append(args)
        return download(*args, **kwargs)

    monkeypatch.setattr(archive.client, "download_artifacts", observed)
    with pytest.raises(ValueError):
        archive.read(receipt)
    assert downloads == [], "oversized bytes reached the whole-file download path"


def test_valid_read_never_downloads_or_copies_artifact_or_uses_read_bytes(
        archive_case, monkeypatch):
    archive, payload, receipt, artifact = archive_case
    copy, copied = shutil.copyfile, []

    def forbidden(*args, **kwargs):
        raise AssertionError("artifact whole-file materialization is forbidden")

    monkeypatch.setattr(archive.client, "download_artifacts", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    def observed(source, destination, *args, **kwargs):
        copied.append(Path(source))
        return copy(source, destination, *args, **kwargs)
    monkeypatch.setattr(shutil, "copyfile", observed)
    assert archive.read(receipt) == payload
    assert copied and artifact not in copied


def test_existing_only_lookup_never_constructs_client_or_creates_missing_default(
        archive_case, monkeypatch):
    import mlflow.tracking

    archive, payload, receipt, _ = archive_case
    with sqlite3.connect(archive.database) as conn:
        conn.execute("DELETE FROM experiments WHERE experiment_id=0")
    before = archive.database.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("existing-only read must not construct MLflowClient")

    monkeypatch.setattr(mlflow.tracking, "MlflowClient", forbidden)
    reader = LocalResearchArchive(archive.tracking_uri, existing_only=True)
    assert reader.read(receipt) == payload
    assert archive.database.read_bytes() == before
    with sqlite3.connect(archive.database) as conn:
        count = conn.execute("SELECT count(*) FROM experiments WHERE experiment_id=0").fetchone()[0]
        assert count == 0
    with pytest.raises(ValueError):
        reader.publish(payload)
    assert archive.database.read_bytes() == before


@pytest.mark.parametrize("run_id", ["Legacy_run-2026", "Legacy_α-2026"])
def test_existing_mlflow_legacy_run_id_remains_readable(archive_case, run_id):
    archive, payload, receipt, _ = archive_case
    # A historical SQLite store may contain MLflow-valid IDs unrelated to generated UUIDs.
    # Rename the actual published run and its tags consistently; retain its real artifact URI.
    with sqlite3.connect(archive.database) as conn:
        conn.execute("UPDATE runs SET run_uuid=? WHERE run_uuid=?", (run_id, receipt["run_id"]))
        conn.execute("UPDATE tags SET run_uuid=? WHERE run_uuid=?", (run_id, receipt["run_id"]))
    assert archive.client.get_run(run_id).info.run_id == run_id
    receipt = {**receipt, "run_id": run_id,
               "reference": f"mlflow:{run_id}/public-evidence.json#sha256={receipt['sha256']}"}
    for existing_only in (False, True):
        assert LocalResearchArchive(archive.tracking_uri, existing_only=existing_only).read(
            receipt) == payload


def test_run_id_vocabulary_matches_installed_mlflow_validator():
    from mlflow.exceptions import MlflowException
    from mlflow.utils.validation import _validate_run_id

    from algua.tracking.research_archive import valid_run_id

    samples = [None, 1, True, "", "_legacy", "-legacy", "αlegacy", "legacy@run", "legacy/run",
               "a", "Legacy_run-2026", "Legacy_α-2026", "a" * 256, "a" * 257,
               "legacy\n", "legacy\n\n", "legacy "]
    for value in samples:
        try:
            _validate_run_id(value)
        except (MlflowException, TypeError):
            accepted = False
        else:
            accepted = True
        assert valid_run_id(value) is accepted, repr(value)


@pytest.mark.parametrize("missing", ["store", "schema", "experiment", "run"])
def test_existing_only_missing_metadata_refuses_without_bootstrap(archive_case, missing):
    from algua.tracking.research_archive import ArchiveReadError

    archive, _, receipt, _ = archive_case
    if missing == "store":
        database = archive.database.parent / "never-created" / "missing.db"
        reader = LocalResearchArchive(f"sqlite:///{database}", existing_only=True)
        value = {**receipt, "tracking_uri": reader.tracking_uri}
    else:
        database = archive.database
        with sqlite3.connect(database) as conn:
            if missing == "schema":
                conn.execute("UPDATE alembic_version SET version_num='unsupported-fixture'")
            elif missing == "experiment":
                conn.execute("UPDATE experiments SET name='other' "
                             "WHERE name='algua-research-memory'")
            else:
                conn.execute("DELETE FROM runs WHERE run_uuid=?", (receipt["run_id"],))
        reader, value = LocalResearchArchive(archive.tracking_uri, existing_only=True), receipt
    before = database.read_bytes() if database.exists() else None
    with pytest.raises(ArchiveReadError) as failure:
        reader.read(value)
    assert failure.value.reason == "archive_store_unavailable"
    assert (database.read_bytes() if database.exists() else None) == before
    if missing == "store":
        assert not database.parent.exists()


def test_wal_visible_metadata_and_source_db_wal_shm_are_unchanged(
        archive_case, record_testsuite_property):
    archive, payload, receipt, _ = archive_case
    conn = sqlite3.connect(archive.database)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("UPDATE tags SET value=? WHERE key='archive_sha256' AND run_uuid=?",
                 ("0" * 64, receipt["run_id"]))
    conn.commit()
    assert conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
    conn.execute("UPDATE tags SET value=? WHERE key='archive_sha256' AND run_uuid=?",
                 (receipt["sha256"], receipt["run_id"]))
    conn.commit()
    files = [archive.database, Path(str(archive.database) + "-wal"),
             Path(str(archive.database) + "-shm")]
    before = {path: path.read_bytes() for path in files}
    def stamps():
        return {path.name: (value.st_dev, value.st_ino, value.st_size,
                            value.st_mtime_ns, value.st_ctime_ns)
                for path in files for value in [path.stat()]}
    original = stamps()
    record_testsuite_property("fixture_metadata_file_bytes",
                             json.dumps({p.name: len(raw) for p, raw in before.items()},
                                        sort_keys=True))
    try:
        reader = LocalResearchArchive(archive.tracking_uri, existing_only=True)
        assert reader.read(receipt) == payload
        assert {path: path.read_bytes() for path in files} == before
        assert stamps() == original
        record_testsuite_property("fixture_metadata_stamps_unchanged", "true")
    finally:
        conn.close()


def test_actual_archive_read_accepts_16mib_and_shared_32mib_exactly(archive_case):
    from algua.tracking.bounded_local_read import ReadBudget
    from algua.tracking.research_archive import ArchiveReadError

    archive, payload, _, _ = archive_case
    receipts = []
    for cycle in ("fixture-large-one", "fixture-large-two"):
        value = {**payload, "research_cycle_id": cycle, "padding": ""}
        size = len(json.dumps(value, sort_keys=True, allow_nan=False,
                              separators=(",", ":"), ensure_ascii=False).encode())
        value["padding"] = "x" * (16 * MIB - size)
        receipts.append(archive.publish(value))
    reader = LocalResearchArchive(archive.tracking_uri, existing_only=True)
    budget = ReadBudget(32 * MIB)
    for receipt in receipts:
        assert reader.read(receipt, budget=budget)["authority"] == "none"
    assert budget.used_bytes == 32 * MIB and budget.remaining_bytes == 0
    with pytest.raises(ArchiveReadError) as failure:
        reader.read(receipts[0], budget=budget)
    assert failure.value.reason == "source_bytes_exceeded"


def test_metadata_size_preflight_refuses_before_private_snapshot_copy(tmp_path, monkeypatch):
    from algua.registry import read_snapshot
    from algua.tracking.research_archive import ArchiveReadError

    database = tmp_path / "oversized.db"
    with database.open("wb") as stream:
        stream.truncate(128 * MIB + 1)
    reader = LocalResearchArchive(f"sqlite:///{database}", existing_only=True)
    def forbidden(*args, **kwargs):
        raise AssertionError("oversized metadata reached private copying")
    monkeypatch.setattr(read_snapshot.shutil, "copyfile", forbidden)
    with pytest.raises(ArchiveReadError) as failure:
        reader._metadata("a" * 32)
    assert failure.value.reason == "source_bytes_exceeded"


@pytest.mark.parametrize("change", [
    "reference", "tag", "membership", "experiment", "sha", "envelope",
])
def test_shared_verification_refusals_apply_to_both_read_modes(archive_case, change):
    from algua.tracking.research_archive import ArchiveReadError

    archive, payload, receipt, artifact = archive_case
    expected = "receipt_invalid"
    if change == "reference":
        receipt = {**receipt, "reference": "mlflow:wrong"}
    elif change == "sha":
        artifact.write_text(json.dumps(payload))
        expected = "artifact_integrity_mismatch"
    elif change == "envelope":
        raw = json.dumps({**payload, "authority": "gate"}).encode()
        artifact.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        receipt = {**receipt, "sha256": digest,
                   "reference": f"mlflow:{receipt['run_id']}/public-evidence.json#sha256={digest}"}
        with sqlite3.connect(archive.database) as conn:
            conn.execute("UPDATE tags SET value=? WHERE key='archive_sha256' AND run_uuid=?",
                         (digest, receipt["run_id"]))
        expected = "artifact_payload_invalid"
    else:
        with sqlite3.connect(archive.database) as conn:
            if change == "tag":
                conn.execute("UPDATE tags SET value='WRONG' "
                             "WHERE key='evidence_mode' AND run_uuid=?",
                             (receipt["run_id"],))
            elif change == "membership":
                conn.execute("UPDATE runs SET experiment_id=0 WHERE run_uuid=?",
                             (receipt["run_id"],))
            else:
                conn.execute("UPDATE experiments SET artifact_location='file:///wrong' "
                             "WHERE name='algua-research-memory'")
    for existing_only in (False, True):
        with pytest.raises(ArchiveReadError) as failure:
            LocalResearchArchive(archive.tracking_uri, existing_only=existing_only).read(receipt)
        assert failure.value.reason == expected


@pytest.mark.parametrize("uri", ["file://localhost/", "file:///tmp/foreign", "query", "fragment"])
def test_only_plain_in_root_file_uris_are_supported(archive_case, uri):
    from algua.tracking.research_archive import ArchiveReadError

    archive, _, receipt, artifact = archive_case
    if uri in ("query", "fragment"):
        uri = artifact.parent.as_uri() + ("?x=1" if uri == "query" else "#fragment")
    with sqlite3.connect(archive.database) as conn:
        conn.execute("UPDATE runs SET artifact_uri=? WHERE run_uuid=?", (uri, receipt["run_id"]))
    with pytest.raises(ArchiveReadError) as failure:
        archive.read(receipt)
    assert failure.value.reason == "artifact_location_unsupported"


@pytest.mark.parametrize("fault", ["duplicate", "nonfinite", "overflow"])
def test_matching_sha_does_not_admit_non_strict_json(archive_case, fault):
    from algua.tracking.research_archive import ArchiveReadError

    archive, payload, receipt, artifact = archive_case
    text = json.dumps(payload)
    if fault == "duplicate":
        text = '{"authority":"none",' + text[1:]
    else:
        text = '{"invalid_number":' + ("NaN" if fault == "nonfinite" else "1e999") + ',' + text[1:]
    raw = text.encode()
    artifact.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    receipt = {**receipt, "sha256": digest,
               "reference": f"mlflow:{receipt['run_id']}/public-evidence.json#sha256={digest}"}
    with sqlite3.connect(archive.database) as conn:
        conn.execute("UPDATE tags SET value=? WHERE key='archive_sha256' AND run_uuid=?",
                     (digest, receipt["run_id"]))
    for existing_only in (False, True):
        with pytest.raises(ArchiveReadError) as failure:
            LocalResearchArchive(archive.tracking_uri, existing_only=existing_only).read(receipt)
        assert failure.value.reason == "artifact_payload_invalid"


@pytest.mark.parametrize("size", [256 * 1024, 16 * MIB])
def test_local_reader_exact_bounds_and_capped_reads(tmp_path, monkeypatch, size):
    from algua.tracking import bounded_local_read as bounded

    path = tmp_path / "exact"
    path.write_bytes(b"x" * size)
    budget = bounded.ReadBudget(size)
    read, requests = os.read, []

    def observed(fd, count):
        requests.append(count)
        return read(fd, count)

    monkeypatch.setattr(bounded.os, "read", observed)
    raw = bounded.read_local_file(path, root=tmp_path, max_bytes=size, budget=budget)
    assert raw == b"x" * size
    assert budget.used_bytes == size and budget.remaining_bytes == 0
    assert max(requests) <= 64 * 1024 and sum(requests) == size


@pytest.mark.parametrize("cap", [256 * 1024, 16 * MIB])
def test_oversize_local_file_has_no_body_read(tmp_path, monkeypatch, cap):
    from algua.tracking import bounded_local_read as bounded

    path = tmp_path / "oversized"
    with path.open("wb") as stream:
        stream.truncate(cap + 1)
    budget = bounded.ReadBudget(32 * MIB)

    def forbidden(*args):
        raise AssertionError("oversized source body was read")

    monkeypatch.setattr(bounded.os, "read", forbidden)
    with pytest.raises(bounded.LocalReadError) as failure:
        bounded.read_local_file(path, root=tmp_path, max_bytes=cap, budget=budget)
    assert failure.value.reason == "source_bytes_exceeded" and budget.used_bytes == 0


def test_aggregate_budget_stops_before_next_artifact_body(tmp_path, monkeypatch):
    from algua.tracking import bounded_local_read as bounded

    path = tmp_path / "artifact"
    path.write_bytes(b"x" * (16 * MIB))
    budget = bounded.ReadBudget(32 * MIB)
    for _ in range(2):
        assert len(bounded.read_local_file(path, root=tmp_path, max_bytes=16 * MIB,
                                          budget=budget)) == 16 * MIB
    monkeypatch.setattr(bounded.os, "read", lambda *args: pytest.fail("aggregate cap was exceeded"))
    with pytest.raises(bounded.LocalReadError) as failure:
        bounded.read_local_file(path, root=tmp_path, max_bytes=16 * MIB, budget=budget)
    assert failure.value.reason == "source_bytes_exceeded" and budget.used_bytes == 32 * MIB


@pytest.mark.parametrize("fault", ["short", "grow", "replace"])
def test_changed_sources_refuse_without_retry(tmp_path, monkeypatch, fault):
    from algua.tracking import bounded_local_read as bounded

    path = tmp_path / "changing"
    original = b"x" * (128 * 1024)
    path.write_bytes(original)
    read, changed = os.read, []

    def modify(fd, count):
        result = read(fd, count)
        if not changed:
            changed.append(True)
            if fault == "short":
                path.write_bytes(b"short")
            elif fault == "grow":
                with path.open("ab") as stream:
                    stream.write(b"growth")
            else:
                path.rename(tmp_path / "old")
                path.write_bytes(original)
        return result

    monkeypatch.setattr(bounded.os, "read", modify)
    with pytest.raises(bounded.LocalReadError) as failure:
        bounded.read_local_file(path, root=tmp_path, max_bytes=16 * MIB)
    assert failure.value.reason == "artifact_changed"


@pytest.mark.parametrize("fault", ["leaf", "parent", "fifo", "outside", "root-link"])
def test_link_nonregular_and_out_of_root_sources_refuse(tmp_path, fault):
    from algua.tracking import bounded_local_read as bounded

    root = tmp_path / "root"
    root.mkdir()
    target = root / "target"
    target.write_bytes(b"fixture")
    path = root / "file"
    if fault == "leaf":
        path.symlink_to(target)
    elif fault == "parent":
        (root / "directory").mkdir()
        (root / "directory/file").write_bytes(b"fixture")
        (root / "linked").symlink_to(root / "directory", target_is_directory=True)
        path = root / "linked/file"
    elif fault == "fifo":
        os.mkfifo(path)
    elif fault == "outside":
        path = tmp_path / "foreign"
        path.write_bytes(b"fixture")
    else:
        (tmp_path / "root-link").symlink_to(root, target_is_directory=True)
        root = tmp_path / "root-link"
        path = root / "target"
    with pytest.raises(bounded.LocalReadError) as failure:
        bounded.read_local_file(path, root=root, max_bytes=16 * MIB)
    assert failure.value.reason == "artifact_location_unsupported"
