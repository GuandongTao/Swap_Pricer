from datetime import date

from swaps.calendar_us import NY_FED


def test_weekend_not_business_day():
    assert not NY_FED.is_business_day(date(2026, 5, 9))   # Sat
    assert not NY_FED.is_business_day(date(2026, 5, 10))  # Sun


def test_standard_weekday_business():
    assert NY_FED.is_business_day(date(2026, 5, 12))  # Tue


def test_new_year_holiday():
    assert not NY_FED.is_business_day(date(2026, 1, 1))  # Thursday


def test_new_year_sunday_observed_monday():
    # 2023-01-01 is Sunday -> Fed closed Monday 2023-01-02
    assert not NY_FED.is_business_day(date(2023, 1, 2))


def test_saturday_holiday_not_observed_friday():
    # Christmas 2027 is Saturday -> Fed open Friday 2027-12-24
    assert NY_FED.is_business_day(date(2027, 12, 24))


def test_juneteenth_post_2021():
    assert not NY_FED.is_business_day(date(2022, 6, 20))  # 19th is Sun -> Mon
    assert NY_FED.is_business_day(date(2020, 6, 19))      # pre-2021: business day


def test_thanksgiving_2026():
    # 4th Thursday of Nov 2026 -> Nov 26
    assert not NY_FED.is_business_day(date(2026, 11, 26))


def test_add_business_days_skips_weekends():
    # Fri 2026-05-08 + 1 BD -> Mon 2026-05-11
    assert NY_FED.add_business_days(date(2026, 5, 8), 1) == date(2026, 5, 11)


def test_add_business_days_skips_holiday():
    # Wed 2025-12-24 + 1 BD -> Fri 2025-12-26 (skip Christmas Thu)
    assert NY_FED.add_business_days(date(2025, 12, 24), 1) == date(2025, 12, 26)


def test_add_business_days_negative():
    # Mon 2026-05-11 - 1 BD -> Fri 2026-05-08
    assert NY_FED.add_business_days(date(2026, 5, 11), -1) == date(2026, 5, 8)


def test_roll_modified_following_keeps_month():
    # Sat 2026-05-30 + ModifiedFollowing -> Fri 2026-05-29 (next BD Mon 2026-06-01 crosses month)
    assert NY_FED.roll(date(2026, 5, 30), "ModifiedFollowing") == date(2026, 5, 29)


def test_roll_following():
    assert NY_FED.roll(date(2026, 5, 9), "Following") == date(2026, 5, 11)
