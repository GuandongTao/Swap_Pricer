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
    _VALID_PEX = {"none", "start", "end", "both"}
    _VALID_ROLL = {
        "None", "NoAdjust", "Following", "ModifiedFollowing",
        "Preceding", "ModifiedPreceding", "Nearest",
    }

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
        principal_exchange: str = "none",
        fixing_roll: str = "Preceding",
        fixing_lag_bdays: int = 0,
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
        pex = str(principal_exchange).lower()
        if pex not in self._VALID_PEX:
            raise ValueError(f"principal_exchange must be one of {self._VALID_PEX}; got {principal_exchange!r}")
        self.principal_exchange = pex
        self.fixing_roll = str(fixing_roll) if fixing_roll else "Preceding"
        if self.fixing_roll not in self._VALID_ROLL:
            raise ValueError(
                f"fixing_roll must be one of {sorted(self._VALID_ROLL)}; got {fixing_roll!r}"
            )
        self.fixing_lag_bdays = int(fixing_lag_bdays)

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
            principal_exchange=self.principal_exchange,
            fixing_roll=self.fixing_roll,
            fixing_lag_bdays=self.fixing_lag_bdays,
        )

    def _principal_rows(self, val_date: date, discount_curve: ZeroCurve) -> tuple[list[dict], list[dict]]:
        """Return (start_rows, end_rows) -- principal-exchange rows for this leg.

        Sign convention: start = -notional (paid out at issuance), end = +notional
        (received at maturity). Combined with the swap-level ``pay_fixed`` sign,
        this naturally lands the cashflow in the right direction.
        """
        start_rows, end_rows = [], []
        if self.principal_exchange in ("start", "both"):
            d = self.schedule[0].start
            n = self.notional(d)
            df = discount_curve.df(d) if d > val_date else float("nan")
            disc = -n * df if d > val_date else 0.0
            start_rows.append({
                "flow_type": "principal_start",
                "period_start": d, "period_end": d, "payment_date": d,
                "fixing_date": d, "accrual_start": d, "accrual_end": d,
                "day_count": 0, "reset_rate": float("nan"), "rate_source": "principal",
                "implied_daily_fwd": float("nan"),
                "df_to_fixing": df, "df_to_payment": df,
                "spread": float("nan"),
                "compounded_coupon": float("nan"), "effective_coupon": float("nan"),
                "period_cashflow": -n, "discounted_cashflow": disc,
            })
        if self.principal_exchange in ("end", "both"):
            last = self.schedule[-1]
            d = last.payment_date
            n = self.notional(last.start)
            df = discount_curve.df(d) if d > val_date else float("nan")
            disc = n * df if d > val_date else 0.0
            end_rows.append({
                "flow_type": "principal_end",
                "period_start": last.end, "period_end": last.end, "payment_date": d,
                "fixing_date": last.end, "accrual_start": last.end, "accrual_end": last.end,
                "day_count": 0, "reset_rate": float("nan"), "rate_source": "principal",
                "implied_daily_fwd": float("nan"),
                "df_to_fixing": df, "df_to_payment": df,
                "spread": float("nan"),
                "compounded_coupon": float("nan"), "effective_coupon": float("nan"),
                "period_cashflow": n, "discounted_cashflow": disc,
            })
        return start_rows, end_rows

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

    def _fixing_date_for(self, accrual_day: date) -> date:
        """Shift accrual_day back by `fixing_lag_bdays` business days, then apply
        `fixing_roll`. With lag=0 this is just the accrual day (no-op)."""
        if self.fixing_lag_bdays > 0:
            d = self.fixing_calendar.add_business_days(accrual_day, -self.fixing_lag_bdays)
        else:
            d = accrual_day
        return self.fixing_calendar.roll(d, self.fixing_roll)

    def _period_fixing_rows(
        self, p: AccrualPeriod, val_date: date
    ) -> list[dict]:
        accrual_days = self._fixing_dates_for_period(p)
        if not accrual_days:
            return []
        # Day-count weights: d_i = days to next accrual anchor (or to period end)
        nexts = accrual_days[1:] + [p.end]
        weights = [(nf - f).days for f, nf in zip(accrual_days, nexts)]
        # Fixing observation dates (lookback-shifted, then rolled)
        fixings = [self._fixing_date_for(a) for a in accrual_days]

        # Apply lockout: last `L` rates frozen at the (L+1)-th-to-last fixing's rate
        L = self.lockout_bdays
        applied_rates: list[float] = [0.0] * len(fixings)
        sources: list[str] = [""] * len(fixings)
        normal_count = len(fixings) - L if L > 0 else len(fixings)
        if normal_count <= 0:
            raise ValueError(f"Lockout ({L}) exceeds period fixings ({len(fixings)})")

        for i in range(normal_count):
            # Forward window for a curve projection is [fixing_date, fixing_date + day_count]
            r, src = self._resolved_rate(fixings[i], fixings[i] + timedelta(days=weights[i]), val_date)
            applied_rates[i] = r
            sources[i] = src
        # Lockout copies the last "normal" rate forward
        if L > 0:
            for i in range(normal_count, len(fixings)):
                applied_rates[i] = applied_rates[normal_count - 1]
                sources[i] = "lockout"

        rows = []
        for a, f, nf, d, r, src in zip(accrual_days, fixings, nexts, weights, applied_rates, sources):
            rows.append(
                {
                    # Outer payment-period context (constant within a period)
                    "period_start": p.start,
                    "period_end": p.end,
                    "payment_date": p.payment_date,
                    # Per-fixing sub-accrual (one row per business day)
                    "fixing_date": f,
                    "accrual_start": a,
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
            df_pay = discount_curve.df(p.payment_date) if p.payment_date > val_date else float("nan")
            disc_cf = period_cf * df_pay if p.payment_date > val_date else 0.0

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
        # Tag coupon rows with flow_type for consistency
        for r in all_rows:
            r.setdefault("flow_type", "coupon")
        # Prepend/append principal-exchange rows
        start_rows, end_rows = self._principal_rows(val_date, discount_curve)
        return pd.DataFrame(start_rows + all_rows + end_rows)

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
            df_pay = discount_curve.df(p.payment_date) if p.payment_date > val_date else float("nan")
            disc_cf = period_cf * df_pay if p.payment_date > val_date else 0.0
            rows.append(
                {
                    "flow_type": "coupon",
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

        # Principal-exchange rows, monthly view
        start_extra: list[dict] = []
        end_extra: list[dict] = []
        if self.principal_exchange in ("start", "both"):
            d = self.schedule[0].start
            n = self.notional(d)
            df = discount_curve.df(d) if d > val_date else float("nan")
            disc = -n * df if d > val_date else 0.0
            start_extra.append({
                "flow_type": "principal_start",
                "accrual_start": d, "accrual_end": d, "payment_date": d,
                "period_days": 0, "day_count_fraction": 0.0,
                "notional": n, "n_fixings": 0,
                "historical_product": float("nan"), "projected_product": float("nan"),
                "growth": float("nan"),
                "compounded_coupon": float("nan"), "spread": float("nan"),
                "effective_coupon": float("nan"),
                "payment_amount": -n, "df_to_payment": df, "discounted_cashflow": disc,
            })
        if self.principal_exchange in ("end", "both"):
            last = self.schedule[-1]
            d = last.payment_date
            n = self.notional(last.start)
            df = discount_curve.df(d) if d > val_date else float("nan")
            disc = n * df if d > val_date else 0.0
            end_extra.append({
                "flow_type": "principal_end",
                "accrual_start": last.end, "accrual_end": last.end, "payment_date": d,
                "period_days": 0, "day_count_fraction": 0.0,
                "notional": n, "n_fixings": 0,
                "historical_product": float("nan"), "projected_product": float("nan"),
                "growth": float("nan"),
                "compounded_coupon": float("nan"), "spread": float("nan"),
                "effective_coupon": float("nan"),
                "payment_amount": n, "df_to_payment": df, "discounted_cashflow": disc,
            })
        return pd.DataFrame(start_extra + rows + end_extra)

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
