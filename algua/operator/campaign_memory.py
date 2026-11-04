"""Opt-in bounded public context. No import-time store access or subprocess launch."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from algua.operator.campaign_memory_schema import (
    ATTEMPT,
    CYCLE,
    MemoryContextError,
    exact,
    integer,
    memory_reference,
    require,
    validate_snapshot,
)
from algua.operator.research_memory_checkpoint import canonical, strict_json

_REASONS = {"activation_invalid", "request_invalid", "runtime_unavailable", "worker_launch_failed",
    "read_deadline_exceeded", "worker_output_exceeded", "worker_exit_abnormal",
    "worker_result_invalid", "archive_store_unavailable", "checkpoint_invalid", "receipt_invalid",
    "artifact_location_unsupported", "source_bytes_exceeded", "artifact_changed",
    "artifact_integrity_mismatch", "artifact_payload_invalid", "context_bytes_exceeded"}
_BOOTSTRAP = """import importlib.util, pathlib, runpy, sys
root = pathlib.Path(sys.argv[1]).resolve()
name = 'algua.operator.campaign_memory_worker'
spec = importlib.util.find_spec(name)
expected = root / 'algua/operator/campaign_memory_worker.py'
if spec is None or pathlib.Path(spec.origin).resolve() != expected:
    raise SystemExit(2)
sys.argv = [name, sys.argv[2]]
runpy.run_module(name, run_name='__main__')
"""


def _run_contained(*args: Any, **kwargs: Any) -> Any:
    # Import only for an activated batch; platforms without waitid cannot run this seam.
    from algua.primitives.contained_process import run_contained

    return run_contained(*args, **kwargs)


def validate_public_memory_snapshot(value: object) -> dict:
    """Pure detached schema/size/reference/count validation, with no archive/process I/O."""
    return validate_snapshot(value)


def select_cycles(menu: dict) -> tuple[list[dict], dict]:
    """Resolve ALL offered prior attempts before the fixed64-row window and cycle dedup."""
    try:
        choices, rows = menu["choices"], menu["scorecard"]["attempts"]
        require(isinstance(choices, list) and isinstance(rows, list), "request_invalid")
        refs: set[str] = set()
        for choice in choices:
            require(isinstance(choice, dict) and isinstance(choice["prior_evidence_ids"], list),
                    "request_invalid")
            refs.update(ref for ref in choice["prior_evidence_ids"]
                        if isinstance(ref, str) and ATTEMPT.fullmatch(ref))
        by_id: dict[int, dict] = {}
        for row in rows:
            require(isinstance(row, dict) and integer(row["id"], 1) and row["id"] not in by_id,
                    "request_invalid")
            by_id[row["id"]] = row
        require(all(int(ref.split(":")[1]) in by_id for ref in refs), "request_invalid")
        relevant = [by_id[int(ref.split(":")[1])] for ref in refs]
        relevant = sorted((r for r in relevant if r["outcome"] is not None),
                          key=lambda row: row["id"], reverse=True)[:64]
        grouped: dict[str, list[dict]] = {}
        references: dict[str, set[str]] = {}
        for row in relevant:
            cycle_id, reference = row["run_stamp"], row["evidence_ref"]
            require(isinstance(cycle_id, str), "request_invalid")
            grouped.setdefault(cycle_id, []).append(row)
            if (isinstance(reference, str) and reference.startswith("mlflow:")
                    and "/public-evidence.json" in reference):
                require(memory_reference(reference) and re.fullmatch(CYCLE, cycle_id),
                        "receipt_invalid")
                references.setdefault(cycle_id, set()).add(reference)
        require(all(len(values) == 1 for values in references.values()), "receipt_invalid")
        selected: list[dict] = []
        for cycle_id, attempts in grouped.items():
            if cycle_id not in references:
                continue
            if len(selected) < 2:
                selected.append({"research_cycle_id": cycle_id,
                    "evidence_ref": next(iter(references[cycle_id])), "attempts": [
                        {"evidence_id": f"idea_attempts:{r['id']}", "idea_id": r["idea_id"]}
                        for r in attempts]})
        return selected, {"candidate_attempts_considered": len(relevant),
            "candidate_cycles": len(grouped),
            "cycles_without_receipt": len(grouped) - len(references)}
    except MemoryContextError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise MemoryContextError("request_invalid") from exc


def _wire(raw: bytes) -> dict:
    try:
        result = strict_json(raw)
        require(isinstance(result, dict) and result.get("schema_version")
                == "campaign-public-memory-result/v1", "worker_result_invalid")
        if result.get("ok") is False:
            require(exact(result, {"schema_version", "ok", "reason"})
                    and result["reason"] in _REASONS, "worker_result_invalid")
            raise MemoryContextError(result["reason"])
        require(result.get("ok") is True and exact(result, {"schema_version", "ok", "snapshot"}),
                "worker_result_invalid")
        return validate_public_memory_snapshot(result["snapshot"])
    except MemoryContextError:
        raise
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise MemoryContextError("worker_result_invalid") from exc


def capture_public_memory(menu: dict, *, cycle_directory: Path, tracking_uri: str,
                          tracking_backend: str, phase: str = "capture") -> dict:
    """One20s work/result-acceptance deadline; blocking full teardown may overhang it."""
    deadline = time.monotonic() + 20.0
    require(phase in ("capture", "revalidate"), "request_invalid")
    cycles, coverage = select_cycles(menu)
    try:
        rows = menu["scorecard"]["attempts"]
        request = {"schema_version": "campaign-public-memory-request/v1", "phase": phase,
            "database": menu["request"]["database"],
            "cycle_directory": str(cycle_directory.resolve()),
            "tracking_uri": tracking_uri, "tracking_backend": tracking_backend,
            "cycles": cycles, "coverage": coverage,
            "cutoff": max((row["id"] for row in rows), default=0)}
        raw = canonical(request)
        require(len(raw) <= 64 * 1024, "request_invalid")
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="algua-public-memory-") as scratch:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "read_deadline_exceeded")
            env = {"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
                "HOME": scratch, "TMPDIR": scratch, "PYTHONDONTWRITEBYTECODE": "1",
                "NUMBA_CACHE_DIR": scratch + "/numba", "MPLCONFIGDIR": scratch + "/mpl",
                "XDG_CACHE_HOME": scratch + "/cache", "XDG_CONFIG_HOME": scratch + "/config"}
            result = _run_contained(
                [sys.executable, "-I", "-B", "-c", _BOOTSTRAP, str(root), raw.decode()],
                cwd=root, env=env, timeout=remaining, grace=0.0,
                max_stdout=25 * 1024, stderr_capture=4096)
            require(time.monotonic() < deadline and not result.timed_out, "read_deadline_exceeded")
            require(not result.stdout_exceeded, "worker_output_exceeded")
            require(result.returncode == 0 and result.signal is None, "worker_exit_abnormal")
            require(len(result.stdout) <= 25 * 1024, "worker_output_exceeded")
            try:
                snapshot = _wire(result.stdout)
            except Exception:
                require(time.monotonic() < deadline, "read_deadline_exceeded")
                raise
            require(time.monotonic() < deadline, "read_deadline_exceeded")
        # Scratch teardown is also allowed to overhang; never accept its result after the deadline.
        require(time.monotonic() < deadline, "read_deadline_exceeded")
        return snapshot
    except MemoryContextError:
        raise
    except AttributeError as exc:
        raise MemoryContextError("runtime_unavailable") from exc
    except OSError as exc:
        raise MemoryContextError("worker_launch_failed") from exc
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise MemoryContextError("request_invalid") from exc
