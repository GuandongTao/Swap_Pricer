"""End-to-end pricer sanity:
  * clean + accrued == dirty
  * NPV ~ 0 at the par fixed rate
  * DV01 sign is correct (receive-fixed -> positive DV01)
"""

from datetime import date

import pytest

from swaps.calendar_us import NY_FED
from swaps.conventions import ACT_360
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.legs.fixed_leg import FixedLeg
from swaps.legs.floating_leg_ois import OISFloatingLeg
from swaps.market_data import MarketData
from swaps.notional import ConstantNotional
from swaps.pricer import SwapPricer
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import generate_schedule
from swaps.swap import Swap


VAL = date(2026, 3, 31)


def _curve(rate: float = 0.04, name: str = "") -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": rate, "1Y": rate, "5Y": rate, "10Y": rate}, ContinuousACT360(), name=name)


def _build_swap(
    fixed_rate: float,
    pay_fixed: bool = True,
    effective_date: date = date(2026, 6, 15),
    termination_date: date = date(2031, 6, 15),
) -> Swap:
    sch = generate_schedule(
        effective_date=effective_date,
        termination_date=termination_date,
        frequency="1Y",
        calendar=NY_FED,
    )
    fixed = FixedLeg(sch, ConstantNotional(10_000_000), fixed_rate, ACT_360)
    floating = OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(10_000_000),
        projection_curve=_curve(0.04, "FF"),
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
    )
    return Swap(trade_id="TEST", fixed=fixed, floating=floating, pay_fixed=pay_fixed)


def test_clean_plus_accrued_equals_dirty():
    swap = _build_swap(0.04)
    md = MarketData(VAL, _curve(0.04, "SOFR"), _curve(0.04, "FF"), FixingHistory())
    v = SwapPricer().price(swap, md)
    assert v.clean + v.accrued == pytest.approx(v.dirty, abs=1e-8)


def test_npv_zero_at_par_rate():
    """Same curve for proj & disc => par rate from telescoped float / annuity."""
    c = _curve(0.04)
    sch = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    annuity = sum(ACT_360.year_fraction(p.start, p.end) * c.df(p.payment_date) for p in sch)
    par = (c.df(sch[0].start) - c.df(sch[-1].end)) / annuity

    swap = _build_swap(par)
    md = MarketData(VAL, c, c, FixingHistory())
    v = SwapPricer().price(swap, md)
    assert v.dirty == pytest.approx(0.0, abs=1e-4)


def test_clean_plus_accrued_equals_dirty_inprogress_period():
    """Mid-period valuation with history -> clean + accrued must equal dirty."""
    from datetime import timedelta

    sch = generate_schedule(
        effective_date=date(2026, 1, 15),
        termination_date=date(2031, 1, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    # Provide a synthetic history for all past business days in the running period
    hist = {}
    d = sch[0].start
    while d < VAL:
        if NY_FED.is_business_day(d):
            hist[d] = 0.035
        d += timedelta(days=1)
    proj_curve = _curve(0.04, "FF")
    fixed = FixedLeg(sch, ConstantNotional(10_000_000), 0.04, ACT_360)
    floating = OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(10_000_000),
        projection_curve=proj_curve,
        fixings=FixingHistory(hist),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
    )
    swap = Swap(trade_id="MID", fixed=fixed, floating=floating, pay_fixed=True)
    md = MarketData(VAL, _curve(0.04, "SOFR"), proj_curve, FixingHistory(hist))
    v = SwapPricer().price(swap, md)
    assert v.clean + v.accrued == pytest.approx(v.dirty, abs=1e-8)
    assert v.accrued != 0.0  # confirms mid-period


def test_dv01_sign_receive_fixed_is_positive():
    """Receive-fixed swaps gain value when rates fall, lose when rates rise -> DV01 > 0."""
    swap = _build_swap(0.04, pay_fixed=False)
    md = MarketData(VAL, _curve(0.04, "SOFR"), _curve(0.04, "FF"), FixingHistory())
    v = SwapPricer().price(swap, md)
    assert v.dv01 > 0


def test_dv01_sign_pay_fixed_is_negative():
    swap = _build_swap(0.04, pay_fixed=True)
    md = MarketData(VAL, _curve(0.04, "SOFR"), _curve(0.04, "FF"), FixingHistory())
    v = SwapPricer().price(swap, md)
    assert v.dv01 < 0


def test_dv01_magnitude_in_ballpark_for_5y_10m_notional():
    """For a 5Y par swap on $10M, DV01 should be ~ $4-6k."""
    swap = _build_swap(0.04, pay_fixed=False)
    md = MarketData(VAL, _curve(0.04, "SOFR"), _curve(0.04, "FF"), FixingHistory())
    v = SwapPricer().price(swap, md)
    assert 2_000 < abs(v.dv01) < 10_000
