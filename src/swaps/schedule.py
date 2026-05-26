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
    first_period_accrual_end_date: date | None = None,
) -> list[date]:
    """Unadjusted period boundaries incl. effective & termination endpoints.

    ``forward*``  : generate from the effective date forward, stub at the back,
                    anchor = effective date.
    ``backward*`` : generate from maturity backward, stub at the front,
                    anchor = maturity.
    ``*_eom``     : if the anchor is its month's last day, snap every interior
                    boundary to month-end (endpoints stay as given).

    BBG "First Payment Date" override: ``first_period_accrual_end_date`` is
    the end of accrual period 1 (= start of period 2). When set:

      * Period 1 unadjusted = ``effective_date -> anchor`` (short front stub).
      * Subsequent unadjusted ends = ``anchor + k * step`` for k=1,2,... using
        strict calendar-day arithmetic (no month-end snapping, regardless of
        ``roll_convention``'s ``_eom`` suffix). 4/30 anchor -> 7/30, 10/30,
        1/30, 4/30 — never February-month-end.
      * Roll continues until the next stepped date would meet or exceed
        ``termination_date``; the last boundary is ``termination_date``
        (back stub absorbed at the end).
      * ``roll_convention`` is effectively ignored — the anchor dictates both
        direction (forward) and roll day.
    """
    if roll_convention not in _VALID_ROLL_CONVENTION:
        raise ValueError(
            f"roll_convention must be one of {sorted(_VALID_ROLL_CONVENTION)}; "
            f"got {roll_convention!r}"
        )

    if first_period_accrual_end_date is not None:
        anchor = first_period_accrual_end_date
        if not (effective_date < anchor < termination_date):
            raise ValueError(
                f"first_period_accrual_end_date {anchor} must lie strictly "
                f"between effective_date {effective_date} and "
                f"termination_date {termination_date}."
            )
        # Anchor overrides roll_convention entirely: forward roll, strict
        # calendar-day stepping (no EOM snapping even if anchor is month-end).
        interior: list[date] = [anchor]
        k = 1
        while True:
            d = anchor + k * step
            if d >= termination_date:
                break
            interior.append(d)
            k += 1
        return [effective_date, *interior, termination_date]

    backward = roll_convention.startswith("backward")
    anchor = termination_date if backward else effective_date
    eom = roll_convention.endswith("eom") and _is_month_end(anchor)

    interior = []
    if backward:
        k = 1
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
        k = 1
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
    first_period_accrual_end_date: date | None = None,
    schedule_warnings: list[str] | None = None,
) -> list[AccrualPeriod]:
    """Generate accrual periods from `effective_date` to `termination_date`.

    `calendar` is the calculation calendar (accrual/effective adjustment).
    The effective date is rolled by `eff_date_adj`; every other boundary
    (including the terminal/maturity date) by `bus_day_adj`. The payment date
    is re-based on the **unadjusted** period end + `payment_delay_bdays`
    business days on `payment_calendar`, then rolled by `pay_date_adj`.

    If two adjacent boundaries adjust to the same business day (typically a
    tiny stub rolled onto its neighbor by a holiday/weekend), the inner
    boundary is dropped so the resulting period has positive length. The
    endpoints (effective and termination) are always preserved. A descriptive
    string is appended to ``schedule_warnings`` (when provided) for each merge.
    """
    if termination_date <= effective_date:
        raise ValueError(f"termination_date {termination_date} must be > effective_date {effective_date}")
    step = parse_frequency(frequency)
    pay_cal = payment_calendar or calendar

    unadjusted = list(_generate_unadjusted(
        effective_date, termination_date, step, roll_convention,
        first_period_accrual_end_date=first_period_accrual_end_date,
    ))

    # Effective date rolls under eff_date_adj; remaining boundaries (incl.
    # maturity) under bus_day_adj.
    adjusted = [calendar.roll(unadjusted[0], eff_date_adj)] + [
        calendar.roll(d, bus_day_adj) for d in unadjusted[1:]
    ]

    # Post-roll dedup: collapse adjacent boundaries that adjusted to the same
    # business day. Drop the interior one (endpoints survive). If a collision
    # happens between the only two boundaries left, the trade is degenerate
    # top-to-bottom and we raise rather than emit an empty schedule.
    i = 0
    while i < len(adjusted) - 1:
        if adjusted[i] != adjusted[i + 1]:
            i += 1
            continue
        last_idx = len(adjusted) - 1
        if i == 0 and i + 1 == last_idx:
            raise ValueError(
                f"effective_date {effective_date} and termination_date "
                f"{termination_date} both adjust to {adjusted[0]}; no periods "
                f"can be generated. Choose dates further apart or change "
                f"eff_date_adj / bus_day_adj."
            )
        # If i+1 is the termination endpoint, drop the inner one (i). Else
        # drop i+1 so we keep moving forward and never lose the termination.
        drop_idx = i if i + 1 == last_idx else i + 1
        if schedule_warnings is not None:
            schedule_warnings.append(
                f"0-day adjusted period merged: unadjusted boundary "
                f"{unadjusted[drop_idx]} adjusted onto its neighbor "
                f"{adjusted[drop_idx]}; the {drop_idx}-th boundary was dropped."
            )
        del unadjusted[drop_idx]
        del adjusted[drop_idx]
        # don't advance i — re-check in case of cascading collapses

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
