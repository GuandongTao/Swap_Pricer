"""Separate payment delay for the fixed vs floating leg.

`fixed_payment_delay_bdays` / `floating_payment_delay_bdays` each fall back to
the shared `payment_delay_bdays` when left None, so existing trades are
unchanged.
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


def _td(**ov) -> TradeDef:
    base = dict(
        trade_id="X", notional=10_000_000, pay_fixed=True, fixed_rate=0.04,
        start_date=date(2026, 6, 15), maturity_date=date(2031, 6, 15),
        fixed_frequency="1Y", fixed_daycount="ACT/360",
    )
    base.update(ov)
    return build_swap(TradeDef(**base), _curve(0.04, "FF"), FixingHistory())


def test_shared_delay_applies_to_both_legs_by_default():
    swap = _td(payment_delay_bdays=2)
    fx, fl = swap.fixed.schedule[-1], swap.floating.schedule[-1]
    assert fx.payment_date == fl.payment_date
    assert swap.meta["fixed_payment_delay_bdays"] == 2
    assert swap.meta["floating_payment_delay_bdays"] == 2


def test_per_leg_override_diverges_payment_dates():
    swap = _td(
        payment_delay_bdays=2,
        fixed_payment_delay_bdays=0,
        floating_payment_delay_bdays=5,
    )
    last_end = swap.fixed.schedule[-1].end
    fx_pay = swap.fixed.schedule[-1].payment_date
    fl_pay = swap.floating.schedule[-1].payment_date
    # Fixed: no delay -> pay == rolled accrual end. Floating: +5 BD beyond fixed.
    assert fx_pay == last_end
    assert fl_pay == NY_FED.add_business_days(fx_pay, 5)
    assert fl_pay > fx_pay
    assert swap.meta["fixed_payment_delay_bdays"] == 0
    assert swap.meta["floating_payment_delay_bdays"] == 5


def test_only_floating_override_set_fixed_uses_shared():
    swap = _td(payment_delay_bdays=2, floating_payment_delay_bdays=0)
    # Fixed falls back to shared 2; floating explicitly 0 -> fixed pays later.
    assert swap.meta["fixed_payment_delay_bdays"] == 2
    assert swap.meta["floating_payment_delay_bdays"] == 0
    assert swap.fixed.schedule[-1].payment_date > swap.floating.schedule[-1].payment_date


def test_invariants_hold_with_split_delays():
    swap = _td(
        payment_delay_bdays=2,
        fixed_payment_delay_bdays=0,
        floating_payment_delay_bdays=5,
    )
    md = MarketData(VAL, _curve(0.045, "SOFR"), _curve(0.04, "FF"), FixingHistory())
    v = SwapPricer().price(swap, md)
    assert v.clean + v.accrued == pytest.approx(v.dirty, abs=1e-8)
