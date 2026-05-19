"""Tests for floating spread and per-trade calendar customization."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from swaps.calendar_us import NY_FED, USCalendar
from swaps.conventions import ACT_360
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.legs.fixed_leg import FixedLeg
from swaps.legs.floating_leg_ois import OISFloatingLeg
from swaps.loaders.calendar_extras import load_extra_holidays
from swaps.market_data import MarketData
from swaps.notional import ConstantNotional
from swaps.pricer import SwapPricer
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import generate_schedule
from swaps.swap import Swap

VAL = date(2026, 3, 31)


def _curve(rate: float = 0.04) -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": rate, "1Y": rate, "5Y": rate, "10Y": rate}, ContinuousACT360())


# --------------------------------------------------------------------- spread
def _build_leg(spread: float, c: ZeroCurve) -> OISFloatingLeg:
    sch = generate_schedule(date(2026, 6, 15), date(2027, 6, 15), "3M", NY_FED)
    return OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=c,
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        spread=spread,
    )


def test_spread_zero_matches_no_spread_baseline():
    c = _curve(0.04)
    a = _build_leg(0.0, c).pv(VAL, c)
    expected = 1_000_000 * (c.df(date(2026, 6, 15)) - c.df(date(2027, 6, 15)))
    assert a == pytest.approx(expected, abs=1e-6)


def test_spread_adds_linearly_to_pv():
    """For each period, the spread contributes N * spread * D/360 * DF(pay) to PV."""
    c = _curve(0.04)
    base = _build_leg(0.0, c)
    spread = 0.0025  # 25 bp
    bumped = _build_leg(spread, c)
    pv_base = base.pv(VAL, c)
    pv_spread = bumped.pv(VAL, c)
    expected_delta = sum(
        1_000_000 * spread * (p.end - p.start).days / 360.0 * c.df(p.payment_date)
        for p in base.schedule
    )
    assert pv_spread - pv_base == pytest.approx(expected_delta, abs=1e-6)


def test_spread_changes_compounded_coupon_display_via_effective_column():
    c = _curve(0.04)
    leg = _build_leg(0.0025, c)
    cf = leg.cashflows(VAL, c)
    last = cf.dropna(subset=["effective_coupon"]).iloc[0]
    assert last["effective_coupon"] == pytest.approx(last["compounded_coupon"] + 0.0025, abs=1e-12)


def test_spread_accrual_inprogress_period():
    """Mid-period valuation: accrued should pick up `spread * partial_days / 360`."""
    sch = generate_schedule(date(2026, 1, 15), date(2028, 1, 15), "1Y", NY_FED)
    # Seed history with a flat 3.5% realized rate
    hist = {}
    d = sch[0].start
    while d < VAL:
        if NY_FED.is_business_day(d):
            hist[d] = 0.035
        d += timedelta(days=1)
    c = _curve(0.04)
    leg_no_spread = OISFloatingLeg(sch, ConstantNotional(1_000_000), c, FixingHistory(hist), ACT_360, NY_FED, spread=0.0)
    leg_spread = OISFloatingLeg(sch, ConstantNotional(1_000_000), c, FixingHistory(hist), ACT_360, NY_FED, spread=0.005)
    partial = (VAL - sch[0].start).days
    expected_delta = 1_000_000 * 0.005 * partial / 360.0
    delta = leg_spread.accrued(VAL) - leg_no_spread.accrued(VAL)
    assert delta == pytest.approx(expected_delta, abs=1e-9)


def test_spread_pricing_flows_through_swap():
    """End-to-end via the pricer: a 25bp spread shifts PV by the expected annuity * spread."""
    sch = generate_schedule(date(2026, 6, 15), date(2031, 6, 15), "1Y", NY_FED)
    c = _curve(0.04)
    fixed = FixedLeg(sch, ConstantNotional(10_000_000), 0.04, ACT_360)
    base_float = OISFloatingLeg(sch, ConstantNotional(10_000_000), c, FixingHistory(), ACT_360, NY_FED)
    spr_float = OISFloatingLeg(sch, ConstantNotional(10_000_000), c, FixingHistory(), ACT_360, NY_FED, spread=0.0025)
    md = MarketData(VAL, c, c, FixingHistory())
    pricer = SwapPricer()
    base = pricer.price(Swap("S0", fixed, base_float, pay_fixed=False), md)
    spr = pricer.price(Swap("S1", fixed, spr_float, pay_fixed=False), md)
    # Receive-fixed pays floating: a spread makes the float leg MORE expensive to the receiver -> dirty drops
    assert spr.dirty < base.dirty
    # And the gap equals the spread annuity term within tight tolerance
    expected = sum(
        10_000_000 * 0.0025 * (p.end - p.start).days / 360.0 * c.df(p.payment_date) for p in sch
    )
    assert base.dirty - spr.dirty == pytest.approx(expected, abs=1e-3)


# ------------------------------------------------------- custom calendar
def test_custom_calendar_extra_holiday_takes_effect():
    """A 'business day' marked as extra holiday should no longer be one."""
    holiday = date(2026, 7, 6)  # a Monday, normally a business day
    assert NY_FED.is_business_day(holiday)
    base_set = set(NY_FED._holidays)
    extended = USCalendar(extra_holidays=base_set | {holiday})
    assert not extended.is_business_day(holiday)


def test_load_extra_holidays_csv(tmp_path):
    p = tmp_path / "extras.csv"
    p.write_text("date\n2026-07-06\n2026-12-31\n", encoding="utf-8")
    dates = load_extra_holidays(p)
    assert dates == [date(2026, 7, 6), date(2026, 12, 31)]


def test_load_extra_holidays_txt(tmp_path):
    p = tmp_path / "extras.txt"
    p.write_text("# trade-desk blackout days\n2026-07-06\n\n2026-12-31  # year-end\n", encoding="utf-8")
    dates = load_extra_holidays(p)
    assert dates == [date(2026, 7, 6), date(2026, 12, 31)]


def test_load_extra_holidays_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_extra_holidays(tmp_path / "missing.csv")


def test_yaml_trade_with_custom_calendar(tmp_path):
    """End-to-end: a YAML trade with `fixing_calendar_extras` produces a calendar that excludes those days."""
    from swaps.loaders.yaml_trades import YamlTradeLoader
    from swaps.trade_builder import build_swap

    trades_dir = tmp_path / "trades"
    trades_dir.mkdir()
    (trades_dir / "TEST.yaml").write_text(
        """
trade_id: TEST_CAL
notional: 1000000
pay_fixed: false
fixed_rate: 0.04
start_date: 2026-06-15
maturity_date: 2027-06-15
fixed_frequency: 3M
fixed_daycount: ACT/360
floating_fixing_calendar_extras:
  - 2026-07-06
""",
        encoding="utf-8",
    )
    td = YamlTradeLoader(trades_dir).load("TEST_CAL")
    assert td.floating_fixing_calendar_extras == [date(2026, 7, 6)]
    swap = build_swap(td, _curve(0.04), FixingHistory())
    # 2026-07-06 is normally a Monday business day; ensure no fixing was generated for it
    rows = swap.floating.fixings_debug(VAL)
    assert date(2026, 7, 6) not in set(rows["fixing_date"])
