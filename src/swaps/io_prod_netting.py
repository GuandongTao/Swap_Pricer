"""IRS Netting CSV writer (KPMG Position Netting feed format).

One row per ``netting_id`` (NOT per trade): trades sharing a netting_id are
aggregated into a single Position-Netting row. Spec lives in
``Output_Format Netting.xlsx``.

Layout
------

    Row 1   5-cell HEADER:   H | <yyyymmdd run date (today)> | IRS_Netting_<val_date>-00001.csv | 00001 | KPMG
    Row 2   21 field-name column headers (see :data:`NETTING_FIELDS`)
    Row 3.. one row per netting_id present in the priced portfolio
    Last    FOOTER row: T | <n_trades> | blanks ... with column-letter sums at
            K (Gross DA), L (Gross DL), M (Netting Amount), N (Net DA), O (Net DL)

Aggregation
-----------
For trades sharing a netting_id::

    Gross DA       = sum( npv for npv > 0 )
    Gross DL       = sum( |npv| for npv < 0 )       # absolute value per spec
    Netting Amount = min(Gross DA, Gross DL)
    Net DA         = Gross DA - Netting Amount
    Net DL         = Gross DL - Netting Amount

A netting_id with only DA exposure (no offsetting DL) emits a row with
``Gross DL = Net DL = Netting Amount = 0`` and ``Net DA = Gross DA``
(symmetric for DL-only). See ``OPEN_QUESTIONS.md`` Q2c.

CCID (cols T / U)
-----------------
Two CCIDs per row, both built off the netting entity from the netting DB:

* Position Netting Asset CCID:      natural account ``192005``
* Position Netting Liability CCID:  natural account ``392004``

RC is looked up from the Entity Reference Report keyed by netting entity.
Both are emitted regardless of whether Net DA or Net DL is zero.

Hard errors (raised, never silently blanked):

* trade carries a netting_id that isn't in the netting DB
* netting DB row has a blank ``netting_entity``
* netting entity has no RC in the entity_rc lookup
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .io_prod import (
    CME_NAME, SOURCE_NAME, VERSION_STAMP, _CCID_TAIL, _fmt, _ccid,
)
from .loaders.base import TradeDef
from .netting_db import NettingRow
from .pricer import SwapValuation

# CCID natural-account codes specific to the netting feed (CCID_Netting.xlsx).
NAT_ACCT_NETTING_ASSET = "192005"
NAT_ACCT_NETTING_LIABILITY = "392004"

# Column order is taken from Output_Format Netting.xlsx (A..U, 21 fields).
NETTING_FIELDS: list[str] = [
    "Field",                                 # A   "Position Netting"
    "As of Date",                            # B   val_date
    "Product",                               # C   "IRS"
    "Entity",                                # D   netting DB AMEX Legal Entity name
    "Oracle Entity Code",                    # E   netting DB Netting Entity (1000/1021)
    "Counterparty",                          # F   netting DB External name
    "Counterparty Code",                     # G   blank
    "Payment Date",                          # H   blank
    "Maturity Date",                         # I   blank
    "Netting ID",                            # J   netting_id
    "Gross DA",                              # K   sum of positive NPVs        SUM
    "Gross DL",                              # L   sum of |negative NPVs|      SUM
    "Netting Amount",                        # M   min(Gross DA, Gross DL)     SUM
    "Net DA",                                # N   Gross DA - Netting Amount   SUM
    "Net DL",                                # O   Gross DL - Netting Amount   SUM
    "Counterparty Type",                     # P   CME -> FMU else Bank
    "Cash Flow Netting Allowed",             # Q   netting DB
    "Position Netting Allowed",              # R   netting DB
    "Netting Entity",                        # S   netting DB Netting Entity
    "Position Netting Asset CCID",           # T   {entity}-{rc}-192005-...
    "Position Netting Liability CCID",       # U   {entity}-{rc}-392004-...
]
N_NETTING_COLS = len(NETTING_FIELDS)
assert N_NETTING_COLS == 21, f"NETTING_FIELDS length must be 21 (got {N_NETTING_COLS})"

_NCOL = {name: i for i, name in enumerate(NETTING_FIELDS)}
_NETTING_SUM_COLS: tuple[int, ...] = (
    _NCOL["Gross DA"],          # K
    _NCOL["Gross DL"],          # L
    _NCOL["Netting Amount"],    # M
    _NCOL["Net DA"],            # N
    _NCOL["Net DL"],            # O
)


@dataclass
class _Group:
    """Per-netting_id accumulator."""
    netting_id: str
    trades: list[TradeDef]
    valuations: list[SwapValuation]

    @property
    def gross_da(self) -> float:
        return sum(v.dirty for v in self.valuations if v.dirty > 0)

    @property
    def gross_dl(self) -> float:
        # Absolute value per spec (Output_Format Netting.xlsx).
        return sum(-v.dirty for v in self.valuations if v.dirty < 0)


def netting_filename(val_date: date) -> str:
    """Spec filename: ``IRS_Netting_<YYYY-MM-DD>-00001.csv``."""
    return f"IRS_Netting_{val_date.isoformat()}-{VERSION_STAMP}.csv"


def _group_by_netting_id(
    trades_by_id: dict[str, TradeDef],
    valuations: list[SwapValuation],
) -> dict[str, _Group]:
    """Bucket priced trades by their ``netting_id``. Trades whose netting_id
    is blank are skipped (they don't belong on the netting feed)."""
    groups: dict[str, _Group] = {}
    for v in valuations:
        td = trades_by_id.get(v.trade_id)
        if td is None:
            continue
        nid = (td.netting_id or "").strip()
        if not nid:
            continue
        g = groups.get(nid)
        if g is None:
            g = _Group(netting_id=nid, trades=[], valuations=[])
            groups[nid] = g
        g.trades.append(td)
        g.valuations.append(v)
    return groups


def _row_for_group(
    g: _Group,
    val_date: date,
    netting_db: dict[str, NettingRow],
    entity_rc: dict[str, str],
) -> list[str]:
    nrow = netting_db.get(g.netting_id)
    if nrow is None:
        # Belt-and-suspenders: the prod CSV writer already raises on this,
        # but keep the check here so the netting writer is correct in
        # isolation (and produces the same error message).
        raise ValueError(
            f"netting_id {g.netting_id!r} not found in netting database; "
            f"every trade with a netting_id must resolve to a row in "
            f"entity/Netting_Database.csv."
        )

    netting_entity = (nrow.netting_entity or "").strip()
    if not netting_entity:
        raise ValueError(
            f"netting_id {g.netting_id!r}: netting database row has a blank "
            f"'Netting Entity' -- cannot build CCIDs."
        )
    rc = (entity_rc or {}).get(netting_entity, "")
    if not rc:
        raise ValueError(
            f"netting_id {g.netting_id!r}: no RC found for netting entity "
            f"{netting_entity!r} in the Entity Reference Report; cannot "
            f"build CCIDs."
        )

    is_cme = (nrow.external_name == CME_NAME)
    counterparty_type = "Financial Market Utility" if is_cme else "Bank"

    gross_da = g.gross_da
    gross_dl = g.gross_dl
    netting_amount = min(gross_da, gross_dl)
    net_da = gross_da - netting_amount
    net_dl = gross_dl - netting_amount

    asset_ccid = _ccid(netting_entity, rc, NAT_ACCT_NETTING_ASSET)
    liab_ccid = _ccid(netting_entity, rc, NAT_ACCT_NETTING_LIABILITY)

    cells: list[object | None] = [None] * N_NETTING_COLS
    cells[_NCOL["Field"]] = "Position Netting"
    cells[_NCOL["As of Date"]] = val_date
    cells[_NCOL["Product"]] = "IRS"
    cells[_NCOL["Entity"]] = nrow.amex_legal_entity_name
    cells[_NCOL["Oracle Entity Code"]] = netting_entity
    cells[_NCOL["Counterparty"]] = nrow.external_name
    cells[_NCOL["Netting ID"]] = g.netting_id
    cells[_NCOL["Gross DA"]] = gross_da
    cells[_NCOL["Gross DL"]] = gross_dl
    cells[_NCOL["Netting Amount"]] = netting_amount
    cells[_NCOL["Net DA"]] = net_da
    cells[_NCOL["Net DL"]] = net_dl
    cells[_NCOL["Counterparty Type"]] = counterparty_type
    cells[_NCOL["Cash Flow Netting Allowed"]] = nrow.cash_flow_netting_allowed
    cells[_NCOL["Position Netting Allowed"]] = nrow.position_netting_allowed
    cells[_NCOL["Netting Entity"]] = netting_entity
    cells[_NCOL["Position Netting Asset CCID"]] = asset_ccid
    cells[_NCOL["Position Netting Liability CCID"]] = liab_ccid
    return [_fmt(c) for c in cells]


def _footer(rows: list[list[str]], n_trades: int) -> list[str]:
    cells = [""] * N_NETTING_COLS
    cells[0] = "T"
    cells[1] = str(n_trades)
    for col_idx in _NETTING_SUM_COLS:
        s = 0.0
        for r in rows:
            v = r[col_idx]
            if v:
                try:
                    s += float(v)
                except ValueError:
                    pass
        cells[col_idx] = repr(s)
    return cells


def write_netting_csv(
    out_path: str | Path,
    trades_by_id: dict[str, TradeDef],
    valuations: list[SwapValuation],
    val_date: date,
    netting_db: dict[str, NettingRow],
    entity_rc: dict[str, str],
) -> Path:
    """Write the IRS Netting feed CSV.

    Only netting_ids that have at least one priced trade in this run are
    emitted (see OPEN_QUESTIONS.md Q2d). Matured trades (``v.dirty == 0``)
    still participate -- they contribute zero to both Gross DA and Gross DL.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header_row = [
        "H",
        date.today().strftime("%Y%m%d"),
        netting_filename(val_date),
        VERSION_STAMP,
        SOURCE_NAME,
    ]
    groups = _group_by_netting_id(trades_by_id, valuations)
    # Deterministic ordering -> sort by netting_id so reruns are diff-clean.
    rows: list[list[str]] = []
    n_trades = 0
    for nid in sorted(groups):
        g = groups[nid]
        rows.append(_row_for_group(g, val_date, netting_db, entity_rc))
        n_trades += len(g.trades)
    footer = _footer(rows, n_trades=n_trades)

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header_row)
        w.writerow(NETTING_FIELDS)
        for r in rows:
            w.writerow(r)
        w.writerow(footer)
    return out_path
