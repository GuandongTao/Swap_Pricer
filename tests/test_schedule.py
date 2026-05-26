from datetime import date

import pytest

from swaps.calendar_us import NY_FED
from swaps.schedule import generate_schedule, parse_frequency


def test_parse_frequency():
    assert parse_frequency("1Y").years == 1
    assert parse_frequency("6M").months == 6
    assert parse_frequency("3M").months == 3
    assert parse_frequency("1W").weeks == 1
    assert parse_frequency("1D").days == 1
    with pytest.raises(ValueError):
        parse_frequency("x")


def test_annual_5y_schedule_count():
    periods = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    assert len(periods) == 5


def test_quarterly_1y_schedule_count():
    periods = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2027, 6, 15),
        frequency="3M",
        calendar=NY_FED,
    )
    assert len(periods) == 4


def test_schedule_contiguous_and_bounded():
    periods = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
    )
    # Each period's end equals the next period's start
    for prev, nxt in zip(periods, periods[1:]):
        assert prev.end == nxt.start
    # Honors the boundaries (rolled to business days)
    assert periods[0].start == NY_FED.roll(date(2026, 6, 15), "ModifiedFollowing")
    assert periods[-1].end == NY_FED.roll(date(2031, 6, 15), "ModifiedFollowing")


def test_payment_delay_applied():
    periods = generate_schedule(
        effective_date=date(2026, 6, 15),
        termination_date=date(2027, 6, 15),
        frequency="3M",
        calendar=NY_FED,
        payment_delay_bdays=2,
    )
    for p in periods:
        assert p.payment_date == NY_FED.add_business_days(p.end, 2)


# --- BBG First Payment Date override (first_period_accrual_end_date) --------
def test_first_period_accrual_end_date_anchors_forward_with_front_stub():
    # Effective 2026-04-02, maturity 2031-04-02, semi-annual.
    # Anchor 2026-04-25 -> period 1 is short front stub 2026-04-02 -> 2026-04-25;
    # later unadjusted ends step by 6M from the anchor (25th of Apr/Oct).
    periods = generate_schedule(
        effective_date=date(2026, 4, 2),
        termination_date=date(2031, 4, 2),
        frequency="6M",
        calendar=NY_FED,
        roll_convention="forward",
        first_period_accrual_end_date=date(2026, 4, 25),
    )
    assert periods[0].unadjusted_start == date(2026, 4, 2)
    assert periods[0].unadjusted_end == date(2026, 4, 25)
    assert periods[1].unadjusted_start == date(2026, 4, 25)
    assert periods[1].unadjusted_end == date(2026, 10, 25)
    interior_days = {p.unadjusted_end.day for p in periods[1:-1]}
    assert interior_days == {25}
    assert periods[-1].unadjusted_end == date(2031, 4, 2)


def test_anchor_overrides_eom_strict_calendar_day():
    # Anchor on 4/30 with quarterly frequency and roll_convention="forward_eom":
    # subsequent unadjusted ends are 7/30, 10/30, 1/30, 4/30, ... NEVER 2/28
    # or 2/29 (EOM is overridden by the anchor per design).
    periods = generate_schedule(
        effective_date=date(2026, 1, 15),
        termination_date=date(2028, 1, 15),
        frequency="3M",
        calendar=NY_FED,
        roll_convention="forward_eom",
        first_period_accrual_end_date=date(2026, 4, 30),
    )
    interior_ends = [p.unadjusted_end for p in periods[:-1]]
    expected = [
        date(2026, 4, 30),
        date(2026, 7, 30),
        date(2026, 10, 30),
        date(2027, 1, 30),
        date(2027, 4, 30),
        date(2027, 7, 30),
        date(2027, 10, 30),
    ]
    assert interior_ends == expected
    assert periods[-1].unadjusted_end == date(2028, 1, 15)


def test_anchor_outside_trade_range_raises():
    with pytest.raises(ValueError, match="strictly between"):
        generate_schedule(
            effective_date=date(2026, 4, 2),
            termination_date=date(2031, 4, 2),
            frequency="6M",
            calendar=NY_FED,
            first_period_accrual_end_date=date(2031, 5, 1),
        )


def test_short_front_stub():
    # Backward generation (anchor = maturity) -> a short front stub appears
    periods = generate_schedule(
        effective_date=date(2026, 8, 1),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
        roll_convention="backward",
    )
    # First period shorter than subsequent ones
    first_days = (periods[0].end - periods[0].start).days
    second_days = (periods[1].end - periods[1].start).days
    assert first_days < second_days
