import hashlib
import json
from datetime import UTC, datetime

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


@pytest.mark.parametrize("metrics", [
    ("symbol",), ("metric",), ("value",), ("knowable_at",), ("fiscal_period_end",),
    ("source",), ("ticker",), ("reportperiod",), ("eps", "eps"), (), ("EPS",), (None,),
])
def test_invalid_fundamental_metrics_refused_before_fetch(monkeypatch, metrics):
    calls = wire(monkeypatch, [])
    with pytest.raises(ProviderError, match="metric names"):
        fetch_fundamentals(SharadarClient(api_key="x"), symbols=("AAPL",),
                          start="2025-02-01", end="2025-03-01", metrics=metrics)
    assert calls == []


@pytest.mark.parametrize("lag", [2, 32, 3.5, "3", True])
def test_invalid_fundamental_lag_refused_before_fetch(monkeypatch, lag):
    calls = wire(monkeypatch, [])
    with pytest.raises(ProviderError, match="filing lag"):
        fetch_fundamentals(SharadarClient(api_key="x"), symbols=("AAPL",),
                          start="2025-02-01", end="2025-03-01", metrics=("eps",),
                          filing_lag_days=lag)
    assert calls == []


@pytest.mark.parametrize("lag", [3, 31])
def test_fundamental_window_and_filing_query_bounds(monkeypatch, lag):
    first = pd.Timestamp("2025-02-04")
    last = pd.Timestamp("2025-02-06")
    rows = []
    for available in pd.date_range(first - pd.Timedelta(days=1), last):
        row = financial((available - pd.Timedelta(days=lag)).date().isoformat())
        rows.append(row)
    calls = wire(monkeypatch, [pd.DataFrame(rows)])
    frame, _ = fetch_fundamentals(
        SharadarClient(api_key="x"), symbols=("AAPL",), start="2025-02-04",
        end="2025-02-06", metrics=("eps",), filing_lag_days=lag)
    assert frame.knowable_at.tolist() == [
        pd.Timestamp("2025-02-04", tz="UTC"), pd.Timestamp("2025-02-05", tz="UTC")]
    params = calls[0][1]["params"]
    assert params["from"] == (first - pd.Timedelta(days=lag)).date().isoformat()
    assert params["to"] == (last - pd.Timedelta(days=lag + 1)).date().isoformat()


def test_fundamental_deferrals_missing_values_and_receipts(monkeypatch):
    from algua.data.providers import sharadar_fundamentals

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025, 2, 4, 12, tzinfo=UTC)

    monkeypatch.setattr(sharadar_fundamentals, "datetime", Clock)
    rows = [financial(day) for day in ("2025-02-01", "2025-02-02", "2025-02-03")]
    rows[0]["eps"] = ""
    raw = pd.DataFrame(rows)
    wire(monkeypatch, [raw])
    frame, meta = fetch_fundamentals(
        SharadarClient(api_key="x"), symbols=("AAPL",), start="2025-02-04",
        end="2025-02-06", metrics=("eps", "revenue"))
    assert len(frame) == 2
    assert frame.loc[frame.metric.eq("eps"), "value"].isna().all()
    assert frame.loc[frame.metric.eq("revenue"), "value"].tolist() == [1000.]
    assert frame.source.unique().tolist() == [
        "sharadar:ARQ:filing_date_plus_3_days_ASSUMED"]
    receipt = json.loads(meta["response_receipts"])["AAPL"]
    assert receipt["deferred_filings"] == 1
    assert receipt["missing_values"] == {"eps": 1, "revenue": 0}
    assert receipt["page_sha256"] == [
        hashlib.sha256(raw.to_csv(index=False).encode()).hexdigest()]
    assert meta["pit_status"] == "unverified_vendor_history"
    assert meta["units"] == "vendor_native_units;no_currency_conversion;consult_metric_dictionary"
    assert meta["retrieved_at"] == "2025-02-04T12:00:00+00:00"


@pytest.mark.parametrize("value", [True, False, "not-numeric", float("inf")])
def test_invalid_fundamental_values_refused(monkeypatch, value):
    row = financial()
    row["eps"] = value
    wire(monkeypatch, [pd.DataFrame([row])])
    with pytest.raises(ProviderError, match="invalid ARQ"):
        fetch_fundamentals(SharadarClient(api_key="x"), symbols=("AAPL",),
                          start="2025-02-01", end="2025-03-01", metrics=("eps",))


@pytest.mark.parametrize("day", ["2025-02-01", "2025-03-01"])
@pytest.mark.parametrize("value", [2., 3., ""])
def test_duplicate_fundamental_keys_refused(monkeypatch, value, day):
    second = financial(day)
    second["eps"] = value
    wire(monkeypatch, [pd.DataFrame([financial("2025-02-02"), financial(day), second])])
    with pytest.raises(ProviderError, match="invalid ARQ"):
        fetch_fundamentals(SharadarClient(api_key="x"), symbols=("AAPL",),
                          start="2025-02-01", end="2025-03-01", metrics=("eps",))


def test_duplicate_fundamental_columns_refused(monkeypatch):
    raw = pd.DataFrame([financial()])
    raw = pd.concat([raw, raw[["eps"]]], axis=1)
    monkeypatch.setattr(SharadarClient, "fetch", lambda *a, **kw: (raw, {}))
    with pytest.raises(ProviderError, match="invalid ARQ"):
        fetch_fundamentals(SharadarClient(api_key="x"), symbols=("AAPL",),
                          start="2025-02-01", end="2025-03-01", metrics=("eps",))


def test_distinct_filings_and_report_periods_are_preserved(monkeypatch):
    amendment = financial("2025-02-02")
    amendment["eps"] = 3.
    other_period = financial()
    other_period["reportperiod"] = "2024-09-30"
    wire(monkeypatch, [pd.DataFrame([financial(), amendment, other_period])])
    frame, _ = fetch_fundamentals(
        SharadarClient(api_key="x"), symbols=("AAPL",), start="2025-02-01",
        end="2025-03-01", metrics=("eps",))
    assert len(frame) == 3
    quarter = frame.loc[frame.fiscal_period_end.eq(datetime(2024, 12, 31).date())]
    assert quarter.value.tolist() == [2., 3.]
    assert quarter.knowable_at.tolist() == [
        pd.Timestamp("2025-02-04", tz="UTC"), pd.Timestamp("2025-02-05", tz="UTC")]


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
