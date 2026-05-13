"""Zero curve: pillars -> discount factors with log-linear interpolation.

The curve is built from a set of (tenor, zero_rate) pillars plus a valuation
date. Each pillar's rate is converted to a discount factor via the chosen
`RateQuoting` strategy. DFs are then log-linearly interpolated on a
calendar-day axis. An implicit anchor (val_date, DF=1.0) is prepended.

Two instances are typically built per valuation: a SOFR curve (used for
discounting) and a Fed Funds curve (used for projection).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .rate_quoting import DEFAULT, RateQuoting

_TENOR_RE = re.compile(r"^(\d+)([DWMY])$", re.IGNORECASE)


def tenor_to_date(val_date: date, tenor: str) -> date:
    """Convert a tenor code to a calendar pillar date under strict ACT/360 day math.

    Day counts:
        D = N         W = 7*N         M = 30*N         Y = 360*N
        ON = 1        TN = 2

    Rationale: this keeps the year-fraction at any pillar exactly ``days/360 = N``
    under ACT/360, so an annual-compounded ACT/360 zero rate ``r`` at the ``NY``
    pillar discounts as ``(1+r)^(-N)``, a Y-year rate at the 5Y pillar as
    ``(1+r)^(-5)``, etc. Alternative interpretation (1Y = 1 calendar year, year
    fraction 365/360) is recorded in questions.md.
    """
    t = tenor.strip().upper()
    if t == "ON":
        return val_date + timedelta(days=1)
    if t == "TN":
        return val_date + timedelta(days=2)
    m = _TENOR_RE.match(t)
    if not m:
        raise ValueError(f"Bad tenor code: {tenor!r}")
    n, unit = int(m.group(1)), m.group(2).upper()
    if unit == "D":
        return val_date + timedelta(days=n)
    if unit == "W":
        return val_date + timedelta(days=7 * n)
    if unit == "M":
        return val_date + timedelta(days=30 * n)
    return val_date + timedelta(days=360 * n)


@dataclass(frozen=True)
class Pillar:
    tenor: str
    pillar_date: date
    days: int
    zero_rate: float
    df: float


class ZeroCurve:
    """Zero curve with log-linear DF interpolation on the calendar-day axis."""

    def __init__(
        self,
        val_date: date,
        pillars: dict[str, float],
        rate_quoting: RateQuoting | None = None,
        name: str = "",
    ) -> None:
        self.val_date = val_date
        self.rate_quoting = rate_quoting or DEFAULT
        self.name = name
        if not pillars:
            raise ValueError("ZeroCurve requires at least one pillar")

        parsed: list[Pillar] = []
        for tenor, rate in pillars.items():
            d = tenor_to_date(val_date, tenor)
            days = (d - val_date).days
            if days <= 0:
                raise ValueError(f"Pillar {tenor!r} resolves to {d} <= val_date {val_date}")
            df = self.rate_quoting.rate_to_df(float(rate), days)
            parsed.append(Pillar(tenor=tenor, pillar_date=d, days=days, zero_rate=float(rate), df=df))

        parsed.sort(key=lambda p: p.days)
        self._pillars: tuple[Pillar, ...] = tuple(parsed)

        # Build interp arrays: prepend (days=0, log_df=0) anchor at val_date.
        self._days = np.concatenate(([0], np.array([p.days for p in parsed], dtype=np.int64)))
        self._log_df = np.concatenate(([0.0], np.log(np.array([p.df for p in parsed], dtype=np.float64))))

    @property
    def pillars(self) -> tuple[Pillar, ...]:
        return self._pillars

    @property
    def max_pillar_days(self) -> int:
        return int(self._days[-1])

    def df(self, d: date) -> float:
        return float(self.df_vector([d])[0])

    def df_vector(self, dates) -> np.ndarray:
        ds = pd.to_datetime(pd.Series(list(dates))).dt.date.values
        days = np.array([(x - self.val_date).days for x in ds], dtype=np.float64)
        if np.any(days < 0):
            bad = [x for x, n in zip(ds, days) if n < 0]
            raise ValueError(f"Cannot evaluate DF before val_date {self.val_date}: {bad[:3]}")
        return np.exp(self._interp_log_df(days))

    def _interp_log_df(self, days: np.ndarray) -> np.ndarray:
        xs, ys = self._days.astype(np.float64), self._log_df
        out = np.interp(days, xs, ys)  # log-linear in DF == linear in log(DF)
        # Extrapolate past last pillar using last-segment slope.
        last_d = xs[-1]
        if np.any(days > last_d):
            slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
            mask = days > last_d
            out[mask] = ys[-1] + slope * (days[mask] - last_d)
        return out

    def forward(self, t1: date, t2: date) -> float:
        """Simple ACT/360 forward rate between two calendar dates."""
        if t2 <= t1:
            raise ValueError(f"forward(): t2 {t2} must be > t1 {t1}")
        df1, df2 = self.df(t1), self.df(t2)
        days = (t2 - t1).days
        return (df1 / df2 - 1.0) * 360.0 / days

    def bumped(self, delta: float) -> "ZeroCurve":
        """Return a new ZeroCurve with all pillar zero rates shifted by ``delta``.

        ``delta`` is in absolute terms (e.g. 1e-4 for a +1 bp parallel shift).
        Used for DV01 / parallel sensitivities.
        """
        bumped_pillars = {p.tenor: p.zero_rate + delta for p in self._pillars}
        return ZeroCurve(self.val_date, bumped_pillars, self.rate_quoting, name=f"{self.name}+{delta}")

    def to_debug_frame(self) -> pd.DataFrame:
        """Pillar table — primary debug surface for the curve."""
        return pd.DataFrame(
            [
                {
                    "tenor": p.tenor,
                    "pillar_date": p.pillar_date,
                    "days": p.days,
                    "zero_rate": p.zero_rate,
                    "df": p.df,
                }
                for p in self._pillars
            ]
        )

    def df_grid_debug(self, start: date, end: date) -> pd.DataFrame:
        """Daily DF/log-DF/implied 1-day forward over [start, end]."""
        if start < self.val_date:
            raise ValueError(f"start {start} < val_date {self.val_date}")
        dates = pd.date_range(start, end, freq="D").date
        dfs = self.df_vector(dates)
        log_dfs = np.log(dfs)
        next_dfs = self.df_vector([d + timedelta(days=1) for d in dates])
        implied_fwd = (dfs / next_dfs - 1.0) * 360.0
        return pd.DataFrame({"date": dates, "df": dfs, "log_df": log_dfs, "implied_daily_fwd": implied_fwd})
