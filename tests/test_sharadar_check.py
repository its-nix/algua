import pandas as pd

from algua.data.sharadar_check import (
    BANKRUPTCY_ACTIONS,
    check_adjusted,
    check_identity,
    check_raw_units,
    check_revisions,
    check_sample_coverage,
    check_terminal,
    run_sharadar_check,
)
from tests._sharadar_fixtures import sample_tables


def _by_name(report, name):
    return next(c for c in report.checks if c.name == name)


def test_clean_sample_passes():
    report = run_sharadar_check(*sample_tables())
    assert report.passed, [(c.name, c.status, c.findings) for c in report.checks]
    assert [c.name for c in report.checks] == [
        "sample_coverage", "identity", "raw_units", "adjusted_close", "terminal"]


def test_sample_coverage_fails_without_bankruptcy():
    sep, actions, tickers = sample_tables()
    actions = actions[actions["action"] != "bankruptcyliquidation"]
    report = run_sharadar_check(sep, actions, tickers)
    assert not report.passed
    cov = _by_name(report, "sample_coverage")
    assert cov.status == "fail" and {"missing": "bankruptcy"} in cov.findings


def test_sample_coverage_needs_acquisition_with_contraticker():
    sep, actions, tickers = sample_tables()
    actions = actions.copy()
    actions.loc[actions["action"] == "acquisitionby", "contraticker"] = None
    res = check_sample_coverage(sep, actions, tickers)
    assert res.status == "fail" and {"missing": "acquisition"} in res.findings


def test_sample_coverage_needs_reused_ticker():
    sep, actions, tickers = sample_tables()
    tickers = tickers[tickers["permaticker"] != 900005]
    res = check_sample_coverage(sep, actions, tickers)
    assert res.status == "fail" and {"missing": "reused_ticker"} in res.findings


def test_identity_passes_on_clean_sample():
    sep, _, tickers = sample_tables()
    res = check_identity(sep, tickers)
    assert res.status == "pass"
    assert res.counts["reused_tickers"] == 1 and res.counts["unassigned_rows"] == 0


def test_identity_fails_on_overlapping_reused_ticker():
    sep, _, tickers = sample_tables()
    tickers = tickers.copy()
    tickers.loc[tickers["permaticker"] == 900005, "firstpricedate"] = pd.Timestamp(
        "2020-01-03", tz="UTC")
    res = check_identity(sep, tickers)
    assert res.status == "fail" and res.counts["overlaps"] == 1


def test_identity_fails_on_row_outside_every_range():
    sep, _, tickers = sample_tables()
    tickers = tickers.copy()
    tickers.loc[tickers["permaticker"] == 900002, "lastpricedate"] = pd.Timestamp(
        "2020-01-06", tz="UTC")
    res = check_identity(sep, tickers)
    assert res.status == "fail" and res.counts["unassigned_rows"] == 1


def test_raw_units_passes_on_clean_sample():
    sep, actions, _ = sample_tables()
    res = check_raw_units(sep, actions)
    assert res.status == "pass" and res.counts["mismatched_rows"] == 0


def test_raw_units_reports_inverted_ratio():
    sep, actions, tickers = sample_tables()
    actions = actions.copy()
    actions.loc[actions["action"] == "split", "value"] = 0.5
    res = check_raw_units(sep, actions)
    assert res.status == "fail"
    assert any(f.get("hint") == "inverted_split_ratio" for f in res.findings)


def test_raw_units_fails_when_split_missing_without_hint():
    sep, actions, _ = sample_tables()
    actions = actions[actions["action"] != "split"]
    res = check_raw_units(sep, actions)
    assert res.status == "fail" and res.counts["mismatched_rows"] == 2
    assert not any(f.get("hint") == "inverted_split_ratio" for f in res.findings)


def test_adjusted_close_is_info_even_when_inconsistent():
    sep, actions, tickers = sample_tables()
    sep = sep.copy()
    first = sep.index[sep["ticker"] == "ZZSP"][0]
    sep.loc[first, "closeadj"] = sep.loc[first, "closeadj"] * 1.1
    report = run_sharadar_check(sep, actions, tickers)
    adj = _by_name(report, "adjusted_close")
    assert adj.status == "info" and adj.counts["inconsistent"] >= 1
    assert report.passed


def test_adjusted_close_consistent_on_clean_sample():
    sep, actions, _ = sample_tables()
    res = check_adjusted(sep, actions)
    assert res.counts["inconsistent"] == 0 and res.counts["consistent"] == 4


def test_terminal_fails_when_delisted_has_no_action():
    sep, actions, tickers = sample_tables()
    actions = actions[~actions["action"].isin(BANKRUPTCY_ACTIONS)]
    res = check_terminal(actions, tickers)
    assert res.status == "fail" and res.counts["no_action"] == 1


def test_terminal_ignores_action_outside_window():
    _, actions, tickers = sample_tables()
    actions = actions.copy()
    actions.loc[actions["action"] == "bankruptcyliquidation", "date"] = pd.Timestamp(
        "2020-03-01", tz="UTC")
    res = check_terminal(actions, tickers)
    assert res.status == "fail" and res.counts["no_action"] == 1


def test_terminal_classifies_zero_recovery_and_acquisition():
    _, actions, tickers = sample_tables()
    res = check_terminal(actions, tickers)
    assert res.status == "pass"
    assert res.counts == {"zero_recovery": 1, "acquisition_resolved": 1,
                          "acquisition_unresolved": 0, "other_delisting": 1, "no_action": 0}


def test_terminal_acquisition_without_value_is_unresolved():
    _, actions, tickers = sample_tables()
    actions = actions.copy()
    actions.loc[actions["action"] == "acquisitionby", "value"] = float("nan")
    res = check_terminal(actions, tickers)
    assert res.status == "pass" and res.counts["acquisition_unresolved"] == 1


def test_revisions_counts_changed_old_rows():
    sep_prev, _, _ = sample_tables()
    sep_now = sep_prev.copy()
    zzsp = sep_now.index[sep_now["ticker"] == "ZZSP"]
    sep_now.loc[zzsp[0], "close"] += 0.01   # 2020-01-02: older than the cutoff -> counted
    sep_now.loc[zzsp[-2], "close"] += 0.01  # 2020-01-09: recent -> not counted
    res = check_revisions(sep_now, sep_prev, older_than_days=5)
    assert res.status == "info"
    assert res.counts["changed_rows"] == 1 and res.counts["missing_rows"] == 0


def test_revisions_counts_rows_missing_from_new_pull():
    sep_prev, _, _ = sample_tables()
    sep_now = sep_prev.drop(index=sep_prev.index[0]).reset_index(drop=True)
    res = check_revisions(sep_now, sep_prev, older_than_days=5)
    assert res.counts["missing_rows"] == 1


def test_run_includes_revisions_when_previous_given():
    sep, actions, tickers = sample_tables()
    report = run_sharadar_check(sep, actions, tickers, sep_prev=sep)
    assert report.checks[-1].name == "revisions"


def test_summary_has_no_findings():
    s = run_sharadar_check(*sample_tables()).summary()
    assert s["passed"] is True
    assert all(set(c) == {"name", "status", "counts"} for c in s["checks"])
