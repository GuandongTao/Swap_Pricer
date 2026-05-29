"""CCID diagnostic — explains why Balance Sheet / PL CCID columns come out blank.

CCID (cols AU/AV) resolves only when, for a trade:
  1. ``oracle_entity_code`` is non-blank, AND
  2. that code is a key in the Entity Reference Report lookup.
Otherwise both CCID cells are emitted blank (no half-built id is ever written).
For Balance Sheet CCID there is a third gate: NPV must be non-zero (NPV == 0
emits a blank BS CCID, mirroring the blank Asset Liability Tag).

This script checks every link in that chain and prints a per-trade verdict.
Run it on the machine where CCID is blank:

    python scripts/diagnose_ccid.py
    python scripts/diagnose_ccid.py --trades data/trades --entity-rc data/entity/Entity_Reference_Report.csv

To also inspect an already-generated production feed (the "final report"),
point --prod-csv at it — the script reports the actual AU/AV cells written:

    python scripts/diagnose_ccid.py --prod-csv "output/.../IRS_Valuation_2026-03-31-00001.csv"

It is read-only — it loads files and reports, it never writes trade or feed data.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from swaps.io_prod import PROD_FIELDS, load_entity_rc  # noqa: E402
from swaps.loaders.csv_trades import CsvTradeLoader  # noqa: E402


def _hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def check_entity_report(path: Path) -> dict[str, str]:
    """Validate the Entity Reference Report and return the parsed lookup."""
    _hr(f"1. ENTITY REFERENCE REPORT  ({path})")
    if not path.exists():
        print("  FAIL  file does not exist -> every CCID will be blank.")
        print("        Put the report here, or pass --entity-rc <path>.")
        return {}

    # raw header inspection — load_entity_rc needs EXACT column names
    raw = path.read_text(encoding="utf-8-sig").splitlines()
    if not raw:
        print("  FAIL  file is empty.")
        return {}
    header = [h.strip() for h in raw[0].split(",")]
    print(f"  header columns : {header}")
    for needed in ("Entity_Code", "Default RC"):
        mark = "ok  " if needed in header else "FAIL"
        print(f"  [{mark}] column '{needed}' present")
    if "Entity_Code" not in header or "Default RC" not in header:
        print("        load_entity_rc keys on these EXACT names — rename the")
        print("        columns in the report to match, or the lookup is empty.")

    lookup = load_entity_rc(path)
    print(f"  parsed entries : {len(lookup)}")
    if not lookup:
        print("  FAIL  lookup is EMPTY -> every CCID will be blank.")
    else:
        sample = list(lookup.items())[:8]
        for ec, rc in sample:
            print(f"           {ec!r} -> RC {rc!r}")
        if len(lookup) > 8:
            print(f"           ... and {len(lookup) - 8} more")
    return lookup


def check_csv_alignment(csv_path: Path) -> bool:
    """Check every data row has the same field count as the header.

    A row count one short of the header makes pandas silently use the first
    column as the index and shift every column left — corrupting
    oracle_entity_code (and counterparty / deal date / netting too).
    """
    lines = [ln for ln in csv_path.read_text(encoding="utf-8-sig").splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        print(f"  {csv_path.name}: no data rows")
        return False
    n_hdr = len(lines[0].split(","))
    aligned = True
    bad = []
    for i, ln in enumerate(lines[1:], 1):
        n = len(ln.split(","))
        if n != n_hdr:
            aligned = False
            bad.append((i, n))
    if aligned:
        print(f"  [ok  ] {csv_path.name}: all {len(lines) - 1} rows have {n_hdr} fields")
    else:
        print(f"  [FAIL] {csv_path.name}: header has {n_hdr} fields but these rows differ:")
        for i, n in bad[:10]:
            delta = n - n_hdr
            print(f"           data row {i}: {n} fields ({delta:+d})")
        if len(bad) > 10:
            print(f"           ... and {len(bad) - 10} more")
        print("         A column-count mismatch shifts oracle_entity_code to the")
        print("         wrong value. Fix the input file so every row matches.")
    return aligned


def inspect_prod_csv(path: Path) -> None:
    """Read a generated prod feed and report the actual AU/AV cells written.

    Layout: row 1 = H header, row 2 = the 49 field-name headers, rows 3..N-1
    = trades, last row = T footer.
    """
    _hr(f"4. PRODUCTION FEED CCID CELLS  ({path})")
    if not path.exists():
        print("  FAIL  feed file does not exist.")
        return
    bs_idx = PROD_FIELDS.index("Balance Sheet CCID")
    pl_idx = PROD_FIELDS.index("PL OCI CCID")
    npv_idx = PROD_FIELDS.index("Total Value (NPV)")
    with path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    if len(rows) < 3:
        print("  feed has no trade rows.")
        return
    trade_rows = rows[2:-1] if rows[-1][:1] == ["T"] else rows[2:]
    n_bs = n_pl = 0
    for r in trade_rows:
        if len(r) <= pl_idx:
            continue
        tid, npv = r[0], r[npv_idx]
        bs, pl = r[bs_idx], r[pl_idx]
        n_bs += bool(bs)
        n_pl += bool(pl)
        print(f"  {tid:<20} NPV={npv:<16} BS CCID={bs or '<blank>':<48} "
              f"PL CCID={pl or '<blank>'}")
    n = len(trade_rows)
    print(f"\n  {n_bs}/{n} rows have Balance Sheet CCID, {n_pl}/{n} have PL OCI CCID.")
    if n_pl == 0:
        print("  PL CCID blank on every row -> the run did not resolve entity_rc.")
        print("  Confirm the pricer was passed --entity-rc <the same report file>.")
    elif n_bs < n_pl:
        print("  Some BS CCID blank while PL is filled -> those trades have NPV == 0.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Diagnose blank CCID output")
    p.add_argument("--trades", default=str(ROOT / "data" / "trades"),
                   help="trade CSV file or directory (default: data/trades)")
    p.add_argument("--entity-rc", default=str(ROOT / "data" / "entity" / "Entity_Reference_Report.csv"),
                   help="Entity Reference Report CSV")
    p.add_argument("--prod-csv", default=None,
                   help="optional: a generated IRS Valuation feed CSV to inspect")
    args = p.parse_args(argv)

    lookup = check_entity_report(Path(args.entity_rc))

    _hr(f"2. TRADE CSV COLUMN ALIGNMENT  ({args.trades})")
    trades_path = Path(args.trades)
    if trades_path.is_dir():
        csv_files = sorted(pp for pp in trades_path.glob("*.csv")
                           if not pp.name.startswith("_"))
        trades_dir = trades_path
    elif trades_path.is_file():
        csv_files = [trades_path]
        trades_dir = trades_path.parent
    else:
        print(f"  FAIL  {trades_path} not found.")
        return 1
    if not csv_files:
        print(f"  no loadable .csv files in {trades_path}")
        print("  (CsvTradeLoader ignores files whose name starts with '_')")
    for cp in csv_files:
        check_csv_alignment(cp)

    _hr("3. PARSED oracle_entity_code  vs  LOOKUP")
    try:
        trades = CsvTradeLoader(str(trades_dir)).load_all()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  CsvTradeLoader could not parse the trades: {exc}")
        return 1
    if not trades:
        print("  no trades parsed.")
        return 1

    n_ok = 0
    for td in trades:
        ec = (td.oracle_entity_code or "").strip()
        if not ec:
            verdict = "BLANK CCID  -- oracle_entity_code is empty on this trade"
        elif ec not in lookup:
            verdict = (f"BLANK CCID  -- entity {ec!r} not in the reference report "
                       f"(check for a '.0' suffix, spaces, or a missing row)")
        else:
            verdict = f"CCID OK     -- entity {ec!r} -> RC {lookup[ec]!r}"
            n_ok += 1
        print(f"  {td.trade_id:<20} oracle_entity_code={ec!r:<14} {verdict}")

    if args.prod_csv:
        inspect_prod_csv(Path(args.prod_csv))

    _hr("VERDICT")
    print(f"  {n_ok}/{len(trades)} trades will produce CCID.")
    if n_ok == len(trades):
        print("  All trades resolve -- if CCID is still blank in the feed, the run")
        print("  is not passing --entity-rc to this same report file. Re-inspect")
        print("  the feed with --prod-csv to confirm.")
        return 0
    print("  Fix the failing items above, then re-run the pricer.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
