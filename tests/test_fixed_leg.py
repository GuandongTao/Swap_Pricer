"""FixedLeg sanity checks against closed-form annuity PV."""

from datetime import date

import pytest

from swaps.calendar_us import NY_FED
from swaps.conventions import ACT_360
from swaps.curve import ZeroCurve
from swaps.legs.fixed_leg import FixedLeg
from swaps.notional import ConstantNotional
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import generate_schedule


VAL = date(2026, 3, 31)


def _flat_curve(rate: float = 0.04) -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": rate, "1Y": rate, "5Y": rate, "10Y": rate}, ContinuousACT360())


def test_fixed_leg_pv_matches_closed_form_annuity():
    schedule = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    leg = FixedLeg(schedule, ConstantNotional(1_000_000), 0.05, ACT_360)
    curve = _flat_curve(0.04)
    pv = leg.pv(VAL, curve)

    # Closed-form: N * R * sum(dcf_i * DF(pay_i))
    expected = sum(
        1_000_000 * 0.05 * ACT_360.year_fraction(p.start, p.end) * curve.df(p.payment_date)
        for p in schedule
    )
    assert pv == pytest.approx(expected, abs=1e-8)


def test_fixed_leg_accrued_debug_matches_accrued():
    schedule = generate_schedule(
        effective_date=date(2026, 1, 15),
        termination_date=date(2031, 1, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    leg = FixedLeg(schedule, ConstantNotional(1_000_000), 0.05, ACT_360)
    dbg = leg.accrued_debug(VAL)
    assert dbg["leg"] == "fixed" and dbg["accruing"] is True
    assert dbg["accrued"] == pytest.approx(leg.accrued(VAL), abs=1e-9)
    assert dbg["coupon_rate"] == 0.05
    # Before the leg starts -> not accruing, zero.
    early = leg.accrued_debug(date(2025, 1, 1))
    assert early["accruing"] is False and early["accrued"] == 0.0


def test_fixed_leg_accrued_proportional_within_period():
    schedule = generate_schedule(
        effective_date=date(2026, 1, 15),
        termination_date=date(2031, 1, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    leg = FixedLeg(schedule, ConstantNotional(1_000_000), 0.05, ACT_360)
    # First period starts ~ Jan 15 2026; val_date Mar 31 sits inside it
    acc = leg.accrued(VAL)
    p0 = schedule[0]
    expected = 1_000_000 * 0.05 * ACT_360.year_fraction(p0.start, VAL)
    assert acc == pytest.approx(expected, abs=1e-9)


def test_fixed_leg_accrued_zero_before_start():
    schedule = generate_schedule(
        effective_date=date(2027, 6, 15),
        termination_date=date(2032, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    leg = FixedLeg(schedule, ConstantNotional(1_000_000), 0.05, ACT_360)
    assert leg.accrued(VAL) == 0.0


def test_fixed_leg_payment_in_past_excluded_from_pv():
    schedule = generate_schedule(
        effective_date=date(2024, 6, 15),
        termination_date=date(2029, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    leg = FixedLeg(schedule, ConstantNotional(1_000_000), 0.05, ACT_360)
    curve = _flat_curve(0.04)
    cf = leg.cashflows(VAL, curve)
    past = cf[cf["payment_date"] < VAL]
    future = cf[cf["payment_date"] >= VAL]
    assert (past["discounted_cashflow"] == 0).all()
    assert leg.pv(VAL, curve) == pytest.approx(future["discounted_cashflow"].sum(), abs=1e-9)
