"""Run-start snapshot (Drive -> files) and the one-time migration (files -> Drive).

The snapshot has the exact layout the file readers already understand, so a driver points
`ALGUA_STEERING_DIR` at it and every existing read path works unchanged (spec 2026-11-12 §4):

    <dest>/categories.txt
    <dest>/inspirations/_sources.yaml
    <dest>/inspirations/<id>.md
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml

from algua.knowledge.drive.tables import (
    CATEGORIES,
    CATEGORY_HEADER,
    CategoriesTable,
    Client,
    InspirationsTable,
    SourcesTable,
    note_from_row,
)
from algua.knowledge.frontmatter import render_doc
from algua.knowledge.inspirations import NOTE_ID_RE, parse_note

_HEADER = ("# Snapshot of the Drive Steering Sheet (Categories tab), exported at run start.\n"
           "# Do not edit: change the Sheet instead.\n")


def export_snapshot(client: Client, dest: Path) -> dict[str, int]:
    """Read everything first, then write a temp dir and swap it in: all or nothing."""
    lines = CategoriesTable(client).lines()
    venues = SourcesTable(client).load()
    rows = InspirationsTable(client).rows()

    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    notes_dir = tmp / "inspirations"
    notes_dir.mkdir(parents=True)
    (tmp / "categories.txt").write_text(_HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    (notes_dir / "_sources.yaml").write_text(
        yaml.safe_dump({"venues": venues}, sort_keys=False), encoding="utf-8")
    written = skipped = 0
    for row in rows:
        if not NOTE_ID_RE.match(row.get("id", "")):
            skipped += 1
            continue
        fm, body = note_from_row(row)
        (notes_dir / f"{row['id']}.md").write_text(render_doc(fm, body), encoding="utf-8")
        written += 1
    if dest.exists():
        shutil.rmtree(dest)
    os.replace(tmp, dest)
    return {"categories": len(lines), "venues": len(venues), "notes": written,
            "skipped": skipped}


def _category_rows(categories_file: Path) -> list[dict[str, str]]:
    rows = []
    for line in categories_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        slug, *hints = stripped.split()
        row = {"slug": slug, "enabled": "yes"}
        for hint in hints:
            key, _, value = hint.partition("=")
            if key in ("market", "horizon") and value:
                row[key] = value
        rows.append(row)
    return rows


def migrate_files(client: Client, *, categories_file: Path,
                  inspirations_dir: Path) -> dict[str, dict[str, int]]:
    """Copy today's steering files and vault notes into the Sheets. Safe to re-run."""
    out: dict[str, dict[str, int]] = {}

    cat_rows = _category_rows(categories_file)
    client.ensure_header(*CATEGORIES, CATEGORY_HEADER)
    if client.read_tab(*CATEGORIES, required=["slug"]):
        out["categories"] = {"added": 0, "already_present": len(cat_rows)}
    else:
        client.append_rows(*CATEGORIES, cat_rows)
        out["categories"] = {"added": len(cat_rows), "already_present": 0}

    sources = SourcesTable(client)
    have = sources.load()
    keys = {v.get("key") for v in have}
    path = inspirations_dir / "_sources.yaml"
    file_venues: list[dict[str, Any]] = (
        list((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("venues") or [])
        if path.exists() else [])
    new = [v for v in file_venues if v.get("key") not in keys]
    if new:
        sources.save(have + new)
    out["venues"] = {"added": len(new), "already_present": len(file_venues) - len(new)}

    table = InspirationsTable(client)
    ids = table.ids()
    added = present = 0
    for note in sorted(inspirations_dir.glob("*.md")):
        if not NOTE_ID_RE.match(note.stem):
            continue
        if note.stem in ids:
            present += 1
            continue
        fm, body = parse_note(note.read_text(encoding="utf-8"))
        table.append(fm, body)
        ids.add(note.stem)
        added += 1
    out["notes"] = {"added": added, "already_present": present}
    return out
