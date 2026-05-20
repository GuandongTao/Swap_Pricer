"""Portfolio pricer CLI.

Usage:
    python scripts/price_portfolio.py --val-date 2026-03-31
    python scripts/price_portfolio.py --val-date 2026-03-31 --pillar-dates -v

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
from swaps.loaders.dated import DatedCurveLoader  # noqa: E402
from swaps.loaders.excel import ExcelCurveLoader, ExcelFixingLoader  # noqa: E402
from swaps.loaders.yaml_trades import YamlTradeLoader  # noqa: E402
from swaps.portfolio import Portfolio  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Price the swap portfolio for one valuation date")
    p.add_argument("--val-date", required=True, help="ISO date, e.g. 2026-03-31")
    p.add_argument("--data-dir", default=str(ROOT / "data"), help="Base data directory")
    p.add_argument("--out-dir", default=str(ROOT / "output"), help="Output directory")
    p.add_argument("--no-detail", action="store_true", help="Skip per-trade detail workbooks")
    p.add_argument("--no-parquet", action="store_true", help="Skip parquet outputs")
    p.add_argument("--debug", action="store_true", help="Write per-trade debug workbooks (intermediate frames)")
    p.add_argument(
        "--pillar-dates", action="store_true",
        help="Use the dated-pillars curve format (sofr_<val_date>.csv + ff_<val_date>.csv) "
             "instead of the market_environment file. Mutually exclusive with the default path.",
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

    if args.pillar_dates:
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
        valuations, manifest = pf.run(
            val_date,
            out_dir=out_dir,
            write_detail=not args.no_detail,
            write_parquet=not args.no_parquet,
            write_debug=args.debug,
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
