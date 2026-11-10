"""Public sweep detail using the existing reserved-tail-safe WF serializer."""
from __future__ import annotations

from typing import Any

from algua.provenance.research_disclosure import public_window_result


def public_sweep(payload: dict[str, Any]) -> dict[str, Any]:
    result = public_window_result(payload)
    for visible, trial in zip(result['ranked'], payload['ranked'], strict=True):
        if 'window_metrics' in trial:
            visible['window_metrics'] = public_window_result(
                {'window_metrics': trial['window_metrics']})['window_metrics']
    return result
