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

## Sample data

`data/curves/Curves20260331.xlsx` is **synthetic** (flat 4.00% SOFR / 3.50% FF) — committed so the test suite and CLI smoke run work out of the box. To run against real market data, drop your `CurvesYYYYMMDD.xlsx` into `data/curves/` (this folder is tracked, so be deliberate about what you commit) and run with the matching `--val-date`. The real-data drop location at the repo root (`/Curves*.xlsx`) is gitignored.

`data/fixings/fedfunds.csv` is also synthetic (~3.65–5.30%).

`data/trades/SWAP_001..003.yaml` are sample trade definitions covering forward-start, in-progress, and short-maturity cases. Add your own `*.yaml` files and the loader will pick them up automatically.
