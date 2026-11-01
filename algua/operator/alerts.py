"""Operator alert hook: one structured log record plus an optional external command.

Every alert ALWAYS lands as a structured ``operator_alert`` log record. Delivery via an
operator-supplied external command is best-effort and HARDENED: the command is split with
``shlex`` and run with ``shell=False`` (no shell interpolation of the payload), under a bounded
timeout, with the JSON payload on stdin and captured output truncated before logging. Any delivery
failure (timeout, non-zero exit, OSError) is logged and swallowed so an alert never crashes the
operator loop.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256

from algua.observability import get_logger
from algua.operator.loop_health import _digest_stamp

__all__ = ["emit_alert", "research_incidents"]

log = get_logger(__name__)

_ALERT_TIMEOUT_SECONDS = 10.0
_OUTPUT_CAP = 500


def research_fault(record: dict) -> str | None:
    """Classify driver failures, never hypothesis economics or unstructured error text."""
    if record.get("rate_limited") is True:
        return "rate_limited"
    if record.get("timed_out") is True:
        return "worker_timeout"
    outcome = record.get("outcome")
    if outcome in ("setup_failed", "claim_failed"):
        return outcome
    if type(record.get("exit_code")) is int:
        return "worker_failed" if record["exit_code"] != 0 else None
    return None


def _evidence_digest(parts: tuple[str, ...]) -> str:
    return sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def research_incidents(records: list[dict], *, now: datetime) -> list[dict]:
    """Project repeated systemic observations into public incident payloads, without delivery.

    The original cycle (legacy: firing stamp) is the independence unit, never a retry/run ID.
    Lineage covers the retained digest; no incident store is created by this read. A clean run or
    claimed merged/deployed fix cannot close an incident: no recovery verifier is available here.
    """
    groups: dict[str, list[tuple[datetime, str]]] = {}
    for record in records:
        cause, stamp = research_fault(record), _digest_stamp(record)
        origin = record.get("research_cycle_id", record.get("stamp"))
        if cause is None or stamp is None or stamp > now:
            continue
        if not isinstance(origin, str) or not 1 <= len(origin) <= 128:
            continue
        groups.setdefault(cause, []).append((stamp, _evidence_digest(("research", cause, origin))))
    incidents = []
    for cause, observations in sorted(groups.items()):
        refs = sorted({ref for _, ref in observations})
        if len(refs) < 2:
            continue
        incidents.append({
            "fingerprint": _evidence_digest(("machine-health/v1", "research", cause)),
            "severity": "important", "source": "research", "cause": cause,
            "first_seen": min(at for at, _ in observations).isoformat(),
            "last_seen": max(at for at, _ in observations).isoformat(),
            "evidence_refs": refs,
            "reproduction": {"method": "distinct_cycles", "observations": len(refs)},
            "owner": "algua-lead", "required_action": "reproduce_test_repair_verify_deployment",
            "status": "open", "recovery": "unverified",
        })
    return incidents


def _default_runner(cmd: str, payload: str) -> int:
    """Run the alert command with ``shell=False``, feeding ``payload`` on stdin; return its rc.

    ``cmd`` is split with :func:`shlex.split` and invoked as an argv vector — the payload is NEVER
    interpolated into a shell string, so operational specifics in the alert detail can never be
    interpreted by a shell. A bounded ``timeout`` prevents a hung alert command from wedging the
    operator; captured stdout/stderr are truncated before logging (they may echo the payload).
    """
    argv = shlex.split(cmd)
    if not argv:
        return 1
    result = subprocess.run(  # noqa: S603 - shell=False, fixed argv from operator config
        argv,
        shell=False,
        input=payload,
        text=True,
        capture_output=True,
        timeout=_ALERT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        log.warning(
            "operator_alert_command_nonzero",
            extra={
                "fields": {
                    "rc": result.returncode,
                    "stdout_head": (result.stdout or "")[:_OUTPUT_CAP],
                    "stderr_head": (result.stderr or "")[:_OUTPUT_CAP],
                }
            },
        )
    return result.returncode


def emit_alert(
    kind: str,
    detail: dict,
    *,
    alert_cmd: str | None = None,
    runner: Callable[[str, str], int] = _default_runner,
) -> bool:
    """Log a structured alert and optionally deliver it via an external command.

    Always emits exactly one ``operator_alert`` ERROR record. When ``alert_cmd`` is set, the JSON
    payload is piped to ``runner``; delivery is best-effort and never propagates (a
    ``TimeoutExpired`` / non-zero rc / ``OSError`` is logged at warning and swallowed). Returns True
    only when the command was invoked and exited 0.
    """
    log.error("operator_alert", extra={"fields": {"kind": kind, **detail}})
    if not alert_cmd:
        return False
    payload = json.dumps({"kind": kind, **detail}, sort_keys=True, default=str)
    try:
        rc = runner(alert_cmd, payload)
    except Exception:
        log.warning(
            "operator_alert_delivery_failed",
            extra={"fields": {"kind": kind}},
            exc_info=True,
        )
        return False
    return rc == 0
