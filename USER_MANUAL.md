# Swap Pricer — User Manual

A daily mark-to-market pricer for a portfolio of USD fixed-vs-float OIS interest
rate swaps (Fed Funds projection, SOFR discounting). This manual is the
authoritative guide to running the scripts and their flags.

---

## 1. Setup

The package is `swaps` (see `pyproject.toml`). Install it once into your
environment; this also pulls the runtime dependencies (numpy, pandas, openpyxl,
pyarrow, python-dateutil, PyYAML).

```bash
pip install .            # runtime only
pip install -e .[dev]    # editable + pytest/ruff/mypy (for running the test suite)
```

The entry-point scripts **self-bootstrap `src/` onto `sys.path`**, so once the
package is installed (or even from a checkout) you can run them directly — no
`PYTHONPATH` export needed:

```bash
python scripts/price_portfolio.py --val-date 2026-03-31 -v
```

Run the test suite with:

```bash
pytest -q
```

---

## 2. Input data layout

Both scripts read from a base data directory (`--data-dir`, default `./data`):

```
data/
  curves/    market_environment_<val_date>.csv   # SOFR + Fed Funds curves
  fixings/   fixing_cail_USD-FEDFUNDS-ON.csv      # overnight EFFR fixing history
  trades/    *.yaml | *.csv                       # the swap portfolio
  entity/    Entity_Reference_Report.csv          # Entity_Code,Default RC  (CCIDs)
             Netting_Database.csv                  # netting flags + netting entity
  debt/      <hedged-debt inputs, valued in-process>
```

Curve format is selectable — see `--pillar-dates` / `--pillar-dates-df` below.

---

## 3. Single-date pricer — `price_portfolio.py`

Prices **one** valuation date.

```bash
python scripts/price_portfolio.py --val-date 2026-04-30 -v
```

| Flag | Default | Purpose |
|---|---|---|
| `--val-date` | **(required)** | ISO valuation date, e.g. `2026-03-31`. |
| `--data-dir` | `./data` | Base input directory (layout in §2). |
| `--out-dir` | `./output` | Where the run folder is written. |
| `--entity-rc` | `data/entity/Entity_Reference_Report.csv` | Entity Reference Report (`Entity_Code,Default RC`) used to build Balance-Sheet / PL CCIDs. Missing file → CCID fields left blank. |
| `--netting-db` | `data/entity/Netting_Database.csv` | Netting Database (keyed by Netting ID). Source of truth for Cash-Flow / Position Netting Allowed flags and the Netting Entity on both feeds. Missing file → IRS Netting feed skipped (warning recorded to manifest). |
| `--version N` | auto | Submission version (sequence) number — see §5. Default auto-increments; pass `N` to re-issue a specific version (`--version 7` → `00007`). |
| `--debug-loan` | off | Also write the hedged-debt summary `Debt_Summary_<val_date>.csv`. Col AW is unaffected — the debt is always valued. |
| `--debug-full` | off | Write **everything**: prod CSV + Debt_Summary + portfolio workbook + per-trade detail + per-trade debug + parquet. Superset of `--debug-loan`. |
| `--pillar-dates` | off | Dated-pillars curve format: `sofr_<val_date>.csv` + `ff_<val_date>.csv` (no header; col A pillar date ISO, col B zero rate decimal). |
| `--pillar-dates-df` | off | Dated-DFs curve format: `sofr_df_<val_date>.csv` + `ff_df_<val_date>.csv` (col B is the discount factor; bypasses rate quoting). Mutually exclusive with `--pillar-dates`. |
| `-v`, `--verbose` | off | INFO-level progress (per-trade timings, run folder, convention/matured/no-curve notices). Default is ERROR-only — warnings still land in `manifest.warnings[]` but stay off stdout (cloud-pipeline friendly). |

**Default (no debug flags)** writes just the production CSV + manifest (+ netting
CSV when the netting DB is present) — the minimal cloud delivery set.

---

## 4. Batch pricer — `price_portfolio_batch.py`

Prices **several** valuation dates in parallel, each in its own isolated
subprocess and its own run folder.

```bash
# pick dates any of these ways:
python scripts/price_portfolio_batch.py --val-date 2026-03-25 --val-date 2026-03-31
python scripts/price_portfolio_batch.py --val-dates 2026-03-25,2026-03-26,2026-03-31
python scripts/price_portfolio_batch.py --start 2026-03-25 --end 2026-03-31 --max-workers 4
```

| Flag | Default | Purpose |
|---|---|---|
| `--val-date` | — | A single valuation date; **repeatable** (`--val-date A --val-date B`). |
| `--val-dates` | — | Comma-separated dates (`D1,D2,...`). |
| `--start` / `--end` | — | Inclusive ISO date range. |
| `--max-workers N` | auto | Number of parallel worker **processes**. Each date is priced in its own subprocess; `N` caps how many run at once. Default = Python auto-select (~CPU count). Lower it (e.g. `2`) on a shared/constrained box. No effect on a single date. |
| `--data-dir`, `--out-dir`, `--entity-rc`, `--netting-db` | as §3 | Same as the single-date pricer; applied to every date. |
| `--debug-loan`, `--debug-full` | off | Same as §3, applied per date. |
| `--pillar-dates`, `--pillar-dates-df` | off | Same as §3. |
| `-v`, `--verbose` | off | INFO-level progress in parent **and** workers. |

> The batch runner does **not** take `--version` — each date auto-increments its
> own submission version independently (see §5).

---

## 5. Output layout & submission versioning

Every run — single-date, or one date inside a batch — is self-contained in its
own folder, named by valuation date, run date, optional data-source tag, and a
**5-digit submission version**:

```
output/valdate_<val_date>_rundate_<run_date>[ BBG]_ver_<NNNNN>/
  IRS_Valuation_<val_date>-<NNNNN>.csv     # production valuation feed
  IRS_Netting_<val_date>-<NNNNN>.csv       # production netting feed (if netting DB present)
  manifest.json                            # outputs, warnings, version, hashes
  # --debug-full additionally writes:
  portfolio_<val_date>.xlsx, detail/, debug/, parquet/, Debt_Summary_<val_date>.csv
```

**Submission version (`<NNNNN>`):**

- A 5-digit sequence number scoped to `(val_date, data source)`.
- **Auto-increments** past the highest prior run for that same as-of date +
  source, starting at `00001`. Legacy folders without a `_ver_` suffix can't be
  read as a sequence, so detection restarts at `00001` (and the new
  `..._ver_00001` folder is a distinct name — the legacy folder is never
  overwritten).
- The **same stamp** drives the folder name, the feed filename, and header-row
  cell 4 — they always agree.
- Override with `--version N` on the single-date pricer to re-issue a specific
  number.

---

## 6. Common recipes

```bash
# One date, quiet (cloud default): just the prod CSV + manifest (+ netting)
python scripts/price_portfolio.py --val-date 2026-04-30

# One date, full diagnostics for investigation
python scripts/price_portfolio.py --val-date 2026-04-30 --debug-full -v

# Re-issue a specific submission version
python scripts/price_portfolio.py --val-date 2026-04-30 --version 3

# A month, 4 dates at a time
python scripts/price_portfolio_batch.py --start 2026-04-01 --end 2026-04-30 --max-workers 4 -v

# Dated-pillars curve inputs instead of the market_environment CSV
python scripts/price_portfolio.py --val-date 2026-04-30 --pillar-dates
```
