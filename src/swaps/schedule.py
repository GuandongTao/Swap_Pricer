"""Accrual schedule generation (Bloomberg-matched roll conventions)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from .calendar_us import BusinessDayConvention, USCalendar

_FREQ_RE = re.compile(r"^(\d+)([DWMY])$", re.IGNORECASE)

RollConvention = str  # forward | forward_eom | backward | backward_eom
_VALID_ROLL_CONVENTION = {"forward", "forward_eom", "backward", "backward_eom"}


def parse_frequency(freq: str) -> relativedelta:
    """'1Y' -> 1 year, '6M' -> 6 months, '3M', '1W', '1D'."""
    m = _FREQ_RE.match(freq.strip())
    if not m:
        raise ValueError(f"Bad frequency string: {freq!r}; expected like '1Y', '6M', '1W', '1D'")
    n, unit = int(m.group(1)), m.group(2).upper()
    if unit == "Y":
        return relativedelta(years=n)
    if unit == "M":
        return relativedelta(months=n)
    if unit == "W":
        return relativedelta(weeks=n)
    return relativedelta(days=n)


def _month_end(d: date) -> date:
    """Last calendar day of d's month."""
    return d + relativedelta(day=31)


def _is_month_end(d: date) -> bool:
    return d == _month_end(d)


@dataclass(frozen=True)
class AccrualPeriod:
    """Carries both the unadjusted (theoretical/roll) bounds and the
    business-day-adjusted bounds. The leg picks which to day-count on via its
    ``adjust`` mode; ``payment_date`` is always a good business day.
    """

    start: date            # adjusted period start
    end: date              # adjusted period end
    payment_date: date
    unadjusted_start: date
    unadjusted_end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days


def _generate_unadjusted(
    effective_date: date,
    termination_date: date,
    step: relativedelta,
    roll_convention: RollConvention,
) -> list[date]:
    """Unadjusted period boundaries incl. effective & termination endpoints.

    ``forward*``  : generate from the effective date forward, stub at the back,
                    anchor = effective date.
    ``backward*`` : generate from maturity backward, stub at the front,
                    anchor = maturity (legacy behaviour).
    ``*_eom``     : if the anchor is its month's last day, snap every interior
                    boundary to month-end (endpoints stay as given).
    """
    if roll_convention not in _VALID_ROLL_CONVENTION:
        raise ValueError(
            f"roll_convention must be one of {sorted(_VALID_ROLL_CONVENTION)}; "
            f"got {roll_convention!r}"
        )
    backward = roll_convention.startswith("backward")
    anchor = termination_date if backward else effective_date
    eom = roll_convention.endswith("eom") and _is_month_end(anchor)

    interior: list[date] = []
    k = 1
    if backward:
        while True:
            d = anchor - k * step
            if eom:
                d = _month_end(d)
            if d <= effective_date:
                break
            interior.append(d)
            k += 1
        interior.reverse()
    else:
        while True:
            d = anchor + k * step
            if eom:
                d = _month_end(d)
            if d >= termination_date:
                break
            interior.append(d)
            k += 1
    return [effective_date, *interior, termination_date]


def generate_schedule(
    effective_date: date,
    termination_date: date,
    frequency: str,
    calendar: USCalendar,
    eff_date_adj: BusinessDayConvention = "ModifiedFollowing",
    bus_day_adj: BusinessDayConvention = "ModifiedFollowing",
    pay_date_adj: BusinessDayConvention = "ModifiedFollowing",
    roll_convention: RollConvention = "forward_eom",
    payment_delay_bdays: int = 0,
    payment_calendar: USCalendar | None = None,
) -> list[AccrualPeriod]:
    """Generate accrual periods from `effective_date` to `termination_date`.

    `calendar` is the calculation calendar (accrual/effective adjustment).
    The effective date is rolled by `eff_date_adj`; every other boundary
    (including the terminal/maturity date) by `bus_day_adj`. The payment date
    is re-based on the **unadjusted** period end + `payment_delay_bdays`
    business days on `payment_calendar`, then rolled by `pay_date_adj`.
    """
    if termination_date <= effective_date:
        raise ValueError(f"termination_date {termination_date} must be > effective_date {effective_date}")
    step = parse_frequency(frequency)
    pay_cal = payment_calendar or calendar

    unadjusted = _generate_unadjusted(effective_date, termination_date, step, roll_convention)

    # Effective date rolls under eff_date_adj; remaining boundaries (incl.
    # maturity) under bus_day_adj.
    adjusted = [calendar.roll(unadjusted[0], eff_date_adj)] + [
        calendar.roll(d, bus_day_adj) for d in unadjusted[1:]
    ]

    periods: list[AccrualPeriod] = []
    for i in range(len(unadjusted) - 1):
        u_s, u_e = unadjusted[i], unadjusted[i + 1]
        a_s, a_e = adjusted[i], adjusted[i + 1]
        # Payment date is derived from the UNADJUSTED period end.
        pay = pay_cal.add_business_days(u_e, payment_delay_bdays) if payment_delay_bdays else u_e
        pay = pay_cal.roll(pay, pay_date_adj)
        periods.append(
            AccrualPeriod(
                start=a_s, end=a_e, payment_date=pay,
                unadjusted_start=u_s, unadjusted_end=u_e,
            )
        )
    return periods
