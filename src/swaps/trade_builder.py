"""Build a Swap object from a (Bloomberg-matched) TradeDef.

Every convention is per-leg. Each leg builds its own schedule from its own
calculation calendar, Eff/Bus/Pay Date Adj, roll convention and payment delay.
Bloomberg-derived fields auto-sync: ``*_pay_date_adj`` blank -> that leg's
``*_bus_day_adj``; ``*_payment_calendar`` blank -> that leg's
``*_calculation_calendar``.
"""

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
from .validation import validate_trade

# Registered "base" calendars. Per-trade extras layer on top.
_BASE_CALENDARS: dict[str, USCalendar] = {"NY_FED": NY_FED}


def _build_calendar(base_name: str, extras: list[date], extras_file: str | None) -> USCalendar:
    try:
        base = _BASE_CALENDARS[(base_name or "NY_FED").upper()]
    except KeyError as e:
        raise ValueError(
            f"Unknown base calendar {base_name!r}; known: {list(_BASE_CALENDARS)}"
        ) from e
    combined: list[date] = list(extras)
    if extras_file:
        combined.extend(load_extra_holidays(extras_file))
    if not combined:
        return base
    base_holidays = base._holidays  # frozenset[date]
    return USCalendar(extra_holidays=set(base_holidays) | set(combined))


def build_swap(td: TradeDef, ff_curve: ZeroCurve, fixings: FixingHistory) -> Swap:
    # Two-tier validation: raises on impossible combos, returns warnings for
    # Bloomberg-grayed-out combos (recorded by the Portfolio runner).
    convention_warnings = validate_trade(td)

    # --- Fixed leg calendars ---
    fixed_calc_cal = _build_calendar(
        td.fixed_calculation_calendar,
        td.fixed_calculation_calendar_extras,
        td.fixed_calculation_calendar_extras_file,
    )
    fixed_pay_cal = _build_calendar(
        td.fixed_payment_calendar or td.fixed_calculation_calendar,
        td.fixed_payment_calendar_extras,
        td.fixed_payment_calendar_extras_file,
    )
    # --- Floating leg calendars ---
    float_calc_cal = _build_calendar(
        td.floating_calculation_calendar,
        td.floating_calculation_calendar_extras,
        td.floating_calculation_calendar_extras_file,
    )
    float_fix_cal = _build_calendar(
        td.floating_fixing_calendar,
        td.floating_fixing_calendar_extras,
        td.floating_fixing_calendar_extras_file,
    )
    float_pay_cal = _build_calendar(
        td.floating_payment_calendar or td.floating_calculation_calendar,
        td.floating_payment_calendar_extras,
        td.floating_payment_calendar_extras_file,
    )

    fixed_bda = td.fixed_bus_day_adj
    float_bda = td.floating_bus_day_adj
    float_freq = td.floating_frequency or td.fixed_frequency

    fixed_schedule = generate_schedule(
        effective_date=td.start_date,
        termination_date=td.maturity_date,
        frequency=td.fixed_frequency,
        calendar=fixed_calc_cal,
        eff_date_adj=td.fixed_eff_date_adj or fixed_bda,
        bus_day_adj=fixed_bda,
        pay_date_adj=td.fixed_pay_date_adj or fixed_bda,
        roll_convention=td.fixed_roll_convention,
        payment_delay_bdays=td.fixed_payment_delay_bdays,
        payment_calendar=fixed_pay_cal,
        first_period_accrual_end_date=td.fixed_first_period_accrual_end_date,
    )
    float_schedule = generate_schedule(
        effective_date=td.start_date,
        termination_date=td.maturity_date,
        frequency=float_freq,
        calendar=float_calc_cal,
        eff_date_adj=td.floating_eff_date_adj or float_bda,
        bus_day_adj=float_bda,
        pay_date_adj=td.floating_pay_date_adj or float_bda,
        roll_convention=td.floating_roll_convention,
        payment_delay_bdays=td.floating_payment_delay_bdays,
        payment_calendar=float_pay_cal,
        first_period_accrual_end_date=td.floating_first_period_accrual_end_date,
    )

    notional = ConstantNotional(td.notional)
    fixed = FixedLeg(
        fixed_schedule, notional, td.fixed_rate, get_daycount(td.fixed_daycount),
        principal_exchange=td.fixed_principal_exchange,
        adjust=td.fixed_adjust,
    )
    floating = OISFloatingLeg(
        schedule=float_schedule,
        notional=notional,
        projection_curve=ff_curve,
        fixings=fixings,
        daycount=get_daycount(td.floating_daycount),
        fixing_calendar=float_fix_cal,
        payment_delay_bdays=td.floating_payment_delay_bdays,
        lockout_bdays=td.floating_lockout_bdays,
        payment_calendar=float_pay_cal,
        spread=td.floating_spread,
        principal_exchange=td.floating_principal_exchange,
        fixing_roll=td.floating_rst_bus_day_adj or float_bda,
        fixing_lag_bdays=td.floating_reset_lag_bdays,
        adjust=td.floating_adjust,
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
            "floating_frequency": float_freq,
            "fixed_daycount": td.fixed_daycount,
            "floating_daycount": td.floating_daycount,
            "fixed_adjust": td.fixed_adjust,
            "floating_adjust": td.floating_adjust,
            "fixed_roll_convention": td.fixed_roll_convention,
            "floating_roll_convention": td.floating_roll_convention,
            "fixed_payment_delay_bdays": td.fixed_payment_delay_bdays,
            "floating_payment_delay_bdays": td.floating_payment_delay_bdays,
            "convention_warnings": convention_warnings,
            **td.meta,
        },
    )
