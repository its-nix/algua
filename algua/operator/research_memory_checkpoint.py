"""Shared retained checkpoint validation; the bounded reader needs no disposable worker."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from algua.tracking.bounded_local_read import LocalReadError, ReadBudget, read_local_file


class CheckpointError(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"public_memory_context:{reason}")


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"),
                      ensure_ascii=False).encode()


def strict_json(raw: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def memory_state(metadata: dict) -> dict:
    state = metadata.get("research_memory", {})
    if not isinstance(state, dict) or set(state) - {"seed", "receipt"}:
        raise ValueError("research memory metadata is malformed")
    return state


def validated_seed(seed: Any, worker_root: Path | None = None) -> dict:
    keys = {"worker_root", "runs_max_id", "inherited_run_count", "registry_digest",
            "inherited_runs_digest", "schema_version"}
    if (not isinstance(seed, dict) or set(seed) != keys
            or not isinstance(seed["worker_root"], str)
            or any(type(seed[k]) is not int or seed[k] < 0
                   for k in ("runs_max_id", "inherited_run_count", "schema_version"))
            or any(not isinstance(seed[k], str) or re.fullmatch(r"[0-9a-f]{64}", seed[k]) is None
                   for k in ("registry_digest", "inherited_runs_digest"))):
        raise ValueError("research memory requires its original seed checkpoint")
    if worker_root is not None and seed["worker_root"] != str(worker_root.resolve()):
        raise ValueError("research memory seed belongs to another worker")
    return seed


def validate_retained_payload(payload: dict, *, metadata: dict, cycle_id: str) -> dict:
    seed = {k: v for k, v in validated_seed(memory_state(metadata).get("seed")).items()
            if k != "worker_root"}
    if (payload["research_cycle_id"] != cycle_id or payload["seed"] != seed
            or payload["controller_context_digest"] != hashlib.sha256(
                canonical(metadata["request"]["context"])).hexdigest()):
        raise ValueError("research memory archive does not match the controller checkpoint")
    return payload


def load_checkpoint(directory: Path, cycle_id: str, *, database: str,
                    budget: ReadBudget) -> dict:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", cycle_id) is None:
        raise CheckpointError("checkpoint_invalid")
    try:
        raw = read_local_file(directory / f"{cycle_id}.json", root=directory,
                              max_bytes=256 * 1024, budget=budget)
        metadata = strict_json(raw)
        request = metadata["request"]
        if (not isinstance(request, dict) or request["research_cycle_id"] != cycle_id
                or not isinstance(request["context"], dict)
                or request["database"] != str(Path(database).resolve())):
            raise ValueError("checkpoint context mismatch")
        state = memory_state(metadata)
        validated_seed(state.get("seed"))
        if not isinstance(state.get("receipt"), dict):
            raise ValueError("missing checkpoint receipt")
        return metadata
    except LocalReadError as exc:
        reason = ("source_bytes_exceeded" if exc.reason == "source_bytes_exceeded"
                  else "checkpoint_invalid")
        raise CheckpointError(reason) from exc
    except (KeyError, TypeError, ValueError, OSError, RecursionError) as exc:
        raise CheckpointError("checkpoint_invalid") from exc
