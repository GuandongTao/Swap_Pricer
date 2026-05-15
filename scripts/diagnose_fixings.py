"""Read-only diagnostic for the historical fixings file.

Why a row that *is* in the file can still come back as a missing fixing:
the loader reads the WHOLE file every run and builds a ``date -> rate`` dict;
any row whose date or rate cell fails to parse is silently skipped, so
``FixingHistory.get(d)`` returns ``None`` even though the line is present.

This script reproduces the loader's parsing step-by-step and reports exactly
where a given date is lost. It writes nothing and never moves the file.

Usage (from repo root):
    python scripts/diagnose_fixings.py
    python scripts/diagnose_fixings.py --date 2026-02-10
    python scripts/diagnose_fixings.py --path data/fixings/fixing_cali_USD-FEDFUNDS-ON.csv --index FEDFUNDS

Add --redact to mask every rate value (<rate>) so the whole output is safe
to paste outside a restricted environment:
    python scripts/diagnose_fixings.py --redact --date 2026-02-10
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--path", default=str(ROOT / "data" / "fixings" / "fixing_cali_USD-FEDFUNDS-ON.csv"))
    p.add_argument("--date", default="2026-02-10", help="Probe date (ISO) expected in the file.")
    p.add_argument("--index", default="FEDFUNDS", help="Index name passed to the loader.")
    p.add_argument("--redact", action="store_true",
                   help="Mask all rate values (<rate>) so the output is safe to share.")
    a = p.parse_args(argv)

    import re as _re

    def _red(x):
        """Mask decimal rate values when --redact is set."""
        if not a.redact:
            return x
        if isinstance(x, (list, tuple)):
            return [("<rate>" if _re.fullmatch(r"-?\d*\.\d+", str(c).strip()) else c)
                    for c in x]
        return _re.sub(r"-?\d*\.\d+", "<rate>", str(x))

    P = Path(a.path)
    probe = datetime.strptime(a.date, "%Y-%m-%d").date()
    print(f"== fixings diagnostic ==\nfile : {P}\nprobe: {probe}\nindex: {a.index}\n")

    if not P.exists():
        print("!! FILE DOES NOT EXIST at that path -> loader returns an EMPTY history")
        print("   (every historical fixing would then be reported missing)")
        return 1
    print(f"exists: yes | size: {P.stat().st_size} bytes")

    # --- replicate ExcelFixingLoader.load() step by step ---------------------
    if P.suffix.lower() == ".csv":
        raw = pd.read_csv(P, header=None, skip_blank_lines=True, dtype=str)
    else:
        raw = pd.read_excel(P, header=None, dtype=str)
    raw = raw.dropna(how="all").reset_index(drop=True)
    print("raw shape (rows, cols):", raw.shape)
    if raw.empty:
        print("!! file parsed to ZERO rows")
        return 1

    try:
        float(str(raw.iloc[0, -1]).strip())
        has_header = False
    except (ValueError, TypeError):
        has_header = True
    print(f"row0: {_red(list(raw.iloc[0]))}")
    print(f"header detected & dropped?: {has_header}"
          + ("  <-- if row0 is real data, the loader is dropping it" if has_header else ""))
    if has_header:
        raw = raw.iloc[1:].reset_index(drop=True)

    ncols = raw.shape[1]
    if ncols < 2:
        print(f"!! only {ncols} column(s); loader needs >=2 (date,rate)")
        return 1
    tcol, dcol, rcol = (None, 0, 1) if ncols == 2 else (0, 1, 2)
    print(f"ncols: {ncols} | date_col={dcol} rate_col={rcol} ticker_col={tcol}")

    if tcol is not None and a.index:
        norm = a.index.upper().replace("_", "").replace("-", "")
        mask = (
            raw[tcol].astype(str).str.upper()
            .str.replace("_", "", regex=False)
            .str.replace("-", "", regex=False)
            .str.contains(norm, na=False)
        )
        print(f"ticker filter '{norm}': {int(mask.sum())}/{len(raw)} rows match")
        if mask.any():
            raw = raw[mask].reset_index(drop=True)
        else:
            print("   (no rows matched -> loader keeps ALL rows as a fallback)")

    bad_date: list[list] = []
    bad_rate: list[list] = []
    mp: dict = {}
    dupes = 0
    for _, row in raw.iterrows():
        dr, rr = row[dcol], row[rcol]
        if pd.isna(dr) or pd.isna(rr):
            bad_date.append(list(row))
            continue
        d = pd.to_datetime(str(dr).strip(), errors="coerce")
        if pd.isna(d):
            bad_date.append(list(row))
            continue
        try:
            v = float(str(rr).strip())
        except (ValueError, TypeError):
            bad_rate.append(list(row))
            continue
        if d.date() in mp:
            dupes += 1
        mp[d.date()] = v

    print("\n-- parse result --")
    print(f"parsed OK : {len(mp)} unique dates ({dupes} duplicate-date overwrites)")
    print(f"bad DATE  : {len(bad_date)} rows (blank/garbled date -> SKIPPED)")
    print(f"bad RATE  : {len(bad_rate)} rows (date ok, rate not a number -> SKIPPED)")
    if mp:
        print(f"date range: {min(mp)} -> {max(mp)}")
    print(f"\n>>> PROBE {probe} in loaded map? : {probe in mp}"
          + (f"  value={_red(mp[probe])}" if probe in mp else "  <-- MISSING"))
    if bad_date[:3]:
        print("first bad-DATE rows:", [_red(r) for r in bad_date[:3]])
    if bad_rate[:3]:
        print("first bad-RATE rows:", [_red(r) for r in bad_rate[:3]])

    # --- raw bytes of any line mentioning the probe date ---------------------
    txt = P.read_text(errors="replace").splitlines()
    iso = probe.isoformat()
    us = f"{probe.month}/{probe.day}/{probe.year}"
    mon = probe.strftime("%d-%b").lower()
    hits = [(i, ln) for i, ln in enumerate(txt, 1)
            if iso in ln or us in ln or mon in ln.lower()]
    print(f"\nraw lines mentioning the probe date ({len(hits)} found):")
    for i, ln in hits[:5]:
        print(f"  line {i}: {_red(ln)!r}")   # repr() exposes BOM, quotes, leading ', \t
    if not hits:
        print("  (none -> the date is not literally in the file, or in a format"
              " none of the probes recognised; check the raw rows around it)")

    # --- authoritative: run the real loader ----------------------------------
    try:
        from swaps.loaders.excel import ExcelFixingLoader
        fh = ExcelFixingLoader(P).load(a.index)
        print(f"\nvia real ExcelFixingLoader: {len(fh)} fixings | "
              f"get({probe})={_red(fh.get(probe))}")
    except Exception as e:  # noqa: BLE001
        print(f"\n(could not import/run ExcelFixingLoader: {type(e).__name__}: {e})")

    print("\n== done ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
