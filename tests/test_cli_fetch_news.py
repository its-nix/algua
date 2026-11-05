"""Synthetic RSS mechanics; real feed acquisition is recorded separately."""
from __future__ import annotations

import io
import json
import signal
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.serve import StoreBackedNewsProvider
from algua.data.store import DataStore

runner = CliRunner()


def feed(item='shared', publication='Thu, 01 Jan 2026 12:00:00 +0000'):
    return (f'<rss version="2.0"><channel><item><guid>{item}</guid>'
            '<title>Fixture &amp; title</title>'
            f'<link>https://example.invalid/{item}</link><pubDate>{publication}</pubDate>'
            '</item></channel></rss>').encode()


def network(monkeypatch, tmp_path, bad=None):
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('ALGUA_DB_PATH', str(tmp_path / 'must-not-open.db'))
    calls = []

    class Response(io.BytesIO):
        status = 200
        headers = {'Content-Type': 'application/xml'}

        def read(self, amount=-1):
            assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
            if bad == 'timeout':
                signal.raise_signal(signal.SIGALRM)
            return super().read(amount)

    def response(_self, request, timeout):
        calls.append((request.full_url, timeout))
        symbol = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)['s'][0]
        data = feed()
        if symbol == 'MSFT':
            data = data.replace(b'</channel>', feed('other').split(b'<channel>')[1]
                                .split(b'</channel>')[0] + b'</channel>')
            if bad == 'partial':
                data = b'<rss><channel/></rss>'
        if bad == 'malformed':
            data = b'<html>not news'
        if bad == 'future':
            data = feed(publication='Thu, 01 Jan 2099 12:00:00 +0000')
        if bad == 'naive':
            data = feed(publication='Thu, 01 Jan 2026 12:00:00')
        if bad == 'oversize':
            data = b'x' * (2 * 1024**2 + 1)
        return Response(data)

    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', response)
    return calls


def test_current_news_collection_preserves_publication_and_gates_on_collection_time(
        monkeypatch, tmp_path):
    calls = network(monkeypatch, tmp_path)
    before = datetime.now(UTC)
    result = runner.invoke(app, ['data', 'fetch-news', '--symbols', 'AAPL,MSFT'])
    after = datetime.now(UTC)
    assert result.exit_code == 0, result.output
    snapshot = json.loads(result.output)['snapshot']
    known = datetime.fromisoformat(snapshot['as_of'])
    assert before <= known <= after and snapshot['row_count'] == 3
    assert len(calls) == 2 and all(timeout == 10 for _, timeout in calls)
    metadata = snapshot['source_metadata']
    assert metadata['historical_availability'] == 'UNKNOWN'
    assert metadata['knowable_at_method'] == 'collection_completed_at'
    assert set(json.loads(metadata['feed_sha256'])) == {'AAPL', 'MSFT'}
    assert 'feed_ticker_association_not_verified_mentions' in json.loads(metadata['limitations'])
    store = DataStore(tmp_path / 'data')
    rows = store.read_news(snapshot['snapshot_id'])
    assert set(rows.knowable_at) == {known}
    assert set(rows.published_at) == {datetime(2026, 1, 1, 12, tzinfo=UTC)}
    assert rows.headline.tolist() == ['Fixture & title'] * 3
    assert rows.body.isna().all()
    serving = StoreBackedNewsProvider(store, snapshot['snapshot_id'])
    assert serving.get_news(['AAPL', 'MSFT'], known).empty
    assert len(serving.get_news(['AAPL', 'MSFT'], known + timedelta(microseconds=1))) == 3
    query = runner.invoke(app, ['data', 'query-news', '--snapshot-id', snapshot['snapshot_id']])
    assert query.exit_code == 0 and len(json.loads(query.output)) == 3
    assert not (tmp_path / 'must-not-open.db').exists()
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@pytest.mark.parametrize('bad', ['partial', 'malformed', 'future', 'naive', 'oversize', 'timeout'])
def test_bad_or_partial_feed_refuses_without_snapshot_or_registry(monkeypatch, tmp_path, bad):
    network(monkeypatch, tmp_path, bad)
    result = runner.invoke(app, ['data', 'fetch-news', '--symbols', 'AAPL,MSFT'])
    assert result.exit_code != 0 and json.loads(result.output)['code'] == 'provider_error'
    assert not (tmp_path / 'data').exists() and not (tmp_path / 'must-not-open.db').exists()
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
