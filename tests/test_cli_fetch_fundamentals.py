"""Current-collected vendor fundamentals, not reconstructed historical knowledge."""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from typer.testing import CliRunner

from algua.cli.main import app
from algua.data.serve import StoreBackedFundamentalsProvider
from algua.data.store import DataStore

runner = CliRunner()


def vendor(monkeypatch, tmp_path, *, bad=None):
    monkeypatch.setenv('ALGUA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('ALGUA_DB_PATH', str(tmp_path / 'must-not-open.db'))
    calls = []

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def get_income_stmt(self, *, freq, pretty):
            calls.append((self.symbol, freq, pretty))
            if bad == 'network':
                raise OSError('offline fixture')
            if bad == 'partial' and self.symbol == 'MSFT':
                return pd.DataFrame()
            frame = pd.DataFrame({pd.Timestamp('2025-09-30'): [100., 2., 20.],
                                  pd.Timestamp('2025-06-30'): [90., 1., 15.]},
                                 index=['TotalRevenue', 'DilutedEPS', 'NetIncome'])
            if bad == 'nonfinite':
                frame.iloc[0, 0] = float('inf')
            if bad == 'future_period':
                frame.columns = [pd.Timestamp('2099-09-30'), pd.Timestamp('2025-06-30')]
            return frame

    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(Ticker=Ticker,
                                                              __version__='fixture-version'))
    return calls


def test_fetch_persists_exact_values_with_current_knowledge_clock_and_pinned_readback(
        monkeypatch, tmp_path):
    calls = vendor(monkeypatch, tmp_path)
    before = datetime.now(UTC)
    result = runner.invoke(app, ['data', 'fetch-fundamentals', '--symbols', ' msft,AAPL,aapl '])
    after = datetime.now(UTC)
    assert result.exit_code == 0, result.output
    snapshot = json.loads(result.output)['snapshot']
    assert calls == [('AAPL', 'quarterly', False), ('MSFT', 'quarterly', False)]
    assert snapshot['symbols'] == ['AAPL', 'MSFT'] and snapshot['row_count'] == 12
    known = datetime.fromisoformat(snapshot['as_of'])
    assert before <= known <= after
    metadata = snapshot['source_metadata']
    assert metadata['knowable_at_method'] == 'collection_completed_at'
    assert metadata['historical_availability'] == 'UNKNOWN'
    assert metadata['library_version'] == 'fixture-version'
    assert 'vendor_restatements_possible' in json.loads(metadata['limitations'])
    store = DataStore(tmp_path / 'data')
    rows = store.read_fundamentals(snapshot['snapshot_id'])
    assert set(rows.knowable_at) == {pd.Timestamp(known)}
    revenue = rows.loc[(rows.symbol == 'AAPL') & (rows.metric == 'revenue'), 'value'].tolist()
    assert revenue == [90., 100.]
    assert set(rows.fiscal_period_end.astype(str)) == {'2025-06-30', '2025-09-30'}
    serving = StoreBackedFundamentalsProvider(store, snapshot['snapshot_id'])
    assert serving.get_fundamentals(['AAPL'], known).empty
    assert len(serving.get_fundamentals(['AAPL'], known + timedelta(microseconds=1))) == 6
    query = runner.invoke(app, ['data', 'query-fundamentals', '--snapshot-id',
                               snapshot['snapshot_id']])
    assert query.exit_code == 0 and len(json.loads(query.output)) == 12
    assert not (tmp_path / 'must-not-open.db').exists()


@pytest.mark.parametrize('bad', ['partial', 'network', 'nonfinite', 'future_period'])
def test_failed_collection_publishes_no_partial_snapshot_or_registry(monkeypatch, tmp_path, bad):
    vendor(monkeypatch, tmp_path, bad=bad)
    result = runner.invoke(app, ['data', 'fetch-fundamentals', '--symbols', 'AAPL,MSFT'])
    assert result.exit_code != 0
    assert json.loads(result.output)['code'] == 'provider_error'
    assert not (tmp_path / 'data').exists()
    assert not (tmp_path / 'must-not-open.db').exists()
