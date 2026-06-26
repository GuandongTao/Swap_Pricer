"""Item 5: Swap Payment Schedule (frequency Once, SFTP).

Excel per ``Payment Schedule.xlsx``. Produced only for the swap id(s) named via
``--new_deal-<id>``. Full per-leg schedule: fixed-leg rows and floating-leg rows
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
from .helpers import coupon_rows, iso, num, period_fixing_dates

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
            iso(r["accrual_start"]),   # Start Date
            iso(r["accrual_end"]),     # End Date
            "", "",                    # Floating Start/End (blank for a fixed row)
            num(r["notional"]),        # Notional
            num(r["coupon_rate"]),     # Swap Rate
            "",                        # Fixed Payment [blank per template]
            "",                        # Rate Fixing Date
            "",                        # Index Rate [blank]
            "",                        # Spread
            "",                        # Floating Interest Rate [blank]
            "",                        # Floating Payment [blank]
            "",                        # Net Amount [blank]
            iso(r["payment_date"]),    # Payment Date
        ]))

    fixings = period_fixing_dates(v.floating_cf)
    for _, r in coupon_rows(v.floating_cf_by_period).iterrows():
        key = (r["accrual_start"], r["accrual_end"])
        fix = fixings.get(key)
        rows.append((r["payment_date"], [
            "", "",                    # Start/End (blank for a floating row)
            iso(r["accrual_start"]),   # Floating Start Date
            iso(r["accrual_end"]),     # Floating Period End Date
            num(r["notional"]),        # Notional
            "",                        # Swap Rate (fixed-only)
            "",                        # Fixed Payment [blank]
            iso(fix) if fix else "",   # Rate Fixing Date
            "",                        # Index Rate [blank]
            num(r["spread"]),          # Spread
            "",                        # Floating Interest Rate [blank]
            "",                        # Floating Payment [blank]
            "",                        # Net Amount [blank]
            iso(r["payment_date"]),    # Payment Date
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
