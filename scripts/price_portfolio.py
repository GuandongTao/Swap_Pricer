"""Portfolio pricer CLI.

Usage:
    # Default: ONLY the prod CSV (IRS Valuation<val_date>-00001.csv)
    python scripts/price_portfolio.py --val-date 2026-03-31

    # Debug: prod CSV + portfolio workbook + per-trade detail + per-trade
    #        debug + parquet (everything the pipeline can emit)
    python scripts/price_portfolio.py --val-date 2026-03-31 --debug

    # Alternate curve inputs
    python scripts/price_portfolio.py --val-date 2026-03-31 --pillar-dates -v
    python scripts/price_portfolio.py --val-date 2026-03-31 --pillar-dates-df

Exit codes:
    0  success (all priced; ``skipped(no-curve)`` counts as success)
    1  hard failure (uncaught exception, or run errored entirely)
    2  CLI usage error (argparse default)
    3  partial (pricing completed but some trades errored)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# allow running without `pip install -e`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swaps.loaders import CombinedTradeLoader  # noqa: E402
from swaps.loaders.csv_trades import CsvTradeLoader  # noqa: E402
from swaps.loaders.dated import DatedCurveLoader, DatedDFCurveLoader  # noqa: E402
from swaps.loaders.excel import ExcelCurveLoader, ExcelFixingLoader  # noqa: E402
from swaps.loaders.yaml_trades import YamlTradeLoader  # noqa: E402
from swaps.portfolio import Portfolio  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Price the swap portfolio for one valuation date")
    p.add_argument("--val-date", required=True, help="ISO date, e.g. 2026-03-31")
    p.add_argument("--data-dir", default=str(ROOT / "data"), help="Base data directory")
    p.add_argument("--out-dir", default=str(ROOT / "output"), help="Output directory")
    p.add_argument(
        "--debug", action="store_true",
        help="Write EVERYTHING: prod CSV + portfolio workbook + per-trade detail + "
             "per-trade debug + parquet. Default (no flag) writes only the prod CSV.",
    )
    curve_src = p.add_mutually_exclusive_group()
    curve_src.add_argument(
        "--pillar-dates", action="store_true",
        help="Dated-pillars curve format: sofr_<val_date>.csv + ff_<val_date>.csv "
             "(no header; col A pillar date ISO; col B zero rate decimal).",
    )
    curve_src.add_argument(
        "--pillar-dates-df", action="store_true",
        help="Dated-DFs curve format: sofr_df_<val_date>.csv + ff_df_<val_date>.csv "
             "(same shape as --pillar-dates but col B is the discount factor; "
             "bypasses RateQuoting entirely).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show INFO-level progress (per-trade timings, run folder, etc.). "
             "Default is WARNING-only (suitable for cloud pipelines).",
    )
    args = p.parse_args(argv)

    level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=level, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("price_portfolio")

    try:
        val_date = datetime.strptime(args.val_date, "%Y-%m-%d").date()
    except ValueError as e:
        log.error("Bad --val-date: %s", e)
        return 2

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)

    if args.pillar_dates_df:
        curve_loader = DatedDFCurveLoader(data_dir / "curves")
    elif args.pillar_dates:
        curve_loader = DatedCurveLoader(data_dir / "curves")
    else:
        curve_loader = ExcelCurveLoader(data_dir / "curves")
    fixing_loader = ExcelFixingLoader(data_dir / "fixings" / "fixing_cail_USD-FEDFUNDS-ON.csv")
    trade_loader = CombinedTradeLoader(
        YamlTradeLoader(data_dir / "trades"),
        CsvTradeLoader(data_dir / "trades"),
    )

    try:
        pf = Portfolio(curve_loader, fixing_loader, trade_loader)
        # Default (no --debug): prod CSV only. --debug: everything.
        valuations, manifest = pf.run(
            val_date,
            out_dir=out_dir,
            write_prod=True,
            write_portfolio_xlsx=args.debug,
            write_detail=args.debug,
            write_debug=args.debug,
            write_parquet=args.debug,
        )
    except Exception:
        logging.getLogger("price_portfolio").exception("Run failed")
        return 1

    log.info("Priced %d trades; status=%s; manifest=%s", len(valuations), manifest.status,
             manifest.outputs.get("manifest"))
    status = (manifest.status or "").lower()
    if status == "error":
        for e in manifest.errors:
            log.error(e)
        return 1
    if status == "partial":
        for e in manifest.errors:
            log.error(e)
        return 3
    # ok (including "skipped" if any future single-date path produces it)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
