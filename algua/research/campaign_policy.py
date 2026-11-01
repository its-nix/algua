"""Pure advisory research menu. Budgets are attempt slots, never capital or alpha estimates."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import TypedDict

from algua.research.idea_dedup import is_collision, signature

_REFERENCE = re.compile(r"(?<![\w:])(?:ideas|idea_attempts|negative_results):[^\s,;()\[\]{}]+")


@dataclass(frozen=True)
class CampaignChoice:
    category: str
    hypothesis_id: int
    reason: str
    prior_evidence_ids: tuple[str, ...]
    budget: int


class CampaignExclusion(TypedDict):
    reason: str
    prior_evidence_ids: tuple[str, ...]


def campaign_menu(scorecard: dict, *, budget: int, novelty_min: int = 1,
                  novelty_max: int | None = None) -> tuple[CampaignChoice, ...]:
    """Allocate one slot per eligible hypothesis, reserving novelty even if it stays unused.

    Novel means an unseen pool family (category fallback for missing families), not a certified
    novel alpha family. Lower observed economic rejection fractions precede higher ones; unknown
    evidence has no estimated return. No outcome is inferred from a stage or a negative-log label.
    Duplicate exceptions require a fresh pool entry with declared, persisted input changes.
    """
    values = (budget, novelty_min) + (() if novelty_max is None else (novelty_max,))
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("budget and novelty bounds must be nonnegative integers")
    reserve = min(budget, novelty_min)
    maximum = budget if novelty_max is None else min(budget, novelty_max)
    if maximum < reserve:
        raise ValueError("novelty_max must cover the reserved novelty slots")
    if budget == 0:
        return ()
    hypotheses = sorted(scorecard["hypotheses"], key=lambda h: h["id"])
    eligible = [h for h in hypotheses if _exclusion(h, scorecard) is None]
    families = scorecard["by_family"]

    def novel(h: dict) -> bool:
        return h["history_key"] not in families

    def priority(h: dict) -> tuple:
        prior = families.get(h["history_key"], {})
        rejected, evaluated = prior.get("economic_rejected", 0), prior.get("economic_evaluated", 0)
        return (Fraction(rejected, evaluated) if evaluated else Fraction(0),
                prior.get("attempted", 0), h["category"] or "legacy", h["id"])

    eligible.sort(key=priority)
    selected = [h for h in eligible if novel(h)][:reserve]
    reserved_ids = {h["id"] for h in selected}
    # Missing novelty does not silently become more spending on familiar directions.
    remaining = budget - reserve
    novel_slots = len(selected)
    for h in eligible:
        if h["id"] in reserved_ids or remaining == 0:
            continue
        if novel(h) and novel_slots >= maximum:
            continue
        selected.append(h)
        remaining -= 1
        novel_slots += int(novel(h))
    choices = []
    for h in selected:
        prior = families.get(h["history_key"], {})
        refs = {f"ideas:{h['id']}", *prior.get("evidence_ids", [])}
        collisions, negatives = _collisions(h, scorecard)
        refs.update(f"ideas:{p['id']}" for p in collisions)
        refs.update(n["evidence_id"] for n in negatives)
        family_ids = {p["id"] for p in hypotheses if p["history_key"] == h["history_key"]}
        refs.update(n["evidence_id"] for n in scorecard["negative_results"]
                    if family_ids.intersection(n.get("idea_ids", [])))
        # All collision evidence matters, including a differently categorized unknown family.
        refs.update(a["evidence_id"] for a in scorecard["attempts"]
                    if a["idea_id"] in {p["id"] for p in collisions})
        label = "novelty reserve" if h["id"] in reserved_ids else "history priority"
        reason = (f"{label}; {h['history_key']}; "
                  f"economic_rejected={prior.get('economic_rejected', 0)}/"
                  f"{prior.get('economic_evaluated', 0)}; "
                  f"attempted={prior.get('attempted', 0)}; "
                  f"invalid={prior.get('invalid', 0)}; run_error={prior.get('run_error', 0)}; "
                  f"unfinished={prior.get('unfinished', 0)}; "
                  f"abandoned={prior.get('abandoned', 0)}; "
                  "negative logs are context, not economic verdicts")
        if collisions or negatives:
            reason += f"; new justification: {h['override_reason']}"
        choices.append(CampaignChoice(h["category"] or "legacy", h["id"], reason,
                                      tuple(sorted(refs)), 1))
    return tuple(choices)


def campaign_exclusions(scorecard: dict) -> dict[int, CampaignExclusion]:
    """Explain ineligible pool entries, separately from resource-deferred eligible entries."""
    exclusions: dict[int, CampaignExclusion] = {}
    for h in sorted(scorecard["hypotheses"], key=lambda h: h["id"]):
        reason = _exclusion(h, scorecard)
        if reason is None:
            continue
        colliding, negatives = _collisions(h, scorecard)
        ids = {h["id"], *(p["id"] for p in colliding)}
        refs = {f"ideas:{i}" for i in ids} | {n["evidence_id"] for n in negatives}
        refs.update(a["evidence_id"] for a in scorecard["attempts"] if a["idea_id"] in ids)
        exclusions[h["id"]] = {"reason": reason, "prior_evidence_ids": tuple(sorted(refs))}
    return exclusions


def _collisions(h: dict, scorecard: dict) -> tuple[list[dict], list[dict]]:
    # Older unattempted pool duplicates block later entries too; otherwise a fresh pool could
    # spend every reserved slot on paraphrases. Attempted entries always block regardless of age.
    attempted = {a["idea_id"] for a in scorecard["attempts"]}
    colliding = [p for p in scorecard["hypotheses"] if p["id"] != h["id"]
                 and (p["id"] < h["id"] or p["id"] in attempted)
                 and is_collision(h["signature"], h["family"], p["signature"], p["family"])]
    collision_ids = {p["id"] for p in colliding}
    negatives = [n for n in scorecard["negative_results"]
                 if (collision_ids | {h["id"]}).intersection(n.get("idea_ids", []))
                 or (n.get("hypothesis") and is_collision(h["signature"], h["family"],
                                                          signature("", n["hypothesis"]), None))]
    return colliding, negatives


def _exclusion(h: dict, scorecard: dict) -> str | None:
    attempts = scorecard["attempts"]
    if any(a["idea_id"] == h["id"] for a in attempts):
        return "already attempted; changed assumptions require a new justified pool entry"
    if h["status"] != "open" or h["claimed_by"] is not None:
        return "not an unclaimed open hypothesis"
    colliding, negatives = _collisions(h, scorecard)
    if not colliding and not negatives:
        return None
    if any(a["idea_id"] in {p["id"] for p in colliding}
           and a["outcome"] in (None, "candidate_preview_pass") for a in attempts):
        return "duplicate has unfinished evidence; wait for its conclusion"
    text = h.get("override_reason") or ""
    reason = _reason_signature(text)
    previous = {_reason_signature(p.get("override_reason") or "") for p in colliding}
    previous.update(_reason_signature(n["reason"]) for n in negatives)
    prior_attempts = [a for a in attempts if a["idea_id"] in {p["id"] for p in colliding}]
    refs = set(_REFERENCE.findall(text))
    evidence = {a["evidence_id"] for a in prior_attempts} | {n["evidence_id"] for n in negatives}
    allowed = evidence | {f"ideas:{p['id']}" for p in colliding}
    required = evidence | {f"ideas:{h.get('duplicate_of_idea_id')}"}
    if not required <= refs <= allowed:
        return "duplicate requires exact, resolved causal evidence anchors"
    if (not reason or reason in previous
            or reason in {"retry", "again try", "new reason", "rerun"}):
        return "duplicate without a new, anchored justification"
    if not _changed_inputs(h, colliding):
        return "duplicate without supported persisted input changes"
    stamps = [p["created_at"] for p in colliding]
    stamps += [a[k] for a in prior_attempts for k in ("claimed_at", "outcome_at")
               if k == "claimed_at" or a["outcome"] is not None]
    stamps += [n["created_at"] for n in negatives]
    try:
        created = _timestamp(h["created_at"])
        if any(created <= _timestamp(s) for s in stamps):
            return "duplicate justification predates blocking evidence; create a fresh entry"
    except (ValueError, TypeError):
        return "duplicate evidence freshness cannot be established"
    return None


def _reason_signature(text: str) -> str:
    # New field lists or reference numbers cannot make a recycled explanation new.
    narrative = re.sub(r"^changed_fields=[a-z_,]+;\s*", "", text)
    return signature("", _REFERENCE.sub("", narrative))


def _timestamp(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError("campaign evidence timestamps must be timezone-aware")
    return stamp


def _changed_inputs(h: dict, colliding: list[dict]) -> bool:
    """Validate declared differences in existing Idea fields, never their semantic truth."""
    declaration = re.fullmatch(r"changed_fields=([a-z_,]+);\s*(\S.*)",
                               h.get("override_reason") or "", re.DOTALL)
    if declaration is None or not colliding:
        return False
    fields = set(declaration[1].split(","))
    supported = {"source_ref", "source_date", "falsification", "required_data", "market", "horizon"}
    if not fields or not fields <= supported:
        return False
    parent = next((p for p in colliding if p["id"] == h.get("duplicate_of_idea_id")
                   and p["id"] < h["id"]), None)

    def value(idea: dict, field: str) -> str | tuple:
        raw = idea.get(field)
        if field == "required_data":
            return tuple(sorted(set(raw or [])))
        if field == "falsification":
            return signature("", raw or "")
        return (raw or "").strip()

    return (parent is not None
            and all(value(h, f) and value(h, f) != value(parent, f) for f in fields)
            and all(any(value(h, f) != value(p, f) for f in fields) for p in colliding))
