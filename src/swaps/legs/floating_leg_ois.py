"""OIS-style floating leg: daily fixings compounded in arrears.

For each accrual period [T_s, T_e]:

  * fixing dates = business days in [T_s, T_e) on `fixing_calendar`
  * each fixing date f_i carries weight d_i = days until the next fixing (or T_e)
  * lockout: the last `lockout_bdays` fixings reuse the rate observed
    `lockout_bdays + 1` business days before T_e
  * applied rate:
      - fixing date < val_date: historical fixing if available, else curve fwd
      - fixing date >= val_date: curve fwd F(f_i, f_i + d_i)
  * compounded coupon = (prod_i (1 + r_i * d_i / 360) - 1) * 360 / D
  * effective coupon  = compounded coupon + spread          (per-period, ACT/360)
  * period cashflow   = notional * ((prod_i (1 + r_i * d_i / 360) - 1) + spread * D / 360)
  * payment date      = T_e + payment_delay_bdays (on `payment_calendar`)
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..calendar_us import USCalendar
from ..conventions import DayCount
from ..curve import ZeroCurve
from ..fixings import FixingHistory
from ..notional import NotionalSchedule
from ..schedule import AccrualPeriod
from .base import Leg


class OISFloatingLeg(Leg):
    def __init__(
        self,
        schedule: list[AccrualPeriod],
        notional: NotionalSchedule,
        projection_curve: ZeroCurve,
        fixings: FixingHistory,
        daycount: DayCount,
        fixing_calendar: USCalendar,
        payment_delay_bdays: int = 0,
        lockout_bdays: int = 0,
        payment_calendar: USCalendar | None = None,
        spread: float = 0.0,
    ) -> None:
        self.schedule = list(schedule)
        self.notional = notional
        self.projection_curve = projection_curve
        self.fixings = fixings
        self.daycount = daycount
        self.fixing_calendar = fixing_calendar
        self.payment_calendar = payment_calendar or fixing_calendar
        self.payment_delay_bdays = int(payment_delay_bdays)
        self.lockout_bdays = int(lockout_bdays)
        self.spread = float(spread)

    def with_projection_curve(self, new_curve: ZeroCurve) -> "OISFloatingLeg":
        """Return a copy with a different projection curve (for DV01 / sensitivities)."""
        return OISFloatingLeg(
            schedule=self.schedule,
            notional=self.notional,
            projection_curve=new_curve,
            fixings=self.fixings,
            daycount=self.daycount,
            fixing_calendar=self.fixing_calendar,
            payment_delay_bdays=self.payment_delay_bdays,
            lockout_bdays=self.lockout_bdays,
            payment_calendar=self.payment_calendar,
            spread=self.spread,
        )

    # ------------------------------------------------------------------ helpers
    def _fixing_dates_for_period(self, p: AccrualPeriod) -> list[date]:
        """Business days in [start, end) per fixing calendar."""
        dates: list[date] = []
        cur = p.start
        while cur < p.end:
            if self.fixing_calendar.is_business_day(cur):
                dates.append(cur)
            cur += timedelta(days=1)
        return dates

    def _resolved_rate(self, fixing_date: date, next_fixing: date, val_date: date) -> tuple[float, str]:
        """Return (rate, source) where source in {'history', 'curve'}."""
        if fixing_date < val_date:
            r = self.fixings.get(fixing_date)
            if r is None:
                raise ValueError(
                    f"Missing historical fixing for {fixing_date} (val_date={val_date}). "
                    "Provide it via FixingHistory or use a forward-start schedule."
                )
            return r, "history"
        return self.projection_curve.forward(fixing_date, next_fixing), "curve"

    def _period_fixing_rows(
        self, p: AccrualPeriod, val_date: date
    ) -> list[dict]:
        fixings = self._fixing_dates_for_period(p)
        if not fixings:
            return []
        # Day-count weights: d_i = days to next fixing (or to period end for the last)
        nexts = fixings[1:] + [p.end]
        weights = [(nf - f).days for f, nf in zip(fixings, nexts)]

        # Apply lockout: last `L` rates frozen at the (L+1)-th-to-last fixing's rate
        L = self.lockout_bdays
        applied_rates: list[float] = [0.0] * len(fixings)
        sources: list[str] = [""] * len(fixings)
        normal_count = len(fixings) - L if L > 0 else len(fixings)
        if normal_count <= 0:
            raise ValueError(f"Lockout ({L}) exceeds period fixings ({len(fixings)})")

        for i in range(normal_count):
            r, src = self._resolved_rate(fixings[i], nexts[i], val_date)
            applied_rates[i] = r
            sources[i] = src
        # Lockout copies the last "normal" rate forward
        if L > 0:
            for i in range(normal_count, len(fixings)):
                applied_rates[i] = applied_rates[normal_count - 1]
                sources[i] = "lockout"

        rows = []
        for f, nf, d, r, src in zip(fixings, nexts, weights, applied_rates, sources):
            rows.append(
                {
                    # Outer payment-period context (constant within a period)
                    "period_start": p.start,
                    "period_end": p.end,
                    "payment_date": p.payment_date,
                    # Per-fixing sub-accrual (one row per business day)
                    "fixing_date": f,
                    "accrual_start": f,
                    "accrual_end": nf,
                    "day_count": d,
                    "reset_rate": r,
                    "rate_source": src,
                }
            )
        return rows

    # ------------------------------------------------------------------ public
    def cashflows(self, val_date: date, discount_curve: ZeroCurve) -> pd.DataFrame:
        all_rows: list[dict] = []
        for p in self.schedule:
            rows = self._period_fixing_rows(p, val_date)
            if not rows:
                continue
            # Period growth product and totals
            growth = 1.0
            for row in rows:
                growth *= 1.0 + row["reset_rate"] * row["day_count"] / 360.0
            D = (p.end - p.start).days
            comp_coupon_rate = (growth - 1.0) * 360.0 / D
            effective_rate = comp_coupon_rate + self.spread
            notional = self.notional(p.start)
            period_cf = notional * ((growth - 1.0) + self.spread * D / 360.0)
            df_pay = discount_curve.df(p.payment_date) if p.payment_date >= val_date else float("nan")
            disc_cf = period_cf * df_pay if p.payment_date >= val_date else 0.0

            # Compute per-row display columns
            for i, row in enumerate(rows):
                f = row["fixing_date"]
                row["implied_daily_fwd"] = self.projection_curve.forward(f, f + timedelta(days=1)) if f >= val_date else float("nan")
                row["df_to_fixing"] = discount_curve.df(f) if f >= val_date else float("nan")
                row["df_to_payment"] = df_pay
                row["spread"] = self.spread
                # Totals only on the last fixing row of the period
                last = i == len(rows) - 1
                row["compounded_coupon"] = comp_coupon_rate if last else float("nan")
                row["effective_coupon"] = effective_rate if last else float("nan")
                row["period_cashflow"] = period_cf if last else float("nan")
                row["discounted_cashflow"] = disc_cf if last else 0.0
            all_rows.extend(rows)
        return pd.DataFrame(all_rows)

    def accrued(self, val_date: date) -> float:
        for p in self.schedule:
            if p.start <= val_date < p.end:
                rows = self._period_fixing_rows(p, val_date)
                if not rows:
                    return 0.0
                # Use only fixings strictly before val_date
                growth = 1.0
                for row in rows:
                    if row["fixing_date"] < val_date:
                        # Cap day count so it doesn't extend past val_date
                        end = min(row["fixing_date"] + timedelta(days=row["day_count"]), val_date)
                        d_eff = (end - row["fixing_date"]).days
                        growth *= 1.0 + row["reset_rate"] * d_eff / 360.0
                partial_days = (val_date - p.start).days
                spread_accrual = self.spread * partial_days / 360.0
                return self.notional(p.start) * ((growth - 1.0) + spread_accrual)
        return 0.0

    # ------------------------------------------------------------------ debug
    def fixings_debug(self, val_date: date) -> pd.DataFrame:
        """Per-fixing rows (no aggregates) — useful for hand-checking compounding."""
        rows: list[dict] = []
        for p in self.schedule:
            rows.extend(self._period_fixing_rows(p, val_date))
        return pd.DataFrame(rows)

    def period_cashflows(self, val_date: date, discount_curve: ZeroCurve) -> pd.DataFrame:
        """One row per accrual period -- monthly-compounded view that mirrors
        the fixed-leg cashflow granularity for side-by-side comparison.

        Columns parallel ``FixedLeg.cashflows()`` with OIS additions:
        ``historical_product``, ``projected_product``, ``growth``,
        ``compounded_coupon``, ``effective_coupon``, ``n_fixings``.
        """
        rows: list[dict] = []
        for p in self.schedule:
            sub = self._period_fixing_rows(p, val_date)
            if not sub:
                continue
            hist_g, proj_g = 1.0, 1.0
            for row in sub:
                factor = 1.0 + row["reset_rate"] * row["day_count"] / 360.0
                if row["fixing_date"] < val_date:
                    hist_g *= factor
                else:
                    proj_g *= factor
            growth = hist_g * proj_g
            D = (p.end - p.start).days
            comp_rate = (growth - 1.0) * 360.0 / D
            notional = self.notional(p.start)
            period_cf = notional * ((growth - 1.0) + self.spread * D / 360.0)
            df_pay = discount_curve.df(p.payment_date) if p.payment_date >= val_date else float("nan")
            disc_cf = period_cf * df_pay if p.payment_date >= val_date else 0.0
            rows.append(
                {
                    "accrual_start": p.start,
                    "accrual_end": p.end,
                    "payment_date": p.payment_date,
                    "period_days": D,
                    "day_count_fraction": D / 360.0,
                    "notional": notional,
                    "n_fixings": len(sub),
                    "historical_product": hist_g,
                    "projected_product": proj_g,
                    "growth": growth,
                    "compounded_coupon": comp_rate,
                    "spread": self.spread,
                    "effective_coupon": comp_rate + self.spread,
                    "payment_amount": period_cf,
                    "df_to_payment": df_pay,
                    "discounted_cashflow": disc_cf,
                }
            )
        return pd.DataFrame(rows)

    def period_breakdown(self, val_date: date) -> pd.DataFrame:
        """One row per accrual period with the gross growth factor decomposed."""
        out = []
        for p in self.schedule:
            rows = self._period_fixing_rows(p, val_date)
            hist_g, proj_g = 1.0, 1.0
            for row in rows:
                factor = 1.0 + row["reset_rate"] * row["day_count"] / 360.0
                if row["fixing_date"] < val_date:
                    hist_g *= factor
                else:
                    proj_g *= factor
            growth = hist_g * proj_g
            D = (p.end - p.start).days
            out.append(
                {
                    "accrual_start": p.start,
                    "accrual_end": p.end,
                    "payment_date": p.payment_date,
                    "days": D,
                    "historical_product": hist_g,
                    "projected_product": proj_g,
                    "growth": growth,
                    "compounded_coupon": (growth - 1.0) * 360.0 / D,
                }
            )
        return pd.DataFrame(out)
