"""Generate a synthetic CurvesYYYYMMDD.xlsx file.

Used to (re)create the test-suite sample data without exposing real market
data. Layout matches what ExcelCurveLoader expects:
  Sheet1 with rows of (IR.USD-{SOFR|FEDFUNDS}-ON.ZERORATE-{TENOR}.MID, rate)
Flat 4.00% SOFR / 3.50% FF across all 48 tenors per curve.

Usage:
    python scripts/generate_synthetic_curve.py
    python scripts/generate_synthetic_curve.py --out path/to/CurvesYYYYMMDD.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]

TENORS = (
    ["ON", "TN", "1W", "2W", "3W"]
    + [f"{n}M" for n in range(1, 12)]
    + [f"{n}Y" for n in range(1, 31)]
    + ["40Y", "50Y"]
)
assert len(TENORS) == 48


def write_curve_file(out_path: Path, sofr_rate: float = 0.04, ff_rate: float = 0.035) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for t in TENORS:
        ws.append([f"IR.USD-SOFR-ON.ZERORATE-{t}.MID", sofr_rate])
    for t in TENORS:
        ws.append([f"IR.USD-FEDFUNDS-ON.ZERORATE-{t}.MID", ff_rate])
    wb.save(out_path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(ROOT / "tests" / "sample_data" / "curves" / "Curves20260331.xlsx"))
    p.add_argument("--sofr", type=float, default=0.04)
    p.add_argument("--ff", type=float, default=0.035)
    a = p.parse_args()
    write_curve_file(Path(a.out), a.sofr, a.ff)
    print(f"Wrote synthetic curve to {a.out}  (SOFR={a.sofr}, FF={a.ff})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
