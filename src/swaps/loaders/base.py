"""Loader abstractions. Implementations plug in Excel today; DB/API later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from ..curve import ZeroCurve
from ..fixings import FixingHistory


class CurveLoader(ABC):
    @abstractmethod
    def load(self, val_date: date, curve_name: str) -> ZeroCurve: ...


class FixingLoader(ABC):
    @abstractmethod
    def load(self, index_name: str) -> FixingHistory: ...


@dataclass
class TradeDef:
    """Bloomberg-matched trade definition. Every *convention* is per-leg; the
    only shared fields are economic terms (notional, dates, rate, direction).

    Roll values accepted everywhere a `*_adj` / roll appears:
    ``None``/``NoAdjust``, ``Following``, ``ModifiedFollowing``, ``Preceding``,
    ``ModifiedPreceding``, ``Nearest``.

    Bloomberg-derived fields (omit on Bloomberg-matched trades):
      * ``*_pay_date_adj``      blank -> that leg's ``*_bus_day_adj``
      * ``*_payment_calendar``  blank -> that leg's ``*_calculation_calendar``
      * ``floating_reset_lag_bdays`` default 0 (in-arrears OIS has no lookback)
    """

    # --- Economic terms (legitimately shared / trade-level) ---
    trade_id: str
    notional: float
    pay_fixed: bool
    fixed_rate: float
    start_date: date
    maturity_date: date
    fixed_frequency: str
    fixed_daycount: str

    # --- Fixed leg conventions (per-leg) ---
    fixed_bus_day_adj: str = "ModifiedFollowing"
    fixed_eff_date_adj: str = ""          # blank -> fixed_bus_day_adj
    fixed_pay_date_adj: str = ""          # blank -> fixed_bus_day_adj
    fixed_adjust: str = "acc_and_pay"     # acc_and_pay | pay | none
    fixed_roll_convention: str = "forward_eom"
    fixed_principal_exchange: str = "none"
    fixed_payment_delay_bdays: int = 0
    fixed_calculation_calendar: str = "NY_FED"
    fixed_payment_calendar: str = ""      # blank -> fixed_calculation_calendar
    fixed_calculation_calendar_extras: list[date] = field(default_factory=list)
    fixed_payment_calendar_extras: list[date] = field(default_factory=list)
    fixed_calculation_calendar_extras_file: str | None = None
    fixed_payment_calendar_extras_file: str | None = None
    # Schedule anchor overrides (BBG-style). At most one per leg; if set,
    # interior coupon dates are anchored at this date instead of effective
    # date / maturity. first_accrual_date forces forward roll from the anchor
    # (front stub between effective_date and the anchor is preserved as a
    # short period). last_accrual_date forces backward roll from the anchor
    # (back stub between the anchor and maturity is preserved).
    fixed_first_accrual_date: date | None = None
    fixed_last_accrual_date: date | None = None

    # --- Floating leg conventions (per-leg) ---
    # Blank floating_frequency -> fixed_frequency (standard OIS: shared periods).
    floating_frequency: str = ""
    floating_daycount: str = "ACT/360"
    floating_spread: float = 0.0
    floating_bus_day_adj: str = "ModifiedFollowing"
    floating_eff_date_adj: str = ""       # blank -> floating_bus_day_adj
    floating_pay_date_adj: str = ""       # blank -> floating_bus_day_adj
    floating_rst_bus_day_adj: str = ""    # blank -> floating_bus_day_adj
    floating_adjust: str = "acc_and_pay"  # acc_and_pay | pay | none
    floating_roll_convention: str = "forward_eom"
    floating_principal_exchange: str = "none"
    floating_payment_delay_bdays: int = 0
    floating_reset_lag_bdays: int = 0     # business-day lookback; 0 = in-arrears
    floating_lockout_bdays: int = 0
    floating_calculation_calendar: str = "NY_FED"
    floating_fixing_calendar: str = "NY_FED"
    floating_payment_calendar: str = ""   # blank -> floating_calculation_calendar
    floating_calculation_calendar_extras: list[date] = field(default_factory=list)
    floating_fixing_calendar_extras: list[date] = field(default_factory=list)
    floating_payment_calendar_extras: list[date] = field(default_factory=list)
    floating_calculation_calendar_extras_file: str | None = None
    floating_fixing_calendar_extras_file: str | None = None
    floating_payment_calendar_extras_file: str | None = None
    # Schedule anchor overrides (see fixed_first_accrual_date for semantics).
    floating_first_accrual_date: date | None = None
    floating_last_accrual_date: date | None = None

    # --- Production-output fields (sourced 1:1 from the trade row; not used by
    # pricing). Every field is optional and defaults to blank: an omitted
    # column in the CSV writes a blank cell in the prod CSV. The CME-branch
    # logic on `current_counterparty` is an EXACT string match against
    # "CME Clearing House"; anything else routes to the Bank/OTC-Bilateral
    # branch. See _template.csv.sample for the full Bloomberg-to-output map.
    quantum_deal_number: str = ""
    oracle_entity_code: str = ""
    notional_currency: str = ""
    intercompany: bool = False
    counterparty_name_quantum: str = ""
    current_counterparty: str = ""
    entity_name_quantum: str = ""
    reporting_party: str = ""
    counterparty_location: str = ""
    deal_date: date | None = None       # trade date (NOT effective / start_date)
    netting_id: str = ""
    cash_flow_netting_allowed: str = ""
    position_netting_allowed: str = ""

    meta: dict = field(default_factory=dict)


class TradeLoader(ABC):
    @abstractmethod
    def load_all(self) -> list[TradeDef]: ...

    @abstractmethod
    def load(self, trade_id: str) -> TradeDef: ...
