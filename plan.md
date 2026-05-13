# Plan: Fed Funds Fixed-Float Swap Pricer

## Context

Build a daily mark-to-market pricer in Python for a portfolio of ~30 USD fixed-vs-float interest rate swaps where:

- **Floating leg**: Effective Fed Funds (EFFR) daily fixings, compounded **in arrears** per accrual period.
- **Fixed leg**: periodic coupons; payment frequency and day-count vary per trade.
- **Discounting**: SOFR OIS zero curve (dual-curve setup: SOFR discounts, FF projects).

Outputs: clean / dirty / accrued / DV01 per trade plus full cashflow detail, exported to Excel **and** Parquet. Development is local first; no GitHub until a first stable draft is ready. Working directory: `F:\Projects - Github\Swaps`.

---

## Resolved Conventions

| Topic | Decision |
|---|---|
| Discount vs. projection | SOFR discounts, FF projects (no basis curve) |
| Curve interpolation | Log-linear on DFs, calendar-day axis (applied identically to SOFR and FF) |
| Zero-rate quoting | Default continuously compounded ACT/360; `RateQuoting` strategy is pluggable |
| OIS period coupon | Derived from two endpoint DFs (curve-implied), not by re-compounding daily forwards. Daily implied forward is displayed as an audit column. |
| Past vs. future fixings | Split at val_date: historical product × curve-implied product |
| Missing historical fixings | **Hard fail per trade** — `OISFloatingLeg._resolved_rate` raises `ValueError` if `fixing_date < val_date` and `FixingHistory.get(d)` is `None`. The Portfolio runner catches it, records the trade in `manifest.errors[]`, and continues with the remaining trades; the run ends `status="partial"`. Rationale: safer than silent fallbacks (carry-forward, front-end-rate substitute, period-skip) which can hide gaps in real history and produce wrong PV that looks plausible. Any softer policy must be an explicit opt-in flag, not the default. |
| Fixed leg freq + DC | Per-trade; supports ACT/360, ACT/365F, 30/360, 30E/360, ACT/ACT-ISDA |
| Payment delay | Per-trade `payment_delay_bdays` (default 0); shifts cash date only |
| Lockout | Per-trade `lockout_bdays` (default 0); last N fixings frozen at the (N+1)th-to-last value |
| Calendars | Per-trade `fixing_calendar` and `payment_calendar` (separate fields) |
| Notional | `NotionalSchedule` callable; constant default, amortization port for later |
| Sign convention | From fixed-rate payer's perspective (configurable on the `Swap`) |

### OPEN — flagged for revisit
- **Q1.** Are `fixing_calendar` and `payment_calendar` ever different? If always identical, we can simplify later — for now they are separate fields and may carry the same vector.
- **Q2.** Confirm the actual zero-rate quoting convention once a sample SOFR/FF Excel arrives. Default `ContinuousACT360` is assumed; swapping to another `RateQuoting` is a one-line change per curve.

---

## OIS Compounding Math (reference)

For accrual period `[T_s, T_e]`, valuation date `t_v`:

```
R_comp = ( ∏_{i: fixing < t_v} (1 + r_hist_i · d_i / 360)
         × ∏_{i: fixing ≥ t_v} (1 + r_fwd_i  · d_i / 360)
         − 1
        ) · 360 / D
```

When the entire period is in the future, this collapses (algebraically) to the curve-implied:

```
R_comp = (DF_FF(T_s) / DF_FF(T_e) − 1) · 360 / D
```

We compute the period coupon **directly from the two endpoint DFs** when no historical fixings are involved (cleaner, no rounding drift). When the period straddles `t_v`, we split: historical product up to `t_v`, then DF ratio from `t_v` to `T_e` for the projected piece.

Standard ISDA OIS day-count weights `d_i` apply (Fri fixing typically carries `d_i = 3` over the weekend).

---

## Object Design

### Conventions & quoting

- **`RateQuoting`** *(strategy)* — `rate_to_df(r, T_years)`, `df_to_rate(df, T_years)`. Variants: `ContinuousACT360` *(default)*, `SimpleACT360`, `ContinuousACT365`, `AnnualCompoundedACT365`.
- **`DayCount`** *(strategy)* — `year_fraction(d1, d2)`. Variants: `ACT_360`, `ACT_365F`, `THIRTY_360`, `THIRTY_E_360`, `ACT_ACT_ISDA`.

### Calendar & schedule

- **`USCalendar`** — business-day calendar (static NY Fed holidays initially). `is_business_day`, `add_business_days`, `roll(d, bdc)`.
- **`AccrualPeriod`** *(dataclass)* — `start, end, payment_date, day_count_fraction, notional`.
- **`generate_schedule(start, end, frequency, calendar, bdc, stub) → list[AccrualPeriod]`**.

### Curve

- **`ZeroCurve`** — built from term pillars (`1D`, `1W`, …, `50Y`) + a `RateQuoting`. Exposes:
  - `df(date)` — log-linear DF interpolation on calendar-day axis
  - `df_vector(dates)`
  - `forward(t1, t2)` — simple ACT/360
  - `to_debug_frame()` — pillar table with parsed dates, days, rates, DFs
  - `df_grid_debug(start, end)` — daily `date, DF, log_DF, implied_daily_fwd`
- Two instances per valuation: `sofr_curve` (discount), `ff_curve` (projection).

### Fixings & notional

- **`FixingHistory`** — `get(date) → rate | None`. `None` ⇒ caller falls through to curve.
- **`NotionalSchedule`** *(callable)* — `date → notional`. `ConstantNotional` now; `StepNotional` port for future amortization.

### Legs

- **`Leg`** *(ABC)* — `cashflows(val_date)`, `pv(val_date, discount_curve)`, `accrued(val_date)`.
- **`FixedLeg(Leg)`** — `schedule, notional, rate, daycount, payment_calendar`.
- **`OISFloatingLeg(Leg)`** — `schedule, notional, projection_curve, fixings, daycount, payment_delay_bdays, lockout_bdays, fixing_calendar, payment_calendar`.

### Swap, market data, pricer

- **`Swap`** — `fixed`, `floating`, `pay_fixed: bool`, `trade_id`, trade-level metadata.
- **`MarketData`** — `val_date, discount_curve, projection_curve, fixings`.
- **`SwapPricer`** — `price(swap, market_data) → SwapValuation`. Also `dv01(swap, market_data)` via parallel +1bp SOFR bump.
- **`SwapValuation`** *(dataclass)* — `clean, dirty, accrued, dv01, fixed_cf: DataFrame, floating_cf: DataFrame` + identifying columns (see DB-readiness).

### Loaders (input abstraction)

- **`CurveLoader`** *(ABC)* — `load(val_date, curve_name) → ZeroCurve`.
  - `ExcelCurveLoader` *(now)*, `DataFrameCurveLoader` *(tests & future automation)*. Ports for DB/API later.
- **`FixingLoader`** *(ABC)* — `ExcelFixingLoader`, `DataFrameFixingLoader`.
- **`TradeLoader`** *(ABC)* — `YamlTradeLoader`, `DataFrameTradeLoader`.

The Excel loader is tolerant: configurable sheet name and column names (`Tenor`, `Rate`).

### Portfolio & output

- **`Portfolio`** — takes loaders + a list of trade ids; iterates, prices each, writes outputs.
- **`io_excel`** — writes portfolio workbook + per-trade detail workbooks (see Output section).
- **`io_parquet`** — same frames also dumped to Parquet for downstream automation / DB load.

### Class count

~20 classes total, half of them strategy variants. Three pluggable axes — `RateQuoting`, `DayCount`, `*Loader` — so new conventions or input sources are subclass additions, not pricer edits.

---

## Output Layout

### `output/portfolio_<val_date>.xlsx` — the everyday view

| Tab | Contents |
|---|---|
| `Summary` | One row per trade: trade_id, notional, fixed_rate, start, maturity, clean, dirty, accrued, DV01, PV(fixed), PV(floating) |
| `FloatingCF` | All floating-leg cashflows stacked, `trade_id` as leading column |
| `FixedCF` | All fixed-leg cashflows stacked, `trade_id` as leading column |
| `Curves` | SOFR + FF zero curves used (audit trail) |

### `output/detail/<trade_id>.xlsx` — drill-down per trade

Two tabs as originally specified — floating cashflow and fixed cashflow with full per-fixing detail. Generated alongside the portfolio file (or on a `--detail` flag).

### Floating-leg cashflow columns (per fixing row)

`run_id · val_date · run_date · git_sha · trade_id · period_start · period_end · payment_date · fixing_date · accrual_start · accrual_end · day_count · reset_rate · rate_source · implied_daily_fwd · df_to_fixing · df_to_payment · spread · compounded_coupon* · effective_coupon* · period_cashflow* · discounted_cashflow*`

`*` = filled only on the last fixing row of each period.

Semantics:
- `period_start` / `period_end` — outer payment-period bounds (constant across all rows within one period). `payment_date = period_end + payment_delay_bdays` (NY-Fed business days).
- `accrual_start` / `accrual_end` — **per-fixing** sub-interval. `accrual_start = fixing_date`; `accrual_end = next fixing date` (or `period_end` on the last fixing of a period). `day_count = (accrual_end − accrual_start).days`.
- `reset_rate` — the rate that applies for [`accrual_start`, `accrual_end`). For past fixings it comes from `FixingHistory`; for future fixings, the simple-ACT/360 forward `(DF(f)/DF(next_f) − 1) × 360/days`.
- `compounded_coupon` = `(∏(1 + r_i · d_i/360) − 1) · 360 / D` where `D = period_end − period_start` in calendar days.

### Fixed-leg cashflow columns

`run_id · val_date · run_date · git_sha · trade_id · accrual_start · accrual_end · payment_date · day_count_fraction · notional · coupon_rate · payment_amount · df_to_payment · discounted_cashflow`

### Parquet output (enabled from day 1)

Same DataFrames written to `output/parquet/<val_date>/{summary,floating_cf,fixed_cf,curves}.parquet`. Adds `pyarrow` dependency; ~1 extra line per frame. Provides immediate DuckDB query layer and a clean migration path to a real DB later.

---

## Debug / Test Output Sockets

Every numeric class exposes `to_debug_frame()` (or named variants) returning a fully-laid-out DataFrame so values can be exported and compared against Bloomberg / hand calcs:

| Class | Method | Contents |
|---|---|---|
| `ZeroCurve` | `to_debug_frame()` | Pillars: tenor, date, days, zero_rate, DF |
| `ZeroCurve` | `df_grid_debug(start, end)` | Daily DF, log_DF, implied daily fwd |
| `FixingHistory` | `to_debug_frame(start, end)` | date, source (history / curve), rate |
| `OISFloatingLeg` | `fixings_debug()` | Per-fixing-row frame before aggregation |
| `OISFloatingLeg` | `period_breakdown()` | historical_product, projected_product, comp_rate, D, comp_coupon |
| `FixedLeg` | `to_debug_frame()` | Per-period accrual, dcf, payment, df, pv |
| `SwapPricer` | n/a — `SwapValuation` is the debug view | |

**CLI `--debug` flag** writes one `output/debug/<trade_id>_debug.xlsx` per trade with each debug frame on a separate tab. Off by default.

---

## Identifying Columns (every output frame)

Enforced from v1 to make future DB migration drop-in:

| Column | Type | Source |
|---|---|---|
| `run_id` | UUID string | Generated once at start of run |
| `val_date` | date | Market date being priced |
| `run_date` | timestamp | Wall-clock execution time |
| `git_sha` | string | `git rev-parse HEAD` at run start |

Triple `(val_date, run_date, git_sha)` uniquely identifies a run; `run_id` is the FK.

---

## Folder Layout

```
F:\Projects - Github\Swaps\
├── plan.md
├── pyproject.toml
├── README.md
├── src/swaps/
│   ├── conventions.py        # DayCount strategies
│   ├── rate_quoting.py       # RateQuoting strategies
│   ├── calendar_us.py        # NY Fed calendar
│   ├── curve.py              # ZeroCurve
│   ├── fixings.py            # FixingHistory
│   ├── schedule.py           # generate_schedule()
│   ├── notional.py           # NotionalSchedule
│   ├── legs/
│   │   ├── base.py           # Leg ABC
│   │   ├── fixed_leg.py
│   │   └── floating_leg_ois.py
│   ├── swap.py
│   ├── market_data.py
│   ├── pricer.py             # SwapPricer + DV01
│   ├── loaders/
│   │   ├── base.py           # CurveLoader / FixingLoader / TradeLoader ABCs
│   │   ├── excel.py
│   │   └── dataframe.py
│   ├── io_excel.py
│   ├── io_parquet.py
│   ├── manifest.py           # run manifest writer
│   └── portfolio.py
├── data/{curves,fixings,trades}/
├── output/
│   ├── portfolio_<val_date>.xlsx
│   ├── detail/<trade_id>.xlsx
│   ├── debug/<trade_id>_debug.xlsx  (when --debug)
│   ├── parquet/<val_date>/{summary,floating_cf,fixed_cf,curves}.parquet
│   └── manifest_<val_date>.json
├── tests/
└── scripts/price_portfolio.py
```

---

## Workflow (implementation order)

**Block A — Foundation** *(curves, conventions, calendar, schedule)*
- `RateQuoting`, `DayCount`, `USCalendar`, `generate_schedule`, `ZeroCurve`
- Tests: DF round-trip, log-linear interp at known points, business-day rolls

**Block B — Pricing core** *(legs + pricer)*
- `FixingHistory`, `NotionalSchedule`, `FixedLeg`, `OISFloatingLeg`, `Swap`, `SwapPricer`, DV01
- Tests: flat-curve sanity, par-swap test, history-split test, `clean + accrued ≈ dirty` invariant

**Block C — I/O & portfolio** *(loaders, Excel, Parquet, portfolio runner, CLI)*
- Excel + Parquet writers, `Portfolio`, `price_portfolio.py`, sample data, manifest
- Smoke run end-to-end on sample data

**Block D — Regression & debug** *(golden-master + debug sockets)*
- `to_debug_frame()` on each class, `--debug` CLI flag
- Golden-master test: pin one canonical run's output JSON; pytest diffs subsequent runs

Tests live alongside the code in each block, not deferred.

---

## Stability Practices

- `pytest` everywhere; ~80% coverage on `legs/`, `curve.py`, `pricer.py`.
- Pinned dependencies in `pyproject.toml`.
- `ruff` + `mypy --strict` on `src/swaps/`.
- Golden-master regression catches accidental numeric drift.
- Pure CLI, no interactive prompts. Stdout logging. Non-zero exit on error. Fail-fast input validation. (All required for future server deployment.)
- Run manifest (`manifest_<val_date>.json`) records `git_sha`, input file hashes, trade count, timings — written from day 1.

---

## Future: Server Deployment (TODO — not implementing now)

**Bake in now** (already in plan above): CLI-only, config-driven paths, non-zero exit codes, stdout logging, fail-fast validation, deterministic outputs, run manifest.

**Target deployment** (recommended order of preference):
1. **AWS Batch (Fargate) + EventBridge schedule** — no instance management; native retries and CloudWatch.
2. **EC2 + cron + Docker** — simplest if curves live on a private network drive.
3. **GitHub Actions scheduled workflow** — viable if all inputs accessible from a hosted runner.

**Storage**: S3 with versioning ON; inputs snapshotted to `s3://.../inputs/<val_date>/`, outputs to `s3://.../outputs/<val_date>/`.

**Monitoring (three layers)**:
1. **Run failure alarm** — CloudWatch on non-zero exit → SNS email/SMS.
2. **Dead-man's switch** — every successful run posts a heartbeat; alarm fires if no heartbeat by 10:00 NY. Catches scheduler-stopped-firing failures of silence.
3. **Output sanity check** — assert trade_count, no NaNs in summary, file size > N KB.

**Backup posture**: same Docker image runs locally with same env vars → identical output. Input snapshots + git_sha in manifest allow bit-exact reproduction from any machine on any day.

---

## Future: Database Integration (TODO — not implementing now)

**Already DB-ready**: long-format DataFrames stacked with `trade_id`, identifying columns (`run_id`, `val_date`, `run_date`, `git_sha`) enforced from v1, Parquet output enabled from day 1.

**Target schema** (append-only):
```
valuation_runs        (run_id PK, val_date, run_date, git_sha, status, trade_count, …)
trade_valuations      (run_id FK, trade_id, clean, dirty, accrued, dv01, pv_fixed, pv_floating)
floating_cashflows    (run_id, trade_id, fixing_date, accrual_start, accrual_end, …)
fixed_cashflows       (run_id, trade_id, accrual_start, accrual_end, …)
curves_used           (run_id, curve_name, tenor, pillar_date, zero_rate, df)
trade_definitions     (trade_id, notional, fixed_rate, start, maturity, …)
```

**Migration path**: Parquet files → `COPY FROM PARQUET` into PostgreSQL. As-of queries: `WHERE val_date = X ORDER BY run_date DESC LIMIT 1`.

**DB choice**: PostgreSQL (default), TimescaleDB extension if time-series queries dominate, DuckDB as the in-process stepping stone.

---

## Verification (v1 done criteria)

1. `pytest -q` — all unit tests + golden-master green.
2. `python scripts/price_portfolio.py --val-date YYYY-MM-DD` produces:
   - `portfolio_<val_date>.xlsx` with four tabs
   - `detail/<trade_id>.xlsx` per trade
   - `parquet/<val_date>/*.parquet`
   - `manifest_<val_date>.json`
3. Hand-check one swap:
   - `clean + accrued == dirty` to < 1e-8
   - Sum of fixed PV − sum of floating PV ≈ reported NPV (within sign convention)
   - DV01 sign and magnitude reasonable vs. analytic estimate
4. `--debug` flag produces per-trade debug workbooks.
5. Manifest contains git_sha, input hashes, trade count, timestamps.

---

## File locations to be created

All under `F:\Projects - Github\Swaps\` — greenfield (folder will be recreated on implementation start). No existing utilities to reuse.
