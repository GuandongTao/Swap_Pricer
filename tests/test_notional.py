from datetime import date

from swaps.notional import ConstantNotional, StepNotional


def test_constant_notional():
    n = ConstantNotional(1_000_000)
    assert n(date(2026, 1, 1)) == 1_000_000
    assert n(date(2030, 5, 5)) == 1_000_000


def test_step_notional():
    n = StepNotional(
        [
            (date(2026, 1, 1), 10_000_000),
            (date(2027, 1, 1), 7_000_000),
            (date(2028, 1, 1), 4_000_000),
        ]
    )
    assert n(date(2025, 12, 31)) == 10_000_000   # before first step -> first bucket
    assert n(date(2026, 6, 1)) == 10_000_000
    assert n(date(2027, 1, 1)) == 7_000_000
    assert n(date(2027, 6, 1)) == 7_000_000
    assert n(date(2028, 1, 1)) == 4_000_000
    assert n(date(2030, 1, 1)) == 4_000_000
