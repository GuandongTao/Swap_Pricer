"""Batch portfolio pricer CLI: several valuation dates, run in parallel.

Each date's results land in its own folder: ``<out-dir>/run_<val_date>/``.

Usage:
    # explicit dates
    python scripts/price_portfolio_batch.py --val-date 2026-03-25 --val-date 2026-03-31
    # comma list
    python scripts/price_portfolio_batch.py --val-dates 2026-03-25,2026-03-26,2026-03-31
    # inclusive calendar-day range
    python scripts/price_portfolio_batch.py --start 2026-03-25 --end 2026-03-31
    # tune parallelism
    python scripts/price_portfolio_batch.py --start 2026-03-25 --end 2026-03-31 --max-workers 4 --debug
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swaps.batch import run_batch  # noqa: E402


def _iso(s: str):
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Price the swap portfolio for several valuation dates in parallel")
    p.add_argument("--val-date", action="append", default=[], metavar="YYYY-MM-DD",
                   help="A valuation date; repeatable.")
    p.add_argument("--val-dates", default=None, metavar="D1,D2,...",
                   help="Comma-separated valuation dates.")
    p.add_argument("--start", default=None, help="Range start (inclusive, ISO).")
    p.add_argument("--end", default=None, help="Range end (inclusive, ISO).")
    p.add_argument("--data-dir", default=str(ROOT / "data"), help="Base data directory")
    p.add_argument("--out-dir", default=str(ROOT / "output"), help="Output directory")
    p.add_argument("--max-workers", type=int, default=None, help="Parallel worker processes (default: auto)")
    p.add_argument("--no-detail", action="store_true", help="Skip per-trade detail workbooks")
    p.add_argument("--no-parquet", action="store_true", help="Skip parquet outputs")
    p.add_argument("--debug", action="store_true", help="Write per-trade debug workbooks")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("price_portfolio_batch")

    dates = []
    try:
        dates += [_iso(d) for d in args.val_date]
        if args.val_dates:
            dates += [_iso(d) for d in args.val_dates.split(",") if d.strip()]
        if args.start or args.end:
            if not (args.start and args.end):
                log.error("--start and --end must be given together")
                return 2
            s, e = _iso(args.start), _iso(args.end)
            if e < s:
                log.error("--end (%s) is before --start (%s)", e, s)
                return 2
            d = s
            while d <= e:
                dates.append(d)
                d += timedelta(days=1)
    except ValueError as ex:
        log.error("Bad date: %s", ex)
        return 2

    if not dates:
        log.error("No valuation dates given (use --val-date / --val-dates / --start+--end)")
        return 2

    results = run_batch(
        dates,
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        max_workers=args.max_workers,
        write_detail=not args.no_detail,
        write_parquet=not args.no_parquet,
        write_debug=args.debug,
    )

    for r in results:
        if r.status == "error":
            log.error("%s ERROR: %s", r.val_date, r.exception)
        elif r.errors:
            for e in r.errors:
                log.error("%s: %s", r.val_date, e)

    # Non-zero exit if any date failed outright or priced partially.
    return 0 if all(r.status == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
