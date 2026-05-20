"""Dated-pillars curve loader.

Alternate input path activated by the ``--pillar-dates`` CLI flag. Two CSVs
per valuation date in ``data/curves/``:

    sofr_YYYY-MM-DD.csv     -> SOFR (discount)
    ff_YYYY-MM-DD.csv       -> FEDFUNDS (projection)

Format per file: NO header. Column A = pillar date (ISO ``YYYY-MM-DD``).
Column B = zero rate as a decimal (e.g. ``0.0361`` = 3.61%). No ticker
filtering or row stripping: every non-empty row is a pillar.

Bypasses ``tenor_to_date`` entirely: the pillar date is taken as given and
fed straight into :py:meth:`ZeroCurve.from_dated_pillars`. Quoting
convention and interpolation are identical to the tenor-keyed path.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from ..curve import ZeroCurve
from ..rate_quoting import DEFAULT, RateQuoting
from .base import CurveLoader

_CANONICAL = {"SOFR": "sofr", "FEDFUNDS": "ff", "FF": "ff", "FED_FUNDS": "ff"}
_CANONICAL_DF = {"SOFR": "sofr_df", "FEDFUNDS": "ff_df", "FF": "ff_df", "FED_FUNDS": "ff_df"}


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


class DatedCurveLoader(CurveLoader):
    def __init__(self, base_dir: str | Path, rate_quoting: RateQuoting | None = None) -> None:
        self.base_dir = Path(base_dir)
        self.rate_quoting = rate_quoting or DEFAULT

    def _file_path(self, val_date: date, curve_name: str) -> Path:
        prefix = _CANONICAL.get(curve_name.upper())
        if prefix is None:
            raise ValueError(
                f"Unknown curve_name {curve_name!r}; expected one of {sorted(_CANONICAL)}"
            )
        p = self.base_dir / f"{prefix}_{val_date.strftime('%Y-%m-%d')}.csv"
        if not p.exists():
            raise FileNotFoundError(
                f"Dated curve file not found: {p} (--pillar-dates expects "
                f"{prefix}_{val_date.strftime('%Y-%m-%d')}.csv)"
            )
        return p

    def _read_pillars(self, path: Path) -> dict[date, float]:
        out: dict[date, float] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for lineno, row in enumerate(csv.reader(fh), start=1):
                if not row or not row[0].strip():
                    continue
                if len(row) < 2:
                    raise ValueError(f"{path}:{lineno} expected 2 columns; got {row!r}")
                try:
                    d = _parse_date(row[0])
                    r = float(row[1])
                except ValueError as e:
                    raise ValueError(
                        f"{path}:{lineno} bad pillar row {row!r}: {e}"
                    ) from e
                if d in out:
                    raise ValueError(f"{path}:{lineno} duplicate pillar date {d}")
                out[d] = r
        if not out:
            raise ValueError(f"{path}: no pillars parsed")
        return out

    def load(self, val_date: date, curve_name: str) -> ZeroCurve:
        path = self._file_path(val_date, curve_name)
        pillars = self._read_pillars(path)
        canonical = "SOFR" if _CANONICAL[curve_name.upper()] == "sofr" else "FEDFUNDS"
        return ZeroCurve.from_dated_pillars(
            val_date, pillars, rate_quoting=self.rate_quoting, name=canonical,
        )


class DatedDFCurveLoader(CurveLoader):
    """Directly take discount factors per pillar date -- bypasses RateQuoting.

    Files: ``sofr_df_YYYY-MM-DD.csv`` and ``ff_df_YYYY-MM-DD.csv`` in the
    curve directory. NO header. Col A = pillar date (ISO). Col B = DF
    (positive float, typically <= 1.0).
    """

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def _file_path(self, val_date: date, curve_name: str) -> Path:
        prefix = _CANONICAL_DF.get(curve_name.upper())
        if prefix is None:
            raise ValueError(
                f"Unknown curve_name {curve_name!r}; expected one of {sorted(_CANONICAL_DF)}"
            )
        p = self.base_dir / f"{prefix}_{val_date.strftime('%Y-%m-%d')}.csv"
        if not p.exists():
            raise FileNotFoundError(
                f"Dated-DF curve file not found: {p} (--pillar-dates-df expects "
                f"{prefix}_{val_date.strftime('%Y-%m-%d')}.csv)"
            )
        return p

    def _read_pillars(self, path: Path) -> dict[date, float]:
        out: dict[date, float] = {}
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for lineno, row in enumerate(csv.reader(fh), start=1):
                if not row or not row[0].strip():
                    continue
                if len(row) < 2:
                    raise ValueError(f"{path}:{lineno} expected 2 columns; got {row!r}")
                try:
                    d = _parse_date(row[0])
                    df = float(row[1])
                except ValueError as e:
                    raise ValueError(f"{path}:{lineno} bad pillar row {row!r}: {e}") from e
                if d in out:
                    raise ValueError(f"{path}:{lineno} duplicate pillar date {d}")
                if df <= 0.0:
                    raise ValueError(f"{path}:{lineno} DF must be > 0; got {df}")
                out[d] = df
        if not out:
            raise ValueError(f"{path}: no pillars parsed")
        return out

    def load(self, val_date: date, curve_name: str) -> ZeroCurve:
        path = self._file_path(val_date, curve_name)
        pillars = self._read_pillars(path)
        canonical = "SOFR" if _CANONICAL_DF[curve_name.upper()] == "sofr_df" else "FEDFUNDS"
        return ZeroCurve.from_dated_dfs(val_date, pillars, name=canonical)
