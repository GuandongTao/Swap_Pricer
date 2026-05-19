"""Different payment frequencies on the fixed vs floating leg.

`floating_frequency` blank => same as `fixed_frequency` (standard OIS, legs
share periods). Set explicitly for cross-frequency structures.
"""

from datetime import date

import pytest

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


def _td(**overrides) -> TradeDef:
    base = dict(
        trade_id="X",
        notional=10_000_000,
        pay_fixed=True,
        fixed_rate=0.04,
        start_date=date(2026, 6, 15),
        maturity_date=date(2031, 6, 15),
        fixed_frequency="1Y",
        fixed_daycount="ACT/360",
    )
    base.update(overrides)
    return TradeDef(**base)


def test_blank_floating_frequency_shares_fixed_schedule():
    td = _td()  # floating_frequency defaults to ""
    swap = build_swap(td, _curve(0.04, "FF"), FixingHistory())
    # Identical period boundaries (standard OIS: legs share the schedule).
    f, fl = swap.fixed.schedule, swap.floating.schedule
    assert [(p.start, p.end, p.payment_date) for p in f] == [
        (p.start, p.end, p.payment_date) for p in fl
    ]
    assert swap.meta["floating_frequency"] == "1Y"  # effective freq recorded


def test_cross_frequency_builds_denser_floating_schedule():
    td = _td(floating_frequency="3M")  # 1Y fixed vs 3M float
    swap = build_swap(td, _curve(0.04, "FF"), FixingHistory())
    assert swap.floating.schedule is not swap.fixed.schedule
    # ~5Y: 5 annual fixed periods, ~20 quarterly floating periods.
    assert len(swap.fixed.schedule) == 5
    assert len(swap.floating.schedule) == pytest.approx(20, abs=1)
    assert swap.meta["floating_frequency"] == "3M"


def test_cross_frequency_pricing_invariants_hold():
    td = _td(floating_frequency="3M")
    swap = build_swap(td, _curve(0.038, "FF"), FixingHistory())
    md = MarketData(VAL, _curve(0.045, "SOFR"), _curve(0.038, "FF"), FixingHistory())
    pricer = SwapPricer()
    v = pricer.price(swap, md)

    # Core invariant survives mismatched leg frequencies.
    assert v.clean + v.accrued == pytest.approx(v.dirty, abs=1e-8)

    # Par-rate decomposition still holds (fixed leg unchanged, annuity from it).
    fixed_cf = swap.fixed.cashflows(md.val_date, md.discount_curve)
    coupons = fixed_cf[fixed_cf["flow_type"] == "coupon"]
    annuity = float(
        (coupons["day_count_fraction"] * coupons["notional"] * coupons["df_to_payment"])
        .fillna(0.0)
        .sum()
    )
    expected_clean = -annuity * (td.fixed_rate - v.par_rate)  # pay-fixed sign
    assert v.clean == pytest.approx(expected_clean, rel=1e-6)
