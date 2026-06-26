"""Item 5: Swap Payment Schedule (frequency Once, SFTP).

Excel per ``Payment Schedule.xlsx``. Produced only for the swap id(s) named via
``--new-deal-<id>``. Full per-leg schedule: fixed-leg rows and floating-leg rows
interleaved by payment date. Columns that are blank in the template stay blank.

ASSUMPTIONS (confirm — see _intake.md):
* One row per leg period; sorted by Payment Date.
* Rate Fixing Date = the period's last OIS fixing date.
* Empty cols (Fixed Payment, Index Rate, Floating Interest Rate, Floating
  Payment, Net Amount) intentionally left blank.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from .base import RunContext
from .helpers import coupon_rows, period_fixing_dates, xldate, xlnum

FIELDS = [
    "Start Date", "End Date", "Floating Start Date", "Floating Period End Date",
    "Notional", "Swap Rate", "Fixed Payment", "Rate Fixing Date", "Index Rate",
    "Spread", "Floating Interest Rate", "Floating Payment", "Net Amount", "Payment Date",
]


def _filename(raw_id: str) -> str:
    return f"{raw_id} Swap Payment Schedule.xlsx"


def _rows_for(pt) -> list[list]:
    td, v = pt.trade, pt.valuation
    rows: list[tuple] = []  # (sort_key, row)

    for _, r in coupon_rows(v.fixed_cf).iterrows():
        rows.append((r["payment_date"], [
            xldate(r["accrual_start"]),   # Start Date
            xldate(r["accrual_end"]),     # End Date
            None, None,                   # Floating Start/End (blank for a fixed row)
            xlnum(r["notional"]),         # Notional
            xlnum(r["coupon_rate"]),      # Swap Rate
            None,                         # Fixed Payment [blank per template]
            None,                         # Rate Fixing Date
            None,                         # Index Rate [blank]
            None,                         # Spread
            None,                         # Floating Interest Rate [blank]
            None,                         # Floating Payment [blank]
            None,                         # Net Amount [blank]
            xldate(r["payment_date"]),    # Payment Date
        ]))

    fixings = period_fixing_dates(v.floating_cf)
    for _, r in coupon_rows(v.floating_cf_by_period).iterrows():
        key = (r["accrual_start"], r["accrual_end"])
        fix = fixings.get(key)
        rows.append((r["payment_date"], [
            None, None,                   # Start/End (blank for a floating row)
            xldate(r["accrual_start"]),   # Floating Start Date
            xldate(r["accrual_end"]),     # Floating Period End Date
            xlnum(r["notional"]),         # Notional
            None,                         # Swap Rate (fixed-only)
            None,                         # Fixed Payment [blank]
            xldate(fix),                  # Rate Fixing Date
            None,                         # Index Rate [blank]
            xlnum(r["spread"]),           # Spread
            None,                         # Floating Interest Rate [blank]
            None,                         # Floating Payment [blank]
            None,                         # Net Amount [blank]
            xldate(r["payment_date"]),    # Payment Date
        ]))

    rows.sort(key=lambda t: (str(t[0]),))
    return [r for _, r in rows]


def produce(ctx: RunContext, dest_dir: Path) -> list[Path]:
    pp = ctx.priced()
    written: list[Path] = []
    dest_dir.mkdir(parents=True, exist_ok=True)

    for raw_id in sorted(ctx.new_deal_ids):
        matches = pp.by_raw_id(raw_id)
        if not matches:
            continue  # unknown id in this portfolio -> nothing to emit
        wb = Workbook()
        ws = wb.active
        ws.title = "Payment Schedule"
        ws.append(FIELDS)
        for pt in matches:
            for row in _rows_for(pt):
                ws.append(row)
        out = dest_dir / _filename(raw_id)
        wb.save(out)
        written.append(out)
    return written
