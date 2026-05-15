"""Portfolio pricer CLI.

Usage:
    python scripts/price_portfolio.py --val-date 2026-03-31
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
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("price_portfolio")

    try:
        val_date = datetime.strptime(args.val_date, "%Y-%m-%d").date()
    except ValueError as e:
        log.error("Bad --val-date: %s", e)
        return 2

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)

    curve_loader = ExcelCurveLoader(data_dir / "curves")
    fixing_loader = ExcelFixingLoader(data_dir / "fixings" / "fixing_cail_USD-FEDFUNDS-ON.csv")
    trade_loader = CombinedTradeLoader(
        YamlTradeLoader(data_dir / "trades"),
        CsvTradeLoader(data_dir / "trades"),
    )

    pf = Portfolio(curve_loader, fixing_loader, trade_loader)
    valuations, manifest = pf.run(
        val_date,
        out_dir=out_dir,
        write_detail=not args.no_detail,
        write_parquet=not args.no_parquet,
        write_debug=args.debug,
    )
    log.info("Priced %d trades; status=%s; manifest=%s", len(valuations), manifest.status,
             manifest.outputs.get("manifest"))
    if manifest.errors:
        for e in manifest.errors:
            log.error(e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
