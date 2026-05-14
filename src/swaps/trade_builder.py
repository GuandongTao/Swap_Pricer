"""Build a Swap object from a TradeDef + MarketData."""

from __future__ import annotations

from datetime import date

from .calendar_us import NY_FED, USCalendar
from .conventions import get_daycount
from .fixings import FixingHistory
from .curve import ZeroCurve
from .legs.fixed_leg import FixedLeg
from .legs.floating_leg_ois import OISFloatingLeg
from .loaders.base import TradeDef
from .loaders.calendar_extras import load_extra_holidays
from .notional import ConstantNotional
from .schedule import generate_schedule
from .swap import Swap

# Registered "base" calendars. Per-trade extras are added on top via USCalendar(extra_holidays=...).
_BASE_CALENDARS: dict[str, USCalendar] = {"NY_FED": NY_FED}


def _build_calendar(base_name: str, extras: list[date], extras_file: str | None) -> USCalendar:
    try:
        base = _BASE_CALENDARS[base_name.upper()]
    except KeyError as e:
        raise ValueError(
            f"Unknown base calendar {base_name!r}; known: {list(_BASE_CALENDARS)}"
        ) from e
    combined: list[date] = list(extras)
    if extras_file:
        combined.extend(load_extra_holidays(extras_file))
    if not combined:
        return base
    # Re-derive the underlying base holiday set and add our extras on top.
    base_holidays = base._holidays  # frozenset[date]
    return USCalendar(extra_holidays=set(base_holidays) | set(combined))


def build_swap(td: TradeDef, ff_curve: ZeroCurve, fixings: FixingHistory) -> Swap:
    fix_cal = _build_calendar(td.fixing_calendar, td.fixing_calendar_extras, td.fixing_calendar_extras_file)
    pay_cal = _build_calendar(td.payment_calendar, td.payment_calendar_extras, td.payment_calendar_extras_file)

    # Per-leg roll overrides; empty string -> fall back to td.business_day_convention.
    # The schedule (shared start/end dates) uses the FIXED leg's rolls, since accrual
    # start/end live in both legs; floating's own pay_roll is honored at the pay-date
    # rebuild below if it diverges from fixed.
    def _r(v: str) -> str:
        return v if v else td.business_day_convention

    schedule = generate_schedule(
        effective_date=td.start_date,
        termination_date=td.maturity_date,
        frequency=td.fixed_frequency,
        calendar=fix_cal,
        business_day_convention=td.business_day_convention,
        payment_delay_bdays=td.payment_delay_bdays,
        payment_calendar=pay_cal,
        spot_roll=_r(td.fixed_spot_roll),
        accrual_roll=_r(td.fixed_accrual_roll),
        pay_roll=_r(td.fixed_pay_roll),
    )
    # If floating accrual/pay rolls differ from fixed, rebuild a floating schedule.
    fl_acc = _r(td.floating_accrual_roll)
    fl_pay = _r(td.floating_pay_roll)
    if (fl_acc, fl_pay) != (_r(td.fixed_accrual_roll), _r(td.fixed_pay_roll)):
        float_schedule = generate_schedule(
            effective_date=td.start_date,
            termination_date=td.maturity_date,
            frequency=td.fixed_frequency,
            calendar=fix_cal,
            business_day_convention=td.business_day_convention,
            payment_delay_bdays=td.payment_delay_bdays,
            payment_calendar=pay_cal,
            spot_roll=_r(td.fixed_spot_roll),
            accrual_roll=fl_acc,
            pay_roll=fl_pay,
        )
    else:
        float_schedule = schedule
    notional = ConstantNotional(td.notional)
    fixed = FixedLeg(
        schedule, notional, td.fixed_rate, get_daycount(td.fixed_daycount),
        principal_exchange=td.fixed_principal_exchange,
    )
    floating = OISFloatingLeg(
        schedule=float_schedule,
        notional=notional,
        projection_curve=ff_curve,
        fixings=fixings,
        daycount=get_daycount(td.floating_daycount),
        fixing_calendar=fix_cal,
        payment_delay_bdays=td.payment_delay_bdays,
        lockout_bdays=td.lockout_bdays,
        payment_calendar=pay_cal,
        spread=td.floating_spread,
        principal_exchange=td.floating_principal_exchange,
        fixing_roll=_r(td.floating_fixing_roll),
        fixing_lag_bdays=td.floating_fixing_lag_bdays,
    )
    return Swap(
        trade_id=td.trade_id,
        fixed=fixed,
        floating=floating,
        pay_fixed=td.pay_fixed,
        meta={
            "notional": td.notional,
            "fixed_rate": td.fixed_rate,
            "start_date": td.start_date,
            "maturity_date": td.maturity_date,
            "fixed_frequency": td.fixed_frequency,
            "fixed_daycount": td.fixed_daycount,
            "floating_daycount": td.floating_daycount,
            **td.meta,
        },
    )
