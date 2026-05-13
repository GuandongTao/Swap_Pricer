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


def test_short_front_stub():
    # Effective deliberately off-grid -> a short front stub should appear
    periods = generate_schedule(
        effective_date=date(2026, 8, 1),
        termination_date=date(2031, 6, 15),
        frequency="1Y",
        calendar=NY_FED,
        stub="ShortFront",
    )
    # First period shorter than subsequent ones
    first_days = (periods[0].end - periods[0].start).days
    second_days = (periods[1].end - periods[1].start).days
    assert first_days < second_days
