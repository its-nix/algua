"""One bounded report interpretation for ledger outcomes, digest and queue publication."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from algua.contracts.idea import AttemptOutcome

REPORT_OUTCOMES = frozenset({
    "integrity_fail", "holdout_negative", "walkforward_refuted", "sweep_unstable",
    "candidate_preview_pass", "run_error", "data_blocked",
})


def completed_research_execution(record: dict[str, Any]) -> bool:
    """Recognize the recorded qualification-only exit, never infer it for legacy rows.

    Final exit 1 remains a qualification refusal. A valid report and matching complete controller
    facts distinguish it from an execution/finalization failure; no publication authority follows.
    """
    cycle_id = record.get("research_cycle_id")
    if (not isinstance(cycle_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", cycle_id) is None):
        return False
    if (record.get("outcome") != "completed" or type(record.get("exit_code")) is not int
            or record["exit_code"] != 1 or type(record.get("worker_exit_code")) is not int
            or record["worker_exit_code"] != 0 or record.get("timed_out") is not False
            or record.get("rate_limited") is not False
            or record.get("trailer_parse_error") is not False):
        return False
    result = record.get("controller")
    if not isinstance(result, dict) or result.get("phase") != "completed":
        return False
    ids, counts = result.get("idea_ids"), result.get("outcome_counts")
    if (result.get("research_cycle_id") != record.get("research_cycle_id")
            or not isinstance(ids, list) or not ids or len(ids) > 40
            or any(type(value) is not int or value <= 0 for value in ids)
            or len(set(ids)) != len(ids) or ids != record.get("idea_ids")
            or not isinstance(counts, dict) or not counts
            or any(key not in REPORT_OUTCOMES - {"run_error"} for key in counts)
            or any(type(value) is not int or value <= 0 for value in counts.values())):
        return False
    keys = ("attempts_total", "terminal_count", "unfinished_count", "invalid_count",
            "write_error_count", "error_count", "ok_count")
    if any(type(result.get(key)) is not int or result[key] < 0 for key in keys):
        return False
    total, invalid = len(ids), counts.get("integrity_fail", 0)
    return (invalid > 0 and sum(counts.values()) == total
            and result["attempts_total"] == result["terminal_count"] == total
            and result["unfinished_count"] == result["invalid_count"]
            == result["write_error_count"] == 0
            and result["error_count"] == invalid
            and result["ok_count"] == total - invalid - counts.get('data_blocked', 0))


def clean_report_text(value: str, limit: int = 120) -> str:
    return re.sub(r"[^A-Za-z0-9 ._,%+-]", "", value)[:limit].strip()


def read_report(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Validate the WHOLE EOF trailer before any consumer can act on one of its entries.

    Legacy title-only reports remain digest-readable, but cannot supply ledger outcomes.
    Merge-back's recipe/commit cross-check remains in the existing publication adapter.
    """
    with path.open("rb") as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 65536))
        text = stream.read().decode("utf-8", errors="replace")
    start = text.rfind("```json")
    match = re.fullmatch(r"\s*(.*?)\s*```\s*", text[start + 7:], re.S)
    if start < 0 or match is None:
        raise ValueError("no EOF-anchored json trailer")
    data = json.loads(match[1])
    if not isinstance(data, dict) or not isinstance(data.get("hypotheses"), list):
        raise ValueError("hypotheses must be a list")
    raw = data["hypotheses"]
    if len(raw) > 40:
        raise ValueError("excessive report entries")
    found = []
    seen: set[int] = set()
    for row in raw:
        if isinstance(row, str):
            row = {"title": row}
        if not isinstance(row, dict) or not isinstance(row.get("title"), str):
            raise ValueError("non-string hypothesis title")
        idea_id, outcome = row.get("idea_id"), row.get("outcome")
        verdict, reason = row.get("verdict"), row.get("reason")
        falsification = row.get("falsification_assessment")
        if idea_id is not None:
            if type(idea_id) is not int or idea_id in seen:
                raise ValueError("invalid or duplicate idea_id")
            seen.add(idea_id)
        if outcome is not None and (not isinstance(outcome, str) or outcome not in REPORT_OUTCOMES):
            raise ValueError("invalid outcome")
        if verdict is not None and (not isinstance(verdict, str) or verdict not in {
            "discarded", "candidate-preview-pass", "error", "blocked",
        }):
            raise ValueError("invalid verdict")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("non-string hypothesis reason")
        if falsification is not None and (
            not isinstance(falsification, str) or falsification not in {
            "refuted", "survived", "untested",
        }):
            raise ValueError("invalid falsification_assessment")
        title = clean_report_text(row["title"])
        clean_reason = clean_report_text(reason, 300) if reason is not None else None
        if outcome is not None and (not title or not clean_reason):
            raise ValueError("outcome requires a usable title and reason")
        if title:
            found.append({"title": title, "verdict": verdict, "idea_id": idea_id,
                          "outcome": outcome, "reason": clean_reason,
                          "falsification_assessment": falsification,
                          "merge_back": row.get("merge_back")})
    gate = data.get("preview_gate")
    if gate is not None:
        if (not isinstance(gate, dict) or type(gate.get("passed")) is not bool
                or not isinstance(gate.get("failed_checks"), list)
                or any(not isinstance(c, str) for c in gate["failed_checks"])):
            raise ValueError("invalid preview_gate")
        gate = {"passed": gate["passed"], "failed_checks": [
            clean_report_text(c) for c in gate["failed_checks"][:40] if clean_report_text(c)]}
    return found, gate


def report_outcomes(path: Path | None) -> dict[int, tuple[AttemptOutcome, str]]:
    if path is None:
        return {}
    try:
        rows, _ = read_report(path)
    except (OSError, ValueError, RecursionError):
        return {}
    return {row["idea_id"]: (AttemptOutcome(row["outcome"]), row["reason"])
            for row in rows if type(row["idea_id"]) is int
            and row["outcome"] is not None and row["reason"]}


def campaign_hypotheses(rows: list[dict[str, Any]], result: dict[str, Any], *,
                        cycle_id: str, claim_tokens: dict) -> list[dict[str, Any]]:
    """Constrain digest/queue publication to selected, fenced, recorded campaign work."""
    try:
        campaign = result["campaign"]
        selected = {c["hypothesis_id"] for c in campaign["selection"]["choices"]}
        attempts = {a["idea_id"]: a for a in result["attempts"]}
        if (result["research_cycle_id"] != cycle_id
                or campaign["menu"]["request"]["research_cycle_id"] != cycle_id
                or set(claim_tokens) != selected or set(attempts) != selected):
            raise ValueError("campaign publication claim/context mismatch")
        bound = []
        for row in rows:
            idea_id = row["idea_id"]
            if idea_id not in selected:
                continue
            if row["outcome"] != attempts[idea_id]["outcome"]:
                raise ValueError("campaign report differs from recorded outcome")
            mb = row["merge_back"]
            if mb is not None and (
                row["outcome"] != "candidate_preview_pass" or not isinstance(mb, dict)
                or type(mb.get("idea_id")) is not int or mb.get("idea_id") != idea_id
            ):
                row = {**row, "merge_back": None}
            bound.append(row)
        return bound
    except (KeyError, TypeError) as exc:
        raise ValueError("missing or malformed campaign completion context") from exc
