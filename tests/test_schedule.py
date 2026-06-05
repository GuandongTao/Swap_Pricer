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


def test_payment_delay_anchors_off_adjusted_end_when_period_end_is_weekend():
    """T+N payment delay must count from the ADJUSTED period end, not the
    unadjusted (raw calendar) end.

    Nov 1 2026 is a Sunday.  The unadjusted monthly period boundary falls on
    that Sunday; ModifiedFollowing rolls it to Monday Nov 2.  With a 2-bday
    delay the payment should be Wednesday Nov 4 (T+2 from Mon Nov 2), not
    Tuesday Nov 3 (which would be T+2 from the unadjusted Sunday Nov 1).
    """
    periods = generate_schedule(
        effective_date=date(2026, 10, 1),   # Thursday
        termination_date=date(2027, 1, 1),
        frequency="1M",
        calendar=NY_FED,
        payment_delay_bdays=2,
    )
    # Find the period whose UNADJUSTED end is Sunday Nov 1 2026
    nov_period = next(p for p in periods if p.unadjusted_end == date(2026, 11, 1))
    assert nov_period.end == date(2026, 11, 2), "MF should roll Sunday Nov 1 to Monday Nov 2"
    # Payment = T+2 from the ADJUSTED end (Mon Nov 2), not unadjusted (Sun Nov 1)
    assert nov_period.payment_date == date(2026, 11, 4), (
        "T+2 from adjusted Mon Nov 2 should be Wed Nov 4, not Tue Nov 3"
    )
    # General invariant: payment_date == adjusted_end + N bdays for every period
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


def test_anchor_tiny_back_stub_collides_on_holiday_is_merged():
    # Reproduces trade 19652363: anchor on 15th, maturity on 16th -> 1-day
    # back stub at 2027-02-15 -> 2027-02-16, but 2027-02-15 is Presidents Day
    # so it rolls onto 2027-02-16 (= maturity) under MFollowing. The 0-day
    # period must be merged into the previous one.
    warnings: list[str] = []
    periods = generate_schedule(
        effective_date=date(2024, 2, 16),
        termination_date=date(2027, 2, 16),
        frequency="3M",
        calendar=NY_FED,
        bus_day_adj="ModifiedFollowing",
        first_period_accrual_end_date=date(2024, 5, 15),
        schedule_warnings=warnings,
    )
    # No zero-length periods survive
    assert all((p.end - p.start).days > 0 for p in periods)
    # Last period extends all the way to the (adjusted) maturity
    assert periods[-1].end == date(2027, 2, 16)
    # Exactly one merge happened and was reported
    assert len(warnings) == 1
    assert "merged" in warnings[0].lower()


def test_effective_and_maturity_collapse_to_same_day_raises():
    # Pathological: effective Saturday rolls forward, maturity Sunday rolls
    # backward to the same Monday under different conventions -> no schedule
    # possible. This is contrived but the guard exists to surface it cleanly.
    with pytest.raises(ValueError, match="no periods can be generated"):
        generate_schedule(
            effective_date=date(2026, 5, 30),    # Sat
            termination_date=date(2026, 5, 31),  # Sun, before any Monday
            frequency="3M",
            calendar=NY_FED,
            eff_date_adj="Following",
            bus_day_adj="Following",
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
