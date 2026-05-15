# Swaps

Daily mark-to-market pricer for a portfolio of USD fixed-vs-float interest rate swaps.

- **Floating leg**: Fed Funds (EFFR), daily fixings compounded in arrears.
- **Fixed leg**: per-trade frequency and day-count.
- **Discounting**: SOFR OIS zero curve (dual-curve: SOFR discounts, FF projects).

See [`plan.md`](plan.md) for design and [`questions.md`](questions.md) for open items.

## Quick start

```powershell
pip install -e .[dev]
$env:PYTHONPATH = "$pwd\src"
pytest -q
python scripts/price_portfolio.py --val-date 2026-03-31 --debug
```

## Output layout

Every run (single-date, or one date inside a batch) is self-contained in its own folder:

```
output/run_<val_date>/
  portfolio_<val_date>.xlsx        # Summary / FloatingCF / FixedCF / Curves
  detail/<trade_id>.xlsx           # per-trade drill-down (+ FloatingByPeriod)
  debug/<trade_id>_debug.xlsx      # with --debug
  parquet/{summary,floating_cf,fixed_cf,curves}.parquet
  manifest_<val_date>.json
```

## Batch runs (several dates, parallel)

```powershell
# any of:
python scripts/price_portfolio_batch.py --val-date 2026-03-25 --val-date 2026-03-31
python scripts/price_portfolio_batch.py --val-dates 2026-03-25,2026-03-26,2026-03-31
python scripts/price_portfolio_batch.py --start 2026-03-25 --end 2026-03-31 --max-workers 4
```

Each date is priced in its own process and writes its own `run_<val_date>/` folder with the **normal daily summary** (nothing aggregated away). In addition, one overarching log is written at the `output/` root, outside all the day folders:

```
output/batch_<UTCstamp>.log    # human-readable: totals + one line per date
output/batch_<UTCstamp>.json   # same, machine-readable (incl. manifest paths)
```

Exit code is non-zero if any date errors or prices only partially.

## Data layout

`data/curves/` and `data/fixings/` are the **single sources of truth** for market data, used by both the CLI and the test suite. Production input formats (the only formats supported):

- Curves: `data/curves/market_environment_YYYY-MM-DD.csv` — raw vendor export with header rows and many interleaved non-USD/IR pillars; the loader filters column A down to `IR.USD-{SOFR|FEDFUNDS}-ON.ZERORATE-{TENOR}.MID`.
- Fixings: `data/fixings/fixing_cali_USD-FEDFUNDS-ON.csv` — `ticker,date,rate` rows.

On a fresh clone, supply real files, or bootstrap synthetic placeholders:

```powershell
python scripts\generate_synthetic_curve.py   --val-date 2026-03-31
python scripts\generate_synthetic_fixings.py
```

`data/trades/` is tracked. Add or edit `*.yaml` files there.

The golden-master JSON in `tests/golden/` is also gitignored because it encodes derived market data. After supplying a curve, pin a local baseline with:
```powershell
$env:REGENERATE_GOLDEN = "1"; pytest tests/test_golden_master.py; Remove-Item Env:\REGENERATE_GOLDEN
```
