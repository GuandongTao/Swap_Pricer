"""Item 4: KPMG Payment Report (daily, SFTP).

Plain CSV of payments SETTLING TODAY -- i.e. whose Payment Date == the valuation
date. One row per such payment (fixed and/or floating). A position with no
payment dated exactly on val_date is omitted; if none settle today the file is
still written header-only (zero data rows). Columns per ``Payment Report.xlsx``.

Behavior (confirmed 2026-07-02):
* Filter = Payment Date == val_date (NOT month-scoped).
* Floating accrual-date cells left blank per the format note; floating day-count
  and payment are filled.
* Net Payment = (floating received - fixed paid) for a pay-fixed swap, else the
  reverse. Index Rate / Current Spread / All-In-Rate left blank per the note.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import RunContext
from .envelope import write_table_csv
from .helpers import _as_date, coupon_rows, mdy, num

FIELDS = [
    "Internal Reference Number", "Product", "Description", "Notional",
    "Start Accrual Date", "End Accrual Date",
    "Number of Days in Accrual Period for the fixed leg", "Fixed Payment",
    "Start Accrual Date(Floating)", "End Accrual Date(Floating)",
    "Number of Days in Accrual Period for the floating leg", "Floating Payment",
    "Net Payment", "Payment Date", "Counterparty",
    "Index Rate", "Current Spread", "All-In-Rate",
]


def _filename(val_date: date) -> str:
    return f"KPMG_AMEX_Payment_Report {val_date:%b %d, %Y}.csv"


def produce(ctx: RunContext, dest_dir: Path) -> list[Path]:
    val_date = ctx.val_date
    pp = ctx.priced()
    rows: list[list[str]] = []

    for pt in pp.priced:
        td, v = pt.trade, pt.valuation
        ref = str(td.meta.get("id", td.trade_id))

        fixed = coupon_rows(v.fixed_cf)
        floating = coupon_rows(v.floating_cf_by_period)

        # Keep only payments settling TODAY (Payment Date == val_date).
        fx_by_date: dict[date, dict] = {}
        for _, r in fixed.iterrows():
            if _as_date(r["payment_date"]) == val_date:
                fx_by_date[r["payment_date"]] = r
        fl_by_date: dict[date, dict] = {}
        for _, r in floating.iterrows():
            if _as_date(r["payment_date"]) == val_date:
                fl_by_date[r["payment_date"]] = r

        pay_dates = sorted(set(fx_by_date) | set(fl_by_date), key=lambda d: (mdy(d), str(d)))
        if not pay_dates:
            continue  # no payment this month -> omit the position

        pay_fixed = bool(td.pay_fixed)
        for pd_ in pay_dates:
            f = fx_by_date.get(pd_)
            g = fl_by_date.get(pd_)
            fixed_pmt = float(f["payment_amount"]) if f is not None else None
            float_pmt = float(g["payment_amount"]) if g is not None else None
            # Net = received - paid.
            net = 0.0
            if fixed_pmt is not None:
                net += -fixed_pmt if pay_fixed else fixed_pmt
            if float_pmt is not None:
                net += float_pmt if pay_fixed else -float_pmt

            rows.append([
                ref,                                                # Internal Reference Number
                "Reverse Swap",                                     # Product
                "",                                                 # Description
                num(td.notional),                                   # Notional
                mdy(f["accrual_start"]) if f is not None else "",   # Start Accrual Date
                mdy(f["accrual_end"]) if f is not None else "",     # End Accrual Date
                num(int(f["period_days"])) if f is not None else "",# Days (fixed)
                num(fixed_pmt) if fixed_pmt is not None else "",    # Fixed Payment
                "",                                                 # Start Accrual Date(Floating) [blank per note]
                "",                                                 # End Accrual Date(Floating)   [blank per note]
                num(int(g["period_days"])) if g is not None else "",# Days (floating)
                num(float_pmt) if float_pmt is not None else "",    # Floating Payment
                num(net),                                           # Net Payment
                mdy(pd_),                                            # Payment Date
                td.debt_counterparty or "",                         # Counterparty
                "",                                                 # Index Rate
                "",                                                 # Current Spread
                "",                                                 # All-In-Rate
            ])

    out = write_table_csv(dest_dir / _filename(val_date), FIELDS, rows)
    return [out]
