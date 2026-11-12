"""Inspirations, sources and categories as Sheets behind the existing writers (spec §6.2–6.6)."""
from __future__ import annotations

import pytest

from algua.config.settings import Settings
from algua.knowledge import inspirations as insp
from algua.knowledge.drive import DriveError, tables
from algua.knowledge.sources_registry import SourcesRegistry
from tests._drive_fake import FakeDrive

CATS = {"momentum", "mean_reversion"}
NOTE = """---
id: {id}
found_at: '2026-11-12'
source_url: https://example.com/{id}
venue: blog/example
source_kind: blog
category: momentum
market: us_equities
horizon: daily
mechanism: quiet names drift
obscurity: niche
status: fresh
---
Body of {id}.
"""


@pytest.fixture
def drive(monkeypatch):
    fake = FakeDrive()
    monkeypatch.setattr(tables, "client_for", lambda _s: fake)
    return fake


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, knowledge_dir=tmp_path / "kb", data_dir=tmp_path / "data",
                    drive_folder_id="F")


def _stage(tmp_path, *ids):
    d = tmp_path / "staged"
    d.mkdir(exist_ok=True)
    for i in ids:
        (d / f"{i}.md").write_text(NOTE.format(id=i))
    return d


def _accept(tmp_path, staged):
    return insp.accept_new_notes(staged_dir=staged, settings=_settings(tmp_path),
                                 seen_path=tmp_path / "seen.jsonl", categories=CATS,
                                 run_stamp="r1", max_notes=10)


def test_accept_appends_rows_and_skips_ids_already_in_sheet(tmp_path, drive):
    drive.seed(*tables.INSPIRATIONS, tables.INSPIRATION_HEADER, [{"id": "2026-11-12-foo"}])
    result = _accept(tmp_path, _stage(tmp_path, "2026-11-12-foo", "2026-11-12-bar"))
    assert result["accepted"] == ["2026-11-12-bar"]
    assert result["rejected"] == [{"file": "2026-11-12-foo.md",
                                   "reasons": ["id already exists in the vault"]}]
    bar = [r for r in drive.rows(*tables.INSPIRATIONS) if r["id"] == "2026-11-12-bar"][0]
    assert bar["body"].strip() == "Body of 2026-11-12-bar."
    assert bar["url_hash"] == insp.url_hash("https://example.com/2026-11-12-bar")
    assert not (tmp_path / "kb" / "inspirations").exists()  # nothing written to the vault


def test_accept_rerun_after_partial_failure_does_not_duplicate(tmp_path, drive):
    staged = _stage(tmp_path, "2026-11-12-aaa", "2026-11-12-bbb")
    drive.fail["append_rows"] = 2
    with pytest.raises(DriveError):
        _accept(tmp_path, staged)
    drive.fail.clear()
    _accept(tmp_path, staged)
    ids = [r["id"] for r in drive.rows(*tables.INSPIRATIONS)]
    assert sorted(ids) == ["2026-11-12-aaa", "2026-11-12-bbb"]


def test_mark_used_appends_leap_and_flips_status_in_sheet(tmp_path, drive):
    _accept(tmp_path, _stage(tmp_path, "2026-11-12-foo"))
    s = _settings(tmp_path)
    fm = insp.mark_used(s, "2026-11-12-foo", idea_id=7)
    assert fm["leaps"] == [7] and fm["status"] == "used"
    insp.mark_used(s, "2026-11-12-foo", idea_id=7)
    row = drive.rows(*tables.INSPIRATIONS)[0]
    assert row["leaps"] == "[7]" and row["status"] == "used"
    insp.mark_exhausted(s, "2026-11-12-foo")
    assert drive.rows(*tables.INSPIRATIONS)[0]["status"] == "exhausted"


def test_sources_roundtrip_is_lossless(tmp_path, drive):
    venues = [
        {"key": "blog/x", "kind": "blog", "url": "https://x", "categories": ["momentum"],
         "yield": {"n": 5, "survival_yield": 0.2}, "notes": "keep me"},
        {"key": "ssrn", "kind": "paper", "url": "https://ssrn.com", "categories": [],
         "added_by": "forage", "added_at": "2026-11-01"},
    ]
    t = tables.SourcesTable(drive)
    t.save(venues)
    assert t.load() == venues


def test_sources_registry_dispatches_to_sheet(tmp_path, drive):
    reg = SourcesRegistry(_settings(tmp_path))
    reg.propose({"key": "blog/new", "kind": "blog", "url": "https://n", "categories": ["momentum"]})
    reg.write_yields({"blog/new": {"n": 9}})
    loaded = tables.SourcesTable(drive).load()
    assert loaded[0]["key"] == "blog/new" and loaded[0]["yield"] == {"n": 9}
    assert loaded[0]["added_by"] == "forage"


def test_categories_lines_render_disabled_as_comments_and_require_one_enabled(drive):
    drive.seed(*tables.CATEGORIES, tables.CATEGORY_HEADER, [
        {"slug": "momentum", "market": "us_equities", "horizon": "daily", "enabled": ""},
        {"slug": "crypto_carry", "enabled": "FALSE"},
    ])
    assert tables.CategoriesTable(drive).lines() == [
        "momentum market=us_equities horizon=daily", "# crypto_carry"]
    drive.seed(*tables.CATEGORIES, tables.CATEGORY_HEADER, [{"slug": "a", "enabled": "no"}])
    with pytest.raises(DriveError) as exc:
        tables.CategoriesTable(drive).lines()
    assert exc.value.code == "drive_schema"


def test_file_backend_untouched_when_drive_disabled(tmp_path, monkeypatch):
    def boom(_s):
        raise AssertionError("Drive must not be touched when disabled")
    monkeypatch.setattr(tables, "client_for", boom)
    s = Settings(_env_file=None, knowledge_dir=tmp_path / "kb", data_dir=tmp_path / "data")
    result = insp.accept_new_notes(staged_dir=_stage(tmp_path, "2026-11-12-foo"), settings=s,
                                   seen_path=tmp_path / "seen.jsonl", categories=CATS,
                                   run_stamp="r", max_notes=5)
    assert result["accepted"] == ["2026-11-12-foo"]
    assert (tmp_path / "kb" / "inspirations" / "2026-11-12-foo.md").exists()
