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
    p.add_argument(
        "--entity-rc", default=str(ROOT / "entity" / "Entity_Reference_Report.csv"),
        help="Entity Reference Report CSV (Entity_Code,Default RC) used to build "
             "Balance Sheet / PL CCIDs. Missing file -> CCID fields left blank.",
    )
    p.add_argument(
        "--netting-db", default=str(ROOT / "entity" / "Netting_Database.csv"),
        help="Netting Database CSV (keyed by Netting ID). Source of truth for "
             "Cash Flow / Position Netting Allowed flags and the Netting Entity "
             "on both the IRS Valuation and IRS Netting feeds. Missing file -> "
             "IRS Netting feed is skipped (warning recorded to manifest).",
    )
    p.add_argument("--max-workers", type=int, default=None, help="Parallel worker processes (default: auto)")
    p.add_argument(
        "--debug", action="store_true",
        help="Write EVERYTHING: prod CSV + portfolio workbook + per-trade detail + "
             "per-trade debug + parquet. Default (no flag) writes only the prod CSV.",
    )
    curve_src = p.add_mutually_exclusive_group()
    curve_src.add_argument(
        "--pillar-dates", action="store_true",
        help="Dated-pillars curve format: sofr_<val_date>.csv + ff_<val_date>.csv.",
    )
    curve_src.add_argument(
        "--pillar-dates-df", action="store_true",
        help="Dated-DFs curve format: sofr_df_<val_date>.csv + ff_df_<val_date>.csv "
             "(col B is the DF; bypasses RateQuoting).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show INFO-level progress in parent and workers (incl. "
             "no-curve skips, convention warnings, matured-trade notices). "
             "Default is ERROR-only -- warnings remain in manifest.warnings[] "
             "but stay off stdout (cloud-pipeline friendly).",
    )
    args = p.parse_args(argv)

    # Default is ERROR-only; -v upgrades to INFO. Warnings still land in
    # each per-date manifest.warnings[] and the batch summary log.
    level = logging.INFO if args.verbose else logging.ERROR
    logging.basicConfig(level=level, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
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
        write_detail=args.debug,
        write_parquet=args.debug,
        write_debug=args.debug,
        pillar_dates=args.pillar_dates,
        pillar_dates_df=args.pillar_dates_df,
        verbose=args.verbose,
        entity_rc_path=args.entity_rc,
        netting_db_path=args.netting_db,
    )

    for r in results:
        if r.status == "error":
            log.error("%s ERROR: %s", r.val_date, r.exception)
        elif r.status == "skipped":
            log.warning("%s SKIPPED (no zero-rate curve, e.g. weekend/holiday): %s",
                        r.val_date, r.exception)
        elif r.errors:
            for e in r.errors:
                log.error("%s: %s", r.val_date, e)

    # Exit codes: 0 ok/skipped; 1 any date errored; 3 partial-only (no errors).
    # 'skipped' (no curve published) is a warning, not a failure.
    if any(r.status == "error" for r in results):
        return 1
    if any(r.status == "partial" for r in results):
        return 3
    return 0


if __name__ == "__main__":
    # Print the exit code unconditionally on the final stdout line so it is
    # visible even at default ERROR-only logging. Argparse's internal
    # SystemExit (bad/missing args) is captured too.
    try:
        _rc = main()
    except SystemExit as _e:
        _rc = _e.code if isinstance(_e.code, int) else (0 if _e.code is None else 1)
    print(f"exit_code={_rc}")
    raise SystemExit(_rc)
