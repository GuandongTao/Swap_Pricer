"""Item 2: Hedge Summary (monthly, SFTP).

Plain Excel workbook (header row + one row per IRS position) per
``Hedge Sumary.xlsx``. NOT the IRS-Valuation H/T feed (no such instruction; the
example is an .xlsx).

ASSUMPTIONS (confirm — see _intake.md):
* xlsx (not csv); "Monthly" coded as month-end (cadence undefined — confirm).
* Legal Entity / Clearing House / Product hard-coded per the sample.
* Spread = floating spread in bps, 2dp, "<x> bps". Strike = raw fixed rate
  (instruction says "2-decimal % format" but the sample shows the raw rate).
* Intrinsic Value = Termination Value = dirty (clean + accrued); Key Rate = par.
* Alias = "<YYYY-MM of trade date> IR Swap <ccy> $<notional> - CME".
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from .base import RunContext
from .helpers import _as_date, xldate, xlnum

FIELDS = [
    "Internal Reference Number", "Trade Date", "Effective Date", "Maturity Date",
    "Notional Currency", "Notional", "Product", "Index", "Spread", "Strike",
    "Counterparty", "Clearing House", "Legal Entity", "Hedged Item", "Alias",
    "Accrued Interest", "Clean Price", "Intrinsic Value", "Key Rate",
    "Termination Value", "Valuation Timestamp",
]


def _filename(val_date: date) -> str:
    return f"Hedge Summary {val_date:%b %d, %Y}.xlsx"


def _fmt_spread_bps(spread: float) -> str:
    return f"{(spread or 0.0) * 1e4:.2f} bps"


def _fmt_notional(n: float) -> str:
    """1.2B / 450MM style. Billions keep 1dp; millions drop a trailing .0."""
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}".rstrip("0").rstrip(".") + "MM"
    return f"{n:.0f}"


def _alias(td) -> str:
    d = _as_date(td.deal_date)
    ym = d.strftime("%Y-%m") if d else ""
    ccy = td.notional_currency or "USD"
    return f"{ym} IR Swap {ccy} ${_fmt_notional(float(td.notional))} - CME"


def produce(ctx: RunContext, dest_dir: Path) -> list[Path]:
    pp = ctx.priced()
    dest_dir.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Hedge Summary"
    ws.append(FIELDS)
    now = datetime.now()
    for pt in pp.priced:
        td, v = pt.trade, pt.valuation
        dirty = v.clean + v.accrued
        ws.append([
            str(td.meta.get("id", td.trade_id)),     # Internal Reference Number
            xldate(td.deal_date),                    # Trade Date
            xldate(td.start_date),                   # Effective Date
            xldate(td.maturity_date),                # Maturity Date
            td.notional_currency or "USD",           # Notional Currency
            xlnum(td.notional),                      # Notional
            "Reverse Swap",                          # Product
            td.floating_index or "",                 # Index
            _fmt_spread_bps(td.floating_spread),     # Spread (bps)
            xlnum(td.fixed_rate),                    # Strike
            td.debt_counterparty or "",              # Counterparty
            "CME Clearing House",                     # Clearing House
            "American Express Company",               # Legal Entity
            td.debt_cusip or "",                     # Hedged Item
            _alias(td),                              # Alias
            xlnum(v.accrued),                        # Accrued Interest
            xlnum(v.clean),                          # Clean Price
            xlnum(dirty),                            # Intrinsic Value
            xlnum(v.par_rate),                       # Key Rate
            xlnum(dirty),                            # Termination Value
            now,                                     # Valuation Timestamp
        ])

    out = dest_dir / _filename(ctx.val_date)
    wb.save(out)
    return [out]
