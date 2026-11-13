"""Read-only advisory projection of completed worker reports, never gate evidence.

The operational digest is not tamper-evident. Match it to ledger identities/outcomes, retain
unknowns, and never change authoritative economic counters or lifecycle decisions from it.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

from algua.config.settings import get_settings
from algua.tracking.bounded_local_read import read_local_file

ASSESSMENTS = ('refuted', 'survived', 'untested', 'unknown')
_MAX_BYTES = 2 * 1024 * 1024


def _unique_keys(pairs: list[tuple]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate digest key')
        result[key] = value
    return result


def reported_assessments(attempts: list[dict]) -> tuple[dict[int, str], str]:
    """Bounded existing-file read; missing, corrupt, changed or oversized sources stay unknown."""
    root = get_settings().data_dir.absolute()
    try:
        raw = read_local_file(root / 'research-runs.jsonl', root=root, max_bytes=_MAX_BYTES)
        records = [json.loads(line, object_pairs_hook=_unique_keys)
                   for line in raw.decode('utf-8').splitlines() if line.strip()]
        if len(records) > 10000 or any(not isinstance(r, dict) for r in records):
            raise ValueError('invalid digest records')
    except (OSError, ValueError, RecursionError):
        return {}, 'unavailable'
    cycles: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        cycle = record.get('research_cycle_id')
        if isinstance(cycle, str):
            cycles[cycle].append(record)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for attempt in attempts:
        grouped[attempt['run_stamp']].append(attempt)
    found: dict[int, str] = {}
    for cycle, rows in grouped.items():
        candidates = cycles.get(cycle, [])
        if len(candidates) == 1:
            found.update(_matched(candidates[0], rows))
    return found, 'available'


def _matched(record: dict, attempts: list[dict]) -> dict[int, str]:
    """Reject ambiguous cycle/idea/outcome associations, including duplicate claims/reports."""
    cycle = attempts[0]['run_stamp']
    controller = record.get('controller')
    hypotheses = record.get('hypotheses')
    if (record.get('stamp') != cycle or record.get('outcome') != 'completed'
            or type(record.get('worker_exit_code')) is not int or record['worker_exit_code'] != 0
            or type(record.get('exit_code')) is not int or record['exit_code'] not in (0, 1)
            or record.get('timed_out') is not False or record.get('rate_limited') is not False
            or record.get('trailer_parse_error') is not False
            or not isinstance(controller, dict) or controller.get('research_cycle_id') != cycle
            or controller.get('phase') != 'completed'
            or not isinstance(hypotheses, list) or not 0 < len(hypotheses) <= 40):
        return {}
    ids = record.get('idea_ids')
    expected = {a['idea_id']: a for a in attempts}
    if (not isinstance(ids, list) or any(type(i) is not int or i < 1 for i in ids)
            or len(ids) != len(set(ids)) or len(expected) != len(attempts)
            or set(ids) != set(expected) or controller.get('idea_ids') != ids):
        return {}
    outcomes = Counter(a['outcome'] for a in attempts)
    counts = controller.get('outcome_counts')
    if (None in outcomes or not isinstance(counts, dict)
            or any(type(v) is not int or v < 1 for v in counts.values())
            or counts != dict(outcomes)):
        return {}
    errors = outcomes['integrity_fail'] + outcomes['run_error']
    expected_counts = dict(attempts_total=len(ids), terminal_count=len(ids), unfinished_count=0,
        write_error_count=0, invalid_count=0, error_count=errors,
        ok_count=len(ids) - errors - outcomes['data_blocked'])
    if (any(type(controller.get(k)) is not int or controller[k] != v
            for k, v in expected_counts.items()) or record['exit_code'] != int(errors > 0)):
        return {}
    result: dict[int, str] = {}
    seen = set()
    for row in hypotheses:
        if not isinstance(row, dict):
            return {}
        idea = row.get('idea_id')
        if type(idea) is not int or idea in seen or idea not in expected:
            return {}
        seen.add(idea)
        if row.get('outcome') != expected[idea]['outcome']:
            return {}
        assessment = row.get('falsification_assessment')
        if assessment is not None and assessment not in ASSESSMENTS[:-1]:
            return {}
        if assessment is not None:
            result[expected[idea]['id']] = assessment
    return result if seen == set(expected) else {}


def empirical_counts(rows: list[dict]) -> dict[str, int]:
    counts = Counter(row.get('reported_falsification_assessment', 'unknown') for row in rows)
    return {key: counts[key] for key in ASSESSMENTS}
