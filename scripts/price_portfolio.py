"""Portfolio pricer CLI.

Usage:
    # Default: prod CSV (IRS_Valuation_<val_date>-00001.csv) + manifest (+ netting)
    python scripts/price_portfolio.py --val-date 2026-03-31

    # + hedged-debt summary (Debt_Summary_<val_date>.csv)
    python scripts/price_portfolio.py --val-date 2026-03-31 --debug-loan

    # Full debug: prod CSV + Debt_Summary + portfolio workbook + per-trade detail
    #        + per-trade debug + parquet (everything the pipeline can emit)
    python scripts/price_portfolio.py --val-date 2026-03-31 --debug-full

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

from swaps.io_prod import load_entity_rc  # noqa: E402
from swaps.netting_db import load_netting_db  # noqa: E402
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
        "--entity-rc", default=str(ROOT / "data" / "entity" / "Entity_Reference_Report.csv"),
        help="Entity Reference Report CSV (Entity_Code,Default RC) used to build "
             "Balance Sheet / PL CCIDs. Missing file -> CCID fields left blank.",
    )
    p.add_argument(
        "--netting-db", default=str(ROOT / "data" / "entity" / "Netting_Database.csv"),
        help="Netting Database CSV (keyed by Netting ID). Source of truth for "
             "Cash Flow / Position Netting Allowed flags and the Netting Entity "
             "on both the IRS Valuation and IRS Netting feeds. Missing file -> "
             "IRS Netting feed is skipped (warning recorded to manifest).",
    )
    p.add_argument(
        "--debug-loan", action="store_true",
        help="Also write the hedged-debt summary (Debt_Summary_<val_date>.csv). "
             "Off by default; col AW is unaffected (the debt is always valued).",
    )
    p.add_argument(
        "--debug-full", action="store_true",
        help="Write EVERYTHING: prod CSV + Debt_Summary + portfolio workbook + "
             "per-trade detail + per-trade debug + parquet. Superset of --debug-loan. "
             "Default (no flag) writes only the prod CSV + manifest (+ netting).",
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
        "--version", type=int, default=None, metavar="N",
        help="Submission version (sequence) number for the output feed. "
             "Default: auto-increment past any prior run for the same "
             "(val_date, data source), starting at 1. The value is zero-padded "
             "to 5 digits and drives the run folder name, the feed filename, and "
             "header-row cell 4. Pass an explicit N to re-issue a specific "
             "version (e.g. --version 7 -> 00007).",
    )
    p.add_argument(
        "--new-deal", action="append", default=[], metavar="SWAP_ID",
        help="Newly-added swap id that triggers the 'Once'-frequency additional "
             "outputs (Swap Payment Schedule, Day 1 Valuations) for that id only. "
             "Repeatable for multiple new deals. Other additional outputs run on "
             "their own schedule regardless.",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Show INFO-level progress (per-trade timings, run folder, "
             "convention warnings, matured-trade notices, no-curve skips). "
             "Default is ERROR-only -- warnings are still recorded to "
             "manifest.warnings[] but stay off stdout (cloud-pipeline friendly).",
    )
    args = p.parse_args(argv)

    # Default is ERROR-only: warnings remain in manifest.warnings[] but stay
    # off stdout, so a no-flag cloud run is silent unless something failed.
    level = logging.INFO if args.verbose else logging.ERROR
    logging.basicConfig(level=level, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("price_portfolio")

    try:
        val_date = datetime.strptime(args.val_date, "%Y-%m-%d").date()
    except ValueError as e:
        log.error("Bad --val-date: %s", e)
        return 2

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)

    # Mark Bloomberg-DF-sourced runs in the output folder name (" BBG").
    folder_suffix = " BBG" if args.pillar_dates_df else ""
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

    entity_rc = load_entity_rc(args.entity_rc)
    if not entity_rc:
        log.warning("entity_rc lookup empty (path=%s) -> CCID fields will be blank", args.entity_rc)

    netting_db = None
    if Path(args.netting_db).exists():
        netting_db = load_netting_db(args.netting_db)
    else:
        log.warning(
            "netting database not found (path=%s) -> IRS Netting feed will "
            "be skipped and netting fields on the IRS Valuation feed will "
            "be blank", args.netting_db,
        )

    try:
        pf = Portfolio(curve_loader, fixing_loader, trade_loader)
        # Default: prod CSV + manifest only. --debug-loan adds Debt_Summary;
        # --debug-full adds everything (and implies --debug-loan).
        valuations, manifest = pf.run(
            val_date,
            out_dir=out_dir,
            write_prod=True,
            write_debt_summary=args.debug_loan or args.debug_full,
            write_portfolio_xlsx=args.debug_full,
            write_detail=args.debug_full,
            write_debug=args.debug_full,
            write_parquet=args.debug_full,
            entity_rc=entity_rc,
            netting_db=netting_db,
            folder_suffix=folder_suffix,
            version=args.version,
            data_dir=data_dir,
            new_deal_ids=frozenset(str(x).strip() for x in args.new_deal if str(x).strip()),
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
    # Print the exit code on the final line unconditionally so a no-flag
    # cloud run (where INFO/WARNING are suppressed) still surfaces it.
    # Catches argparse's internal SystemExit too (bad/missing args -> code 2).
    try:
        _rc = main()
    except SystemExit as _e:
        _rc = _e.code if isinstance(_e.code, int) else (0 if _e.code is None else 1)
    print(f"exit_code={_rc}")
    raise SystemExit(_rc)
