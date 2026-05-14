"""Per-leg roll-convention and fixing-lookback plumbing."""

from datetime import date

import pytest

from swaps.calendar_us import NY_FED
from swaps.conventions import ACT_360
from swaps.curve import ZeroCurve
from swaps.fixings import FixingHistory
from swaps.legs.floating_leg_ois import OISFloatingLeg
from swaps.notional import ConstantNotional
from swaps.rate_quoting import ContinuousACT360
from swaps.schedule import generate_schedule


VAL = date(2026, 3, 31)


def _curve(r: float = 0.04) -> ZeroCurve:
    return ZeroCurve(VAL, {"1M": r, "1Y": r, "5Y": r}, ContinuousACT360())


# -------------------------------------------------------------- calendar.roll
def test_calendar_roll_nearest_picks_closer_side():
    # 2026-07-04 is Saturday (Independence Day observed on Friday in practice,
    # but algorithmically NY_FED keeps Friday open).  Saturday -> Nearest BD
    # should pick Friday (1 day back) over Monday (2 days fwd).
    sat = date(2026, 7, 4)
    assert NY_FED.roll(sat, "Nearest") == date(2026, 7, 3)


def test_calendar_roll_noadjust_alias():
    sat = date(2026, 7, 4)
    assert NY_FED.roll(sat, "NoAdjust") == sat
    assert NY_FED.roll(sat, "None") == sat


# -------------------------------------------------------------- schedule rolls
def test_generate_schedule_separate_pay_roll():
    # Force an end date that lands on a NY_FED holiday: 2026-07-03 is Friday
    # (Fed open).  Try 2026-12-25 (Christmas) -- a Friday holiday.
    sched = generate_schedule(
        effective_date=date(2026, 11, 25),
        termination_date=date(2026, 12, 25),  # Friday, Christmas (NY_FED holiday)
        frequency="1M",
        calendar=NY_FED,
        accrual_roll="Preceding",
        pay_roll="Following",
        payment_delay_bdays=0,
    )
    last = sched[-1]
    # Accrual end should roll backward; pay date follows-rolled forward from same date
    assert last.end == NY_FED.roll(date(2026, 12, 25), "Preceding")


# -------------------------------------------------------------- fixing lag
def _make_float_leg(lag: int, roll: str = "Preceding") -> OISFloatingLeg:
    sched = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2026, 9, 15),
        frequency="1M",
        calendar=NY_FED,
    )
    return OISFloatingLeg(
        schedule=sched,
        notional=ConstantNotional(1_000_000),
        projection_curve=_curve(),
        fixings=FixingHistory(),
        daycount=ACT_360,
        fixing_calendar=NY_FED,
        fixing_lag_bdays=lag,
        fixing_roll=roll,
    )


def test_fixing_lag_zero_means_fixing_equals_accrual_day():
    leg = _make_float_leg(lag=0)
    df = leg.cashflows(VAL, _curve())
    coupons = df[df["flow_type"] == "coupon"]
    # accrual_start == fixing_date when no lag
    assert (coupons["accrual_start"] == coupons["fixing_date"]).all()


def test_fixing_lag_two_bdays_shifts_fixing_back():
    leg = _make_float_leg(lag=2)
    df = leg.cashflows(VAL, _curve())
    coupons = df[df["flow_type"] == "coupon"]
    # fixing_date is 2 NY_FED business days before accrual_start
    for _, row in coupons.iterrows():
        expected = NY_FED.add_business_days(row["accrual_start"], -2)
        assert row["fixing_date"] == expected


def test_fixing_lag_with_invalid_roll_raises():
    with pytest.raises(ValueError):
        _make_float_leg(lag=1, roll="Bogus")


# -------------------------------------------------------------- TradeDef plumbing
def test_yaml_loader_passes_through_roll_fields(tmp_path):
    from swaps.loaders.yaml_trades import YamlTradeLoader

    (tmp_path / "X.yaml").write_text(
        """
trade_id: ROLL_TEST
notional: 1000000
pay_fixed: true
fixed_rate: 0.04
start_date: 2026-06-15
maturity_date: 2031-06-15
fixed_frequency: 1Y
fixed_daycount: ACT/360
fixed_spot_roll: Following
fixed_accrual_roll: ModifiedFollowing
fixed_pay_roll: Following
floating_accrual_roll: ModifiedFollowing
floating_pay_roll: Following
floating_fixing_roll: Preceding
floating_fixing_lag_bdays: 2
""",
        encoding="utf-8",
    )
    td = YamlTradeLoader(tmp_path).load("ROLL_TEST")
    assert td.fixed_spot_roll == "Following"
    assert td.fixed_accrual_roll == "ModifiedFollowing"
    assert td.floating_fixing_roll == "Preceding"
    assert td.floating_fixing_lag_bdays == 2
