"""OISFloatingLeg sanity:
  * with same projection==discount curve and no payment delay, PV telescopes to N*(DF(start)-DF(end)).
  * par-swap test: fixed rate that makes NPV=0 matches the curve-implied swap rate.
  * history split: with known history, period coupon reflects the realized product.
  * lockout: last N rates are copied forward from the (N+1)-th-to-last fixing.
"""

from datetime import date, timedelta

import pytest

from swaps.calendar_us import NY_FED
from swaps.conventions import ACT_360
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.legs.fixed_leg import FixedLeg
from swaps.legs.floating_leg_ois import OISFloatingLeg
from swaps.notional import ConstantNotional
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import generate_schedule


VAL = date(2026, 3, 31)


def _curve(rate: float = 0.04) -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": rate, "1Y": rate, "5Y": rate, "10Y": rate}, ContinuousACT360())


def _make_float_leg(curve, fixings=None, payment_delay_bdays=0, lockout_bdays=0):
    sch = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
        payment_delay_bdays=payment_delay_bdays,
    )
    return OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=curve,
        fixings=fixings or FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        payment_delay_bdays=payment_delay_bdays,
        lockout_bdays=lockout_bdays,
    )


def test_floating_leg_accrued_debug_matches_accrued():
    c = _curve(0.04)
    leg = _make_float_leg(c)  # first period starts 2026-06-15; VAL is before it
    dbg = leg.accrued_debug(VAL)
    assert dbg["leg"] == "floating" and dbg["accruing"] is False
    assert dbg["accrued"] == 0.0
    assert dbg["accrued"] == pytest.approx(leg.accrued(VAL), abs=1e-12)


def _flat_history(rate, start, end):
    days = {}
    d = start
    while d <= end:
        days[d] = rate
        d += timedelta(days=1)
    return FixingHistory(days)


def _early_curve(rate=0.04):
    # Anchored before the delayed-leg test dates so DFs are evaluable in Feb.
    return ZeroCurve(date(2025, 12, 1), {"1M": rate, "3M": rate, "1Y": rate, "5Y": rate},
                     ContinuousACT360())


def _delayed_leg(curve, fixings, delay):
    sch = generate_schedule(
        effective_date=date(2026, 1, 1),
        termination_date=date(2026, 4, 1),
        frequency="1M",
        calendar=NY_FED,
        payment_delay_bdays=delay,
    )
    return OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=curve,
        fixings=fixings,
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        payment_delay_bdays=delay,
    )


def test_accrued_full_period_when_accrual_ended_but_unpaid():
    """On val_date = acc_e with a payment delay, accrued EXCEEDS the period
    coupon under the inclusive convention: p0 includes acc_e itself (+1 day)
    and p1 starts contributing too (its first day = val_date = acc_e)."""
    c = _early_curve(0.04)
    fixings = _flat_history(0.04, date(2025, 12, 1), date(2026, 5, 1))
    leg = _delayed_leg(c, fixings, delay=3)
    p0 = leg.schedule[0]
    acc_e, pay0 = p0.end, p0.payment_date
    assert pay0 > acc_e  # payment delay puts pay date after accrual end
    accrued = leg.accrued(acc_e)
    cf = leg.cashflows(acc_e, c)
    coupon = cf[(cf["flow_type"] == "coupon") & (cf["period_end"] == acc_e)]
    period_cf = coupon["period_cashflow"].dropna().iloc[0]
    # Inclusive convention: accrued > period coupon on the accrual-end date.
    assert accrued > period_cf
    assert accrued > 0.0


def test_accrued_sums_completed_unpaid_plus_next_started():
    """Between a period's accrual end and its (delayed) pay date, the next
    period has already started accruing -> both contribute."""
    c = _early_curve(0.04)
    fixings = _flat_history(0.04, date(2025, 12, 1), date(2026, 5, 1))
    leg = _delayed_leg(c, fixings, delay=3)
    p0, p1 = leg.schedule[0], leg.schedule[1]
    acc_e0, pay0 = p0.end, p0.payment_date
    val = acc_e0 + timedelta(days=1)
    assert acc_e0 <= val < pay0          # still in the unpaid window for p0
    assert p1.start <= val < p1.end      # p1 has started accruing
    d0 = leg._period_accrued_detail(p0, val)
    d1 = leg._period_accrued_detail(p1, val)
    assert d0 is not None and d1 is not None and d1["accrued"] > 0.0
    assert leg.accrued(val) == pytest.approx(d0["accrued"] + d1["accrued"], abs=1e-9)


def test_accrued_zero_after_payment_date():
    c = _early_curve(0.04)
    fixings = _flat_history(0.04, date(2025, 12, 1), date(2026, 5, 1))
    leg = _delayed_leg(c, fixings, delay=3)
    p0 = leg.schedule[0]
    # A day on/after p0's pay date but before p1 end: p0 is paid (excluded),
    # only p1 should accrue -> p0 contributes nothing.
    d0 = leg._period_accrued_detail(p0, p0.payment_date)
    assert d0 is None


def test_telescoping_when_projection_equals_discount_flat():
    """With proj == disc, no delay, no history, no lockout, PV telescopes."""
    c = _curve(0.04)
    leg = _make_float_leg(c)
    pv = leg.pv(VAL, c)
    expected = 1_000_000 * (c.df(leg.schedule[0].start) - c.df(leg.schedule[-1].end))
    assert pv == pytest.approx(expected, abs=1e-6)


def test_telescoping_holds_for_non_flat_curve():
    pillars = {"1M": 0.030, "6M": 0.035, "1Y": 0.040, "5Y": 0.045, "10Y": 0.043}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    leg = _make_float_leg(c)
    pv = leg.pv(VAL, c)
    expected = 1_000_000 * (c.df(leg.schedule[0].start) - c.df(leg.schedule[-1].end))
    assert pv == pytest.approx(expected, rel=1e-6, abs=1e-3)


def test_par_swap_rate_matches_curve_implied():
    """The fixed rate making NPV=0 equals N*(DF(s)-DF(e)) / sum(DCF * DF(pay))."""
    c = _curve(0.04)
    sch = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    float_leg = OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=c,
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
    )
    pv_float = float_leg.pv(VAL, c)
    annuity = sum(ACT_360.year_fraction(p.start, p.end) * c.df(p.payment_date) for p in sch)
    par_rate = pv_float / (1_000_000 * annuity)

    fixed_leg = FixedLeg(sch, ConstantNotional(1_000_000), par_rate, ACT_360)
    pv_fixed = fixed_leg.pv(VAL, c)
    assert pv_fixed == pytest.approx(pv_float, abs=1e-6)


def test_history_overrides_curve_for_past_fixings():
    """When val_date is inside the first period, historical fixings drive the realized part."""
    c = _curve(0.04)
    sch = generate_schedule(
        effective_date=date(2026, 1, 15),
        termination_date=date(2031, 1, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    # Inject a history with a much higher realized rate for the past portion
    p0 = sch[0]
    hist = {}
    d = p0.start
    while d < VAL:
        if NY_FED.is_business_day(d):
            hist[d] = 0.10  # very high realized
        d += timedelta(days=1)
    leg = OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=c,
        fixings=FixingHistory(hist),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
    )
    pb = leg.period_breakdown(VAL)
    # Historical product should reflect ~10% compounding for ~75 days
    p0_row = pb.iloc[0]
    assert p0_row["historical_product"] > 1.015  # at least ~1.5% from ~75 days of 10%
    # Compounded coupon for that period should be visibly above 4%
    assert p0_row["compounded_coupon"] > 0.05


def test_round_pct5_half_up():
    from swaps.legs.floating_leg_ois import _round_pct5
    # 5 dp in percent == 7 dp on the decimal rate; ties round half-up.
    assert _round_pct5(0.05123455) == 0.0512346
    assert _round_pct5(0.05123454) == 0.0512345
    assert _round_pct5(0.0512345) == 0.0512345


def test_period_cashflows_compounded_coupon_rounded_to_pct5():
    """FloatingCF_byPeriod col L is display-rounded to 5 dp in percent."""
    c = _curve(0.0412345678)  # curve rate with digits past the 7th dp
    leg = _make_float_leg(c)
    pcf = leg.period_cashflows(VAL, c)
    coupons = pcf.dropna(subset=["compounded_coupon"])["compounded_coupon"]
    assert len(coupons) > 0
    for v in coupons:
        # Quantized to 1e-7: scaling by 1e7 yields an integer.
        assert round(v * 1e7) == pytest.approx(v * 1e7, abs=1e-6)
    # effective_coupon stays on the raw (unrounded) rate (spread == 0 here),
    # so it sits within one rounding step of the displayed compounded coupon
    # but is not itself quantized to 7 dp.
    last = pcf.dropna(subset=["effective_coupon"]).iloc[0]
    assert abs(last["effective_coupon"] - last["compounded_coupon"]) < 1e-7
    assert round(last["effective_coupon"] * 1e7) != pytest.approx(
        last["effective_coupon"] * 1e7, abs=1e-9
    )


def test_lockout_freezes_last_n_rates():
    """With lockout=2, the last 2 fixing rates equal the 3rd-to-last fixing rate."""
    # Quarterly schedule so each period has more fixings to play with
    sch = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2027, 6, 15),
        frequency="3M",
        calendar=NY_FED,
    )
    # Curve with non-trivial slope so forwards differ between fixings
    pillars = {"1M": 0.030, "3M": 0.035, "6M": 0.040, "9M": 0.045, "1Y": 0.050, "2Y": 0.05}
    c = ZeroCurve(VAL, pillars, ContinuousACT360())
    leg = OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=c,
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        lockout_bdays=2,
    )
    rows = leg.fixings_debug(VAL)
    # Pick the last period
    last_period_start = sch[-1].start
    period_rows = rows[rows["period_start"] == last_period_start].reset_index(drop=True)
    n = len(period_rows)
    assert n >= 4
    last_normal_rate = period_rows.loc[n - 3, "reset_rate"]
    assert period_rows.loc[n - 2, "reset_rate"] == last_normal_rate
    assert period_rows.loc[n - 1, "reset_rate"] == last_normal_rate
    assert period_rows.loc[n - 1, "rate_source"] == "lockout"


def test_payment_delay_shifts_payment_date_and_df():
    c = _curve(0.04)
    sch = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2027, 6, 15),
        frequency="3M",
        calendar=NY_FED,
        payment_delay_bdays=2,
    )
    leg = OISFloatingLeg(
        schedule=sch,
        notional=ConstantNotional(1_000_000),
        projection_curve=c,
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        payment_delay_bdays=2,
    )
    cf = leg.cashflows(VAL, c)
    last_rows = cf.dropna(subset=["period_cashflow"])
    for _, row in last_rows.iterrows():
        assert row["payment_date"] == NY_FED.add_business_days(row["period_end"], 2)
