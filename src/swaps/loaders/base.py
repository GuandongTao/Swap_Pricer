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
    trade_id: str
    notional: float
    pay_fixed: bool
    fixed_rate: float
    start_date: date
    maturity_date: date
    fixed_frequency: str
    fixed_daycount: str
    floating_daycount: str = "ACT/360"
    floating_spread: float = 0.0
    # Principal-exchange policy, separately configurable per leg.
    # Accepted: "none" (default), "start", "end", "both".
    fixed_principal_exchange: str = "none"
    floating_principal_exchange: str = "none"
    # Calendar base name (must be registered) and optional extra holidays
    fixing_calendar: str = "NY_FED"
    payment_calendar: str = "NY_FED"
    fixing_calendar_extras: list[date] = field(default_factory=list)
    payment_calendar_extras: list[date] = field(default_factory=list)
    fixing_calendar_extras_file: str | None = None
    payment_calendar_extras_file: str | None = None
    payment_delay_bdays: int = 0
    lockout_bdays: int = 0
    business_day_convention: str = "ModifiedFollowing"
    # Per-leg roll conventions. Each falls back to `business_day_convention` when
    # left blank (empty string or None). Accepted values: None, NoAdjust, Following,
    # ModifiedFollowing, Preceding, ModifiedPreceding, Nearest.
    fixed_spot_roll: str = ""
    fixed_accrual_roll: str = ""
    fixed_pay_roll: str = ""
    floating_accrual_roll: str = ""
    floating_pay_roll: str = ""
    # Fixing/lookback roll convention defaults to Preceding (standard for OIS
    # observation when the natural observation date is non-BD). Lookback lag in
    # business days; 0 = rate-set-in-advance / no lag.
    floating_fixing_roll: str = ""
    floating_fixing_lag_bdays: int = 0
    meta: dict = field(default_factory=dict)


class TradeLoader(ABC):
    @abstractmethod
    def load_all(self) -> list[TradeDef]: ...

    @abstractmethod
    def load(self, trade_id: str) -> TradeDef: ...
