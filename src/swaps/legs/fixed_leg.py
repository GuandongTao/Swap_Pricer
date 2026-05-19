"""Fixed leg: periodic coupons at a constant rate, per-trade day-count."""

from __future__ import annotations

from datetime import date

import pandas as pd

from ..conventions import DayCount
from ..curve import ZeroCurve
from ..notional import NotionalSchedule
from ..schedule import AccrualPeriod
from .base import Leg


_VALID_PEX = {"none", "start", "end", "both"}


class FixedLeg(Leg):
    _VALID_ADJUST = {"acc_and_pay", "pay", "none"}

    def __init__(
        self,
        schedule: list[AccrualPeriod],
        notional: NotionalSchedule,
        fixed_rate: float,
        daycount: DayCount,
        principal_exchange: str = "none",
        adjust: str = "acc_and_pay",
    ) -> None:
        self.schedule = list(schedule)
        self.notional = notional
        self.fixed_rate = float(fixed_rate)
        self.daycount = daycount
        pex = str(principal_exchange).lower()
        if pex not in _VALID_PEX:
            raise ValueError(f"principal_exchange must be one of {_VALID_PEX}; got {principal_exchange!r}")
        self.principal_exchange = pex
        adj = str(adjust).lower()
        if adj not in self._VALID_ADJUST:
            raise ValueError(f"adjust must be one of {self._VALID_ADJUST}; got {adjust!r}")
        self.adjust = adj

    def _acc(self, p: AccrualPeriod) -> tuple[date, date]:
        """Accrual bounds for day-count: adjusted under ``acc_and_pay``,
        else the unadjusted (theoretical) bounds."""
        if self.adjust == "acc_and_pay":
            return p.start, p.end
        return p.unadjusted_start, p.unadjusted_end

    def cashflows(self, val_date: date, discount_curve: ZeroCurve) -> pd.DataFrame:
        rows = []
        for p in self.schedule:
            s, e = self._acc(p)
            dcf = self.daycount.year_fraction(s, e)
            notional = self.notional(s)
            payment_amount = notional * self.fixed_rate * dcf
            df_pay = discount_curve.df(p.payment_date) if p.payment_date > val_date else float("nan")
            disc_cf = payment_amount * df_pay if p.payment_date > val_date else 0.0
            rows.append(
                {
                    "flow_type": "coupon",
                    "accrual_start": s,
                    "accrual_end": e,
                    "payment_date": p.payment_date,
                    "period_days": (e - s).days,
                    "day_count_fraction": dcf,
                    "notional": notional,
                    "coupon_rate": self.fixed_rate,
                    "payment_amount": payment_amount,
                    "df_to_payment": df_pay,
                    "discounted_cashflow": disc_cf,
                }
            )

        # Principal exchange rows
        if self.principal_exchange in ("start", "both"):
            d = self.schedule[0].start
            n = self.notional(d)
            df = discount_curve.df(d) if d > val_date else float("nan")
            disc = -n * df if d > val_date else 0.0
            rows.insert(0, {
                "flow_type": "principal_start",
                "accrual_start": d,
                "accrual_end": d,
                "payment_date": d,
                "period_days": 0,
                "day_count_fraction": 0.0,
                "notional": n,
                "coupon_rate": float("nan"),
                "payment_amount": -n,
                "df_to_payment": df,
                "discounted_cashflow": disc,
            })
        if self.principal_exchange in ("end", "both"):
            last = self.schedule[-1]
            d = last.payment_date
            n = self.notional(last.start)
            df = discount_curve.df(d) if d > val_date else float("nan")
            disc = n * df if d > val_date else 0.0
            rows.append({
                "flow_type": "principal_end",
                "accrual_start": last.end,
                "accrual_end": last.end,
                "payment_date": d,
                "period_days": 0,
                "day_count_fraction": 0.0,
                "notional": n,
                "coupon_rate": float("nan"),
                "payment_amount": n,
                "df_to_payment": df,
                "discounted_cashflow": disc,
            })
        return pd.DataFrame(rows)

    def accrued(self, val_date: date) -> float:
        for p in self.schedule:
            s, e = self._acc(p)
            if s <= val_date < e:
                dcf = self.daycount.year_fraction(s, val_date)
                return self.notional(s) * self.fixed_rate * dcf
        return 0.0

    def to_debug_frame(self, val_date: date, discount_curve: ZeroCurve) -> pd.DataFrame:
        return self.cashflows(val_date, discount_curve)
