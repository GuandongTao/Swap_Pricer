"""Item: Month End Data (frequency = month-end, channel = email).

Emails a snapshot of the raw market-data inputs used for the month-end run:

  1. Used-curve extract -- the ``market_environment_<curve_date>.csv`` actually
     consumed in pricing, filtered to ONLY the two USD curves the model uses
     (``IR.USD-SOFR-ON.ZERORATE-*.MID`` and ``IR.USD-FEDFUNDS-ON.ZERORATE-*.MID``),
     with the vendor metadata header block dropped. The filename keeps the title
     of the source file used.
  2. Fixings input copy -- ``fixing_cail_USD-FEDFUNDS-ON.csv`` copied verbatim.

Curve-date fallback: on a weekend/holiday month-end the model prices off the
previous business day's curve (``month_end_curve_date``); the extract is taken
from -- and named after -- that actually-used file.
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from ..calendar_us import month_end_curve_date
from .base import RunContext

# Column-A identifiers of the two USD curves the model consumes.
_CURVE_ROW = re.compile(r"IR\.USD-(?:SOFR|FEDFUNDS)-ON\.ZERORATE-.*\.MID")

_FIXINGS_FILENAME = "fixing_cail_USD-FEDFUNDS-ON.csv"


def used_curve_date(val_date: date) -> date:
    """The as-of date of the curve file actually consumed for ``val_date``.

    Equals ``val_date`` on a business-day month-end; falls back to the previous
    business day (normally the prior Friday) when the month-end is a weekend or
    Fed holiday.
    """
    fallback = month_end_curve_date(val_date)
    return fallback if fallback is not None else val_date


def produce(ctx: RunContext, dest_dir: Path) -> list[Path]:
    val_date, data_dir = ctx.val_date, ctx.data_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # 1. Used-curve extract (filtered; metadata header dropped by virtue of the
    #    keep-only filter).
    curve_date = used_curve_date(val_date)
    curve_name = f"market_environment_{curve_date.isoformat()}.csv"
    src_curve = data_dir / "curves" / curve_name
    if not src_curve.exists():
        raise FileNotFoundError(
            f"Month End Data: curve file not found for {val_date} "
            f"(curve_date={curve_date}): {src_curve}"
        )
    kept = [
        line
        for line in src_curve.read_text(encoding="utf-8-sig").splitlines()
        if _CURVE_ROW.match(line)
    ]
    if not kept:
        raise ValueError(
            f"Month End Data: no USD curve rows matched in {src_curve}; "
            f"refusing to write an empty extract."
        )
    out_curve = dest_dir / curve_name
    out_curve.write_text("\n".join(kept) + "\n", encoding="utf-8")
    written.append(out_curve)

    # 2. Fixings input copy (verbatim).
    src_fix = data_dir / "fixings" / _FIXINGS_FILENAME
    if not src_fix.exists():
        raise FileNotFoundError(f"Month End Data: fixings file not found: {src_fix}")
    out_fix = dest_dir / _FIXINGS_FILENAME
    shutil.copyfile(src_fix, out_fix)
    written.append(out_fix)

    return written
