"""Bind the existing advisory policy to explicit choices at the ledger write boundary."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict

from algua.registry.idea_scorecard import campaign_scorecard
from algua.research.campaign_policy import campaign_exclusions, campaign_menu


def menu_from_history(history: dict, request: dict) -> dict:
    """Capture complete feedback and resources; attempt slots are not statistical trials."""
    category = request["category"]
    # Keep every hypothesis in collision history, but admit only the requested category.
    eligible_history = {**history, "hypotheses": [
        h if category is None or h["category"] == category else {**h, "claimed_by": "filtered"}
        for h in history["hypotheses"]]}
    choices = campaign_menu(eligible_history, budget=request["limits"]["max_hypotheses"])
    history = {**history, "hypotheses": [
        {k: v for k, v in h.items() if k != "claim_token"} for h in history["hypotheses"]]}
    body = {"request": request, "scorecard": history,
            "choices": [asdict(c) for c in choices if category is None or c.category == category],
            "exclusions": campaign_exclusions(history)}
    # JSON normalizes enums, tuples and integer keys and detaches all caller-owned objects.
    body = json.loads(json.dumps(body, allow_nan=False, sort_keys=True))
    identity = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return {"menu_id": identity, **body}


def selection_ids(campaign: dict) -> list[int]:
    """Validate the complete chooser reply, including exact resolved evidence and slot costs."""
    if not isinstance(campaign, dict) or set(campaign) != {"menu", "selection"}:
        raise ValueError("campaign requires menu and selection")
    menu, reply = campaign["menu"], campaign["selection"]
    if (not isinstance(menu, dict) or not isinstance(reply, dict)
            or set(reply) != {"menu_id", "choices"}
            or reply["menu_id"] != menu.get("menu_id")
            or not isinstance(reply["choices"], list)):
        raise ValueError("malformed or stale campaign selection")
    try:
        if menu != menu_from_history(menu["scorecard"], menu["request"]):
            raise ValueError("changed campaign menu")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("malformed campaign menu") from exc
    options = {c["hypothesis_id"]: c for c in menu["choices"]}
    ids = []
    for choice in reply["choices"]:
        if (not isinstance(choice, dict) or set(choice) != {
            "category", "hypothesis_id", "reason", "prior_evidence_ids", "budget"}
            or type(choice["hypothesis_id"]) is not int
            or type(choice["budget"]) is not int
            or not isinstance(choice["reason"], str) or not choice["reason"].strip()
            or len(choice["reason"]) > 2000):
            raise ValueError("malformed campaign choice or missing explanation")
        idea_id = choice["hypothesis_id"]
        admitted = options.get(idea_id)
        if (idea_id in ids or admitted is None
                or any(choice[k] != admitted[k] for k in (
                    "category", "prior_evidence_ids", "budget"))):
            raise ValueError("duplicate or out-of-menu campaign choice")
        ids.append(idea_id)
    return ids


def validate_campaign(conn: sqlite3.Connection, campaign: dict, *, run_stamp: str,
                      category: str | None, ttl_minutes: int, preview_hold_hours: int) -> list[int]:
    """Bind claim resources and recompute feedback under BEGIN IMMEDIATE, before reaping."""
    try:
        ids = selection_ids(campaign)
        campaign = json.loads(json.dumps(campaign, allow_nan=False))
        request = campaign["menu"]["request"]
        expected = (request["research_cycle_id"], request["category"],
                    request["claim_ttl_minutes"], request["preview_hold_hours"])
        max_cost = request["limits"]["max_cost"]
    except (KeyError, TypeError) as exc:
        raise ValueError("malformed campaign resource context") from exc
    if expected != (run_stamp, category, ttl_minutes, preview_hold_hours):
        raise ValueError("campaign claim resource context changed")
    if max_cost is not None:
        raise ValueError("campaign monetary cost is unknown; configured cap forbids claims")
    menu = campaign["menu"]
    if menu != menu_from_history(campaign_scorecard(conn), menu["request"]):
        raise ValueError("stale or changed campaign feedback/menu context")
    return ids
