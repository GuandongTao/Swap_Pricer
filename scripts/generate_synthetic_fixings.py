"""Generate a synthetic Fed Funds fixings CSV for development / testing.

Real fixing files are gitignored at ``data/fixings/*.csv``; this script lets a
fresh clone bootstrap a working sample. Output format matches the real-vendor
layout the loader handles: ``ticker, date, rate`` per row, M/D/YYYY dates,
no header.

Usage:
    python scripts/generate_synthetic_fixings.py
    python scripts/generate_synthetic_fixings.py --start 2026-01-02 --end 2026-03-31 --rate 0.0364
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swaps.calendar_us import NY_FED  # noqa: E402


def write_fixings(out_path: Path, start: date, end: date, rate: float, ticker: str) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        d = start
        while d <= end:
            if NY_FED.is_business_day(d):
                w.writerow([ticker, f"{d.month}/{d.day}/{d.year}", f"{rate:.4f}"])
                n += 1
            d += timedelta(days=1)
    return n


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(ROOT / "data" / "fixings" / "fedfunds.csv"))
    p.add_argument("--start", default="2026-01-02", help="First fixing date (inclusive, ISO).")
    p.add_argument("--end", default="2026-03-31", help="Last fixing date (inclusive, ISO).")
    p.add_argument("--rate", type=float, default=0.0364, help="Flat fixing rate (decimal).")
    p.add_argument("--ticker", default="USD-FEDFUNDS-ON", help="Ticker string in column 1.")
    a = p.parse_args()
    s = datetime.strptime(a.start, "%Y-%m-%d").date()
    e = datetime.strptime(a.end, "%Y-%m-%d").date()
    n = write_fixings(Path(a.out), s, e, a.rate, a.ticker)
    print(f"Wrote {n} synthetic fixings to {a.out}  ({a.start} to {a.end} @ {a.rate})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
