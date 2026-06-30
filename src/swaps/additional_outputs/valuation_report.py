"""Item 9: KPMG Valuation Report (daily, SFTP).

H/T feed (same envelope as the IRS Valuation feed) over ALL IRS positions.
Columns per ``Valuation Report.xlsx``.

ASSUMPTIONS (confirm — see _intake.md):
* Internal Reference Number = the IRS raw deal id.
* Legal Entity / Clearing House / Product are hard-coded constants per the sample.
* Key Rate = par rate; Total Value = clean + accrued.
* Plain CSV (field-name row + data rows; no H/T, no footer); dates mm/dd/yyyy.
* Written to the SFTP run folder AND copied into the email/ subfolder.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .base import Channel, RunContext, resolve_channel_dir
from .envelope import write_table_csv
from .helpers import mdy, num

FIELDS = [
    "Internal Reference Number", "Product", "Legal Entity", "Counterparty",
    "Clearing House", "Index", "Trade Date", "Maturity Date", "Notional",
    "DV01", "Key Rate", "Clean Price", "Accrued Interest", "Total Value",
]


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

    name = _filename(val_date)
    written = [write_table_csv(dest_dir / name, FIELDS, rows)]
    # Also drop a copy in the email/ subfolder of the run folder.
    email_dir = resolve_channel_dir(Channel.EMAIL, ctx.run_dir)
    written.append(write_table_csv(email_dir / name, FIELDS, rows))
    return written
