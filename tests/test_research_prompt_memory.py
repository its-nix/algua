"""Pure forwarding of a real temporary admission; no model/author delivery is asserted."""
from __future__ import annotations

import copy
import hashlib
import sqlite3
import subprocess
from dataclasses import asdict

import pytest

from algua.operator.campaign_memory_worker import project_snapshot
from algua.operator.research_cycle import CycleLimits, ResearchCycle
from algua.operator.research_memory_checkpoint import canonical
from algua.registry.campaign_selection import menu_from_history
from tests.campaign_fixtures import add_idea
from tests.test_research_memory import _explore
from tests.test_research_memory import memory_case as memory_case


@pytest.fixture
def admission(memory_case):
    authority, old, worker, source, archive, memory = memory_case
    _explore(source)
    receipt = memory.capture(worker, worker_exit=0, source_commit="b" * 40)
    report = worker / "report.md"
    report.write_text('```json\n{"hypotheses":[{"idea_id":1,"title":"fixture",'
                      '"outcome":"sweep_unstable","reason":"SYNTHETIC_FIXTURE"}]}\n```')
    old.finish(phase="completed", worker_exit=0, report=report, evidence_ref=receipt["reference"])
    snapshot = project_snapshot([{"receipt": receipt, "payload": memory.read()}],
        coverage={"candidate_attempts_considered": 1, "candidate_cycles": 1,
                  "cycles_without_receipt": 0}, cutoff=1, tracking_uri=archive.tracking_uri)
    add_idea(authority, "SYNTHETIC_FIXTURE retention hypothesis", family="retention",
        duplicate_of_idea_id=1, source_ref="SYNTHETIC_FIXTURE archived-input-v2",
        override_reason="changed_fields=source_ref; ideas:1 idea_attempts:1; "
                        "Archived timestamps replace original sampling")
    add_idea(authority, "SYNTHETIC_FIXTURE calendar rotation", family="calendar")
    cycle = ResearchCycle(authority, old.directory, "prompt-fixture")
    request = {"limits": CycleLimits(max_hypotheses=3),
               "context": {"public_research_memory": snapshot}, "ttl_minutes": 1440}
    menu = cycle.campaign_menu(**request)
    campaign = {"menu": menu, "selection": {"menu_id": menu["menu_id"], "choices": [
        {**choice, "reason": "SYNTHETIC_FIXTURE choose declared input change"}
        for choice in menu["choices"]]}}
    claimed, response = cycle.start(**request, campaign=campaign)
    assert len(claimed) == 2
    response["claimed"] = [asdict(idea) for idea in claimed]
    database = menu["request"]["database"]
    return response, cycle.cycle_id, database


def decode(case):
    from algua.operator.research_prompt_memory import decode_admitted_memory

    response, cycle, database = case
    return decode_admitted_memory(canonical(response), cycle_id=cycle, database=database)


def reseal(response):
    campaign = response["campaign"]
    previous = campaign["menu"]
    campaign["menu"] = menu_from_history(previous["scorecard"], previous["request"])
    campaign["selection"]["menu_id"] = campaign["menu"]["menu_id"]


def test_actual_admitted_snapshot_is_forwarded_without_current_credentials(admission, monkeypatch):
    from algua.config.settings import Settings
    from algua.operator.research_prompt_memory import decode_admitted_memory
    from algua.tracking.research_archive import LocalResearchArchive

    response, cycle, database = admission
    before = copy.deepcopy(response)

    def forbidden(*args, **kwargs):
        raise AssertionError("pure helper performed configuration/store/process/DB work")

    monkeypatch.setattr(Settings, "__init__", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(LocalResearchArchive, "read", forbidden)
    result = decode_admitted_memory(canonical(response), cycle_id=cycle, database=database)
    assert set(result) == {"schema_version", "research_cycle_id", "menu_id",
                           "snapshot_sha256", "snapshot"}
    expected = response["campaign"]["menu"]["request"]["context"]["public_research_memory"]
    assert result["snapshot"] == expected and result["snapshot"] is not expected
    assert result["snapshot_sha256"] == hashlib.sha256(canonical(expected)).hexdigest()
    assert len(canonical(result)) <= 25 * 1024
    assert all(idea["claim_token"].encode() not in canonical(result)
               for idea in response["claimed"])
    assert response == before


def test_claim_order_is_not_an_extra_admission_constraint(admission):
    expected = decode(admission)
    admission[0]["claimed"].reverse()
    assert decode(admission) == expected


def test_raw_exact_ceiling_and_unforwarded_private_response_fields(admission):
    from algua.operator.research_prompt_memory import decode_admitted_memory

    response, cycle, database = admission
    response["raw_report"] = "PRIVATE_REPORT_SENTINEL"
    response["claims_debug"] = {"secret": "PRIVATE_DEBUG_SENTINEL"}
    raw = canonical(response)
    result = decode_admitted_memory(raw + b" " * (1024 * 1024 - len(raw)),
                                    cycle_id=cycle, database=database)
    assert b"PRIVATE_" not in canonical(result)


@pytest.mark.parametrize("fault", ["ok", "phase", "response-cycle", "menu-cycle", "database",
    "selection", "missing-claim", "duplicate-claim", "bool-id", "extra-id", "empty-claims",
    "missing-snapshot", "authority", "missing-token", "empty-token", "null-campaign"])
def test_wrong_admission_refuses_with_fixed_non_data_error(admission, fault):
    response, cycle, database = admission
    if fault == "ok":
        response["ok"] = 1
    elif fault == "phase":
        response["phase"] = "controller_restart"
    elif fault == "response-cycle":
        response["research_cycle_id"] = "another"
    elif fault in ("menu-cycle", "database"):
        key = "research_cycle_id" if fault == "menu-cycle" else "database"
        response["campaign"]["menu"]["request"][key] = "another"
        reseal(response)
    elif fault == "selection":
        response["campaign"]["selection"]["menu_id"] = "a" * 64
    elif fault == "missing-claim":
        response["claimed"].pop()
    elif fault == "duplicate-claim":
        response["claimed"].append(copy.deepcopy(response["claimed"][0]))
    elif fault == "bool-id":
        response["claimed"][0]["id"] = True
    elif fault == "extra-id":
        response["claimed"][0]["id"] = 9999
    elif fault == "empty-claims":
        response["claimed"] = []
    elif fault in ("missing-snapshot", "authority"):
        context = response["campaign"]["menu"]["request"]["context"]
        if fault == "missing-snapshot":
            context.pop("public_research_memory")
        else:
            context["public_research_memory"]["authority"] = "trusted"
        reseal(response)
    elif fault == "missing-token":
        response["claimed"][0].pop("claim_token")
    elif fault == "empty-token":
        response["claimed"][0]["claim_token"] = ""
    else:
        response["campaign"] = None
    with pytest.raises(ValueError, match="^research_prompt_memory:invalid_admission$") as stopped:
        decode((response, cycle, database))
    assert all(idea.get("claim_token", "") not in str(stopped.value)
               for idea in response["claimed"] if idea.get("claim_token"))


def test_raw_ceiling_is_checked_before_json_parser(monkeypatch):
    from algua.operator import research_prompt_memory as module

    def forbidden(raw):
        raise AssertionError("oversized response reached parser")

    monkeypatch.setattr(module, "strict_json", forbidden)
    with pytest.raises(ValueError, match="^research_prompt_memory:response_too_large$"):
        module.decode_admitted_memory(b" " * (1024 * 1024 + 1),
                                       cycle_id="fixture", database="/fixture.db")


@pytest.mark.parametrize("raw", [b'{"ok":true,"ok":false}', b'{"ok":NaN}', b"not JSON"])
def test_strict_raw_json_failure_never_echoes_input(raw):
    from algua.operator.research_prompt_memory import decode_admitted_memory

    with pytest.raises(ValueError, match="^research_prompt_memory:invalid_admission$"):
        decode_admitted_memory(raw, cycle_id="fixture", database="/fixture.db")


def test_current_token_collision_refuses_without_redacting_opaque_params(admission):
    response, _, _ = admission
    snapshot = response["campaign"]["menu"]["request"]["context"]["public_research_memory"]
    token = response["claimed"][0]["claim_token"]
    snapshot["observations"][0]["inputs"]["params"]["opaque"] = "declared:" + token
    reseal(response)
    before = copy.deepcopy(response)
    pattern = "^research_prompt_memory:credential_collision$"
    with pytest.raises(ValueError, match=pattern) as stopped:
        decode(admission)
    assert token not in str(stopped.value) and response == before


def test_unicode_legacy_refs_and_opaque_values_are_preserved(admission):
    response, _, _ = admission
    snapshot = response["campaign"]["menu"]["request"]["context"]["public_research_memory"]
    reference = "mlflow:Legacy_α\n/public-evidence.json#sha256=" + "b" * 64
    snapshot["receipts"][0].update(evidence_ref=reference, archive_sha256="b" * 64)
    for observation in snapshot["observations"]:
        observation["archive_ref"] = reference
        observation["inputs"].setdefault("params", {})["opaque"] = "quote' `data`\n雪"
    reseal(response)
    assert decode(admission)["snapshot"] == snapshot


def test_render_preserves_old_goal_and_counts_exact_written_newline(admission):
    from algua.operator.research_prompt_memory import render_research_goal

    wrapper = decode(admission)
    goal = "\nExisting instructions and trailer grammar.\n\n"
    rendered = render_research_goal(goal, wrapper)
    assert rendered.startswith(goal) and not rendered.endswith("\n")
    assert canonical(wrapper).decode() in rendered
    assert "UNTRUSTED" in rendered and "cycle_only" in rendered and "author" in rendered
    overhead = len(render_research_goal("G", wrapper).encode()) + 1
    exact = render_research_goal("G" + "x" * (96 * 1024 - overhead), wrapper)
    assert len(exact.encode()) + 1 == 96 * 1024
    with pytest.raises(ValueError, match="^research_prompt_memory:goal_too_large$"):
        render_research_goal("G" + "x" * (96 * 1024 - overhead + 1), wrapper)
    available = 96 * 1024 - overhead
    unicode_goal = "G" + "雪" * (available // 3) + "x" * (available % 3)
    assert len(render_research_goal(unicode_goal, wrapper).encode()) + 1 == 96 * 1024
    with pytest.raises(ValueError, match="^research_prompt_memory:goal_too_large$"):
        render_research_goal(unicode_goal + "雪", wrapper)


def test_unavailable_snapshot_is_explicit_and_valid(admission):
    from algua.operator.research_prompt_memory import render_research_goal

    response, _, _ = admission
    empty = project_snapshot([], coverage={"candidate_attempts_considered": 0,
        "candidate_cycles": 0, "cycles_without_receipt": 0}, cutoff=0,
        tracking_uri="sqlite:////fixture-unused-store.db")
    response["campaign"]["menu"]["request"]["context"]["public_research_memory"] = empty
    reseal(response)
    assert decode(admission)["snapshot"] == empty
    assert '"status":"unavailable"' in render_research_goal("Goal", decode(admission))


@pytest.mark.parametrize("fault", ["extra", "hash", "snapshot", "cycle", "menu"])
def test_render_rejects_changed_wrapper(admission, fault):
    from algua.operator.research_prompt_memory import render_research_goal

    wrapper = decode(admission)
    if fault == "extra":
        wrapper["claimed"] = admission[0]["claimed"]
    elif fault == "hash":
        wrapper["snapshot_sha256"] = "f" * 64
    elif fault == "snapshot":
        wrapper["snapshot"]["authority"] = "trusted"
    elif fault == "cycle":
        wrapper["research_cycle_id"] = "../foreign"
    else:
        wrapper["menu_id"] = "invalid"
    with pytest.raises(ValueError, match="^research_prompt_memory:invalid_wrapper$"):
        render_research_goal("Goal", wrapper)
