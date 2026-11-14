import json

import pytest
import requests

from algua.config.settings import Settings
from algua.data.contracts import BarRequest
from algua.data.providers import get_provider
from algua.data.providers.eodhd import EodhdBarProvider
from algua.data.providers.errors import ProviderError
from algua.data.schema import to_bar_schema


def bar(day="2020-08-28", **overrides):
    return {"date": day, "open": 500, "high": 510, "low": 490,
            "close": 505, "adjusted_close": 120, "volume": 4000, **overrides}


def wire(monkeypatch, payloads):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        item = payloads.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item if isinstance(item, tuple) else (200, item)
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(payload).encode()
        return response
    monkeypatch.setattr("algua.data.providers.eodhd.requests.get", get)
    return calls


def test_split_after_requested_end_restores_raw_volume_and_clips_end(monkeypatch):
    calls = wire(monkeypatch, [[bar(), bar("2020-08-31")],
                              [{"date": "2020-08-31", "split": "4.000000/1.000000"}]])
    result = EodhdBarProvider(api_key="demo").get_bars(
        BarRequest(("AAPL",), "2020-08-28", "2020-08-31"))
    frame = to_bar_schema(result.frame, timeframe="1d")
    assert len(frame) == 1
    assert frame.iloc[0].volume == 1000
    assert frame.iloc[0].close == 505
    assert frame.iloc[0].adj_close == 120
    assert calls[0][1]["params"]["to"] == "2020-08-30"
    assert calls[1][1]["params"]["to"] >= "2026-01-01"
    assert calls[0][0].endswith("/eod/AAPL.US")
    assert all(call[1]["allow_redirects"] is False for call in calls)
    assert "demo" not in json.dumps(result.source_metadata)
    assert result.source_metadata["price_vintages"] == "current_only_not_historical_pit"


def test_compound_and_reverse_splits_exclude_split_day(monkeypatch):
    wire(monkeypatch, [[bar("2020-08-28"), bar("2020-08-31")], [
        {"date": "2020-08-31", "split": "4/1"},
        {"date": "2021-01-04", "split": "1/2"}]])
    frame = EodhdBarProvider(api_key="demo").get_bars(
        BarRequest(("AAPL",), "2020-08-28", "2020-09-01")).frame
    assert frame.volume.tolist() == [2000, 8000]


@pytest.mark.parametrize("payload", [[], {"error": "not entitled"}, [bar(volume=None)],
                                     [bar(volume=-1)], [bar(close=float("inf"))],
                                     [bar(), bar()], [bar("not-a-date")]])
def test_bad_bars_fail_instead_of_publishing_partial_data(monkeypatch, payload):
    wire(monkeypatch, [payload, []])
    with pytest.raises(ProviderError):
        EodhdBarProvider(api_key="demo").get_bars(
            BarRequest(("AAPL",), "2020-08-28", "2020-09-01"))


@pytest.mark.parametrize("events", [[{"date": "2020-08-31", "split": "0/1"}],
                                    [{"date": "2020-08-31", "split": 4}],
                                    [{"date": "2020-08-31", "split": "broken"}],
                                    [{"date": "2020-08-31", "split": "4/1"}] * 2])
def test_bad_splits_fail_closed(monkeypatch, events):
    wire(monkeypatch, [[bar()], events])
    with pytest.raises(ProviderError):
        EodhdBarProvider(api_key="demo").get_bars(
            BarRequest(("AAPL",), "2020-08-28", "2020-09-01"))


@pytest.mark.parametrize("status", [301, 401, 403])
def test_http_errors_are_not_retried_and_never_expose_token(monkeypatch, status):
    calls = wire(monkeypatch, [(status, {"message": "secret-key"})])
    with pytest.raises(ProviderError) as error:
        EodhdBarProvider(api_key="secret-key").get_bars(
            BarRequest(("AAPL",), "2025-01-01", "2026-01-01"))
    assert len(calls) == 1
    assert "secret-key" not in str(error.value)


def test_missing_second_symbol_fails_whole_request(monkeypatch):
    wire(monkeypatch, [[bar()], [], []])
    with pytest.raises(ProviderError):
        EodhdBarProvider(api_key="demo").get_bars(
            BarRequest(("AAPL", "AMZN"), "2020-08-28", "2020-09-01"))


@pytest.mark.parametrize("bar_request", [BarRequest(("AAPL",), "bad", "2026-01-01"),
    BarRequest(("AAPL",), "2026-01-01", "2025-01-01"),
    BarRequest(("AAPL",), "2025-01-01", "2026-01-01", timeframe="1h"),
    BarRequest(("AAPL",), "2025-01-01", "2026-01-01", adjustment="all"),
    BarRequest(("AAPL.US",), "2025-01-01", "2026-01-01"),
    BarRequest((), "2025-01-01", "2026-01-01")])
def test_unsupported_request_fails_before_network(monkeypatch, bar_request):
    calls = wire(monkeypatch, [])
    with pytest.raises(ProviderError):
        EodhdBarProvider(api_key="demo").get_bars(bar_request)
    assert not calls


def test_registered_provider_requires_explicit_key():
    with pytest.raises(ValueError, match="ALGUA_EODHD_API_KEY"):
        get_provider("eodhd", Settings(_env_file=None, eodhd_api_key=None))
    assert isinstance(get_provider("eodhd", Settings(_env_file=None, eodhd_api_key="demo")),
                      EodhdBarProvider)


def test_transient_http_is_retried_without_partial_output(monkeypatch):
    calls = wire(monkeypatch, [(429, {}), (503, {}), [bar()], []])
    from algua.data.providers import eodhd
    original = eodhd.call_with_backoff
    monkeypatch.setattr(eodhd, "call_with_backoff", lambda *args, **kwargs:
                        original(*args, **kwargs, sleep=lambda _: None))
    result = EodhdBarProvider(api_key="demo").get_bars(
        BarRequest(("AAPL",), "2020-08-28", "2020-09-01"))
    assert len(calls) == 4
    assert len(result.frame) == 1


def test_timeout_is_bounded_and_token_redacted(monkeypatch):
    calls = wire(monkeypatch, [requests.Timeout("secret-key")] * 3)
    from algua.data.providers import eodhd
    original = eodhd.call_with_backoff
    monkeypatch.setattr(eodhd, "call_with_backoff", lambda *args, **kwargs:
                        original(*args, **kwargs, sleep=lambda _: None))
    with pytest.raises(ProviderError) as error:
        EodhdBarProvider(api_key="secret-key").get_bars(
            BarRequest(("AAPL",), "2020-08-28", "2020-09-01"))
    assert len(calls) == 3
    assert "secret-key" not in str(error.value)


def test_missing_session_is_not_fabricated(monkeypatch):
    wire(monkeypatch, [[bar("2025-01-02"), bar("2025-01-06")], []])
    result = EodhdBarProvider(api_key="demo").get_bars(
        BarRequest(("AAPL",), "2025-01-01", "2025-01-07"))
    assert len(result.frame) == 2
    assert result.source_metadata["coverage"] == "missing_sessions_are_not_filled_or_certified"
