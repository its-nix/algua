"""Actual Bash adapters and real chooser/ledger validation with a trusted child fixture.

No model, research worker, host sandbox or scheduled service runs here. Only the chooser's
subprocess boundary is substituted; the root CLI, event parsing, feedback checks and CAS run.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from algua.operator.campaign_memory import _REASONS
from algua.operator.research_cycle import ResearchCycle
from algua.registry.db import connect, migrate
from tests.campaign_fixtures import add_idea

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / '.opencode/scripts/run-research-loop.sh'

# The fixture emits the existing output-only wire files without executing the platform-specific
# process launcher. Production choose_campaign still checks events, session, menu and feedback.
FIXTURE_CLI = '''
import json, os
from pathlib import Path
from algua.config.settings import Settings
Settings.model_config['env_file'] = None
from algua.cli.main import main
from algua.operator import campaign_choice

class FixtureChild:
    pid = 1
    def __init__(self, command, **kwargs):
        directory = Path(command[command.index('--workdir') + 1])
        menu = json.loads((directory / 'menu.json').read_text())
        with Path(os.environ['FIXTURE_CALLS']).open('a') as stream:
            stream.write(json.dumps({'command': command, 'menu': menu}) + '\\n')
        case = os.environ.get('FIXTURE_CASE', '')
        self.code = 3 if case == 'provider' else 0
        if self.code:
            return
        choice = {**menu['choices'][-1], 'reason': 'SYNTHETIC_FIXTURE cites captured feedback'}
        selection = {'menu_id': menu['menu_id'], 'choices': [choice]}
        if case == 'invalid':
            choice['hypothesis_id'] = 999
        if case == 'feedback':
            from algua.registry.db import connect
            from tests.campaign_fixtures import add_idea
            conn = connect(Path(os.environ['ALGUA_DB_PATH']))
            add_idea(conn, 'SYNTHETIC_FIXTURE concurrent new evidence', family='new')
            conn.close()
        events = [
            {'type': 'step_start', 'part': {'type': 'step-start'}},
            {'type': 'text', 'part': {'type': 'text', 'text': json.dumps(selection)}},
            {'type': 'step_finish', 'part': {'type': 'step-finish', 'reason': 'stop'}},
        ]
        for event in events:
            event['sessionID'] = 'SYNTHETIC_FIXTURE-session'
        (directory / 'runtime.jsonl').write_text(''.join(json.dumps(e) + '\\n' for e in events))
        (directory / 'session.json').write_text(json.dumps({
            'info': {'id': 'SYNTHETIC_FIXTURE-session'},
            'messages': [{'info': {'role': 'assistant', 'providerID': 'fixture',
                                   'modelID': 'fixture'}}],
        }))
    def poll(self):
        return self.code
    def wait(self):
        return self.code

campaign_choice.subprocess.Popen = FixtureChild
campaign_choice.os.killpg = lambda *args: None
main()
'''


@pytest.fixture
def driver_pool(tmp_path, monkeypatch):
    database = tmp_path / 'SYNTHETIC_FIXTURE.db'
    conn = connect(database)
    migrate(conn)
    for title, family in [('auction pressure', 'a'), ('dividend drift', 'b'),
                          ('liquidity recovery', 'c')]:
        add_idea(conn, title, family=family)
    monkeypatch.setenv('ALGUA_DB_PATH', str(database))
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('FIXTURE_CALLS', str(tmp_path / 'calls.jsonl'))
    yield conn
    conn.close()


def _preamble(tmp_path, **changes):
    values = {
        'AUTH_DB': str(tmp_path / 'SYNTHETIC_FIXTURE.db'),
        'AUTH_DATA_DIR': str(tmp_path / 'data'), 'STAMP': 'first',
        'N_HYPOTHESES': '3', 'TIMEOUT': '45m', 'WORKER_LIMIT': '1',
        'CPU_SECONDS': '2700', 'MEMORY_MB': '16384', 'FILE_MB': '512',
        'MAX_COST': '', 'CATEGORY': '', 'CAMPAIGN': '', 'CHOOSE_CAMPAIGN': '0',
        **changes,
    }
    return 'set -euo pipefail\n' + '\n'.join(
        f'{k}={shlex.quote(v)}' for k, v in values.items()) + '\n'


def _driver_start(tmp_path, *args, stamp='first', **changes):
    """Run the actual argument and claim adapters, without worktree/scheduler operations."""
    driver = DRIVER.read_text()
    parser = driver[driver.index('while [[ $#'):driver.index('\nREPO_ROOT=')]
    claim = driver[driver.index('  CLAIM_ARGS=('):driver.index('  N_CLAIMED=')]
    command = _preamble(tmp_path, STAMP=stamp, **changes)
    command += f'AUTH_CLI=({shlex.quote(sys.executable)} -c {shlex.quote(FIXTURE_CLI)})\n'
    command += 'set -- ' + shlex.join(args) + '\n' + parser + claim
    command += '\nprintf "%s\\n%s" "${CYCLE_CAMPAIGN:-}" "$CLAIMED_JSON"'
    # Use the prepared test interpreter for the driver's stdlib JSON extraction.
    command = command.replace('python3 -c', shlex.quote(sys.executable) + ' -c')
    return subprocess.run(['bash', '-c', command], cwd=ROOT, env=os.environ.copy(),
                          capture_output=True, text=True, timeout=30)


def _calls(tmp_path):
    path = tmp_path / 'calls.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _started(result):
    assert result.returncode == 0, result.stdout + result.stderr
    marker, claimed = result.stdout.split('\n', 1)
    return marker, json.loads(claimed)


def _finish(conn, tmp_path, cycle_id, idea_id, *, extra=False):
    entries = [{'idea_id': idea_id, 'title': 'Trusted fixture', 'outcome': 'sweep_unstable',
                'reason': 'SYNTHETIC_FIXTURE rejected by declared stability criterion'}]
    if extra:
        entries.append({'idea_id': 999, 'title': 'Unowned fixture entry', 'outcome': 'run_error',
                        'reason': 'SYNTHETIC_FIXTURE unselected work'})
    report = tmp_path / f'{cycle_id}.md'
    report.write_text('```json\n' + json.dumps({'hypotheses': entries}) + '\n```\n')
    cycle = ResearchCycle(conn, tmp_path / 'data/research-cycles', cycle_id)
    done = cycle.finish(phase='completed', worker_exit=0, report=report,
                        evidence_ref=f'SYNTHETIC_FIXTURE:{cycle_id}')
    assert done['terminal_count'] == 1 and done['unfinished_count'] == 0
    return report, done


def test_driver_chooser_uses_causal_feedback_in_two_cycles(driver_pool, tmp_path):
    marker, first = _started(_driver_start(tmp_path, '--choose-campaign'))
    assert marker and [idea['id'] for idea in first] == [3]
    directory = tmp_path / 'data/research-cycles/first.choice'
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / 'campaign.json').is_file()
    _finish(driver_pool, tmp_path, 'first', 3)

    second_marker, second = _started(_driver_start(tmp_path, '--choose-campaign', stamp='second'))
    assert second_marker and [idea['id'] for idea in second] == [2]
    calls = _calls(tmp_path)
    assert len(calls) == 2
    assert calls[0]['menu']['scorecard']['totals']['economic_rejected'] == 0
    assert calls[1]['menu']['scorecard']['totals']['economic_rejected'] == 1
    assert calls[1]['menu']['exclusions']['3']['prior_evidence_ids'] == [
        'idea_attempts:1', 'ideas:3']
    # An unordered ledger SELECT may use the idea_id index; verify exact cycle/idea bindings
    # as a sorted list so extra or duplicate attempts still fail, independently of query order.
    recorded = [(row[0], row[1]) for row in driver_pool.execute(
        'SELECT run_stamp, idea_id FROM idea_attempts')]
    assert sorted(recorded) == [('first', 3), ('second', 2)]


@pytest.mark.parametrize('case', ['provider', 'invalid', 'feedback'])
def test_rejected_driver_choice_never_claims_or_falls_back(driver_pool, tmp_path,
                                                         monkeypatch, case):
    monkeypatch.setenv('FIXTURE_CASE', case)
    result = _driver_start(tmp_path, '--choose-campaign')
    assert result.returncode != 0
    assert len(_calls(tmp_path)) == 1
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
    assert not (tmp_path / 'data/research-cycles/first.json').exists()
    # Failed private artifacts are retained; the same cycle cannot quietly spend another call.
    assert _driver_start(tmp_path, '--choose-campaign').returncode != 0
    assert len(_calls(tmp_path)) == 1
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0


def test_driver_preserves_failed_chooser_error_envelope(driver_pool, tmp_path, monkeypatch):
    monkeypatch.setenv('FIXTURE_CASE', 'provider')
    result = _driver_start(tmp_path, '--choose-campaign')
    assert result.returncode != 0
    envelope = json.loads(next(line for line in result.stderr.splitlines()
                               if line.startswith('{')))
    assert envelope == {'ok': False,
                        'error': 'chooser runtime failed (exit 3); see private artifacts',
                        'code': 'invalid_input', 'retryable': False, 'phase': 'cycle_start'}
    assert result.stdout == ''
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0


@pytest.mark.parametrize('reason', sorted(_REASONS))
def test_failed_start_preserves_only_closed_public_memory_reason(
        driver_pool, tmp_path, monkeypatch, reason):
    error = 'public_memory_context:' + reason
    payload = {'ok': False, 'error': error, 'code': 'invalid_input', 'retryable': False}
    raw = json.dumps(payload)
    monkeypatch.setitem(globals(), 'FIXTURE_CLI',
                        f'import sys; sys.stdout.write({raw!r}); raise SystemExit(1)')
    result = _driver_start(tmp_path, '--choose-campaign')
    assert result.returncode != 0 and result.stdout == ''
    envelope = json.loads(next(line for line in result.stderr.splitlines()
                               if line.startswith('{')))
    assert envelope == {'ok': False, 'error': error, 'code': 'invalid_input',
                        'retryable': False, 'phase': 'cycle_start'}
    assert not _calls(tmp_path)
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['envelope', 'malformed', 'wrong_status', 'wrong_types',
                                  'retryable', 'memory_unknown', 'memory_suffix', 'memory_prefix'])
def test_failed_start_diagnostics_never_echo_claims_or_free_text(
        driver_pool, tmp_path, monkeypatch, kind):
    secret = 'SYNTHETIC_FIXTURE_PRIVATE_TOKEN'
    payload = {'ok': False, 'error': secret, 'code': 'invalid_input', 'retryable': False,
               'phase': secret, 'claimed': [{'id': 3, 'claim_token': secret}], 'token': secret}
    if kind == 'wrong_status':
        payload['ok'] = True
    if kind == 'wrong_types':
        payload.update(code=secret, retryable=secret)
    if kind == 'retryable':
        payload.update(code='db_unavailable', retryable=True)
    if kind == 'memory_unknown':
        payload['error'] = 'public_memory_context:unrecognized_reason'
    if kind == 'memory_suffix':
        payload['error'] = 'public_memory_context:artifact_changed ' + secret
    if kind == 'memory_prefix':
        payload['error'] = secret + ' public_memory_context:artifact_changed'
    raw = secret if kind == 'malformed' else json.dumps(payload)
    monkeypatch.setitem(globals(), 'FIXTURE_CLI',
                        f'import sys; sys.stdout.write({raw!r}); raise SystemExit(1)')
    result = _driver_start(tmp_path, '--choose-campaign')
    assert result.returncode != 0
    assert secret not in result.stdout + result.stderr
    envelope = json.loads(next(line for line in result.stderr.splitlines()
                               if line.startswith('{')))
    assert set(envelope) == {'ok', 'error', 'code', 'retryable', 'phase'}
    assert envelope['ok'] is False and envelope['retryable'] is (kind == 'retryable')
    expected_code = ('db_unavailable' if kind == 'retryable' else 'invalid_input'
                     if kind == 'envelope' or kind.startswith('memory_') else 'cycle_start_failed')
    assert envelope['code'] == expected_code
    assert envelope['error'] == 'cycle-start failed; inspect private artifacts'
    assert envelope['phase'] == 'cycle_start'
    assert result.stdout == ''
    assert not _calls(tmp_path)
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0


def test_driver_restart_never_calls_chooser_or_claims_twice(driver_pool, tmp_path):
    _started(_driver_start(tmp_path, '--choose-campaign'))
    before = list(driver_pool.execute('SELECT id, claim_token FROM idea_attempts'))
    repeat = _driver_start(tmp_path, '--choose-campaign')
    assert repeat.returncode != 0
    assert len(_calls(tmp_path)) == 1
    assert list(driver_pool.execute('SELECT id, claim_token FROM idea_attempts')) == before
    _finish(driver_pool, tmp_path, 'first', 3)
    assert _driver_start(tmp_path, '--choose-campaign').returncode != 0
    assert len(_calls(tmp_path)) == 1


@pytest.mark.parametrize('args', [('--choose-campaign', '--campaign', 'unused'),
                                  ('--campaign', 'unused', '--choose-campaign')])
def test_explicit_choices_are_mutually_exclusive_before_any_call(driver_pool, tmp_path, args):
    result = _driver_start(tmp_path, *args)
    assert result.returncode == 2
    assert not _calls(tmp_path)
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0


def test_unknown_cost_blocks_driver_chooser_before_spending(driver_pool, tmp_path):
    result = _driver_start(tmp_path, '--choose-campaign', '--max-cost', '0')
    assert result.returncode != 0
    assert not _calls(tmp_path)
    assert driver_pool.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0


def test_legacy_driver_has_no_chooser_call_or_campaign_marker(driver_pool, tmp_path):
    marker, claimed = _started(_driver_start(tmp_path))
    assert not marker and [idea['id'] for idea in claimed] == [1, 2, 3]
    assert not _calls(tmp_path)
    assert not (tmp_path / 'data/research-cycles/first.choice').exists()


def test_fixture_child_ignores_explicit_synthetic_dotenv(driver_pool, tmp_path, monkeypatch):
    dotenv = tmp_path / 'SYNTHETIC_FIXTURE.env'
    assert not dotenv.is_relative_to(ROOT)
    dotenv.write_text('ALGUA_IDEA_CLAIM_TTL_MINUTES=1\n')
    monkeypatch.delenv('ALGUA_IDEA_CLAIM_TTL_MINUTES', raising=False)
    # A one-minute TTL would refuse this real controller's 45-minute request if it were read.
    prefix = ('from algua.config.settings import Settings\n'
              f'Settings.model_config["env_file"] = {str(dotenv)!r}\n')
    monkeypatch.setitem(globals(), 'FIXTURE_CLI', prefix + FIXTURE_CLI)
    marker, claimed = _started(_driver_start(tmp_path, '--choose-campaign'))
    assert marker and [idea['id'] for idea in claimed] == [3]
    assert len(_calls(tmp_path)) == 1


def test_chooser_start_payload_enforces_campaign_digest_publication(driver_pool, tmp_path):
    marker, claimed = _started(_driver_start(tmp_path, '--choose-campaign'))
    report, done = _finish(driver_pool, tmp_path, 'first', 3, extra=True)
    result_path = tmp_path / 'first.result.json'
    result_path.write_text(json.dumps(done))
    driver = DRIVER.read_text()
    append = driver[driver.index('append_digest() {'):driver.index('\n# Close the ideation loop')]
    values = {
        'REPO_ROOT': str(ROOT), 'AUTH_DIGEST': str(tmp_path / 'digest.jsonl'),
        'AUTH_QUEUE': str(tmp_path / 'queue.json'), 'AUTH_QUEUE_LOCK': str(tmp_path / 'queue.lock'),
        'DIGEST_BRANCH': '', 'DIGEST_REPORT_PATH': str(report), 'STRATEGY_MODULE_NAMES': '',
        'rc': '0', 'timed_out': '0', 'wall_s': '1', 'n_strategy_files': '0', 'rate_limited': '0',
        'CLAIMED_JSON': json.dumps(claimed), 'CYCLE_RESULT': str(result_path),
        'CYCLE_CAMPAIGN': marker,
    }
    command = _preamble(tmp_path, **values) + append + '\nappend_digest completed\n'
    command = command.replace('python3 - ', shlex.quote(sys.executable) + ' - ')
    result = subprocess.run(['bash', '-c', command], cwd=ROOT, env=os.environ.copy(),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    digest = json.loads((tmp_path / 'digest.jsonl').read_text())
    assert not digest['trailer_parse_error']
    assert [row['idea_id'] for row in digest['hypotheses']] == [3]
    assert digest['attempts_total'] == 1
