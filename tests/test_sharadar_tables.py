import pandas as pd
import pytest

from algua.data.importers.sharadar_tables import (
    ACTIONS_COLUMNS,
    SEP_COLUMNS,
    TICKERS_COLUMNS,
    SharadarSchemaError,
    read_actions,
    read_sep,
    read_tickers,
)
from tests._sharadar_fixtures import sample_tables, write_csvs


def test_read_sep_normalizes(tmp_path):
    paths = write_csvs(tmp_path)
    sep = read_sep(paths["sep"])
    assert list(sep.columns) == list(SEP_COLUMNS)
    assert str(sep["date"].dt.tz) == "UTC"
    assert (sep["date"].dt.hour == 0).all()
    assert sep["ticker"].str.isupper().all()
    assert sep.equals(sep.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True))


def test_read_sep_round_trips_fixture(tmp_path):
    paths = write_csvs(tmp_path)
    expected, _, _ = sample_tables()
    pd.testing.assert_frame_equal(read_sep(paths["sep"]), expected, check_dtype=False)


def test_read_sep_lowercase_ticker_is_upper_cased(tmp_path):
    p = tmp_path / "sep.csv"
    p.write_text(",".join(SEP_COLUMNS) + "\nzza,2020-01-02,1,1,1,1,10,1,1,2020-01-03\n")
    assert read_sep(p)["ticker"].tolist() == ["ZZA"]


def test_read_sep_missing_column_names_it(tmp_path):
    p = tmp_path / "sep.csv"
    p.write_text("ticker,date,open\nZZA,2020-01-02,1\n")
    with pytest.raises(SharadarSchemaError, match="closeunadj"):
        read_sep(p)


def test_read_sep_duplicate_ticker_date_refused(tmp_path):
    p = tmp_path / "sep.csv"
    row = "ZZA,2020-01-02,1,1,1,1,10,1,1,2020-01-03"
    p.write_text(",".join(SEP_COLUMNS) + f"\n{row}\n{row}\n")
    with pytest.raises(SharadarSchemaError, match="duplicate"):
        read_sep(p)


def test_read_sep_non_numeric_price_refused(tmp_path):
    p = tmp_path / "sep.csv"
    p.write_text(",".join(SEP_COLUMNS) + "\nZZA,2020-01-02,x,1,1,1,10,1,1,2020-01-03\n")
    with pytest.raises(SharadarSchemaError, match="open"):
        read_sep(p)


def test_read_tickers_keeps_sep_table_only(tmp_path):
    paths = write_csvs(tmp_path)
    tickers = read_tickers(paths["tickers"])
    assert list(tickers.columns) == list(TICKERS_COLUMNS)
    assert set(tickers["table"]) == {"SEP"}
    assert len(tickers) == 5
    assert tickers["permaticker"].dtype == "int64"
    flags = tickers.set_index("permaticker")["isdelisted"]
    assert bool(flags[900002]) and not bool(flags[900001])
    assert str(tickers["lastpricedate"].dt.tz) == "UTC"


def test_read_tickers_bad_isdelisted_refused(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(",".join(TICKERS_COLUMNS) + "\nSEP,1,ZZA,A,NYSE,maybe,X,2020-01-02,2020-01-03\n")
    with pytest.raises(SharadarSchemaError, match="isdelisted"):
        read_tickers(p)


def test_read_actions_lowercases_action(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text(",".join(ACTIONS_COLUMNS) + "\n2020-01-06,Split,zza,A,2,,\n")
    actions = read_actions(p)
    assert list(actions.columns) == list(ACTIONS_COLUMNS)
    assert actions["action"].tolist() == ["split"]
    assert actions["ticker"].tolist() == ["ZZA"]
    assert actions["contraticker"].tolist() == [None]
    assert actions["value"].tolist() == [2.0]


def test_read_actions_round_trips_fixture(tmp_path):
    paths = write_csvs(tmp_path)
    _, expected, _ = sample_tables()
    got = read_actions(paths["actions"])
    assert got["action"].tolist() == expected["action"].tolist()
    assert got["contraticker"].tolist() == expected["contraticker"].tolist()
