"""Generic KPMG IRS-Valuation-style H/T feed envelope.

Reuses the default feed's header/footer SHAPE for items that ask to "use the same
header and footer format for irs valuation" (Treasury Valuation, Payment Report),
but with each item's own column set, filename, and footer-sum columns.

Layout (matches ``swaps.io_prod``):
    Row 1   H | <yyyymmdd val_date> | <filename> | <version> | KPMG
    Row 2   field-name header row
    Row 3.. data rows
    Last    T | <n_rows> | ... with sums in the requested numeric columns
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

from ..io_prod import SOURCE_NAME, VERSION_STAMP, write_csv_no_trailing_newline


def _sum_cell(rows: Sequence[Sequence[str]], col: int) -> str:
    total = 0.0
    seen = False
    for r in rows:
        if col >= len(r):
            continue
        try:
            total += float(str(r[col]).replace(",", ""))
            seen = True
        except (ValueError, TypeError):
            continue
    if not seen:
        return ""
    return str(int(total)) if float(total).is_integer() else f"{total:.6f}".rstrip("0").rstrip(".")


def write_feed(
    out_path: Path,
    val_date: date,
    field_names: Sequence[str],
    rows: Sequence[Sequence[str]],
    sum_cols: Sequence[int] = (),
    version: str = VERSION_STAMP,
) -> Path:
    """Write an H/T feed file. Returns the path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = ["H", val_date.strftime("%Y%m%d"), out_path.name, version, SOURCE_NAME]

    n = len(field_names)
    footer = [""] * n
    footer[0] = "T"
    if n > 1:
        footer[1] = str(len(rows))
    for c in sum_cols:
        if 0 <= c < n:
            footer[c] = _sum_cell(rows, c)

    write_csv_no_trailing_newline(out_path, [header, list(field_names), *[list(r) for r in rows], footer])
    return out_path


def read_feed_column(path: Path, key_col: int, value_col: int) -> dict[str, str]:
    """Read a previously-written H/T feed: map data-row[key_col] -> data-row[value_col].

    Skips the H header, the field-name row, and the T footer. Defensive: returns
    ``{}`` on any problem. Used for the Treasury report's prior-month diff.
    """
    import csv

    out: dict[str, str] = {}
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            reader = list(csv.reader(fh))
    except OSError:
        return {}
    for r in reader:
        if not r:
            continue
        if r[0] in ("H", "T"):
            continue
        if key_col < len(r) and value_col < len(r):
            k = str(r[key_col]).strip()
            if k and k != "Internal Reference Number":  # skip the field-name row
                out[k] = str(r[value_col]).strip()
    return out
