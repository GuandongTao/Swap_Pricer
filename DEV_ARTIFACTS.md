# Development Artifacts — Test & Diagnostic Inventory

A register of every test, diagnostic, and ad-hoc development artifact in this
repo, so a production packaging step can **strip or hide** them. Keep this file
up to date whenever a test or diagnostic file is added, renamed, or removed.

**Production keeps:** `src/swaps/`, `scripts/price_portfolio.py`,
`scripts/price_portfolio_batch.py`, `data/`, `entity/`, `pyproject.toml`,
`README.md`. Everything listed below can be excluded from a production build.

---

## 1. Test suite — `tests/` (exclude entire directory)

The formal pytest suite. Not needed at runtime; exclude the whole `tests/`
folder from a production package.

| Path | Covers |
|---|---|
| `tests/test_conventions.py` | day-count / business-day conventions |
| `tests/test_rate_quoting.py` | rate→DF quoting |
| `tests/test_calendar.py` | holiday calendars |
| `tests/test_fixings.py` | historical fixing lookup |
| `tests/test_notional.py` | notional handling |
| `tests/test_fixed_leg.py` | fixed-leg cashflows |
| `tests/test_curve.py` | zero curve / interpolation |
| `tests/test_floating_leg.py` | floating-leg cashflows |
| `tests/test_principal_exchange.py` | principal exchange |
| `tests/test_pricer.py` | swap pricing |
| `tests/test_golden_master.py` | golden-master regression |
| `tests/test_cross_frequency.py` | cross-frequency legs |
| `tests/test_schedule.py` | schedule generation |
| `tests/test_roll_conventions.py` | roll conventions |
| `tests/test_spread_and_custom_calendar.py` | spreads + custom calendars |
| `tests/test_csv_trade_loader.py` | CSV trade loader |
| `tests/test_payment_delay_per_leg.py` | per-leg payment delay |
| `tests/test_dated_curve_loader.py` | dated curve loader |
| `tests/test_dated_df_loader.py` | dated DF loader |
| `tests/test_cli_flags.py` | CLI flag handling |
| `tests/test_loaders_and_portfolio.py` | loaders + portfolio |
| `tests/test_bloomberg_conventions.py` | Bloomberg convention validation |
| `tests/test_io_prod.py` | production CSV writer (incl. CCID) |
| `tests/__init__.py` | test package marker |
| `tests/golden/*.json` | golden snapshots (already gitignored) |

## 2. Diagnostic scripts — `scripts/` (exclude individually)

Read-only investigation tools. Useful in dev/support; not part of the
production run path.

| Path | Purpose | Prod |
|---|---|---|
| `scripts/diagnose_fixings.py` | explains why a present fixing row reads as missing | exclude |
| `scripts/discount_factor_test.py` | discount-factor inspection / hand-check dump | exclude |
| `scripts/generate_synthetic_curve.py` | generates synthetic curve test data | exclude |
| `scripts/generate_synthetic_fixings.py` | generates synthetic fixing test data | exclude |

## 3. Production scripts — `scripts/` (KEEP)

| Path | Purpose |
|---|---|
| `scripts/price_portfolio.py` | single-date pricing entry point |
| `scripts/price_portfolio_batch.py` | multi-date batch pricing entry point |

## 4. Ad-hoc scratch — `_scratch/` (never committed)

`/_scratch/` is the scratch directory for one-off diagnostics and throwaway
test files. It is gitignored — never commit it, never ship it. Delete freely.

---

_Last updated: 2026-05-22_
