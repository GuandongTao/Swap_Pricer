"""Item 2: Hedge Summary (monthly = month-end, SFTP).

Plain CSV (header row + one row per IRS position) per ``Hedge Sumary.xlsx``.
NOT the IRS-Valuation H/T feed (no such instruction).

CONFIRMED (2026-06-30):
* Monthly == month-end (last calendar day).
* Plain CSV output.
* Strike = raw fixed rate from the input (no special formatting).
* Key Rate = par rate as of the month-end valuation date.
Other constants (Legal Entity / Clearing House / Product) hard-coded per sample.
Spread = floating spread in bps, 2dp + " bps". Intrinsic = Termination = dirty.
Alias = "<YYYY-MM of trade date> IR Swap <ccy> $<notional> - CME".
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from .base import RunContext
from .helpers import _as_date, mdy, num

FIELDS = [
    "Internal Reference Number", "Trade Date", "Effective Date", "Maturity Date",
    "Notional Currency", "Notional", "Product", "Index", "Spread", "Strike",
    "Counterparty", "Clearing House", "Legal Entity", "Hedged Item", "Alias",
    "Accrued Interest", "Clean Price", "Intrinsic Value", "Key Rate",
    "Termination Value", "Valuation Timestamp",
]


def _filename(val_date: date) -> str:
    return f"Hedge Summary {val_date:%b %d, %Y}.csv"


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
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows: list[list[str]] = [FIELDS]
    for pt in pp.priced:
        td, v = pt.trade, pt.valuation
        dirty = v.clean + v.accrued
        rows.append([
            str(td.meta.get("id", td.trade_id)),     # Internal Reference Number
            mdy(td.deal_date),                       # Trade Date
            mdy(td.start_date),                      # Effective Date
            mdy(td.maturity_date),                   # Maturity Date
            td.notional_currency or "USD",           # Notional Currency
            num(td.notional),                        # Notional
            "Reverse Swap",                          # Product
            td.floating_index or "",                 # Index
            _fmt_spread_bps(td.floating_spread),     # Spread (bps)
            num(td.fixed_rate),                      # Strike (raw fixed rate)
            td.debt_counterparty or "",              # Counterparty
            "CME Clearing House",                     # Clearing House
            "American Express Company",               # Legal Entity
            td.debt_cusip or "",                     # Hedged Item
            _alias(td),                              # Alias
            num(v.accrued),                          # Accrued Interest
            num(v.clean),                            # Clean Price
            num(dirty),                              # Intrinsic Value
            num(v.par_rate),                         # Key Rate
            num(dirty),                              # Termination Value
            now,                                     # Valuation Timestamp
        ])

    out = dest_dir / _filename(ctx.val_date)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return [out]
