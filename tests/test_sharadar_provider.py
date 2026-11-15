import pandas as pd
import pytest
import requests

from algua.config.settings import Settings
from algua.data.contracts import BarRequest
from algua.data.providers import get_provider
from algua.data.providers.errors import ProviderError
from algua.data.providers.sharadar import SharadarBarProvider
from algua.data.providers.sharadar_client import SharadarClient
from algua.data.providers.sharadar_fundamentals import fetch_fundamentals
from algua.data.schema import to_bar_schema


def price(day="2025-01-02", **kw):
    return dict(ticker="AAPL", date=day, open=25., high=26., low=24., close=25.,
                closeunadj=100., closeadj=23., volume=4000., lastupdated=day, **kw)


def financial(day="2025-02-01", dimension="ARQ"):
    return dict(ticker="AAPL", date=day, dimension=dimension, reportperiod="2024-12-31",
                eps=2., revenue=1000.)


def wire(monkeypatch, pages):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        item = pages.pop(0)
        if isinstance(item, Exception):
            raise item
        response = requests.Response()
        if isinstance(item, int):
            response.status_code = item
            response._content = b"private-token"
        else:
            response.status_code = 200
            response._content = item.to_csv(index=False).encode()
        response._content_consumed = True
        return response
    monkeypatch.setattr("algua.data.providers.sharadar_client.requests.get", get)
    return calls


def test_raw_units_and_half_open_window(monkeypatch):
    wire(monkeypatch, [pd.DataFrame([price(),price("2025-01-03")]), pd.DataFrame([
        dict(ticker="AAPL",date="2025-01-06",action="split",value=4.)])])
    result = SharadarBarProvider(api_key="test-api-key").get_bars(
        BarRequest(("AAPL",), "2025-01-02", "2025-01-03"))
    out = to_bar_schema(result.frame, timeframe="1d")
    assert len(out) == 1
    assert out.iloc[0].open == 100
    assert out.iloc[0].volume == 1000
    assert out.iloc[0].adj_close == 23
    assert result.source_metadata["pit_status"] == "unverified_vendor_history"


def test_pagination_does_not_truncate(monkeypatch):
    calls = wire(monkeypatch, [pd.DataFrame([price(),price("2025-01-03")]),
                              pd.DataFrame([price("2025-01-06")])])
    client = SharadarClient(api_key="test-api-key", page_size=2)
    frame, meta = client.fetch("stocks", "AAPL", "2025-01-01", "2025-01-10")
    assert len(frame) == 3
    assert [c[1]["params"]["skip"] for c in calls] == [0,2]
    assert len(meta["page_sha256"]) == 2
    assert all(not c[1]["allow_redirects"] for c in calls)


@pytest.mark.parametrize("status", [301,401,403])
def test_http_refusal_redacts_key(monkeypatch, status):
    calls = wire(monkeypatch, [status])
    with pytest.raises(ProviderError) as e:
        SharadarClient(api_key="private-token").fetch("stocks", "AAPL", "2025-01-01",
                                                    "2025-02-01")
    assert "private-token" not in str(e.value)
    assert len(calls) == 1


def test_repeated_page_refused(monkeypatch):
    frame = pd.DataFrame([price(),price("2025-01-03")])
    wire(monkeypatch, [frame, frame])
    with pytest.raises(ProviderError, match="page"):
        SharadarClient(api_key="x", page_size=2).fetch("stocks", "AAPL", "2025-01-01",
                                                     "2025-02-01")


@pytest.mark.parametrize("column,value", [("close",0),("volume",-1),("closeadj",float("inf")),
                                         ("open",None),("ticker","WRONG")])
def test_invalid_prices_fail(monkeypatch, column, value):
    row=price()
    row[column]=value
    wire(monkeypatch,[pd.DataFrame([row])])
    with pytest.raises(ProviderError):
        SharadarBarProvider(api_key="x").get_bars(
            BarRequest(("AAPL",),"2025-01-01","2025-02-01"))


def test_fundamentals_use_report_period_and_explicit_availability_lag(monkeypatch):
    calls = wire(monkeypatch,[pd.DataFrame([financial()])])
    frame,meta=fetch_fundamentals(SharadarClient(api_key="x"),symbols=("AAPL",),
        start="2025-02-01",end="2025-03-01",metrics=("eps","revenue"),filing_lag_days=3)
    assert len(frame)==2
    assert frame.knowable_at.min()==pd.Timestamp("2025-02-04",tz="UTC")
    assert str(frame.fiscal_period_end.iloc[0])=="2024-12-31"
    assert calls[0][1]["params"]["dimension"]=="ARQ"
    assert meta["availability_policy"]=="filing_date_plus_3_calendar_days_assumed"
    assert meta["pit_status"]=="unverified_vendor_history"


def test_restated_fundamentals_not_silently_accepted(monkeypatch):
    wire(monkeypatch,[pd.DataFrame([financial(dimension="MRQ")])])
    with pytest.raises(ProviderError):
        fetch_fundamentals(SharadarClient(api_key="x"),symbols=("AAPL",),
            start="2025-01-01",end="2025-03-01",metrics=("eps",),filing_lag_days=3)


def test_missing_metric_not_silently_zero(monkeypatch):
    wire(monkeypatch,[pd.DataFrame([financial()])])
    with pytest.raises(ProviderError):
        fetch_fundamentals(SharadarClient(api_key="x"),symbols=("AAPL",),
            start="2025-01-01",end="2025-03-01",metrics=("not_a_metric",),filing_lag_days=3)


def test_provider_requires_explicit_key():
    with pytest.raises(ValueError,match="ALGUA_SHARADAR_API_KEY"):
        get_provider("sharadar",Settings(_env_file=None,sharadar_api_key=None))
    assert isinstance(get_provider("sharadar",Settings(_env_file=None,sharadar_api_key="x")),
                      SharadarBarProvider)


def test_spinoff_refused_instead_of_changing_frozen_adjustment_contract(monkeypatch):
    wire(monkeypatch,[pd.DataFrame([price()]),pd.DataFrame([
        dict(ticker="AAPL",date="2025-01-06",action="spinofffrom",value=1.)])])
    with pytest.raises(ProviderError,match="spinoff"):
        SharadarBarProvider(api_key="x").get_bars(
            BarRequest(("AAPL",),"2025-01-01","2025-02-01"))


def test_page_limit_refuses_incomplete_download(monkeypatch):
    wire(monkeypatch,[pd.DataFrame([price(),price("2025-01-03")])])
    with pytest.raises(ProviderError,match="bound"):
        SharadarClient(api_key="x",page_size=2,max_pages=1).fetch(
            "stocks","AAPL","2025-01-01","2025-02-01")


def test_timeout_retries_bounded_and_redacts_token(monkeypatch):
    from algua.data.providers import sharadar_client
    original=sharadar_client.call_with_backoff
    monkeypatch.setattr(sharadar_client,"call_with_backoff",lambda *a,**kw:
                        original(*a,**kw,sleep=lambda _:None))
    calls=wire(monkeypatch,[requests.Timeout("private-token")]*3)
    with pytest.raises(ProviderError) as e:
        SharadarClient(api_key="private-token").fetch("stocks","AAPL","2025-01-01",
                                                    "2025-02-01")
    assert len(calls)==3
    assert "private-token" not in str(e.value)


def test_oversized_stream_stops_before_reading_every_chunk(monkeypatch):
    from contextlib import contextmanager
    chunks_read = []
    class LargeResponse:
        status_code = 200
        def iter_content(self, chunk_size):
            for i in range(200):
                chunks_read.append(i)
                yield b"x" * 65536
    closed = []
    @contextmanager
    def get(*args, **kwargs):
        assert kwargs["stream"] is True
        try:
            yield LargeResponse()
        finally:
            closed.append(True)
    monkeypatch.setattr("algua.data.providers.sharadar_client.requests.get", get)
    with pytest.raises(ProviderError, match="size bound"):
        SharadarClient(api_key="x").fetch("stocks", "AAPL", "2025-01-01", "2025-02-01")
    assert len(chunks_read) == 129
    assert closed == [True]
