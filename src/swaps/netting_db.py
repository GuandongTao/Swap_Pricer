"""Netting Database loader.

Reads ``entity/Netting_Database.csv`` and exposes a ``netting_id -> NettingRow``
lookup. The DB is the single source of truth for the per-netting-group
fields that used to be carried on each trade row:

* ``cash_flow_netting_allowed``   (= column "Multiple Transactions Netting Allowed")
* ``position_netting_allowed``
* ``netting_entity``               (Amex legal-entity code, e.g. ``1000`` / ``1021``)
* ``amex_legal_entity_name``       (used as the "Entity" cell on the netting feed)
* ``external_name``                 (counterparty legal name)

File shape: row 1 is a free-form title row that the CSV emitter spits out;
row 2 is the column-header row. We skip row 1 and key on the row-2 names.

Blank cells are kept as ``""``. Lookups against a missing key raise
``KeyError`` so callers can convert that to a hard input-validation error
analogous to a missing maturity date.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


# Column names taken from row 2 of ``Netting_Database.csv``. Keep these as
# constants so a header rename in the upstream CSV surfaces as a clear error
# (KeyError on the dict lookup below) rather than silent miswiring.
_COL_NETTING_ID = "Netting ID"
_COL_POSITION_NETTING = "Position Netting Allowed"
_COL_CASH_FLOW_NETTING = "Multiple Transactions Netting Allowed"
_COL_NETTING_ENTITY = "Netting Entity"
_COL_AMEX_LEGAL_NAME = "AMEX Legal Entity name"
_COL_EXTERNAL_NAME = "External name"
_COL_PRODUCT = "Product"

# We only consume Swap rows; FX rows in the same workbook are ignored.
_PRODUCT_KEEP = "Swap"


@dataclass(frozen=True)
class NettingRow:
    netting_id: str
    cash_flow_netting_allowed: str
    position_netting_allowed: str
    netting_entity: str
    amex_legal_entity_name: str
    external_name: str


def load_netting_db(path: str | Path) -> dict[str, NettingRow]:
    """Parse the netting database CSV into ``{netting_id: NettingRow}``.

    Raises:
        FileNotFoundError: file missing.
        ValueError:        duplicate netting_id, or a required column missing
                           from the header row.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Netting database not found: {p}")

    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        rows = [r for r in reader]

    if len(rows) < 2:
        raise ValueError(f"{p}: expected a title row and a header row")
    # Row 0 is the free-form title row; row 1 is the column header.
    header = [c.strip() for c in rows[1]]
    required = {
        _COL_NETTING_ID, _COL_POSITION_NETTING, _COL_CASH_FLOW_NETTING,
        _COL_NETTING_ENTITY, _COL_AMEX_LEGAL_NAME, _COL_EXTERNAL_NAME,
        _COL_PRODUCT,
    }
    missing = required - set(header)
    if missing:
        raise ValueError(
            f"{p}: header row 2 missing required columns: {sorted(missing)}; "
            f"got {header}"
        )
    idx = {name: header.index(name) for name in required}

    out: dict[str, NettingRow] = {}
    for r in rows[2:]:
        if not any((c or "").strip() for c in r):
            continue
        # CSV rows can be shorter than the header if trailing cells are empty.
        def cell(name: str) -> str:
            i = idx[name]
            return (r[i].strip() if i < len(r) and r[i] is not None else "")
        # IRS pricer only consumes Swap-product rows; skip FX silently. The
        # same physical file feeds both pipelines and FX netting_ids overlap
        # the swap ones only by coincidence.
        if cell(_COL_PRODUCT).casefold() != _PRODUCT_KEEP.casefold():
            continue
        nid = cell(_COL_NETTING_ID)
        if not nid:
            continue
        if nid in out:
            raise ValueError(f"{p}: duplicate netting_id {nid!r}")
        out[nid] = NettingRow(
            netting_id=nid,
            cash_flow_netting_allowed=cell(_COL_CASH_FLOW_NETTING),
            position_netting_allowed=cell(_COL_POSITION_NETTING),
            netting_entity=cell(_COL_NETTING_ENTITY),
            amex_legal_entity_name=cell(_COL_AMEX_LEGAL_NAME),
            external_name=cell(_COL_EXTERNAL_NAME),
        )
    return out
