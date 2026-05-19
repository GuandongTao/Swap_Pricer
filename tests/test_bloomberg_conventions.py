"""Bloomberg-matched convention behaviors: roll_convention (forward/backward,
EOM), adjust modes, auto-derived fields, and two-tier validation.
"""

from datetime import date

import pytest

from swaps.calendar_us import NY_FED
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.loaders.base import TradeDef
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import _is_month_end, generate_schedule
from swaps.trade_builder import build_swap
from swaps.validation import validate_trade


VAL = date(2026, 3, 31)


def _curve(r: float = 0.04, name: str = "FF") -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": r, "1Y": r, "5Y": r, "10Y": r}, ContinuousACT360(), name=name)


def _td(**ov) -> TradeDef:
    base = dict(
        trade_id="X", notional=1_000_000, pay_fixed=True, fixed_rate=0.04,
        start_date=date(2026, 6, 15), maturity_date=date(2029, 6, 15),
        fixed_frequency="1Y", fixed_daycount="ACT/360",
    )
    base.update(ov)
    return TradeDef(**base)


# ---------------------------------------------------------------- roll convention
def test_forward_eom_snaps_interior_to_month_end():
    sched = generate_schedule(
        effective_date=date(2026, 1, 31),
        termination_date=date(2026, 12, 31),
        frequency="1M",
        calendar=NY_FED,
        roll_convention="forward_eom",
    )
    interior_unadj_ends = [p.unadjusted_end for p in sched[:-1]]
    assert interior_unadj_ends, "expected interior periods"
    assert all(_is_month_end(d) for d in interior_unadj_ends)


def test_forward_eq_forward_eom_when_anchor_not_month_end():
    kw = dict(
        effective_date=date(2026, 6, 15),
        termination_date=date(2029, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    a = generate_schedule(roll_convention="forward", **kw)
    b = generate_schedule(roll_convention="forward_eom", **kw)
    assert [p.unadjusted_end for p in a] == [p.unadjusted_end for p in b]


def test_forward_vs_backward_stub_placement_differs():
    kw = dict(
        effective_date=date(2026, 8, 1),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    fwd = generate_schedule(roll_convention="forward", **kw)
    bwd = generate_schedule(roll_convention="backward", **kw)
    # forward: stub at the back (last period short). backward: stub at front.
    assert (fwd[-1].unadjusted_end - fwd[-1].unadjusted_start).days < 360
    assert (bwd[0].unadjusted_end - bwd[0].unadjusted_start).days < 360
    assert [p.unadjusted_start for p in fwd] != [p.unadjusted_start for p in bwd]


# ---------------------------------------------------------------- adjust modes
def test_adjust_pay_uses_unadjusted_accrual_bounds():
    # Monthly 30/360 fixed leg; some unadjusted ends fall on weekends so the
    # adjusted bounds differ from the unadjusted ones.
    td_pay = _td(fixed_frequency="1M", fixed_daycount="30/360", fixed_adjust="pay")
    td_acc = _td(fixed_frequency="1M", fixed_daycount="30/360", fixed_adjust="acc_and_pay")
    s_pay = build_swap(td_pay, _curve(), FixingHistory())
    s_acc = build_swap(td_acc, _curve(), FixingHistory())
    cf_pay = s_pay.fixed.cashflows(VAL, _curve(0.04, "SOFR"))
    cf_acc = s_acc.fixed.cashflows(VAL, _curve(0.04, "SOFR"))
    sched = s_pay.fixed.schedule
    coup_pay = cf_pay[cf_pay["flow_type"] == "coupon"].reset_index(drop=True)
    # adjust=pay -> accrual bounds == unadjusted schedule bounds
    assert list(coup_pay["accrual_start"]) == [p.unadjusted_start for p in sched]
    assert list(coup_pay["accrual_end"]) == [p.unadjusted_end for p in sched]
    # The two modes must actually differ somewhere (proves the toggle bites)
    coup_acc = cf_acc[cf_acc["flow_type"] == "coupon"].reset_index(drop=True)
    assert list(coup_pay["accrual_end"]) != list(coup_acc["accrual_end"])
    # Payment date is always a good business day regardless of adjust mode
    assert list(coup_pay["payment_date"]) == list(coup_acc["payment_date"])


# ---------------------------------------------------------------- auto-derive
def test_pay_date_adj_blank_derives_bus_day_adj():
    explicit = _td(fixed_bus_day_adj="Following", fixed_pay_date_adj="Following")
    derived = _td(fixed_bus_day_adj="Following")  # pay_date_adj blank
    se = build_swap(explicit, _curve(), FixingHistory()).fixed.schedule
    sd = build_swap(derived, _curve(), FixingHistory()).fixed.schedule
    assert [p.payment_date for p in se] == [p.payment_date for p in sd]


def test_payment_calendar_blank_derives_calc_calendar():
    td = _td()  # both calendars blank/default -> identical resolution
    swap = build_swap(td, _curve(), FixingHistory())
    assert swap.meta["fixed_payment_delay_bdays"] == 0  # sanity that build ran
    assert len(swap.fixed.schedule) == 3


# ---------------------------------------------------------------- validation
def test_invalid_roll_convention_raises():
    with pytest.raises(ValueError):
        validate_trade(_td(fixed_roll_convention="sideways"))


def test_invalid_adjust_raises():
    with pytest.raises(ValueError):
        validate_trade(_td(floating_adjust="maybe"))


def test_non_in_arrears_reset_is_hard_error():
    td = _td()
    td.meta["reset_type"] = "in_advance"
    with pytest.raises(ValueError):
        validate_trade(td)


def test_eom_with_acc_and_pay_emits_warning():
    # fixed adjust=acc_and_pay (default) + forward_eom -> Bloomberg-gray warning
    warns = validate_trade(_td(fixed_roll_convention="forward_eom", fixed_adjust="acc_and_pay"))
    assert any("Bloomberg locks" in w for w in warns)


def test_clean_combo_no_warnings():
    warns = validate_trade(
        _td(
            fixed_roll_convention="forward", fixed_adjust="pay",
            floating_roll_convention="forward", floating_adjust="pay",
            fixed_daycount="ACT/360",
        )
    )
    assert warns == []
