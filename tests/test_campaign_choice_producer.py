"""Executable chooser wiring with a fake runtime; these are never provider/model calls."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from algua.registry.db import connect, migrate
from tests.campaign_fixtures import add_idea

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fixture_pool(tmp_path, monkeypatch):
    database = tmp_path / 'SYNTHETIC_FIXTURE.db'
    conn = connect(database)
    migrate(conn)
    for title, family in [('auction pressure', 'a'), ('dividend drift', 'b'),
                          ('liquidity recovery', 'c')]:
        add_idea(conn, title, family=family)
    conn.close()
    monkeypatch.setenv('ALGUA_DB_PATH', str(database))
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path / 'data'))
    return database


@pytest.fixture
def fake_runtime(tmp_path, monkeypatch):
    """Only the executable boundary is substituted; CLI/controller/ledger are real."""
    binary = tmp_path / 'bin'
    binary.mkdir()
    runtime = binary / 'opencode'
    runtime.write_text('#!' + sys.executable + '\n' + '''
import json, os, sys
from pathlib import Path
with Path(os.environ['FIXTURE_CALLS']).open('a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
case = os.environ.get('FIXTURE_CASE', '')
if 'export' in sys.argv:
    export = {'info':{'id':sys.argv[sys.argv.index('--sanitize')+1]},
        'messages':[{'info':{'role':'assistant','providerID':'fixture',
        'modelID':'fixture','finish':'stop'},'parts':[]}],
        'padding':'x'*300000 if case == 'oversized_export' else ''}
    if case == 'export_session': export['info']['id'] = 'other-session'
    if case == 'export_no_assistant': export['messages'] = []
    if case == 'export_no_model': del export['messages'][0]['info']['modelID']
    if case == 'export_shape': export = {'messages': None}
    print(json.dumps(export))
    sys.exit(0)
if 'debug' in sys.argv:
    agent = {'name':'chooser','tools': {'read':False,'bash':False,'task':False},
        'mode':os.environ.get('FIXTURE_MODE','primary'),'steps':1,
        'model':{'providerID':'fixture','modelID':'fixture'},'permission':[
        {'permission':'*','pattern':'*','action':'deny'}]}
    if case == 'tool': agent['tools']['bash'] = True
    if case == 'missing_deny': agent['permission'] = []
    print(json.dumps(agent))
    sys.exit(0)
Path('fixture-environment.json').write_text(json.dumps({k:os.environ.get(k) for k in
    ['XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME','XDG_CACHE_HOME']}))
if case == 'internal_state':
    state = Path(os.environ['XDG_DATA_HOME']) / 'opencode/runtime-state.bin'
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.open('wb') as stream:
        for _ in range(9):
            stream.write(b'x' * 1024 * 1024)
prompt = Path(sys.argv[sys.argv.index('-f')+1]).read_text()
menu = json.loads(prompt.split('MENU_JSON\\n',1)[1])
choice = {**menu['choices'][-1], 'reason':'SYNTHETIC_FIXTURE uses the captured evidence'}
reply = {'menu_id': menu['menu_id'], 'choices':[choice]}
case = os.environ.get('FIXTURE_CASE', '')
if case == 'provider':
    print('provider unavailable',file=sys.stderr)
    sys.exit(3)
if case == 'no_output': sys.exit(0)
if case == 'empty': reply['choices'] = []
if case == 'duplicate': reply['choices'] *= 2
if case == 'stale': reply['menu_id'] = 'stale'
if case == 'out_of_menu': choice['hypothesis_id'] = 999
if case == 'bool_id': choice['hypothesis_id'] = True
if case == 'category': choice['category'] = 'elsewhere'
if case == 'evidence': choice['prior_evidence_ids'] = ['idea_attempts:999']
if case == 'budget': choice['budget'] = 2
if case == 'bool_budget': choice['budget'] = True
if case == 'reason': choice['reason'] = ' '
if case == 'long_reason': choice['reason'] = 'x'*2001
if case == 'extra': choice['extra'] = 'untrusted'
if case == 'missing': del choice['budget']
if case == 'extra_reply': reply['extra'] = 'untrusted'
text = json.dumps(reply)
if case == 'malformed': text = 'not json'
if case == 'fenced': text = '```json'+text+'```'
if case == 'duplicate_keys': text = text.replace('"choices":', '"choices": [], "choices":')
if case == 'oversized': text = ' '*300000 + text
session = 'SYNTHETIC_FIXTURE-session'
for kind,part in [('step_start',{'type':'step-start'}),
    ('text',{'type':'text','text':text}),
    ('step_finish',{'type':'step-finish','reason':'stop','cost':0,'tokens':{}})]:
    if case == 'error_event' and kind == 'step_start': kind = 'error'
    if case == 'tool_event' and kind == 'step_start': kind = 'tool_use'
    if case == 'missing_finish' and kind == 'step_finish': continue
    if case == 'bad_finish' and kind == 'step_finish': part['reason'] = 'length'
    if case == 'session_drift' and kind == 'text': session = 'other-session'
    print(json.dumps({'type':kind,'sessionID':session,'part':part}),flush=True)
''')
    runtime.chmod(0o755)
    calls = tmp_path / 'calls.jsonl'
    monkeypatch.setenv('PATH', str(binary) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('FIXTURE_CALLS', str(calls))
    monkeypatch.setenv('OPENCODE_AUTH_CONTENT', '{}')  # no native credential reads in fixtures
    # Fake runtime only. This does not alter or exercise host containment policy.
    monkeypatch.setenv('ALGUA_AGENT_SANDBOX', 'none')
    return calls


def cli(*args):
    return subprocess.run([sys.executable, '-c', 'from algua.cli.main import main; main()',
                           'research', 'idea', *args], cwd=ROOT, env=os.environ.copy(),
                          capture_output=True, text=True, timeout=30)


def test_executable_opt_in_chooses_only_runtime_selection(fixture_pool, fake_runtime, tmp_path):
    evidence = tmp_path / 'choice'
    result = cli('cycle-start', '--run', 'producer', '--limit', '3',
                 '--choose', '--choice-dir', str(evidence))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert [i['id'] for i in payload['claimed']] == [3]
    assert [c['hypothesis_id'] for c in payload['campaign']['selection']['choices']] == [3]
    assert (evidence / 'campaign.json').is_file()
    assert (evidence / 'runtime.jsonl').is_file()
    runtime_env = json.loads((evidence/'fixture-environment.json').read_text())
    assert all(v and Path(v).is_relative_to(evidence) for v in runtime_env.values())
    calls = [json.loads(line) for line in fake_runtime.read_text().splitlines()]
    assert len([c for c in calls if c[0] == 'run']) == 1
    run = next(c for c in calls if c[0] == 'run')
    assert '--format' in run and 'json' in run
    assert '--agent' in run and 'chooser' in run
    session = json.loads((evidence/'session.json').read_text())
    assert session['info']['id'] == 'SYNTHETIC_FIXTURE-session'
    assert session['messages'][0]['info']['modelID'] == 'fixture'
    conn = connect(fixture_pool)
    try:
        assert [r[0] for r in conn.execute('SELECT idea_id FROM idea_attempts')] == [3]
    finally:
        conn.close()


def prepared(database, tmp_path, **changes):
    from algua.operator.research_cycle import CycleLimits, ResearchCycle

    conn = connect(database)
    cycle = ResearchCycle(conn, tmp_path / 'cycles', 'bounded')
    args = {'limits': CycleLimits(max_hypotheses=3), 'context': {'tier':'synthetic_fixture'},
            'ttl_minutes':180, **changes}
    return conn, cycle, args, cycle.campaign_menu(**args)


def test_large_history_has_bounded_prompt_but_complete_admission_menu(
        fixture_pool, fake_runtime, tmp_path):
    from algua.operator.campaign_choice import MAX_PROMPT_BYTES, choose_campaign
    from algua.registry.negative_results import record_negative_result

    conn = connect(fixture_pool)
    for i in range(40):
        add_idea(conn, f'archived alternative {i}', family=f'archive-{i}',
                 hypothesis='SYNTHETIC_FIXTURE research description ' * 80)
        record_negative_result(conn, kind='discard', verdict='CRITIC:fixture', actor='agent',
            reason='SYNTHETIC_FIXTURE conceptual concern ' * 100,
            hypothesis='SYNTHETIC_FIXTURE earlier proposed test ' * 100, source='manual',
            params={'not_needed_for_ranking': 'SYNTHETIC_FIXTURE parameter ' * 100})
    conn.close()
    conn, cycle, args, menu = prepared(fixture_pool, tmp_path)
    assert len(json.dumps(menu).encode()) > MAX_PROMPT_BYTES
    before = list(conn.iterdump())
    try:
        directory = tmp_path / 'bounded-history'
        campaign = choose_campaign(cycle, menu=menu, directory=directory, **args)
        prompt = (directory / 'prompt.txt').read_text()
        view = json.loads(prompt.split('MENU_JSON\n', 1)[1])
        assert len(prompt.encode()) <= MAX_PROMPT_BYTES
        assert view['menu_id'] == menu['menu_id']
        assert view['choices'] == menu['choices'] and view['request'] == menu['request']
        offered = {c['hypothesis_id'] for c in menu['choices']}
        assert view['scorecard']['hypotheses'] == [
            h for h in menu['scorecard']['hypotheses'] if h['id'] in offered]
        assert view['scorecard']['totals'] == menu['scorecard']['totals']
        assert view['scorecard']['by_family'] == menu['scorecard']['by_family']
        assert view['prompt_coverage']['hypotheses']['omitted'] > 0
        assert view['prompt_coverage']['negative_results']['omitted'] > 0
        assert view['prompt_coverage']['negative_results']['truncated_fields'] > 0
        assert json.loads((directory / 'menu.json').read_text()) == menu
        assert campaign['menu'] == menu and list(conn.iterdump()) == before
        claimed, result = cycle.start(**args, campaign=campaign)
        assert result['ok'] and [i.id for i in claimed] == [menu['choices'][-1]['hypothesis_id']]
    finally:
        conn.close()


def test_prompt_view_keeps_old_evidence_referenced_by_offered_choices(
        fixture_pool, tmp_path):
    from algua.operator.campaign_choice import _prompt_menu

    conn, _, _, menu = prepared(fixture_pool, tmp_path)
    try:
        menu['choices'][0]['prior_evidence_ids'] += ['idea_attempts:1', 'negative_results:1']
        for key, prefix in [('attempts', 'idea_attempts'),
                            ('negative_results', 'negative_results')]:
            menu['scorecard'][key] = [
                {'id': i, 'evidence_id': f'{prefix}:{i}', 'reason': 'SYNTHETIC_FIXTURE ' * 80,
                 'idea_id': 999, 'idea_ids': []} for i in reversed(range(1, 20))]
            related = next(row for row in menu['scorecard'][key] if row['id'] == 2)
            offered = menu['choices'][0]['hypothesis_id']
            related.update(idea_id=offered if key == 'attempts' else 999,
                           idea_ids=[offered] if key == 'negative_results' else [])
        view = _prompt_menu(menu)
        for key in ('attempts', 'negative_results'):
            ids = [row['id'] for row in view['scorecard'][key]]
            assert 1 in ids and 2 in ids and 19 in ids and ids == sorted(ids)
            assert view['prompt_coverage'][key]['required_rows'] == 2
            assert view['prompt_coverage'][key]['omitted'] == 19 - len(ids)
            assert view['prompt_coverage'][key]['referenced_rows'] == 1
            assert view['prompt_coverage'][key]['referenced_rows_omitted'] == 0
            assert view['prompt_coverage'][key]['truncated_fields'] > 0
    finally:
        conn.close()


def test_oversized_essential_hypothesis_still_refuses_before_runtime(
        fixture_pool, fake_runtime, tmp_path):
    from algua.operator.campaign_choice import choose_campaign

    conn = connect(fixture_pool)
    add_idea(conn, 'large required specification', family='large',
             hypothesis='SYNTHETIC_FIXTURE essential specification ' * 4000)
    conn.close()
    conn, cycle, args, menu = prepared(fixture_pool, tmp_path, category='large')
    assert len(menu['choices']) == 1
    before = list(conn.iterdump())
    try:
        directory = tmp_path / 'essential-too-large'
        with pytest.raises(ValueError, match='chooser prompt exceeds byte bound'):
            choose_campaign(cycle, menu=menu, directory=directory, **args)
        assert list(conn.iterdump()) == before
        assert not fake_runtime.exists() and not directory.exists() and not cycle.path.exists()
    finally:
        conn.close()


@pytest.mark.parametrize('file_mb', [16, 4])
def test_native_state_uses_configured_file_budget_without_enlarging_output_bounds(
        fixture_pool, fake_runtime, tmp_path, monkeypatch, file_mb):
    monkeypatch.setenv('FIXTURE_CASE', 'internal_state')
    evidence = tmp_path / 'native-state'
    result = cli('cycle-start', '--run', 'native-state', '--limit', '3',
                 '--file-mb', str(file_mb), '--choose', '--choice-dir', str(evidence))
    payload = json.loads(result.stdout)
    state = evidence / 'data/opencode/runtime-state.bin'
    if file_mb == 16:
        assert result.returncode == 0, result.stdout + result.stderr
        assert state.stat().st_size == 9 * 1024 * 1024
        assert [idea['id'] for idea in payload['claimed']] == [3]
        assert (evidence / 'runtime.jsonl').stat().st_size < 256 * 1024
        assert (evidence / 'session.json').stat().st_size < 256 * 1024
    else:
        assert result.returncode != 0 and payload['ok'] is False
        assert state.stat().st_size <= file_mb * 1024 * 1024
        assert not (evidence / 'campaign.json').exists()
        assert not (tmp_path / 'data/research-cycles/native-state.json').exists()


@pytest.mark.parametrize('case', [
    'provider', 'no_output', 'empty', 'duplicate', 'stale', 'out_of_menu', 'bool_id',
    'category', 'evidence', 'budget', 'bool_budget', 'reason', 'long_reason', 'extra',
    'missing', 'extra_reply', 'malformed', 'fenced', 'duplicate_keys', 'oversized',
    'error_event', 'tool_event', 'missing_finish', 'bad_finish', 'session_drift', 'tool',
    'missing_deny',
])
def test_bad_runtime_reply_has_zero_controller_or_ledger_effects(
        fixture_pool, fake_runtime, tmp_path, monkeypatch, case):
    from algua.operator.campaign_choice import choose_campaign

    monkeypatch.setenv('FIXTURE_CASE', case)
    conn, cycle, args, menu = prepared(fixture_pool, tmp_path)
    before = list(conn.iterdump())
    try:
        with pytest.raises(ValueError):
            campaign = choose_campaign(cycle, menu=menu, directory=tmp_path / 'rejected', **args)
            cycle.start(**args, campaign=campaign)
        assert list(conn.iterdump()) == before
        assert not cycle.path.exists()
        assert not (tmp_path / 'rejected/campaign.json').exists()
        if case in {'tool', 'missing_deny'}:
            calls = [json.loads(line) for line in fake_runtime.read_text().splitlines()]
            assert all(c[0] == 'debug' for c in calls)
    finally:
        conn.close()


@pytest.mark.parametrize('case', ['context', 'run', 'category', 'ttl', 'preview', 'budget',
                                  'cpu', 'memory', 'file', 'wall', 'feedback', 'menu',
                                  'unknown_cap', 'empty_menu', 'prompt_bound'])
def test_preflight_refuses_before_any_runtime_or_claim(
        fixture_pool, fake_runtime, tmp_path, case):
    from dataclasses import replace

    from algua.operator.campaign_choice import choose_campaign

    conn, cycle, args, menu = prepared(fixture_pool, tmp_path)
    if case == 'context':
        args['context'] = {'changed':True}
    elif case == 'run':
        cycle.cycle_id = 'different'
    elif case == 'category':
        args['category'] = 'a'
    elif case == 'ttl':
        args['ttl_minutes'] = 181
    elif case == 'preview':
        args['preview_hold_hours'] = 1
    elif case in {'budget','cpu','memory','file','wall'}:
        field = {'budget':'max_hypotheses','cpu':'cpu_seconds','memory':'memory_mb',
                 'file':'file_mb','wall':'max_wall_seconds'}[case]
        args['limits'] = replace(args['limits'], **{field:2})
    elif case == 'feedback':
        add_idea(conn, 'new feedback', family='d')
    elif case == 'menu':
        menu['choices'][0]['reason'] = 'altered'
    elif case == 'unknown_cap':
        args['limits'] = replace(args['limits'], max_cost=0)
        menu = cycle.campaign_menu(**args)
    elif case == 'empty_menu':
        args['category'] = 'no-such-category'
        menu = cycle.campaign_menu(**args)
    else:
        args['context'] = {'oversized':'x'*100000}
        menu = cycle.campaign_menu(**args)
    before = list(conn.iterdump())
    try:
        with pytest.raises(ValueError):
            choose_campaign(cycle, menu=menu, directory=tmp_path / 'rejected', **args)
        assert not fake_runtime.exists()
        assert list(conn.iterdump()) == before
        assert not cycle.path.exists()
        assert not (tmp_path / 'rejected').exists()
    finally:
        conn.close()


@pytest.mark.parametrize('extra', [[], ['--menu-only'], ['--campaign','unused']])
def test_cli_legacy_and_explicit_channels_do_not_call_chooser(
        fixture_pool, fake_runtime, tmp_path, extra):
    args = ['cycle-start','--run','legacy','--limit','1',*extra]
    if extra and extra[0] == '--campaign':
        path = tmp_path / 'bad.json'
        path.write_text('null')
        args[-1] = str(path)
    result = cli(*args)
    assert result.returncode == (1 if '--campaign' in extra else 0)
    assert not fake_runtime.exists()


@pytest.mark.parametrize('extra', [[], ['--menu-only'], ['--campaign','unused']])
def test_cli_cannot_mix_opt_in_channels(fixture_pool, fake_runtime, tmp_path, extra):
    result = cli('cycle-start','--run','mixed','--limit','1','--choose',*extra)
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False
    assert not fake_runtime.exists()


def test_restart_never_spends_another_chooser_call(fixture_pool, fake_runtime, tmp_path):
    from algua.operator.campaign_choice import choose_campaign

    conn, cycle, args, menu = prepared(fixture_pool, tmp_path)
    try:
        campaign = choose_campaign(cycle, menu=menu, directory=tmp_path / 'first', **args)
        cycle.start(**args, campaign=campaign)
        before = fake_runtime.read_bytes()
        with pytest.raises(ValueError, match='already started'):
            choose_campaign(cycle, menu=menu, directory=tmp_path / 'restart', **args)
        assert fake_runtime.read_bytes() == before
        assert not (tmp_path / 'restart').exists()
    finally:
        conn.close()


def test_feedback_changed_during_runtime_refuses_before_intake(
        fixture_pool, fake_runtime, tmp_path, monkeypatch):
    from algua.operator.campaign_choice import choose_campaign

    conn, cycle, args, menu = prepared(fixture_pool, tmp_path)
    original = cycle.campaign_menu
    count = 0

    def current(**kwargs):
        nonlocal count
        count += 1
        if count == 2:
            add_idea(conn, 'SYNTHETIC_FIXTURE concurrent feedback', family='d')
        return original(**kwargs)

    monkeypatch.setattr(cycle, 'campaign_menu', current)
    try:
        with pytest.raises(ValueError, match='stale'):
            choose_campaign(cycle, menu=menu, directory=tmp_path / 'stale', **args)
        assert cycle.rows() == [] and not cycle.path.exists()
        assert not (tmp_path / 'stale/campaign.json').exists()
    finally:
        conn.close()


@pytest.mark.parametrize('case', ['tool', 'missing_deny'])
@pytest.mark.parametrize('optimized', ['0', '1'])
def test_tool_preflight_is_enforced_with_python_optimization(
        fixture_pool, fake_runtime, tmp_path, monkeypatch, case, optimized):
    monkeypatch.setenv('FIXTURE_CASE', case)
    monkeypatch.setenv('PYTHONOPTIMIZE', optimized)
    evidence = tmp_path / 'optimized'
    result = cli('cycle-start','--run','optimized','--limit','3','--choose',
                 '--choice-dir',str(evidence))
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False
    assert all(json.loads(line)[0] == 'debug' for line in fake_runtime.read_text().splitlines())
    message = 'tool exposed' if case == 'tool' else 'deny-all permission missing'
    assert message in (evidence / 'seam.stderr').read_text()
    assert not (evidence / 'campaign.json').exists()
    assert not (tmp_path / 'data/research-cycles/optimized.json').exists()
    conn = connect(fixture_pool)
    try:
        assert conn.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize('case', ['export_session', 'export_no_assistant',
                                  'export_no_model', 'export_shape'])
def test_invalid_export_refuses_cli_json_before_admission(
        fixture_pool, fake_runtime, tmp_path, monkeypatch, case):
    monkeypatch.setenv('FIXTURE_CASE', case)
    evidence = tmp_path / 'invalid-export'
    result = cli('cycle-start', '--run', 'invalid-export', '--limit', '3',
                 '--choose', '--choice-dir', str(evidence))
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False
    calls = [json.loads(line)[0] for line in fake_runtime.read_text().splitlines()]
    assert calls == ['debug', 'run', 'export']
    assert not (evidence / 'campaign.json').exists()
    assert not (tmp_path / 'data/research-cycles/invalid-export.json').exists()
    conn = connect(fixture_pool)
    try:
        assert conn.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
    finally:
        conn.close()


def test_legacy_ignores_unrelated_sibling_stderr(tmp_path):
    from tests.test_agent_runtime_seam import _REJECTED, _run_seam

    (tmp_path/'agent.log.stderr').write_text(_REJECTED)
    result = _run_seam(tmp_path, 'clean legacy fixture\n')
    assert result.returncode == 0, result.stdout + result.stderr


def test_subagent_mode_cannot_fall_back_to_broader_default(
        fixture_pool, fake_runtime, tmp_path, monkeypatch):
    monkeypatch.setenv('FIXTURE_MODE', 'subagent')
    result = cli('cycle-start','--run','subagent','--limit','3','--choose',
                 '--choice-dir',str(tmp_path/'subagent'))
    assert result.returncode == 1, result.stdout
    assert all(json.loads(line)[0] == 'debug' for line in fake_runtime.read_text().splitlines())


def test_source_identity_drift_during_choice_refuses_before_claim(
        fixture_pool, fake_runtime, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from algua.cli import idea_ops_cmd
    from algua.cli.main import app

    original = idea_ops_cmd._cycle_context
    calls = 0

    def source(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls > 1:
            result['source_baseline_sha256'] = 'SYNTHETIC_FIXTURE concurrent source edit'
        return result

    monkeypatch.setattr(idea_ops_cmd, '_cycle_context', source)
    result = CliRunner().invoke(app, ['research','idea','cycle-start','--run','source-drift',
                                '--limit','3','--choose','--choice-dir',str(tmp_path/'source')])
    assert result.exit_code == 1, result.stdout
    conn = connect(fixture_pool)
    try:
        assert conn.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
        assert not (tmp_path/'data/research-cycles/source-drift.json').exists()
    finally:
        conn.close()


def test_slow_runtime_times_out_without_claims(fixture_pool, fake_runtime, tmp_path, monkeypatch):
    runtime = tmp_path/'bin/opencode'
    source = runtime.read_text().replace("case = os.environ.get('FIXTURE_CASE', '')",
        "import time; time.sleep(3)\ncase = os.environ.get('FIXTURE_CASE', '')")
    runtime.write_text(source)
    result = cli('cycle-start','--run','timeout','--limit','3','--timeout','1s',
                 '--choose','--choice-dir',str(tmp_path/'timeout'))
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False
    assert not (tmp_path/'data/research-cycles/timeout.json').exists()
    conn = connect(fixture_pool)
    try:
        assert conn.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
    finally:
        conn.close()


def test_missing_runtime_never_substitutes_legacy_choices(
        fixture_pool, tmp_path, monkeypatch):
    monkeypatch.setenv('PATH','/usr/bin:/bin')
    monkeypatch.setenv('OPENCODE_AUTH_CONTENT','{}')
    # The seam exits at its runtime presence check, before any containment launch.
    result = cli('cycle-start','--run','unavailable','--limit','3','--choose',
                 '--choice-dir',str(tmp_path/'unavailable'))
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False
    assert not (tmp_path/'data/research-cycles/unavailable.json').exists()
    conn = connect(fixture_pool)
    try:
        assert conn.execute('SELECT COUNT(*) FROM idea_attempts').fetchone()[0] == 0
    finally:
        conn.close()


def test_fast_exit_cannot_bypass_export_size_bound(
        fixture_pool, fake_runtime, tmp_path, monkeypatch):
    from algua.operator import campaign_choice

    monkeypatch.setenv('FIXTURE_CASE','oversized_export')
    sleep = campaign_choice.time.sleep
    monkeypatch.setattr(campaign_choice.time,'sleep',lambda _:sleep(1))
    conn, cycle, args, menu = prepared(fixture_pool, tmp_path)
    try:
        with pytest.raises(ValueError, match='byte bound'):
            campaign_choice.choose_campaign(cycle,menu=menu,directory=tmp_path/'large',**args)
        assert cycle.rows() == [] and not cycle.path.exists()
    finally:
        conn.close()
