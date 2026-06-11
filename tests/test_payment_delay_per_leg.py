"""Per-leg payment delay (Bloomberg schema: no shared payment_delay field).

`fixed_payment_delay_bdays` / `floating_payment_delay_bdays` are independent
ints (default 0). Payment date is based on the unadjusted period end.
"""

from datetime import date

import pytest

from swaps.calendar_us import NY_FED
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.loaders.base import TradeDef
from swaps.market_data import MarketData
from swaps.pricer import SwapPricer
from swaps.rate_quoting import ContinuousACT360
from swaps.trade_builder import build_swap


VAL = date(2026, 3, 31)


def _curve(rate: float = 0.04, name: str = "") -> ZeroCurve:
    return ZeroCurve(
        VAL, {"1M": rate, "1Y": rate, "5Y": rate, "10Y": rate},
        ContinuousACT360(), name=name,
    )


def _swap(**ov):
    base = dict(
        trade_id="X", notional=10_000_000, pay_fixed=True, fixed_rate=0.04,
        start_date=date(2026, 6, 15), maturity_date=date(2031, 6, 15),
        fixed_frequency="1Y", fixed_daycount="ACT/360",
    )
    base.update(ov)
    return build_swap(TradeDef(**base), _curve(0.04, "FF"), FixingHistory())


def test_default_zero_delay_both_legs_equal_payment_dates():
    swap = _swap()
    fx, fl = swap.fixed.schedule[-1], swap.floating.schedule[-1]
    assert fx.payment_date == fl.payment_date
    assert swap.meta["fixed_payment_delay_bdays"] == 0
    assert swap.meta["floating_payment_delay_bdays"] == 0


def test_per_leg_delay_diverges_payment_dates():
    swap = _swap(fixed_payment_delay_bdays=0, floating_payment_delay_bdays=5)
    last_uend = swap.fixed.schedule[-1].unadjusted_end  # 2031-06-15
    fx_pay = swap.fixed.schedule[-1].payment_date
    fl_pay = swap.floating.schedule[-1].payment_date
    # Fixed: 0 BD delay -> pay = roll(unadjusted end). Floating: +5 BD from adjusted end.
    assert fl_pay == NY_FED.add_business_days(
        NY_FED.roll(last_uend, "ModifiedFollowing"), 5
    )
    assert fl_pay > fx_pay
    assert swap.meta["fixed_payment_delay_bdays"] == 0
    assert swap.meta["floating_payment_delay_bdays"] == 5


def test_only_fixed_delay_set():
    swap = _swap(fixed_payment_delay_bdays=2)
    assert swap.meta["fixed_payment_delay_bdays"] == 2
    assert swap.meta["floating_payment_delay_bdays"] == 0
    assert swap.fixed.schedule[-1].payment_date > swap.floating.schedule[-1].payment_date


def test_invariants_hold_with_split_delays():
    swap = _swap(fixed_payment_delay_bdays=0, floating_payment_delay_bdays=5)
    md = MarketData(VAL, _curve(0.045, "SOFR"), _curve(0.04, "FF"), FixingHistory())
    v = SwapPricer().price(swap, md)
    assert v.clean + v.accrued == pytest.approx(v.dirty, abs=1e-8)
