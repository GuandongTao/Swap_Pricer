"""Generate a synthetic ``market_environment_YYYY-MM-DD.csv`` file.

Used to (re)create test-suite / dev sample data without exposing real market
data. Layout matches the raw production export ExcelCurveLoader expects:
  * a few non-data header rows (Name / Date / Property...) in column A,
  * a handful of irrelevant pillars interleaved (so the col-A filter is
    actually exercised),
  * rows of (IR.USD-{SOFR|FEDFUNDS}-ON.ZERORATE-{TENOR}.MID, rate).
Flat 4.00% SOFR / 3.50% FF across all 48 tenors per curve.

Usage:
    python scripts/generate_synthetic_curve.py
    python scripts/generate_synthetic_curve.py --val-date 2026-03-31 --out path/to/market_environment_2026-03-31.csv
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TENORS = (
    ["ON", "TN", "1W", "2W", "3W"]
    + [f"{n}M" for n in range(1, 12)]
    + [f"{n}Y" for n in range(1, 31)]
    + ["40Y", "50Y"]
)
assert len(TENORS) == 48

# Irrelevant pillars, included so the col-A TICKER_RE filter is exercised.
JUNK_ROWS = [
    ("IR.AUD-BBSW-6M.ZERORATE-10Y.MID", 0.050331254),
    ("EQ.USD-NYQ-WMT.SPOT.VOL::6M::0.900::STRIKE-RLTV.MID", 0.269758421),
    ("IR.USD-SOFR-ON.VOL.SWPT.RLTV.ATM+50BPS::5Y::1Y::NORMAL.MID", 0.009559),
    ("FX.GBPAUD.VOL::4M::25D PUT::MID", 0.083565398),
]


def write_curve_file(
    out_path: Path, val_date_str: str, sofr_rate: float = 0.04, ff_rate: float = 0.035
) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dt = datetime.strptime(val_date_str, "%Y-%m-%d").date()
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Name", "amer-est-eod-synthetic-market", ""])
        w.writerow(["Date", dt.strftime("%d-%b-%y"), ""])
        w.writerow(["Property", "Label", "Base"])
        w.writerow(["Property", "Description", "amer-est-eod-synthetic-market"])
        w.writerow(["Property", "mktEnvType", "EOD"])
        for ticker, val in JUNK_ROWS:
            w.writerow([ticker, val, ""])
        for t in TENORS:
            w.writerow([f"IR.USD-SOFR-ON.ZERORATE-{t}.MID", sofr_rate, ""])
        for t in TENORS:
            w.writerow([f"IR.USD-FEDFUNDS-ON.ZERORATE-{t}.MID", ff_rate, ""])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--val-date", default="2026-03-31", help="Valuation date (ISO).")
    p.add_argument("--out", default=None,
                   help="Output path; default data/curves/market_environment_<val-date>.csv")
    p.add_argument("--sofr", type=float, default=0.04)
    p.add_argument("--ff", type=float, default=0.035)
    a = p.parse_args()
    out = a.out or str(ROOT / "data" / "curves" / f"market_environment_{a.val_date}.csv")
    write_curve_file(Path(out), a.val_date, a.sofr, a.ff)
    print(f"Wrote synthetic curve to {out}  (SOFR={a.sofr}, FF={a.ff})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
