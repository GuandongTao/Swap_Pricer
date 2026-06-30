"""Item 9: KPMG Valuation Report (daily, SFTP).

H/T feed (same envelope as the IRS Valuation feed) over ALL IRS positions.
Columns per ``Valuation Report.xlsx``.

ASSUMPTIONS (confirm — see _intake.md):
* Internal Reference Number = the IRS raw deal id.
* Legal Entity / Clearing House / Product are hard-coded constants per the sample.
* Key Rate = par rate; Total Value = clean + accrued.
* Footer sums the monetary columns; dates rendered mm/dd/yyyy.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import RunContext
from .envelope import write_feed
from .helpers import mdy, num

FIELDS = [
    "Internal Reference Number", "Product", "Legal Entity", "Counterparty",
    "Clearing House", "Index", "Trade Date", "Maturity Date", "Notional",
    "DV01", "Key Rate", "Clean Price", "Accrued Interest", "Total Value",
]
_SUM_COLS = [8, 9, 11, 12, 13]  # Notional / DV01 / Clean / Accrued / Total


def _filename(val_date: date) -> str:
    return f"KPMG_AMEX_Valuation_Report {val_date:%b %d, %Y}.csv"


def produce(ctx: RunContext, dest_dir: Path) -> list[Path]:
    val_date = ctx.val_date
    pp = ctx.priced()

    rows: list[list[str]] = []
    for pt in pp.priced:
        td, v = pt.trade, pt.valuation
        rows.append([
            str(td.meta.get("id", td.trade_id)),   # Internal Reference Number
            "Reverse Swap",                         # Product
            "American Express Company",             # Legal Entity
            td.debt_counterparty or "",             # Counterparty
            "CME Clearing House",                    # Clearing House
            td.floating_index or "",                # Index
            mdy(td.deal_date),                      # Trade Date
            mdy(td.maturity_date),                  # Maturity Date
            num(td.notional),                       # Notional
            num(v.dv01),                            # DV01
            num(v.par_rate),                        # Key Rate
            num(v.clean),                           # Clean Price
            num(v.accrued),                         # Accrued Interest
            num(v.clean + v.accrued),               # Total Value
        ])

    out = write_feed(dest_dir / _filename(val_date), val_date, FIELDS, rows, _SUM_COLS)
    return [out]
