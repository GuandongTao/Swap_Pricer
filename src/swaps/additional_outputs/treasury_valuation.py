"""Item 3: Treasury Valuation Report (month-end, SFTP).

H/T feed (same envelope as the IRS Valuation feed) over ALL IRS positions.
Columns per ``Treasury Report.xlsx``.

ASSUMPTIONS (confirm — see _intake.md open questions):
* Internal Reference Number = the IRS raw deal id (``meta['id']`` / trade_id).
* Total Value = clean + accrued (= dirty).
* Total Value Change = this Total Value minus the SAME deal's Total Value in the
  previous month-end's Treasury report found in the SFTP dir; blank if no prior.
* Pmt-frequency cells use a tenor->word map (3M->Quarterly, 6M->Semi-annually...).
* Index cell = the ``floating_index`` input passthrough.
* Footer sums the monetary columns.
* Dates rendered mm/dd/yyyy (prod-CSV convention).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from ..calendar_us import is_month_end
from .base import RunContext
from .envelope import read_feed_column, write_feed
from .helpers import freq_label, mdy, num

FIELDS = [
    "Internal Reference Number", "Product", "Hedged Item", "Counterparty",
    "Clearing House", "Trade Date", "Effective Date", "Maturity Date",
    "Hedged Item Notional", "Total Value Change", "DV01", "Clean Price",
    "Accrued Interest", "Total Value", "Floating Pmt Frequency", "Index",
    "Current Spread", "Fixed Pmt Frequency", "Fixed Rate", "Notional",
]
_REF, _TOTAL_VALUE = 0, 13
_SUM_COLS = [8, 9, 10, 11, 12, 13, 19]  # notional/change/dv01/clean/accrued/total/notional


def _filename(val_date: date) -> str:
    return f"American Express {val_date:%b %d, %Y} Treasury Valuation Report.csv"


def _prev_month_end(d: date) -> date:
    first = d.replace(day=1)
    return first - timedelta(days=1)


_VER_RE = re.compile(r"_ver_(\d+)")


def _ver_key(p: Path) -> tuple[int, float]:
    """Sort key: submission version in the run-folder name, then mtime as tiebreak."""
    m = _VER_RE.search(p.parent.name)
    return (int(m.group(1)) if m else -1, p.stat().st_mtime)


def _prior_total_values(out_root: Path, val_date: date) -> dict[str, str]:
    """Total Value by Internal Reference Number from the previous month's report.

    Each run writes into its own dated ``..._ver_<NNNNN>/`` folder, so a month-end
    can have several re-run versions. Search the output root recursively for the
    previous month-end's report and use the HIGHEST submission version (the
    latest re-issue), not merely the most recently touched file.
    """
    prev_name = _filename(_prev_month_end(val_date))
    matches = sorted(Path(out_root).rglob(prev_name), key=_ver_key)
    if not matches:
        return {}
    return read_feed_column(matches[-1], key_col=_REF, value_col=_TOTAL_VALUE)


def produce(ctx: RunContext, dest_dir: Path) -> list[Path]:
    val_date = ctx.val_date
    pp = ctx.priced()
    prior = _prior_total_values(ctx.out_root, val_date)

    rows: list[list[str]] = []
    for pt in pp.priced:
        td, v = pt.trade, pt.valuation
        ref = str(td.meta.get("id", td.trade_id))
        total_value = v.clean + v.accrued

        change = ""
        if ref in prior:
            try:
                change = num(total_value - float(prior[ref]))
            except (ValueError, TypeError):
                change = ""

        float_freq = td.floating_frequency or td.fixed_frequency
        rows.append([
            ref,                                    # Internal Reference Number
            "Reverse Swap",                         # Product
            "",                                     # Hedged Item
            td.debt_counterparty or "",             # Counterparty
            "CME Clearing House",                    # Clearing House
            mdy(td.deal_date),                      # Trade Date
            mdy(td.start_date),                     # Effective Date
            mdy(td.maturity_date),                  # Maturity Date
            num(td.notional),                       # Hedged Item Notional
            change,                                 # Total Value Change
            num(v.dv01),                            # DV01
            num(v.clean),                           # Clean Price
            num(v.accrued),                         # Accrued Interest
            num(total_value),                       # Total Value
            freq_label(float_freq),                 # Floating Pmt Frequency
            td.floating_index or "",                # Index
            num(td.floating_spread),                # Current Spread
            freq_label(td.fixed_frequency),         # Fixed Pmt Frequency
            num(td.fixed_rate),                     # Fixed Rate
            num(td.notional),                       # Notional
        ])

    out = write_feed(dest_dir / _filename(val_date), val_date, FIELDS, rows, _SUM_COLS)
    return [out]
