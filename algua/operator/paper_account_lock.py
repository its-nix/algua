"""Serialize manual paper-account mutations with the installed operator/transition lock."""
from __future__ import annotations

import os
import socket
from contextlib import contextmanager

from algua.operator.deployment_lock import _operator_lock_path
from algua.operator.schedule import OperatorLockHeld, operator_run_lock


@contextmanager
def paper_account_lock(lane: str):
    if lane != "paper":
        yield
        return
    try:
        with operator_run_lock(_operator_lock_path(), job="paper-account",
                               host=socket.gethostname(), pid=os.getpid()):
            yield
    except OperatorLockHeld as exc:
        raise ValueError("paper account operator.lock is held") from exc
