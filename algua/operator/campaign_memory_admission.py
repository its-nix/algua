"""Optional retained-memory context at the existing driver/controller seam."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from algua.operator.research_cycle import ResearchCycle
from algua.registry.campaign_selection import menu_from_history


def checkpoint_context(cycle: ResearchCycle, context: dict[str, Any]) -> dict[str, Any]:
    """Carry only the original decision snapshot alongside completely recomputed base fields.

    Recovery/setup does not read another archive, replace a decision or accept worker memory.
    The caller still passes this entire context through the controller's exact comparison.
    """
    metadata = cycle._metadata()
    original = metadata["request"]["context"]
    if "public_research_memory" not in original:
        return context
    from algua.operator.campaign_memory import validate_public_memory_snapshot

    if metadata["request"]["research_cycle_id"] != cycle.cycle_id:
        raise ValueError("public_memory_context:checkpoint_invalid")
    try:
        snapshot = validate_public_memory_snapshot(original["public_research_memory"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("public_memory_context:checkpoint_invalid") from exc
    return {**context, "public_research_memory": snapshot}


def prepare_memory_context(
    cycle: ResearchCycle, *, request: dict[str, Any], manual: bool, choose: bool,
    tracking_uri: str, tracking_backend: str, choice_directory: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Capture with no feedback transaction held, then verify the same feedback still applies."""
    from algua.operator.campaign_memory import capture_public_memory

    if choose and (cycle.path.exists() or cycle.rows() or choice_directory is not None
                   and (choice_directory.exists() or choice_directory.is_symlink())):
        raise ValueError("chooser cycle already started; reconcile without another call")
    if manual and cycle.path.exists():
        context = checkpoint_context(cycle, request["context"])
        if "public_research_memory" not in context:
            raise ValueError("cycle identity/context is immutable")
        return context, None
    base_menu = cycle.campaign_menu(**request)
    snapshot = capture_public_memory(
        base_menu, cycle_directory=cycle.directory, tracking_uri=tracking_uri,
        tracking_backend=tracking_backend)
    context = {**request["context"], "public_research_memory": snapshot}
    menu = cycle.campaign_menu(**{**request, "context": context})
    expected = menu_from_history(
        base_menu["scorecard"], {**base_menu["request"], "context": context})
    if menu != expected:
        raise ValueError("stale campaign feedback during public memory capture")
    return context, menu


def revalidate_memory_context(
    cycle: ResearchCycle, menu: dict[str, Any], *, tracking_uri: str, tracking_backend: str,
) -> dict[str, Any]:
    """Recheck the originally selected receipts once, before the unchanged controller/CAS."""
    from algua.operator.campaign_memory import capture_public_memory

    snapshot = capture_public_memory(
        menu, cycle_directory=cycle.directory, tracking_uri=tracking_uri,
        tracking_backend=tracking_backend, phase="revalidate")
    if snapshot != menu["request"]["context"]["public_research_memory"]:
        raise ValueError("public_memory_context:artifact_changed")
    return snapshot
