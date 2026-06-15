"""NY Fed business-day calendar.

Holiday rules (Fed observance):
  - Saturday holidays are NOT observed on the preceding Friday (Fed is open Friday).
  - Sunday holidays are observed on the following Monday.

Holidays computed algorithmically; refresh range as needed.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable, Literal

BusinessDayConvention = Literal[
    "Following", "ModifiedFollowing", "Preceding", "ModifiedPreceding", "Nearest", "None", "NoAdjust"
]


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth occurrence of given weekday (Mon=0..Sun=6) in (year, month)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Last occurrence of given weekday in (year, month)."""
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _shift_if_sunday(d: date) -> date:
    """Return the following Monday if ``d`` is a Sunday, otherwise ``d`` unchanged."""
    return d + timedelta(days=1) if d.weekday() == 6 else d


def _fed_holidays_for_year(y: int) -> list[date]:
    """Return all NY Fed holidays for year ``y`` as a list of calendar dates."""
    h: list[date] = [
        _shift_if_sunday(date(y, 1, 1)),                    # New Year's
        _nth_weekday(y, 1, 0, 3),                           # MLK (3rd Mon Jan)
        _nth_weekday(y, 2, 0, 3),                           # Washington's Birthday
        _last_weekday(y, 5, 0),                             # Memorial Day
        _shift_if_sunday(date(y, 7, 4)),                    # Independence Day
        _nth_weekday(y, 9, 0, 1),                           # Labor Day
        _nth_weekday(y, 10, 0, 2),                          # Columbus Day
        _shift_if_sunday(date(y, 11, 11)),                  # Veterans Day
        _nth_weekday(y, 11, 3, 4),                          # Thanksgiving (4th Thu Nov)
        _shift_if_sunday(date(y, 12, 25)),                  # Christmas
    ]
    if y >= 2021:
        h.append(_shift_if_sunday(date(y, 6, 19)))          # Juneteenth (federal from 2021)
    return h


@lru_cache(maxsize=1)
def _holiday_set(start_year: int = 1990, end_year: int = 2100) -> frozenset[date]:
    """Build and cache the complete NY Fed holiday set from ``start_year`` to ``end_year``."""
    s: set[date] = set()
    for y in range(start_year, end_year + 1):
        s.update(_fed_holidays_for_year(y))
    return frozenset(s)


class USCalendar:
    """NY Fed business-day calendar."""

    name = "NY_FED"

    def __init__(self, extra_holidays: Iterable[date] = ()) -> None:
        self._holidays: frozenset[date] = _holiday_set() | frozenset(extra_holidays)

    def is_business_day(self, d: date) -> bool:
        """Return ``True`` if ``d`` is a weekday and not a NY Fed holiday."""
        return d.weekday() < 5 and d not in self._holidays

    def add_business_days(self, d: date, n: int) -> date:
        """Return the date ``n`` business days after (or before, if negative) ``d``."""
        step = 1 if n >= 0 else -1
        remaining = abs(n)
        cur = d
        while remaining > 0:
            cur += timedelta(days=step)
            if self.is_business_day(cur):
                remaining -= 1
        return cur

    def next_business_day(self, d: date) -> date:
        """Return the first business day on or after ``d``."""
        cur = d
        while not self.is_business_day(cur):
            cur += timedelta(days=1)
        return cur

    def prev_business_day(self, d: date) -> date:
        """Return the last business day on or before ``d``."""
        cur = d
        while not self.is_business_day(cur):
            cur -= timedelta(days=1)
        return cur

    def roll(self, d: date, bdc: BusinessDayConvention) -> date:
        """Adjust ``d`` to a business day using the given business-day convention."""
        if bdc in ("None", "NoAdjust") or self.is_business_day(d):
            return d
        if bdc == "Following":
            return self.next_business_day(d)
        if bdc == "Preceding":
            return self.prev_business_day(d)
        if bdc == "ModifiedFollowing":
            n = self.next_business_day(d)
            return self.prev_business_day(d) if n.month != d.month else n
        if bdc == "ModifiedPreceding":
            p = self.prev_business_day(d)
            return self.next_business_day(d) if p.month != d.month else p
        if bdc == "Nearest":
            n = self.next_business_day(d)
            p = self.prev_business_day(d)
            return n if (n - d).days <= (d - p).days else p
        raise ValueError(f"Unknown BusinessDayConvention: {bdc!r}")


NY_FED = USCalendar()


def is_month_end(d: date) -> bool:
    """True if ``d`` is the last calendar day of its month."""
    return (d + timedelta(days=1)).day == 1


def month_end_curve_date(val_date: date, calendar: USCalendar = NY_FED) -> date | None:
    """Previous-close curve date for a month-end that is itself a non-business day.

    When a month-end valuation date falls on a weekend or Fed holiday there is
    no published market data for it. In that case we value *as of* ``val_date``
    but source the curve from the **previous business day** (consistent with a
    ``Preceding`` roll: weekends and holidays are skipped in one hop until a
    real business day is reached).

    Returns that previous-business-day date, or ``None`` when no fallback
    applies -- i.e. ``val_date`` is itself a business day, or is not the last
    calendar day of its month. The caller requires data for the returned date
    exactly and does **not** roll back any further (a missing previous-close
    file is a hard error, not a reason to keep searching).
    """
    if is_month_end(val_date) and not calendar.is_business_day(val_date):
        return calendar.prev_business_day(val_date)
    return None
