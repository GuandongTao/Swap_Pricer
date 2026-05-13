"""Discount-factor inspection script.

Run from the project root:

    python scripts/discount_factor_test.py
    # or with custom date / data dir:
    python scripts/discount_factor_test.py --val-date 2026-03-31

What it does:
  1. Loads SOFR + FEDFUNDS curves from data/curves/CurvesYYYYMMDD.xlsx
  2. Prints pillar DFs (no interpolation) with hand-check math for one pillar
  3. Dumps pillar DFs to Excel for spreadsheet inspection
  4. Shows interpolated DFs at a few arbitrary intermediate dates
  5. Dumps a daily grid (DF, log_DF, implied 1-day fwd) over [val_date, val_date + N days]

The quoting convention comes from the project default (currently
AnnualCompoundedACT360 -- DF = (1+r)^(-days/360)). To compare against another
convention, pass --quoting ContinuousACT360 / SimpleACT360 / etc.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

# Make the package importable without `pip install -e`
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swaps.loaders.excel import ExcelCurveLoader  # noqa: E402
from swaps.rate_quoting import DEFAULT, get_rate_quoting  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--val-date", default="2026-03-31", help="Valuation date (ISO). Default 2026-03-31.")
    p.add_argument("--data-dir", default=str(ROOT / "data"), help="Data directory containing curves/.")
    p.add_argument("--out-dir", default=str(ROOT / "output"), help="Output directory for DF excel dumps.")
    p.add_argument(
        "--quoting",
        default=DEFAULT.name,
        help=f"Rate quoting convention. Default: {DEFAULT.name}.",
    )
    p.add_argument("--grid-days", type=int, default=120, help="Daily-grid horizon (calendar days).")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    val_date = datetime.strptime(args.val_date, "%Y-%m-%d").date()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    quoting = get_rate_quoting(args.quoting)

    print("=" * 72)
    print(f"Discount-factor test")
    print(f"  val_date      = {val_date}")
    print(f"  data_dir      = {args.data_dir}")
    print(f"  rate quoting  = {quoting.name}")
    print("=" * 72)

    loader = ExcelCurveLoader(Path(args.data_dir) / "curves", rate_quoting=quoting)
    sofr = loader.load(val_date, "SOFR")
    ff = loader.load(val_date, "FEDFUNDS")

    # ---------------- (1) Pillar DFs (no interpolation) ----------------
    sofr_pillars = sofr.to_debug_frame()
    ff_pillars = ff.to_debug_frame()

    print("\n--- SOFR pillar DFs (first 12 rows) ---")
    print(sofr_pillars.head(12).to_string(index=False))
    print(f"... ({len(sofr_pillars)} pillars total)")

    print("\n--- FEDFUNDS pillar DFs (first 12 rows) ---")
    print(ff_pillars.head(12).to_string(index=False))
    print(f"... ({len(ff_pillars)} pillars total)")

    # ---------------- (2) Hand-check one pillar ----------------
    sample = sofr_pillars[sofr_pillars["tenor"] == "1Y"].iloc[0]
    r = float(sample["zero_rate"])
    d = int(sample["days"])
    df_from_class = float(sample["df"])
    df_recomputed = quoting.rate_to_df(r, d)
    print("\n--- Hand-check: SOFR 1Y pillar under {} ---".format(quoting.name))
    print(f"  zero_rate r      = {r:.10f}")
    print(f"  days T           = {d}")
    print(f"  DF (class output)= {df_from_class:.12f}")
    print(f"  DF (recomputed)  = {df_recomputed:.12f}")
    print(f"  match            = {abs(df_from_class - df_recomputed) < 1e-15}")

    # ---------------- (3) Excel dumps for spreadsheet inspection ----------------
    pillars_path = out_dir / f"pillar_dfs_{val_date.isoformat()}.xlsx"
    with pd.ExcelWriter(pillars_path, engine="openpyxl") as w:
        sofr_pillars.to_excel(w, sheet_name="SOFR_pillars", index=False)
        ff_pillars.to_excel(w, sheet_name="FF_pillars", index=False)
        # Side-by-side merged for easy comparison
        merged = sofr_pillars.merge(
            ff_pillars, on=["tenor", "pillar_date", "days"], suffixes=("_sofr", "_ff")
        )
        merged.to_excel(w, sheet_name="SideBySide", index=False)
    print(f"\n[wrote] {pillars_path}")

    # ---------------- (4) Interpolated DFs at a few intermediate dates ----------------
    print("\n--- Interpolated SOFR DFs at arbitrary dates ---")
    probe_dates = [
        val_date + timedelta(days=10),
        val_date + timedelta(days=45),
        val_date + timedelta(days=100),
        val_date + timedelta(days=180),
        val_date + timedelta(days=400),
        val_date + timedelta(days=1825),  # ~5Y
    ]
    rows = []
    for d in probe_dates:
        days = (d - val_date).days
        df_s = sofr.df(d)
        df_f = ff.df(d)
        rows.append({"date": d, "days_from_val": days, "df_sofr": df_s, "df_ff": df_f})
    interp_frame = pd.DataFrame(rows)
    print(interp_frame.to_string(index=False))

    # ---------------- (5) Daily grid with implied 1-day forwards ----------------
    end = val_date + timedelta(days=args.grid_days)
    sofr_grid = sofr.df_grid_debug(val_date, end)
    ff_grid = ff.df_grid_debug(val_date, end)
    grid_path = out_dir / f"df_grid_{val_date.isoformat()}.xlsx"
    with pd.ExcelWriter(grid_path, engine="openpyxl") as w:
        sofr_grid.to_excel(w, sheet_name="SOFR_daily", index=False)
        ff_grid.to_excel(w, sheet_name="FF_daily", index=False)
    print(f"\n--- Daily interpolated grid for next {args.grid_days} days (SOFR head) ---")
    print(sofr_grid.head(10).to_string(index=False))
    print(f"\n[wrote] {grid_path}")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
