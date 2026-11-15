from algua.portfolio.equity_curve import change_today, pnl_curve


def tick(day, equity, lane="paper"):
    return {"tick_ts": f"{day}T20:00:00+00:00", "equity": equity, "lane": lane}


def test_allocation_entry_is_not_profit():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-02", 1010)],
         "b": [tick("2026-11-02", 500)]}
    pts = pnl_curve(s)
    assert [p["pnl"] for p in pts] == [0.0, 10.0]
    assert pts[-1]["equity"] == 1510.0


def test_loss_shows_negative():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-02", 980)]}
    assert pnl_curve(s)[-1]["pnl"] == -20.0


def test_empty_fleet():
    assert pnl_curve({}) == []


def test_last_tick_per_session_wins_and_lanes_are_separate():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-02", 1005), tick("2026-11-02", 1020),
               tick("2026-11-01", 50, "live"), tick("2026-11-02", 40, "live")]}
    pts = pnl_curve(s)
    assert [p["pnl"] for p in pts] == [0.0, 10.0]
    assert pts[-1]["equity"] == 1060.0


def test_gap_session_carries_equity_forward():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-03", 1030)],
         "b": [tick("2026-11-01", 100), tick("2026-11-02", 110), tick("2026-11-03", 110)]}
    pts = pnl_curve(s)
    assert [p["session"] for p in pts] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert [p["pnl"] for p in pts] == [0.0, 10.0, 40.0]
    assert pts[1]["equity"] == 1110.0


def test_lane_move_does_not_double_count_equity():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-02", 1010),
               tick("2026-11-03", 1010, "live")]}
    pts = pnl_curve(s, active_lanes={"a": {"live"}})
    assert [p["equity"] for p in pts] == [1000.0, 1010.0, 1010.0]
    assert [p["pnl"] for p in pts] == [0.0, 10.0, 10.0]


def test_retired_strategy_drops_out_after_last_tick():
    s = {"a": [tick("2026-11-01", 1000), tick("2026-11-02", 1010)],
         "b": [tick("2026-11-01", 500), tick("2026-11-02", 500), tick("2026-11-03", 510)]}
    pts = pnl_curve(s, active_lanes={"a": set(), "b": {"paper"}})
    assert [p["equity"] for p in pts] == [1500.0, 1510.0, 510.0]
    assert pts[-1]["pnl"] == 20.0


def test_change_today_only_when_last_session_is_today():
    pts = [{"session": "2026-11-01", "pnl": 0.0, "equity": 1.0},
           {"session": "2026-11-02", "pnl": 7.0, "equity": 1.0}]
    assert change_today(pts, "2026-11-02") == 7.0
    assert change_today(pts, "2026-11-03") == 0.0
    assert change_today(pts[:1], "2026-11-01") == 0.0
    assert change_today([], "2026-11-01") == 0.0


def test_same_tenant_inflow_and_outflow_are_not_profit():
    rows = [
        {**tick("2026-11-01", 1000), "allocated_capital": 1000},
        {**tick("2026-11-02", 1500), "allocated_capital": 1500},
        {**tick("2026-11-03", 700), "allocated_capital": 700},
    ]
    points = pnl_curve({"a": rows})
    assert [p["pnl"] for p in points] == [0.0, 0.0, 0.0]
    assert [p["equity"] for p in points] == [1000.0, 1500.0, 700.0]


def test_resize_preserves_real_gains_losses_and_last_tick_in_session():
    rows = [
        {**tick("2026-11-01", 1010), "allocated_capital": 1000},
        {**tick("2026-11-02", 1515), "allocated_capital": 1500},
        {**tick("2026-11-02", 1520), "allocated_capital": 1500},
        {**tick("2026-11-03", 690), "allocated_capital": 700},
    ]
    points = pnl_curve({"a": rows})
    assert [p["pnl"] for p in points] == [0.0, 10.0, -20.0]
    assert points[-1]["equity"] == 690.0
    # A filtered or newest-N slice still starts from its first retained observation.
    assert [p["pnl"] for p in pnl_curve({"a": rows[1:]})] == [0.0, -30.0]
