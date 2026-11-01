"""Finite process supervisor for the existing driver; does not replace its runtime seam.

These are per-process resource limits and adopted-child cleanup, not a strategy sandbox.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import signal
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from algua.operator.research_cycle import CycleLimits, duration_seconds


def _subreaper(value: int | None = None) -> int:
    """Linux adoption is unprivileged and must be established BEFORE the trusted launch."""
    libc = ctypes.CDLL(None, use_errno=True)
    current = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(current), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot read child subreaper state")
    if value is not None and libc.prctl(36, value, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "cannot establish child subreaper")
    return current.value


def _children() -> set[int]:
    return {int(pid) for pid in Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()}


def _reap_owned(existing: set[int]) -> None:
    # An exiting intermediate parent can adopt another generation while we kill/reap this one.
    # Re-scan direct children until empty; polling ancestry alone loses quick-exit parents.
    while owned := _children() - existing:
        for pid in owned:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pid in owned:
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass


def run_bounded(command: Sequence[str], limits: CycleLimits, *, grace_seconds: float = 5) -> int:
    if not command:
        raise ValueError("worker command is empty")
    env = {**os.environ, "ALGUA_CYCLE_SUPERVISED": "1", "OMP_NUM_THREADS": "1",
           "OPENBLAS_NUM_THREADS": "1", "NUMBA_NUM_THREADS": "1"}
    argv = ["prlimit", f"--cpu={limits.cpu_seconds}",
            f"--as={limits.memory_mb * 1024 * 1024}",
            f"--fsize={limits.file_mb * 1024 * 1024}", "--nofile=256", "--", *command]
    interrupted = 0

    def interrupt(signum: int, frame: FrameType | None) -> None:
        nonlocal interrupted
        interrupted = signum

    existing = _children()
    prior_subreaper = _subreaper(1)
    previous = {sig: signal.signal(sig, interrupt) for sig in (signal.SIGTERM, signal.SIGINT)}
    worker: subprocess.Popen[bytes] | None = None
    deadline = time.monotonic() + limits.max_wall_seconds
    try:
        worker = subprocess.Popen(argv, start_new_session=True, env=env)
        while worker.poll() is None and not interrupted and time.monotonic() < deadline:
            time.sleep(0.05)
        aborted = interrupted or (signal.SIGTERM if worker.poll() is None else 0)
        if aborted:
            try:
                os.killpg(worker.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                worker.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                worker.wait()
            return 128 + interrupted if interrupted else 124
        code = worker.wait()
        return 128 - code if code < 0 else code
    finally:
        if worker is not None:
            try:
                os.killpg(worker.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            worker.wait()
        _reap_owned(existing)
        _subreaper(prior_subreaper)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", required=True)
    parser.add_argument("--hypotheses", type=int, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--cpu-seconds", type=int, default=2700)
    parser.add_argument("--memory-mb", type=int, default=16384)
    parser.add_argument("--file-mb", type=int, default=512)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        limits = CycleLimits(max_hypotheses=args.hypotheses,
                             max_wall_seconds=duration_seconds(args.timeout),
                             worker_limit=args.workers, cpu_seconds=args.cpu_seconds,
                             memory_mb=args.memory_mb, file_mb=args.file_mb)
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        return run_bounded(command, limits)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"research cycle refused: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
