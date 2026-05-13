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

## Data layout

`data/curves/` is the **single source of truth** for curve files (both for the CLI and for the test suite). Curve files there are gitignored — drop your real `CurvesYYYYMMDD.xlsx` here and it stays local.

On a fresh clone, the folder is empty. Either:
- supply a real curve file, or
- bootstrap a synthetic placeholder:
  ```powershell
  python scripts\generate_synthetic_curve.py --out data\curves\Curves20260331.xlsx
  ```

`data/fixings/fedfunds.csv` and `data/trades/SWAP_001..003.yaml` are committed synthetic samples. Replace or extend with your own.

The golden-master JSON in `tests/golden/` is also gitignored because it encodes derived market data. After supplying a curve, pin a local baseline with:
```powershell
$env:REGENERATE_GOLDEN = "1"; pytest tests/test_golden_master.py; Remove-Item Env:\REGENERATE_GOLDEN
```
