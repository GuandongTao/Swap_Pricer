"""Production CSV writer (KPMG IRS valuation feed format).

Layout (one file per run):

    Row 1   5-cell HEADER:   H | <yyyymmdd val_date> | IRS Valuation<val_date>-00001.csv | 00001 | KPMG
    Row 2   49 field-name column headers (see :data:`PROD_FIELDS`)
    Row 3.. one row per priced trade, 49 columns
    Last    FOOTER row: T | <n_trades> | blanks ... with column-letter sums at
            G/H/I/J/Q/R/U/V/W/AK/AL/AW

Encoding: UTF-8 (no BOM). Cells with commas/quotes are CSV-quoted by the
:mod:`csv` module's default :class:`csv.writer`.

The version stamp is hard-coded to ``"00001"`` per spec; we are not in
production yet and the consumer hasn't asked for an auto-increment scheme.

CME branch
==========
Several output fields branch on whether the trade's counterparty is the CME
Clearing House. The check is an **exact string equality** against
``"CME Clearing House"``; anything else (including ``"cme clearing house"``
or ``"CME"``) routes to the Bank / OTC-Bilateral branch. This is intentional
and documented in ``_template.csv.sample`` so users can't silently drift.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .loaders.base import TradeDef
from .pricer import SwapValuation

# --- Spec constants ----------------------------------------------------------
VERSION_STAMP = "00001"
SOURCE_NAME = "KPMG"
CME_NAME = "CME Clearing House"

# Field order MUST match Output_Format.xlsx exactly: column letters A..AW
# (49 fields). The footer-sum column-letter mapping (G/H/I/J, Q/R, U/V/W,
# AK/AL, AW) is derived from this order.
PROD_FIELDS: list[str] = [
    "Trade Reference Number",                       # A   blank
    "Internal Reference Number",                    # B   blank
    "Quantum Deal Number",                          # C   input
    "Oracle Entity Code",                           # D   input
    "Notional Currency",                            # E   input
    "As of Date",                                   # F   val_date
    "Clean price",                                  # G   v.clean         SUM
    "Accrued Interest",                             # H   v.accrued       SUM
    "Total Value (NPV)",                            # I   v.dirty         SUM
    "DV01",                                         # J   v.dv01          SUM
    "Valuation Currency",                           # K   "USD"
    "Child Reference Number (if applicable)",       # L   blank
    "Period Start Date",                            # M   blank
    "Period End Date",                              # N   blank
    "Period Payment Date",                          # O   blank
    "Maturity Date",                                # P   td.maturity_date
    "Notional 1 Amount",                            # Q   td.notional     SUM
    "Notional 1 Amount USD",                        # R   td.notional     SUM
    "Pay_Rec Status",                               # S   blank
    "Component Type",                               # T   blank
    "Coupon FV (Future Value)",                     # U   blank           SUM (=0)
    "Intrinsic Value FV (Future Value)",            # V   blank           SUM (=0)
    "Time Value FV (Future Value)",                 # W   blank           SUM (=0)
    "Intercompany Trade",                           # X   Yes/No
    "Counterparty Name - Internal Quantum Name",    # Y   input
    "Current Counterparty",                         # Z   input
    "Entity Name - Internal Quantum Name",          # AA  input
    "Reporting Party",                              # AB  input
    "InternalFacing-StreetFacing",                  # AC  blank
    "Product",                                      # AD  "IR"
    "Sub-Product2",                                 # AE  CME -> Centralized else Bilateral
    "Collateral Level",                             # AF  "Fully Collateralized"
    "Counterparty Code",                            # AG  blank
    "Counterparty Type",                            # AH  CME -> FMU else Bank
    "Counterparty Location",                        # AI  input
    "HCL Type",                                     # AJ  "Interest Rate Swap"
    "DA",                                           # AK  npv if >0 else blank  SUM
    "DL",                                           # AL  npv if <0 else blank  SUM
    "Asset_Liability Tag",                          # AM  Asset/Liability/blank
    "Qualifying Central Counterparty Indicator",    # AN  YES/NO
    "Cleared Transaction indicator",                # AO  YES/NO
    "Cash Settled CCP indicator",                   # AP  YES/NO
    "Deal Date",                                    # AQ  td.deal_date
    "Netting ID",                                   # AR  input
    "Cash Flow Netting Allowed",                    # AS  input
    "Position Netting Allowed",                     # AT  input
    "Balance Sheet CCID",                           # AU  blank
    "PL/OCI CCID",                                  # AV  blank
    "Hedged Debt MTM",                              # AW  v.pv_fixed       SUM
]
N_COLS = len(PROD_FIELDS)              # 49
assert N_COLS == 49, f"PROD_FIELDS length must be 49 (got {N_COLS})"

# 0-based column indices, mirroring the spreadsheet letters used in the spec.
_COL = {name: i for i, name in enumerate(PROD_FIELDS)}
_SUM_COLS: tuple[int, ...] = (
    _COL["Clean price"],                # G
    _COL["Accrued Interest"],           # H
    _COL["Total Value (NPV)"],          # I
    _COL["DV01"],                       # J
    _COL["Notional 1 Amount"],          # Q
    _COL["Notional 1 Amount USD"],      # R
    _COL["Coupon FV (Future Value)"],            # U
    _COL["Intrinsic Value FV (Future Value)"],   # V
    _COL["Time Value FV (Future Value)"],        # W
    _COL["DA"],                         # AK
    _COL["DL"],                         # AL
    _COL["Hedged Debt MTM"],            # AW
)


def _fmt(v) -> str:
    """Render a value for the CSV. ``None`` / NaN -> blank string."""
    if v is None:
        return ""
    if isinstance(v, float):
        # NaN -> blank (matched-on-input matures, missing par, etc.)
        if v != v:
            return ""
        return repr(v) if abs(v) >= 1e16 else format(v, "g")  # 'g' trims trailing zeros
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _row_for(td: TradeDef, v: SwapValuation, val_date: date) -> list[str]:
    is_cme = (td.current_counterparty == CME_NAME)
    npv = v.dirty
    da = npv if npv > 0 else None
    dl = npv if npv < 0 else None
    if npv > 0:
        al_tag: str | None = "Asset"
    elif npv < 0:
        al_tag = "Liability"
    else:
        al_tag = ""  # exactly zero -> leave blank rather than guessing

    sub_product2 = "OTC - Centralized (Principal)" if is_cme else "OTC - Bilateral"
    counterparty_type = "Financial Market Utility" if is_cme else "Bank"
    cme_indicator = "YES" if is_cme else "NO"

    cells: list[object | None] = [None] * N_COLS
    # Direct fills (positions match PROD_FIELDS exactly).
    cells[_COL["Quantum Deal Number"]] = td.quantum_deal_number
    cells[_COL["Oracle Entity Code"]] = td.oracle_entity_code
    cells[_COL["Notional Currency"]] = td.notional_currency
    cells[_COL["As of Date"]] = val_date
    cells[_COL["Clean price"]] = v.clean
    cells[_COL["Accrued Interest"]] = v.accrued
    cells[_COL["Total Value (NPV)"]] = npv
    cells[_COL["DV01"]] = v.dv01
    cells[_COL["Valuation Currency"]] = "USD"
    cells[_COL["Maturity Date"]] = td.maturity_date
    cells[_COL["Notional 1 Amount"]] = td.notional
    cells[_COL["Notional 1 Amount USD"]] = td.notional
    cells[_COL["Intercompany Trade"]] = "Yes" if td.intercompany else "No"
    cells[_COL["Counterparty Name - Internal Quantum Name"]] = td.counterparty_name_quantum
    cells[_COL["Current Counterparty"]] = td.current_counterparty
    cells[_COL["Entity Name - Internal Quantum Name"]] = td.entity_name_quantum
    cells[_COL["Reporting Party"]] = td.reporting_party
    cells[_COL["Product"]] = "IR"
    cells[_COL["Sub-Product2"]] = sub_product2
    cells[_COL["Collateral Level"]] = "Fully Collateralized"
    cells[_COL["Counterparty Type"]] = counterparty_type
    cells[_COL["Counterparty Location"]] = td.counterparty_location
    cells[_COL["HCL Type"]] = "Interest Rate Swap"
    cells[_COL["DA"]] = da
    cells[_COL["DL"]] = dl
    cells[_COL["Asset_Liability Tag"]] = al_tag
    cells[_COL["Qualifying Central Counterparty Indicator"]] = cme_indicator
    cells[_COL["Cleared Transaction indicator"]] = cme_indicator
    cells[_COL["Cash Settled CCP indicator"]] = cme_indicator
    cells[_COL["Deal Date"]] = td.deal_date
    cells[_COL["Netting ID"]] = td.netting_id
    cells[_COL["Cash Flow Netting Allowed"]] = td.cash_flow_netting_allowed
    cells[_COL["Position Netting Allowed"]] = td.position_netting_allowed
    cells[_COL["Hedged Debt MTM"]] = v.pv_fixed
    return [_fmt(c) for c in cells]


def _footer(rows: list[list[str]], n_trades: int) -> list[str]:
    cells = [""] * N_COLS
    cells[0] = "T"
    cells[1] = str(n_trades)
    for col_idx in _SUM_COLS:
        s = 0.0
        for r in rows:
            v = r[col_idx]
            if v:
                try:
                    s += float(v)
                except ValueError:
                    pass
        cells[col_idx] = format(s, "g")
    return cells


def prod_filename(val_date: date) -> str:
    """Spec filename: ``IRS Valuation<YYYY-MM-DD>-00001.csv``."""
    return f"IRS Valuation{val_date.isoformat()}-{VERSION_STAMP}.csv"


def write_prod_csv(
    out_path: str | Path,
    trades_by_id: dict[str, TradeDef],
    valuations: list[SwapValuation],
    val_date: date,
) -> Path:
    """Write the prod feed CSV.

    Matured trades (``v.meta['matured']`` truthy) are still emitted with
    pricing fields = 0; the row is included in the trade count and sums.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header_row = [
        "H",
        val_date.strftime("%Y%m%d"),
        prod_filename(val_date),
        VERSION_STAMP,
        SOURCE_NAME,
    ]
    rows: list[list[str]] = []
    for v in valuations:
        td = trades_by_id.get(v.trade_id)
        if td is None:
            # Trade definition not provided (shouldn't happen in normal runs);
            # emit a stub row with pricing-only values to preserve column alignment.
            td = TradeDef(
                trade_id=v.trade_id, notional=v.meta.get("notional", 0.0),
                pay_fixed=False, fixed_rate=v.meta.get("fixed_rate", 0.0),
                start_date=v.meta.get("start_date", val_date),
                maturity_date=v.meta.get("maturity_date", val_date),
                fixed_frequency="1Y", fixed_daycount="ACT/360",
            )
        rows.append(_row_for(td, v, val_date))
    footer = _footer(rows, n_trades=len(rows))

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header_row)
        w.writerow(PROD_FIELDS)
        for r in rows:
            w.writerow(r)
        w.writerow(footer)
    return out_path
