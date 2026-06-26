"""Shared formatting / lookup helpers for additional-output producers."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Iterable

import pandas as pd

# Tenor -> human-readable payment frequency (Treasury report etc.).
_FREQ_LABELS = {
    "1D": "Daily", "1W": "Weekly", "2W": "Bi-weekly",
    "1M": "Monthly", "2M": "Bi-monthly", "3M": "Quarterly",
    "4M": "Every 4 months", "6M": "Semi-annually", "1Y": "Annually",
}


def freq_label(tenor: str | None) -> str:
    t = (tenor or "").strip().upper()
    return _FREQ_LABELS.get(t, tenor or "")


def num(x: object) -> str:
    """Plain numeric string: blank for None/NaN, int when integral, else trimmed."""
    if x is None or x == "":
        return ""
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, (int,)):
        return str(x)
    if isinstance(x, float):
        if math.isnan(x):
            return ""
        if x.is_integer():
            return str(int(x))
        return f"{x:.6f}".rstrip("0").rstrip(".")
    return str(x)


def _as_date(x: object) -> date | None:
    if x is None or x == "":
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return pd.to_datetime(x).date()
    except Exception:
        return None


def mdy(x: object) -> str:
    """mm/dd/yyyy (the production-CSV date convention). Blank when not a date."""
    d = _as_date(x)
    return d.strftime("%m/%d/%Y") if d else ""


def iso(x: object) -> str:
    d = _as_date(x)
    return d.strftime("%Y-%m-%d") if d else ""


def same_month(x: object, ref: date) -> bool:
    d = _as_date(x)
    return d is not None and d.year == ref.year and d.month == ref.month


def period_fixing_dates(floating_cf: pd.DataFrame) -> dict[tuple[date, date], date]:
    """Map each floating *period* (period_start, period_end) -> its last fixing date.

    Used as the period's representative 'Rate Fixing Date' for OIS-in-arrears.
    """
    out: dict[tuple[date, date], date] = {}
    if floating_cf is None or floating_cf.empty:
        return out
    if not {"period_start", "period_end", "fixing_date"} <= set(floating_cf.columns):
        return out
    for (ps, pe), grp in floating_cf.groupby(["period_start", "period_end"]):
        ps_d, pe_d = _as_date(ps), _as_date(pe)
        fx = max((_as_date(f) for f in grp["fixing_date"] if _as_date(f)), default=None)
        if ps_d and pe_d and fx:
            out[(ps_d, pe_d)] = fx
    return out


def coupon_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Coupon (non-principal) rows of a cashflow frame."""
    if df is None or df.empty or "flow_type" not in df.columns:
        return df if df is not None else pd.DataFrame()
    return df[df["flow_type"] == "coupon"]
