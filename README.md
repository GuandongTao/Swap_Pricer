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

`data/curves/` and `data/fixings/` are the **single sources of truth** for market data, used by both the CLI and the test suite. Files there are gitignored — drop your real curve/fixings here and they stay local.

On a fresh clone, both folders are empty. Either supply real files, or bootstrap synthetic placeholders:

```powershell
python scripts\generate_synthetic_curve.py   --out data\curves\Curves20260331.xlsx
python scripts\generate_synthetic_fixings.py --out data\fixings\fedfunds.csv
```

`data/trades/` is tracked. Add or edit `*.yaml` files there.

The golden-master JSON in `tests/golden/` is also gitignored because it encodes derived market data. After supplying a curve, pin a local baseline with:
```powershell
$env:REGENERATE_GOLDEN = "1"; pytest tests/test_golden_master.py; Remove-Item Env:\REGENERATE_GOLDEN
```
