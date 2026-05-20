# Open Questions & Assumptions

Living list of things assumed during initial build that need confirmation before going live.
Update this file as questions are answered (move resolved items to the bottom with the answer).

---

## OPEN — please clarify

### Q1. Calendars: are `fixing_calendar` and `payment_calendar` ever different per trade?
**Currently assumed:** they are stored as two separate per-trade fields. If they're always identical, we can simplify by collapsing them into one field.
**Impact if wrong:** none for correctness — the worst case is two fields carrying the same vector. Simplification only.

### Q2. Zero-rate quoting convention on the curve Excel
**Now assumed (updated 2026-05-13 PM):** **continuously compounded ACT/360**, i.e. `DF(T) = exp(-r · T / 360)`.
**History:** Continuous (2026-05-12) → AnnualCompoundedACT360 (2026-05-13 AM) → Continuous (2026-05-13 PM, this entry). The annual-compounded numbers ran higher than benchmark; continuous lowers DF uniformly and matched closer.
**File analyzed:** `Curves20260331.xlsx`. Both SOFR and FEDFUNDS zero rates are decimals (~0.036), but the file does not state the compounding convention.
**Impact if wrong:** DFs will be biased — small at short tenors, larger at long tenors. All downstream PVs shift.
**How to confirm:** ask the curve provider, or back-check one known DF (e.g., compare to Bloomberg `SWPM` or any vendor screen for `2026-03-31` curve).
**Alternatives to switch to:** `ContinuousACT360`, `SimpleACT360`, `ContinuousACT365`, `AnnualCompoundedACT365`. Change the `DEFAULT` in `src/swaps/rate_quoting.py` or pass `rate_quoting=...` to `ZeroCurve` / `ExcelCurveLoader`.

### Q3a. Tenor → pillar date convention (resolved 2026-05-13 PM)
**Now assumed:** **calendar-tenor convention.** `ND=+N days`, `NW=+N weeks`, `NM=+N calendar months`, `NY=+N calendar years`. `ON=+1 day`, `TN=+2 days`.
**Reason:** benchmark curve dates (`1Y → 2027-03-31`, `50Y → 2076-03-31`) confirm calendar dating. DF formula stays ACT/360 (`T = actual_days / 360`), which produced DFs closest to benchmark; switching the DF formula to /365 or /ACT moved further away.
**History:** Calendar (2026-05-12) → strict 360-day (2026-05-13 AM) → Calendar (2026-05-13 PM, this entry).

### Q3. `ON` and `TN` pillar semantics
**Currently assumed (more common version):** both are zero rates anchored at `val_date`, i.e.
- `ON` pillar date = `val_date` + 1 calendar day (term ~1/360)
- `TN` pillar date = `val_date` + 2 calendar days (term ~2/360)
Both treated like any other zero pillar.
**Alternative interpretation:** `ON` represents the deposit rate for `[val_date, val_date+1BD]` and `TN` for `[val_date+1BD, val_date+2BD]` — requires a different conversion (forward rates rather than zero rates).
**Impact if wrong:** affects the very front end of the curve (first few days of DFs).
**How to confirm:** ask the curve provider; or check whether `DF(ON) ≈ 1 - r·1/360` with the given numbers.

### Q4. Fixed-leg payment frequency and day-count per trade
**Currently assumed:** every trade definition (YAML) carries `fixed_frequency` (e.g. `1Y`, `6M`, `3M`, `1M`) and `fixed_daycount` (one of `ACT/360`, `ACT/365F`, `30/360`, `30E/360`, `ACT/ACT-ISDA`).
**Status:** awaiting actual trade definitions for the 30 instruments to see what conventions appear in practice.

### Q5. Floating-leg payment delay and lockout per trade
**Currently assumed:** every trade carries `payment_delay_bdays` (int, default 0) and `lockout_bdays` (int, default 0).
**Defaults match:** no lag, no lockout (i.e. payment date = accrual end, all fixings observed).
**Status:** awaiting trade definitions. Standard cleared OIS would be `payment_delay_bdays = 2`, `lockout_bdays = 0`.

### Q6. NY Fed holiday calendar — algorithmic, verified for 2026
**Implementation:** holidays computed algorithmically in `src/swaps/calendar_us.py`. 11 federal holidays per year with the standard rules; Sunday-falling holidays shift forward to Monday (Fed Banks rule); Saturday-falling holidays are *not* shifted to Friday (Fed Banks stay open Friday per Fed's published note).
**Verification (2026-05-13):** all 11 of our 2026 holidays match the official Federal Reserve Bank schedule at https://www.federalreserve.gov/aboutthefed/k8.htm exactly. 2027-2030 follow the same algorithmic rules; spot-check on demand. 2023-2025 are historical and not on the Fed's current page — our algorithmic output is consistent with the actually-observed dates but not vendor-verified.
**One-off closures (e.g. presidential funerals)** are not derivable algorithmically; use per-trade `fixing_calendar_extras` or `fixing_calendar_extras_file` to add them.

### Q7. Pay-fixed vs receive-fixed — sign convention per trade
**Currently assumed:** each `Swap` has a `pay_fixed: bool` field; PV reported from that party's perspective.
**Status:** awaiting trade definitions to confirm both directions occur in the portfolio.

### Q8. Curve / fixing file naming convention (resolved 2026-05-15)
**Resolved:** production inputs are the raw vendor formats and the legacy synthetic
formats have been retired:
- Curve: `data/curves/market_environment_YYYY-MM-DD.csv` (ISO date). One conceptual
  sheet (`in`). A few header rows (`Name`/`Date`/`Property` in col A) precede the
  data; many irrelevant pillars (other currencies, EQ/FX/VOL tickers) are
  interleaved and filtered out by col-A `TICKER_RE` to keep only
  `IR.USD-{SOFR|FEDFUNDS}-ON.ZERORATE-{TENOR}.MID`.
- Fixings: `data/fixings/fixing_cail_USD-FEDFUNDS-ON.csv`, `ticker,date,rate`
  content identical to the old `fedfunds.csv` (no special handling).
`ExcelCurveLoader` resolves the curve file by ISO `val_date` in the name; the
old `CurvesYYYYMMDD.xlsx` path is no longer supported.

### Q9. Historical FF fixings — source format and location
**Currently assumed:** a CSV or Excel under `data/fixings/` with columns `date, rate`.
**Status:** awaiting a sample file. Must cover at least the longest in-flight accrual period of the oldest trade.

### Q10. Trade definition format
**Currently assumed:** one YAML file per trade under `data/trades/`, with fields:
```yaml
trade_id: SWAP_001
notional: 10_000_000
currency: USD
pay_fixed: true
fixed_rate: 0.04
start_date: 2024-06-15
maturity_date: 2029-06-15
fixed_frequency: 1Y
fixed_daycount: ACT/360
floating_daycount: ACT/360
fixing_calendar: NY_FED
payment_calendar: NY_FED
payment_delay_bdays: 2
lockout_bdays: 0
business_day_convention: ModifiedFollowing
```
**Status:** schema is a strawman; awaiting real trade definitions to validate fields.

---

## Resolved

- **2026-05-12 — Floating spread**: per-trade `floating_spread` (decimal, default 0.0) added to the trade YAML schema. Applied per ISDA OIS convention: `period_cf = N * ((growth - 1) + spread * D / 360)`. Effective coupon column added to the floating cashflow frame.
- **2026-05-12 — Customized calendars**: per-trade `fixing_calendar_extras` (inline list of dates) and `fixing_calendar_extras_file` (CSV / TXT / XLSX path) supported, on top of the named base calendar. Same fields exist for `payment_calendar_*`.
- **2026-05-13 — Floating-leg per-row schedule**: the per-row `accrual_start` / `accrual_end` columns in the floating cashflow frame are now the **per-fixing sub-accrual bounds** (one row per business day in the period). New columns `period_start` / `period_end` carry the outer payment-period bounds. Coupon is compounded across all per-fixing rows at the period end and discounted at the SOFR DF on `payment_date`.
- **2026-05-13 — SWAP_DEBUG_001 conventions** (updated 2026-05-13 PM): hand-debug test trade. 500,000,000 notional, pay floating / receive 5.41% fixed, ACT/360 day-count on both legs (fixed coupon = `N × R × days/360`), monthly periods rolling on the **8th** (ModifiedFollowing — skip weekend by rolling forward to next business day), payment delay **2** NY-Fed business days (weekends skipped), no lockout, no spread, NY-Fed fixing calendar. First accrual day 2026-03-09; last accrual ends 2035-11-08; final payment derived as 2035-11-08 + 2 BD.
- **2026-05-13 PM — Missing-historical-fixings policy: hard fail per trade.** If `FixingHistory.get(fixing_date)` returns `None` for any `fixing_date < val_date`, `OISFloatingLeg` raises `ValueError`; the Portfolio runner records the trade in `manifest.errors[]` and continues with the remaining trades. No silent fallback. Recorded in `plan.md` Resolved Conventions table for future reference. Any softer policy (carry-forward, front-end-rate substitute, period-skip) must be opt-in via an explicit flag, not the default.
- **2026-05-14 — Per-leg roll conventions + fixing lookback.** Accepted roll values across the system: `None` / `NoAdjust`, `Following`, `ModifiedFollowing` (default), `Preceding`, `ModifiedPreceding`, `Nearest` (closest BD, ties forward). New `TradeDef` fields, each blank-fallback to `business_day_convention`:
  - **Fixed leg**: `fixed_spot_roll` (rolls the unadjusted effective date), `fixed_accrual_roll` (rolls each accrual end), `fixed_pay_roll` (rolls each payment date).
  - **Floating leg**: `floating_accrual_roll`, `floating_pay_roll`, `floating_fixing_roll` (default `Preceding`), `floating_fixing_lag_bdays` (default 0 = rate set in advance; positive shifts the observation date back by N BDs).
  When floating accrual/pay rolls differ from fixed, the floating leg gets its own rebuilt schedule. Wired through both YAML and CSV loaders. Roll-name validation is eager in the leg constructor.
- **2026-05-14 — Payment-date = val_date policy: excluded from valuation.** If `payment_date == val_date`, that period's cashflow is treated as already paid and contributes 0 to dirty/clean PV. Applies to fixed coupons, floating period payoffs, and both principal-exchange rows on each leg. `df_to_payment` and `discounted_cashflow` columns show `NaN`/`0` for those rows so it's visible in the detail workbook. Equivalent to using strict `payment_date > val_date` everywhere previously gated by `>=`.
- **2026-05-14 — Matured-trade policy: warn, value 0.** If `td.maturity_date < val_date`, the Portfolio runner does **not** call `build_swap` / pricer. It emits a `WARNING` log line, records the trade in `manifest.warnings[]`, and produces a `SwapValuation` with all numeric fields = 0 and empty cashflow frames (`meta.matured = True`). Detail and debug workbooks are skipped for matured trades; the Summary tab still lists them with zeros so portfolio totals stay traceable. Distinct from the hard-fail policy for missing fixings, which still raises for live trades.
- **2026-05-19 — Par rate as standard output.** `SwapPricer.par_rate(swap, md)` added: closed-form `par = (PV_floating − PV_fixed_principal) / annuity`, where `annuity = Σ τ_i·DF_SOFR(t_i)·N_i` over **remaining** fixed coupons (`payment_date > val_date`). Recomputed every valuation date from that day's curves over the remaining schedule — **not** an inception value. `SwapValuation` gains `par_rate` + `rate_diff_bp = (contract_fixed_rate − par)·1e4`; both surfaced in the Summary tab/Parquet and pinned in the golden master. Invariant `clean ≈ ±annuity·(fixed − par)` covered by `test_clean_decomposes_into_annuity_times_rate_gap`. Note: par uses the floating leg's embedded projection curve (existing pricer architecture; `md.projection_curve` is only used in the DV01 rebuild).
- **2026-05-20 — `--pillar-dates-df` (DF-direct curve input).** Third curve-input path; bypasses `RateQuoting` entirely so the user supplies discount factors per pillar date. New `DatedDFCurveLoader` reads `sofr_df_YYYY-MM-DD.csv` and `ff_df_YYYY-MM-DD.csv` (same shape as `--pillar-dates`: no header, col A pillar date ISO, col B = DF; positive, typically ≤ 1). `ZeroCurve.from_dated_dfs` feeds the DFs straight into the log-linear interpolation pipeline; `Pillar.zero_rate` is NaN (no quoting convention was applied). CLI flags `--pillar-dates`, `--pillar-dates-df`, and the default `market_environment_*` path are now an argparse mutually-exclusive group on both scripts; passed through to per-date workers in batch. As part of this, `ZeroCurve.bumped()` was rewritten to bump uniformly at the DF level — rate-valued pillars are re-quoted via `self.rate_quoting`, NaN-rate pillars get the continuous-ACT/360-equivalent DF shift `DF_new = DF · exp(−δ · days / 360)` — which also fixes a latent bug where `bumped()` would have failed on `from_dated_pillars` curves (ISO-date pillar tenors). Tests in `tests/test_dated_df_loader.py`.
- **2026-05-20 — `--pillar-dates` ingestion + `-v` verbose + standardized exit codes.** New `DatedCurveLoader` reads two no-header CSVs per val_date in `data/curves/`: `sofr_<val_date>.csv` (discount) and `ff_<val_date>.csv` (projection) — col A pillar date (ISO), col B zero rate (decimal). `ZeroCurve.from_dated_pillars` skips `tenor_to_date` and feeds pillar dates straight into the existing build path; quoting/interpolation/dual-curve pricing unchanged. Selected by CLI `--pillar-dates` on both single-date and batch scripts; mutually exclusive with the default `market_environment_*` path (no fallback). New `-v`/`--verbose` flag toggles logging WARNING (default, cloud-friendly) → INFO; applied to parent and per-date workers. Exit-code scheme: **0** = success (skipped-no-curve counts as success); **1** = hard failure (uncaught exception or a date errored entirely); **2** = CLI usage (argparse); **3** = partial (some trades errored). Tests in `tests/test_dated_curve_loader.py` and `tests/test_cli_flags.py`.
- **2026-05-19 — Bloomberg convention rewrite (branch `feature/bloomberg-convention-match`).** Decided: every convention is per-leg, named in Bloomberg vocabulary; only economic terms (`trade_id`, `notional`, `pay_fixed`, `fixed_rate`, `start_date`, `maturity_date`) stay shared. Removed the global `business_day_convention` (no shared roll fallback — derive per leg), shared calendars, and shared `payment_delay_bdays`. Added per-leg `eff_date_adj` / `bus_day_adj` / `pay_date_adj` / `adjust` / `roll_convention`, floating `rst_bus_day_adj`, per-leg calculation/fixing/payment calendars (default FD). `roll_convention` owns generation direction + stub + EOM; **engine default = `forward_eom`** (legacy backward/`ShortFront` becomes `backward`; golden master regenerated). `adjust` ∈ {`acc_and_pay` (legacy), `pay`, `none`} drives unadjusted-vs-adjusted accrual; `AccrualPeriod` carries both bound sets; pay date re-based on unadjusted end. Validation: allow all input, hard error on impossible combos, WARNING on Bloomberg-grayed combos (no strict flag). Full schema in `plan.md` → *Bloomberg-Matched Convention Schema*.
- **2026-05-19 — Separate payment delay per leg.** New `TradeDef.fixed_payment_delay_bdays` / `floating_payment_delay_bdays` (default `None`). Each falls back to the shared `payment_delay_bdays` when None, so all existing trades are unchanged. The delay is baked into each leg's schedule by `generate_schedule`; `build_swap` now resolves `fixed_pd`/`float_pd` separately, uses `fixed_pd` for the fixed schedule, and rebuilds an independent floating schedule when `float_pd != fixed_pd` (in addition to the existing frequency/roll divergence triggers). Wired through YAML + CSV loaders (optional columns; blank => fallback) and documented in the `.sample`/`template` files. Effective per-leg delays recorded in `swap.meta`. Covered by `tests/test_payment_delay_per_leg.py`.
- **2026-05-19 — Independent floating-leg payment frequency.** New `TradeDef.floating_frequency` field (default `""`). Blank falls back to `fixed_frequency` — the standard compounded-in-arrears OIS convention where both legs share period boundaries, so all existing trades are unchanged. Set explicitly (e.g. `1Y` fixed / `3M` floating) for cross-frequency structures; `build_swap` then builds an independent floating schedule (it already did so for divergent rolls — frequency divergence now also triggers the rebuild). Wired through YAML + CSV loaders and the `.sample`/`template` files. `OISFloatingLeg`/pricer/par-rate need no change (legs were already schedule-independent; par rate sums each leg's own cashflow frame). Effective frequency recorded in `swap.meta["floating_frequency"]`. Covered by `tests/test_cross_frequency.py`.
- **2026-05-19 — Floating spread convention confirmed: excluded from compounding.** Implemented method is `period_cf = N·((∏(1+rᵢ·dᵢ/360) − 1) + spread·D/360)` — only the index compounds; the spread is a simple, non-compounded add-on (ISDA "spread exclusive of compounding"). Same in `accrued()`. This is hardcoded; there is **no** toggle for the "spread included in compounding" variant. Adding an inclusive-mode flag is a future opt-in if ever required.
- **2026-05-13 PM — Per-leg principal exchange.** Two new fields on the trade YAML/CSV: `fixed_principal_exchange` and `floating_principal_exchange`. Each accepts `none` (default) \| `start` \| `end` \| `both`. Sign convention: `start` row = `-notional` at `start_date`; `end` row = `+notional` at the final payment date. Discounted with SOFR DF on the payment date. Cashflow frames gain a `flow_type` column. Default `none` keeps plain swaps unchanged. Examples: bond/note style = principal `end` on one leg only; cross-currency-style bilateral exchange = `both` on both legs (PV-neutral).
