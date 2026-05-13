from datetime import date

from swaps.conventions import (
    ACT_360,
    ACT_365F,
    ACT_ACT_ISDA,
    THIRTY_360,
    THIRTY_E_360,
    get_daycount,
)


def test_act_360_basic():
    assert ACT_360.year_fraction(date(2026, 1, 1), date(2027, 1, 1)) == 365 / 360


def test_act_365f_basic():
    assert ACT_365F.year_fraction(date(2026, 1, 1), date(2027, 1, 1)) == 365 / 365


def test_thirty_360_full_year():
    assert THIRTY_360.year_fraction(date(2026, 1, 1), date(2027, 1, 1)) == 1.0


def test_thirty_360_end_of_month():
    # d1=31 -> 30; d2=31 with d1=30 -> 30
    assert THIRTY_360.year_fraction(date(2026, 1, 31), date(2026, 7, 31)) == 0.5


def test_thirty_e_360_full_year():
    assert THIRTY_E_360.year_fraction(date(2026, 1, 1), date(2027, 1, 1)) == 1.0


def test_act_act_isda_non_leap():
    yf = ACT_ACT_ISDA.year_fraction(date(2026, 1, 1), date(2027, 1, 1))
    assert abs(yf - 1.0) < 1e-12


def test_act_act_isda_leap_crossing():
    # 2024 is leap; period straddles year-end
    yf = ACT_ACT_ISDA.year_fraction(date(2024, 7, 1), date(2025, 7, 1))
    # half of 2024 (leap) + half of 2025 (non-leap)
    expected = (date(2025, 1, 1) - date(2024, 7, 1)).days / 366.0 + (date(2025, 7, 1) - date(2025, 1, 1)).days / 365.0
    assert abs(yf - expected) < 1e-12


def test_registry_lookup():
    assert get_daycount("ACT/360") is ACT_360
    assert get_daycount("act / 360") is ACT_360  # case + whitespace tolerant
