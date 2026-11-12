"""Run-start snapshot export and one-time migration (spec 2026-11-12 §4, §6.7)."""
from __future__ import annotations

import pytest

from algua.config.settings import Settings
from algua.knowledge.drive import DriveError, tables
from algua.knowledge.drive.snapshot import export_snapshot, migrate_files
from algua.knowledge.inspirations import list_notes
from algua.knowledge.sources_registry import SourcesRegistry
from algua.research.categories import load_categories
from tests._drive_fake import FakeDrive


def _seeded() -> FakeDrive:
    d = FakeDrive()
    d.seed(*tables.CATEGORIES, tables.CATEGORY_HEADER, [
        {"slug": "momentum", "horizon": "daily"}, {"slug": "crypto", "enabled": "no"}])
    d.seed(*tables.SOURCES, tables.SOURCES_HEADER, [
        {"key": "ssrn", "kind": "paper", "url": "https://ssrn.com", "categories": "momentum"}])
    d.seed(*tables.INSPIRATIONS, tables.INSPIRATION_HEADER, [{
        "id": "2026-11-12-quiet-drift", "found_at": "2026-11-12", "source_url": "https://x/1",
        "venue": "ssrn", "source_kind": "paper", "category": "momentum",
        "market": "us_equities", "horizon": "daily", "mechanism": "drift",
        "obscurity": "niche", "status": "fresh", "leaps": "[3]", "body": "Body text.\n"},
        {"id": "not a valid id", "status": "fresh"}])
    return d


def test_export_writes_files_readable_by_existing_readers(tmp_path):
    dest = tmp_path / "steering-1"
    counts = export_snapshot(_seeded(), dest)
    assert counts == {"categories": 2, "venues": 1, "notes": 1, "skipped": 1}
    assert load_categories(dest / "categories.txt") == ["momentum"]
    s = Settings(_env_file=None, steering_dir=dest)
    notes = list_notes(s)
    assert [n["id"] for n in notes] == ["2026-11-12-quiet-drift"]
    assert notes[0]["leaps"] == [3]
    assert "Body text." in (dest / "inspirations" / "2026-11-12-quiet-drift.md").read_text()
    assert SourcesRegistry(s).load()[0]["key"] == "ssrn"


def test_export_is_all_or_nothing(tmp_path):
    dest = tmp_path / "steering-1"
    dest.mkdir()
    (dest / "marker").write_text("old")
    d = _seeded()
    d.fail["read_tab"] = 3  # categories, sources ok; inspirations read fails
    with pytest.raises(DriveError):
        export_snapshot(d, dest)
    assert (dest / "marker").read_text() == "old"
    assert not (tmp_path / "steering-1.tmp").exists()


def test_migrate_is_idempotent(tmp_path):
    cats = tmp_path / "categories.txt"
    cats.write_text("# comment\nmomentum market=us_equities\nseasonality horizon=daily\n# vol_x\n")
    kb = tmp_path / "kb" / "inspirations"
    kb.mkdir(parents=True)
    (kb / "_sources.yaml").write_text("venues:\n  - key: ssrn\n    kind: paper\n")
    (kb / "2026-11-05-one-note.md").write_text(
        "---\nid: 2026-11-05-one-note\nstatus: used\nleaps: [1]\nsource_url: https://a\n---\nB\n")
    d = FakeDrive()
    first = migrate_files(d, categories_file=cats, inspirations_dir=kb)
    assert first == {"categories": {"added": 2, "already_present": 0},
                     "venues": {"added": 1, "already_present": 0},
                     "notes": {"added": 1, "already_present": 0}}
    second = migrate_files(d, categories_file=cats, inspirations_dir=kb)
    assert second == {"categories": {"added": 0, "already_present": 2},
                      "venues": {"added": 0, "already_present": 1},
                      "notes": {"added": 0, "already_present": 1}}
    assert len(d.rows(*tables.INSPIRATIONS)) == 1
    assert d.rows(*tables.INSPIRATIONS)[0]["leaps"] == "[1]"
    assert [r["slug"] for r in d.rows(*tables.CATEGORIES)] == ["momentum", "seasonality"]
