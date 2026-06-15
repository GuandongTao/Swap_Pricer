"""Fixed leg: periodic coupons at a constant rate, per-trade day-count."""

from __future__ import annotations

from datetime import date, timedelta

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
        """Return one coupon row per period plus any principal-exchange rows.

        Columns: ``flow_type``, ``accrual_start/end``, ``payment_date``,
        ``period_days``, ``day_count_fraction``, ``notional``, ``coupon_rate``,
        ``payment_amount``, ``df_to_payment``, ``discounted_cashflow``.
        Past payments (``payment_date <= val_date``) have NaN DF and zero
        discounted cashflow.
        """
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

    def _period_accrued_detail(self, p: AccrualPeriod, val_date: date) -> dict | None:
        """Accrued contribution of one period as of ``val_date`` (``None`` if the
        period is not accruing -- not yet started, or already paid).

        A period accrues from its start until its **payment** date (not its
        accrual end). The day-count fraction runs to ``min(val_date,
        accrual_end)`` **inclusive** (client convention: both accrual start and
        val_date are counted), so a period whose accrual has ended but has not
        yet paid (``accrual_end <= val_date < payment_date``) contributes its
        **full** coupon -- it is owed but unpaid."""
        s, e = self._acc(p)
        if not (s <= val_date < p.payment_date):
            return None
        # eff_end is an exclusive upper bound; +1 day makes val_date inclusive.
        eff_end = min(val_date, e) + timedelta(days=1)
        dcf = self.daycount.year_fraction(s, eff_end)
        n = self.notional(s)
        return {
            "accrual_start": s,
            "accrual_end": e,
            "payment_date": p.payment_date,
            "period_complete": val_date >= e,
            "elapsed_days": (eff_end - s).days,
            "period_days": (e - s).days,
            "day_count_fraction": dcf,
            "coupon_rate": self.fixed_rate,
            "notional": n,
            "accrued": n * self.fixed_rate * dcf,
        }

    def accrued(self, val_date: date) -> float:
        # Sum over periods: a just-ended-but-unpaid period and the next, already
        # started period can both be accruing at once (with a payment delay).
        return sum(
            d["accrued"]
            for d in (self._period_accrued_detail(p, val_date) for p in self.schedule)
            if d is not None
        )

    def accrued_debug(self, val_date: date) -> dict:
        """Per-leg accrued breakdown for the debug workbook. ``accrued`` is the
        total over all accruing periods; the period-detail columns describe the
        representative period (the one still mid-accrual if any, else the
        completed-but-unpaid one). ``periods_accruing`` flags when more than one
        period contributes (period boundary under a payment delay)."""
        details = [
            d for d in (self._period_accrued_detail(p, val_date) for p in self.schedule)
            if d is not None
        ]
        total = sum(d["accrued"] for d in details)
        if not details:
            return {
                "leg": "fixed", "accruing": False, "accrual_start": None,
                "val_date": val_date, "accrual_end": None, "period_complete": False,
                "periods_accruing": 0, "elapsed_days": 0, "period_days": 0,
                "day_count_fraction": 0.0, "coupon_rate": self.fixed_rate,
                "notional": 0.0, "accrued": 0.0,
            }
        open_d = [d for d in details if not d["period_complete"]]
        rep = open_d[0] if open_d else details[0]
        return {
            "leg": "fixed",
            "accruing": True,
            "accrual_start": rep["accrual_start"],
            "val_date": val_date,
            "accrual_end": rep["accrual_end"],
            "period_complete": rep["period_complete"],
            "periods_accruing": len(details),
            "elapsed_days": rep["elapsed_days"],
            "period_days": rep["period_days"],
            "day_count_fraction": rep["day_count_fraction"],
            "coupon_rate": self.fixed_rate,
            "notional": rep["notional"],
            "accrued": total,
        }

    def to_debug_frame(self, val_date: date, discount_curve: ZeroCurve) -> pd.DataFrame:
        return self.cashflows(val_date, discount_curve)
