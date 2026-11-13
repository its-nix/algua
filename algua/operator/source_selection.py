"""Bounded source-level scheduling and review; never empirical/qualification authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from algua.config.settings import Settings
from algua.knowledge.inspirations import NOTE_ID_RE, parse_note
from algua.operator.research_memory_checkpoint import canonical, strict_json
from algua.operator.source_recipe import assess_recipe
from algua.primitives.atomic_io import write_bytes_durable
from algua.tracking.bounded_local_read import read_local_file


def _digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _state(directory: Path) -> dict:
    path = directory / "leap-sources.json"
    if not path.exists() and not path.is_symlink():
        return {}
    value = strict_json(read_local_file(path, root=directory.absolute(), max_bytes=1024 * 1024))
    if not isinstance(value, dict) or len(value) > 200:
        raise ValueError("source_selection:invalid_state")
    for key, row in value.items():
        if (
            not NOTE_ID_RE.fullmatch(key)
            or not isinstance(row, dict)
            or set(row) != {"source_key", "passes", "recipe", "reason"}
            or not isinstance(row["source_key"], str)
            or len(row["source_key"]) != 64
            or type(row["passes"]) is not int
            or not 0 <= row["passes"] <= 2
            or not isinstance(row["reason"], str)
        ):
            raise ValueError("source_selection:invalid_state")
    return value


def source_plan(
    settings: Settings, profile: dict, *, code: str, limit: int = 3, force: bool = False
) -> dict:
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError("source_selection:invalid_limit")
    progress = _state(settings.data_dir)
    environment = _digest({"profile": profile, "code": code})
    rows = []
    paths = sorted((settings.knowledge_dir / "inspirations").glob("*.md"), reverse=True)
    for path in [p for p in paths if NOTE_ID_RE.fullmatch(p.stem)][:200]:
        identity = path.stem
        raw = read_local_file(path, root=settings.knowledge_dir.absolute(), max_bytes=16384)
        frontmatter, body = parse_note(raw.decode())
        if frontmatter.get("id") != identity:
            raise ValueError("source_selection:note_identity_mismatch")
        if frontmatter.get("status") == "exhausted":
            continue
        frontmatter = json.loads(json.dumps(frontmatter, default=str))
        metadata = frontmatter
        # Mutable use/exhaustion bookkeeping must not reset substantive source history.
        content = {k: v for k, v in frontmatter.items() if k not in {"status", "leaps"}}
        source_hash = _digest({"metadata": content, "body": body})
        key = _digest({"source": source_hash, "environment": environment})
        prior = progress.get(identity, {})
        same = prior.get("source_key") == key
        recipe = prior.get("recipe") if same else frontmatter.get("pilot_recipe")
        try:
            verdict = assess_recipe(recipe, profile)
        except ValueError:
            recipe = None
            verdict = {"status": "unknown", "reasons": ["invalid_declared_recipe"]}
        passes = prior.get("passes", 0) if same else 0
        waiting = not force and (verdict["status"] == "blocked" or passes >= 2)
        rows.append(
            {
                "source_id": identity,
                "source_hash": source_hash,
                "source_key": key,
                "metadata": metadata,
                "recipe": recipe,
                "assessment": verdict,
                "passes": passes,
                "waiting": waiting,
            }
        )
    rows.sort(
        key=lambda r: (
            r["waiting"],
            r["assessment"]["status"] != "feasible",
            # Soft cold-start preferences for the fixed US-equity daily pilot only.
            r["assessment"]["status"] != "feasible"
            and r["metadata"].get("market") != "us_equities",
            r["assessment"]["status"] != "feasible" and r["metadata"].get("horizon") != "daily",
            r["assessment"]["status"] != "feasible" and r["metadata"].get("status") == "used",
            r["passes"],
            r["source_id"],
        )
    )
    selected = [r for r in rows if not r["waiting"]][:limit]
    return {
        "schema_version": "leap-source-plan/v1",
        "profile": profile,
        "environment": environment,
        "sources": selected,
        "backlog": [
            {
                "source_id": r["source_id"],
                "reasons": r["assessment"]["reasons"],
                "passes": r["passes"],
            }
            for r in rows
            if r not in selected
        ],
        "limit": limit,
        "authority": "none",
    }


def review_sources(plan: dict, reviews: object, *, new_ideas: list) -> dict:
    """Validate the whole declared review before the trusted import; no authored code loads."""
    if not isinstance(reviews, list) or len(reviews) > len(plan["sources"]):
        raise ValueError("source_selection:invalid_reviews")
    offered = {s["source_id"]: s for s in plan["sources"]}
    found = {}
    for row in reviews:
        if (
            not isinstance(row, dict)
            or set(row) != {"source_id", "recipe", "reason"}
            or row["source_id"] not in offered
            or row["source_id"] in found
            or not isinstance(row["reason"], str)
            or not 1 <= len(row["reason"]) <= 2000
        ):
            raise ValueError("source_selection:invalid_review")
        verdict = assess_recipe(row["recipe"], plan["profile"])
        found[row["source_id"]] = {
            **row,
            "assessment": verdict,
            "source_key": offered[row["source_id"]]["source_key"],
        }
    for idea in new_ideas:
        links = {link.inspiration_id for link in idea.inspirations}
        if (
            not links
            or not links <= set(found)
            or not any(
                found[s]["assessment"]["status"] == "feasible"
                and found[s]["recipe"]["market"] == idea.market
                and found[s]["recipe"]["horizon"] == idea.horizon
                and set(found[s]["recipe"]["required_data"]) == set(idea.required_data)
                for s in links
            )
        ):
            raise ValueError("source_selection:idea_without_feasible_offered_source")
    return {
        "complete": set(found) == set(offered),
        "reviews": list(found.values()),
        "missing_sources": sorted(set(offered) - set(found)),
        "authority": "none",
    }


def record_source_pass(
    directory: Path, result: dict, *, clean: bool, imported_sources: set[str]
) -> None:
    if not clean:
        return
    state = _state(directory)
    for row in result["reviews"]:
        source = row["source_id"]
        prior = state.get(source, {})
        count = prior.get("passes", 0) if prior.get("source_key") == row["source_key"] else 0
        state[source] = {
            "source_key": row["source_key"],
            "passes": 0 if source in imported_sources else min(2, count + 1),
            "recipe": row["recipe"],
            "reason": row["reason"],
        }
    # Keep bounded operational memory; archived criticism/experiments are never pruned here.
    state = {key: state[key] for key in sorted(state)[-200:]}
    write_bytes_durable(canonical(state) + b"\n", directory / "leap-sources.json")
