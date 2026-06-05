# Schema: Fed Funds Fixed-Float Swap Pricer

## Context

Daily mark-to-market pricer in Python for a portfolio of ~30 USD fixed-vs-float interest rate swaps where:

- **Floating leg**: Effective Fed Funds (EFFR) daily fixings, compounded **in arrears** per accrual period.
- **Fixed leg**: periodic coupons; payment frequency and day-count vary per trade.
- **Discounting**: SOFR OIS zero curve (dual-curve setup: SOFR discounts, FF projects).

Outputs: clean / dirty / accrued / DV01 per trade plus full cashflow detail, exported to Excel **and** Parquet. Production output is the KPMG IRS Valuation and IRS Netting CSV feeds.

---

## Bloomberg-Matched Convention Schema — branch `feature/bloomberg-convention-match`

This branch rewrites the convention model to mirror Bloomberg SWPM leg
settings. **Every convention is per-leg; the only shared (trade-level) fields
are economic terms.**

**Shared / trade-level (unchanged, legitimately overarching):**
`trade_id`, `notional`, `pay_fixed`, `fixed_rate` (fixed-only), `start_date`,
`maturity_date`.

**Removed:** `business_day_convention` (global roll fallback — gone, no shared
fallback), shared `fixing_calendar` / `payment_calendar`, shared
`payment_delay_bdays`, the `*_spot_roll` / `*_accrual_roll` / `*_pay_roll` /
`*_fixing_roll` names, unprefixed `lockout_bdays`.

**Per-leg field schema (Bloomberg vocabulary):**

| Bloomberg | Fixed field | Floating field | Values / default |
|---|---|---|---|
| Eff Date Adj | `fixed_eff_date_adj` | `floating_eff_date_adj` | roll value; blank → leg Bus Day Adj |
| Bus Day Adj | `fixed_bus_day_adj` | `floating_bus_day_adj` | roll value (required) |
| Pay Date Adj | `fixed_pay_date_adj` | `floating_pay_date_adj` | roll value; blank → **leg's own Bus Day Adj** |
| Rst Bus Day Adj | — | `floating_rst_bus_day_adj` | roll value; blank → leg Bus Day Adj |
| Adjust | `fixed_adjust` | `floating_adjust` | `acc_and_pay` (=legacy) \| `pay` \| `none`; default `acc_and_pay` |
| Roll Convention | `fixed_roll_convention` | `floating_roll_convention` | `forward` \| `forward_eom` \| `backward` \| `backward_eom`; **default `forward_eom`** |
| Calc calendar | `fixed_calculation_calendar` | `floating_calculation_calendar` | calendar name; default `NY_FED` (FD) |
| Reset calendar | — | `floating_fixing_calendar` | default `NY_FED` (FD) |
| Pay calendar | `fixed_payment_calendar` | `floating_payment_calendar` | blank → **leg's Calculation calendar** (= FD) |
| (extras) | `fixed_*_calendar_extras[/_file]` | `floating_*_calendar_extras[/_file]` | per-leg, optional |
| Pay delay | `fixed_payment_delay_bdays` | `floating_payment_delay_bdays` | int, default 0 (no shared field) |
| Reset/lookback lag | — | `floating_reset_lag_bdays` | int, default 0 (was `floating_fixing_lag_bdays`) |
| Lockout | — | `floating_lockout_bdays` | int, default 0 (was `lockout_bdays`) |
| (kept) | `fixed_frequency`, `fixed_daycount`, `fixed_principal_exchange` | `floating_frequency`, `floating_daycount`, `floating_spread`, `floating_principal_exchange` | unchanged |

Roll values accepted (unchanged set): `None`/`NoAdjust`, `Following`,
`ModifiedFollowing`, `Preceding`, `ModifiedPreceding`, `Nearest`.

**Semantics / engine changes:**

- **Roll Convention** owns generation direction **and** stub placement **and**
  the EOM rule: `forward*` = generate from effective date forward, stub at
  back, anchor = effective date; `backward*` = generate from maturity
  backward, stub at front, anchor = maturity (this *backward* is the legacy
  `ShortFront` behavior). `*_eom` arms the end-of-month rule: when the anchor
  is its month's last day, every period boundary snaps to month-end; for
  non-month-end anchors `forward_eom` ≡ `forward`. **Engine default is now
  `forward_eom`** — existing trades & golden master move and are regenerated.
- **Adjust** selects which dates the accrual day-count uses:
  `acc_and_pay` → adjusted bounds (legacy behavior); `pay` → **unadjusted**
  bounds for accrual, only the payment date adjusted; `none` → nothing
  adjusted. `AccrualPeriod` carries **both** unadjusted and adjusted bounds
  (additive). Payment date is re-based on the **unadjusted** period end +
  pay delay, then rolled by Pay Date Adj (corrects the legacy behavior of
  deriving pay from the already-accrual-adjusted end).
- **Validation (two-tier, no strict flag):** any input combination is
  accepted; *impossible* combos raise a hard error; combinations Bloomberg
  grays out (e.g. fixed `adjust=acc_and_pay` with an EOM roll + 30/360
  family) emit a WARNING into `manifest.warnings[]`. Trades still price.
- **Hardcoded-assumption guards** (not settings): a trade requesting an
  unimplemented calendar, a non-in-arrears reset, or a non-coupon payment
  type raises a clear error rather than mispricing silently.

**Bloomberg-derived (not separate BBG inputs — omit on matched trades):**
`*_pay_date_adj` blank → that leg's Bus Day Adj; `*_payment_calendar` blank →
that leg's Calculation calendar; `floating_reset_lag_bdays` default `0`
(in-arrears OIS has no lookback). Present only so non-Bloomberg trades can
override; omitting all five reproduces Bloomberg exactly.

**Known simplifications:** the terminal/maturity date is rolled under the
leg's Bus Day Adj (no separate termination-date adjustment); reset uses
lookback only (no observation-shift variant) — flag per trade if needed.

---

## Resolved Conventions

| Topic | Decision |
|---|---|
| Discount vs. projection | SOFR discounts, FF projects (no basis curve) |
| Curve interpolation | Log-linear on DFs, calendar-day axis (applied identically to SOFR and FF) |
| Zero-rate quoting | Default continuously compounded ACT/360; `RateQuoting` strategy is pluggable |
| OIS period coupon | Derived by compounding daily forward rates (one per fixing date) via `_period_fixing_rows()`. Daily rates come from `FixingHistory` for past dates or the curve's ACT/360 forward for future dates. No endpoint-DF shortcut is used — all periods go through the daily product regardless of whether fixings are historical or projected. |
| Past vs. future fixings | Split at val_date: historical product × curve-implied product |
| Month-end on weekend/holiday | When `val_date` is the **last calendar day of its month** *and* a non-business day (NY_FED), no market data is published for it. All three curve loaders source the curve from the **previous business day's file** (`calendar_us.month_end_curve_date` → `prev_business_day`, one `Preceding`-style hop skipping weekends + holidays) while the `ZeroCurve` stays **anchored at `val_date`**. Effect vs. the previous-business-day's own run: identical SOFR/FF zero-rate pillars, but every DF re-anchors forward 1–2 days and accrual runs 1–2 extra days — there is no other moving part (one nuance: the just-realized fixing on the prev-close date becomes *historical* rather than curve-projected). The portfolio runner emits a WARNING and records `manifest.warnings[]` when this fires (visible on stdout under `-v`; always in the manifest). **No further roll-back**: the previous-business-day file is *required* — a missing one raises `MissingPreviousCloseError` (a `RuntimeError`, deliberately **not** a `FileNotFoundError`, so batch treats it as a hard error rather than a benign `skipped(no-curve)` weekend). Ordinary (non-month-end) weekends/holidays are unaffected and still `skip`. Dated loaders (`--pillar-dates`/`-df`) carry absolute pillar dates, so the 1–2 day re-anchor drops any pillar landing on/before `val_date`. |
| Missing historical fixings | **Hard fail per trade** — `OISFloatingLeg._resolved_rate` raises `ValueError` if `fixing_date < val_date` and `FixingHistory.get(d)` is `None`. The Portfolio runner catches it, records the trade in `manifest.errors[]`, and continues with the remaining trades; the run ends `status="partial"`. Rationale: safer than silent fallbacks (carry-forward, front-end-rate substitute, period-skip) which can hide gaps in real history and produce wrong PV that looks plausible. Any softer policy must be an explicit opt-in flag, not the default. |
| Principal exchange | Per-leg toggle via trade YAML/CSV: `fixed_principal_exchange` and `floating_principal_exchange`, each accepting `none` (default) \| `start` \| `end` \| `both`. Sign convention: `start` row pays out `-notional` at `start_date`; `end` row receives `+notional` at the final payment date (= `maturity + payment_delay_bdays`). Discounted via SOFR DF on the payment date. Past flows (`< val_date`) carry NaN DF and zero discounted cashflow, so a `start` flow on an in-progress trade contributes nothing to PV. The leg-side sign combined with the swap-level `pay_fixed` flag routes the cashflow to the correct side of `dirty`. Cashflow tables gain a `flow_type` column (`coupon` / `principal_start` / `principal_end`) for easy filtering. |
| Fixed leg freq + DC | Per-trade; supports ACT/360, ACT/365F, 30/360, 30E/360, ACT/ACT-ISDA |
| Payment delay | Per-leg `*_payment_delay_bdays` (default 0); shifts cash date only. T+N is counted from the **adjusted** period end (Bloomberg/ISDA standard), then rolled by `*_pay_date_adj`. |
| Accrued interest | Both legs accrue a period from its **start until its payment date** (not its accrual end). The accrual day-count / OIS compounding runs to `min(val_date, accrual_end)`, so a period whose accrual has ended but has not yet paid (`accrual_end ≤ val_date < payment_date`, e.g. under a payment delay) contributes its **full undiscounted coupon** — it is owed but unpaid. Accrued sums across periods, so a just-ended-unpaid period and the next, already-started period can both contribute around a boundary. A period that has already paid (`payment_date ≤ val_date`) contributes nothing. `clean = dirty − accrued` holds throughout. |
| Lockout | Per-trade `floating_lockout_bdays` (default 0); last N fixings frozen at the (N+1)th-to-last value |
| Roll conventions | **Per-leg Bloomberg fields** (see Bloomberg-Matched Convention Schema above): `*_bus_day_adj`, `*_eff_date_adj`, `*_pay_date_adj`, and (floating only) `floating_rst_bus_day_adj`. No shared `business_day_convention` fallback. Accepted values: `None`/`NoAdjust`, `Following`, `ModifiedFollowing`, `Preceding`, `ModifiedPreceding`, `Nearest`. |
| Floating fixing lookback | Per-trade `floating_reset_lag_bdays` (int, default 0). For each accrual sub-day, the observation date is shifted back by N business days on `floating_fixing_calendar`, then rolled by `floating_rst_bus_day_adj`. Lag = 0 reproduces in-arrears behavior (fixing date = accrual day). |
| Notional | `NotionalSchedule` callable; `ConstantNotional` (fixed amount) and `StepNotional` (piecewise-constant amortization) are implemented |
| Sign convention | From fixed-rate payer's perspective (configurable via `pay_fixed` on the `Swap`) |
| Compounded coupon display rounding | In `OISFloatingLeg.period_cashflows()` (the monthly period view / FloatingCF_byPeriod tab), `compounded_coupon` is display-rounded to **5 dp in percent** (e.g. `5.12345%`), half-up, via `_round_pct5()`. The daily `cashflows()` view and all downstream pricing use the raw unrounded rate. |

---

## OIS Compounding Math (reference)

For accrual period `[T_s, T_e]`, valuation date `t_v`:

```
R_comp = ( ∏_{i: fixing < t_v} (1 + r_hist_i · d_i / 360)
         × ∏_{i: fixing ≥ t_v} (1 + r_fwd_i  · d_i / 360)
         − 1
        ) · 360 / D
```

where:
- `r_hist_i` — historical fixing from `FixingHistory` for dates before `t_v`
- `r_fwd_i` — simple ACT/360 forward rate from the FF curve: `(DF(f_i)/DF(f_{i+1}) − 1) × 360/d_i`
- `d_i` — calendar days from accrual day `i` to the next accrual day (or `T_e`)
- `D` — calendar days in the full period `T_e − T_s`

The product is always computed by compounding each daily fixing individually — no endpoint-DF shortcut is used. Standard ISDA OIS day-count weights `d_i` apply (Fri fixing typically carries `d_i = 3` over the weekend).

Lockout: the last `L` applied rates are frozen at the `(L+1)`-th-to-last fixing's value. Rate source is tagged `"history"`, `"curve"`, or `"lockout"` per row.

---

## DV01 Methodology (reference)

DV01 is the position's **loss for a +1bp parallel shift of the rate environment**, computed by full revaluation (bump-and-reprice), not by an analytic/closed-form sensitivity.

**Bump definition.** A single `+1bp` (`BUMP = 1e-4`) parallel shift is applied to **both** curves simultaneously:
- the **SOFR discount curve** (`md.discount_curve.bumped(+1bp)`), and
- the **FF projection curve** (`md.projection_curve.bumped(+1bp)`).

This is a *parallel* bump — every pillar moves by the same +1bp, not a key-rate / per-tenor bucket. It is a *dual-curve* bump — discounting and forward projection move together, so the reported number is the total rate sensitivity.

**Computation.**
```
DV01 = PV_base − PV_bumped
```
where `PV` is the signed dirty PV under the trade's sign convention:
- `pay_fixed=True`  → PV = PV(float) − PV(fixed)
- `pay_fixed=False` → PV = PV(fixed) − PV(float)

The bumped PV is obtained by rebuilding the swap with its floating leg repointed at the bumped projection curve (`floating.with_projection_curve(bumped_proj)`) and repricing against a `MarketData` carrying both bumped curves (same `val_date`, same `fixings`).

**Sign convention.** A **positive DV01 means the position loses value when rates rise** (`PV_base − PV_bumped > 0`).

**Properties / caveats.**
- One-sided (forward-difference) bump, not a central difference; bias is `O(bump)` and negligible at 1bp for linear OIS swaps.
- Fixings are held fixed across the bump — only projected (future) rates and discount factors move.
- Matured trades carry `dv01 = 0` (set explicitly by the portfolio runner).
- Bump size is configurable via `SwapPricer(bump_size=...)`; default `1e-4`.

---

## Object Design

### Conventions & quoting

- **`RateQuoting`** *(strategy)* — `rate_to_df(r, days)`, `df_to_rate(df, days)`. Variants: `ContinuousACT360` *(default)*, `SimpleACT360`, `ContinuousACT365`, `AnnualCompoundedACT360`, `AnnualCompoundedACT365`.
- **`DayCount`** *(strategy)* — `year_fraction(d1, d2)`. Variants: `ACT_360`, `ACT_365F`, `THIRTY_360`, `THIRTY_E_360`, `ACT_ACT_ISDA`.

### Calendar & schedule

- **`USCalendar`** — business-day calendar (NY Fed holidays). `is_business_day`, `add_business_days`, `roll(d, bdc)`, `month_end_curve_date(val_date)`.
- **`AccrualPeriod`** *(dataclass, frozen)* — `start, end, payment_date, unadjusted_start, unadjusted_end`. Adjusted and unadjusted bounds are both stored; which pair the leg uses depends on its `adjust` setting.
- **`generate_schedule(effective_date, termination_date, frequency, calendar, payment_delay_bdays, ...) → list[AccrualPeriod]`** — Bloomberg-matched roll logic (forward/backward, EOM, first_period_accrual_end_date override, post-roll dedup).

### Curve

- **`ZeroCurve`** — built from term pillars (`1D`, `1W`, …, `50Y`) or explicit dated pillars + a `RateQuoting`. Exposes:
  - `df(date)` — log-linear DF interpolation on calendar-day axis
  - `df_vector(dates)`
  - `forward(t1, t2)` — simple ACT/360 forward rate
  - `bumped(delta) → ZeroCurve` — parallel-shift for DV01
  - `to_debug_frame()` — pillar table with parsed dates, days, rates, DFs
  - `df_grid_debug(start, end)` — daily `date, DF, log_DF, implied_daily_fwd`
- Two instances per valuation: `sofr_curve` (discount), `ff_curve` (projection).

### Fixings & notional

- **`FixingHistory`** — `get(date) → rate | None`. `None` triggers hard error in the floating leg. `to_debug_frame()` returns a date/rate table.
- **`NotionalSchedule`** *(callable)* — `date → notional`. `ConstantNotional` (single fixed value) and `StepNotional` (piecewise-constant with bisect-based lookup) are implemented.

### Legs

- **`Leg`** *(ABC)* — `cashflows(val_date, discount_curve) → DataFrame`, `pv(val_date, discount_curve) → float`, `accrued(val_date) → float`.
- **`FixedLeg(Leg)`** — `schedule, notional, fixed_rate, daycount`. `adjust` selects adjusted (`acc_and_pay`) or unadjusted (`pay` / `none`) accrual bounds.
- **`OISFloatingLeg(Leg)`** — `schedule, notional, projection_curve, fixings, daycount, fixing_calendar, payment_calendar, payment_delay_bdays, lockout_bdays, spread, principal_exchange, fixing_roll, fixing_lag_bdays, adjust`. Exposes `cashflows()` (daily per-fixing rows), `period_cashflows()` (one row per accrual period), `accrued()`, `accrued_debug()`, `fixings_debug()`, `period_breakdown()`, `with_projection_curve()`.

### Swap, market data, pricer

- **`Swap`** — `fixed: FixedLeg`, `floating: OISFloatingLeg`, `pay_fixed: bool`, `trade_id: str`, `meta: dict`.
- **`MarketData`** — `val_date, discount_curve, projection_curve, fixings`.
- **`SwapPricer`** — `price(swap, market_data) → SwapValuation`. Also `par_rate(swap, md)` and `_dv01(swap, md)`.
- **`SwapValuation`** *(dataclass)* — `trade_id, val_date, clean, dirty, accrued, dv01, pv_fixed, pv_floating, par_rate, rate_diff_bp, fixed_cf: DataFrame, floating_cf: DataFrame, floating_cf_by_period: DataFrame, meta: dict`.

### Validation & trade building

- **`validation.py`** — `validate_trade(td: TradeDef) → list[str]`. Tier 1 hard errors (invalid roll/adjust, bad date order, unknown reset/payment type) raise immediately. Tier 2 soft warnings (e.g. `acc_and_pay` with 30/360 family) are returned as strings and recorded in `manifest.warnings[]`.
- **`trade_builder.py`** — `build_swap(td: TradeDef, ff_curve: ZeroCurve, fixings: FixingHistory) → Swap`. Validates the trade, builds per-leg calendars (merging extras), generates both leg schedules, constructs `FixedLeg` and `OISFloatingLeg`, attaches convention metadata to `Swap.meta`. Also handles Bloomberg auto-sync defaults (`*_pay_date_adj` blank → leg's `*_bus_day_adj`; `*_payment_calendar` blank → leg's calculation calendar; `floating_frequency` blank → `fixed_frequency`).

### Auxiliary modules

- **`netting_db.py`** — `NettingRow(frozen dataclass)`: `netting_id, cash_flow_netting_allowed, position_netting_allowed, netting_entity, amex_legal_entity_name, external_name`. `load_netting_db(path) → dict[str, NettingRow]`. Parses the netting CSV (row 1 free-form title, row 2 headers, row 3+ data; FX rows silently skipped). Authoritative source for position-netting rules and entity info.
- **`debt.py`** — `load_deal_number_map(path)`, `load_debt_mtm(path)`, `resolve_hedged_debt_mtm(trade_id, hedge, quantum_deal_number, swap_clean, deal_map, debt_mtm) → float`. Implements the Long/Short hedge direction logic for column AW of the prod CSV.
- **`manifest.py`** — `RunManifest` dataclass: `run_id` (UUID), `val_date`, `run_date` (UTC), `git_sha`, `status`, `timings`, `errors`, `warnings`, `per_trade_timings`. Helper: `file_sha256(path)`.

### Loaders (input abstraction)

- **`CurveLoader`** *(ABC)* — `load(val_date, curve_name) → ZeroCurve`. Three concrete implementations selected by CLI flag:
  - `ExcelCurveLoader` *(default)* — reads `market_environment_YYYY-MM-DD.csv`; filters col A by `TICKER_RE` (`^IR\.USD-(SOFR|FEDFUNDS)-ON\.ZERORATE-([0-9A-Z]+)\.MID$`); col B is the zero rate.
  - `DatedCurveLoader` *(`--pillar-dates`)* — no-header CSVs `sofr_YYYY-MM-DD.csv` / `ff_YYYY-MM-DD.csv`; col A pillar date (ISO), col B zero rate.
  - `DatedDFCurveLoader` *(`--pillar-dates-df`)* — `sofr_df_YYYY-MM-DD.csv` / `ff_df_YYYY-MM-DD.csv`; col B is the DF directly; bypasses `RateQuoting`. DV01 bumping uses `DF_new = DF · exp(−δ · days / 360)`.
  - All three support month-end fallback to the previous-business-day file.
- **`FixingLoader`** *(ABC)* — `load(index_name) → FixingHistory`. Concrete: `ExcelFixingLoader` (auto-detects 2-col or 3-col CSV/XLSX layout, flexible date parsing).
- **`TradeLoader`** *(ABC)* — `load_all() → list[TradeDef]`, `load(trade_id) → TradeDef`. Concrete:
  - `YamlTradeLoader` — globs `*.yaml` files in trades_dir; unknown keys preserved in `TradeDef.meta`.
  - `CsvTradeLoader` — multi-file CSV support; skips `#`-prefixed comment lines; detects duplicate `trade_id`; requires non-blank `netting_id`; strips spurious `.0` from identifier fields. Carries only a short trailing ID; `Portfolio.run()` reconstructs the full `AMEX_DAILY_IRS_<YYYYMMDD>_<short_id>` form once `val_date` is known.
  - `CombinedTradeLoader` — wraps multiple `TradeLoader` instances and concatenates results, deduplicating by `trade_id`.
- **`load_extra_holidays(path) → list[date]`** (`loaders/calendar_extras.py`) — loads custom per-trade holiday lists from CSV (with "date" column) or TXT (one ISO date per line, `#` comments).

**`TradeDef` economic fields (shared):** `trade_id`, `notional`, `pay_fixed`, `fixed_rate`, `start_date`, `maturity_date`, `fixed_frequency`, `fixed_daycount`.

**Production output fields on `TradeDef`:** `quantum_deal_number`, `oracle_entity_code`, `notional_currency`, `intercompany`, `counterparty_name_quantum`, `current_counterparty`, `entity_name_quantum`, `reporting_party`, `counterparty_location`, `deal_date`, `hedge` ("Long" | "Short"), `netting_id`.

### Portfolio & output

- **`Portfolio`** — takes loaders + pricer; `run(val_date, out_dir, ...)` orchestrates load → build → price → write. One run is self-contained under `output/valdate_<val_date>_rundate_<run_date>/`. Skips matured trades (`maturity_date < val_date`). Catches per-trade errors into `manifest.errors[]`.
- **`io_excel`** — portfolio workbook + per-trade detail + debug workbooks.
- **`io_parquet`** — same frames dumped to Parquet.
- **`io_prod`** — KPMG IRS Valuation feed CSV (49 columns).
- **`io_prod_netting`** — KPMG IRS Netting feed CSV (21 columns).
- **`batch.run_batch(val_dates, …)`** — fans valuation dates across a `ProcessPoolExecutor`. Each date priced in its own worker process (loaders rebuilt inside, no pickling). Statuses: `ok` / `partial` / `error` / `skipped`. Dates with no published curve are `skipped` (WARNING, exit code 0). Batch log at `output/batch_<UTCstamp>.{log,json}`.

### Class count

~25 classes total, roughly half of them strategy variants. Three pluggable axes — `RateQuoting`, `DayCount`, `*Loader` — so new conventions or input sources are subclass additions, not pricer edits.

---

## Output Layout

Every run (single-date *or* one date within a batch) is self-contained under
`output/valdate_<val_date>_rundate_<run_date>/`. **By default (no flag) the
run writes ONLY the prod CSV (`IRS_Valuation_<val_date>-00001.csv`).** Passing
`--debug` flips every other artifact on (portfolio workbook + per-trade detail
+ per-trade debug + parquet). A batch additionally drops `batch_<UTCstamp>.log`
and `batch_<UTCstamp>.json` at the `output/` root. Full layout under
`--debug`:

```
output/
├── valdate_<val_date>_rundate_<run_date>/
│   ├── IRS_Valuation_<val_date>-00001.csv   (ALWAYS, even without --debug)
│   ├── IRS_Netting_<val_date>-00001.csv     (when netting_db + entity_rc present)
│   ├── portfolio_<val_date>.xlsx            (only with --debug)
│   ├── detail/<trade_id>.xlsx              (only with --debug)
│   ├── debug/<trade_id>_debug.xlsx         (only with --debug)
│   ├── parquet/{summary,floating_cf,fixed_cf,curves}.parquet  (only with --debug)
│   └── manifest_<val_date>.json
├── batch_<UTCstamp>.log                    (batch runs only)
└── batch_<UTCstamp>.json                   (batch runs only)
```

### Production CSV (`IRS_Valuation_<val_date>-00001.csv`)

Matches the KPMG IRS-valuation feed spec (`Output_Format.xlsx`). Written by `src/swaps/io_prod.py::write_prod_csv`.

**Encoding**: UTF-8 (no BOM). **Version stamp**: hard-coded `"00001"`.

**Row structure** (49 columns wide, A..AW):

| Row | Cells | Contents |
|---|---|---|
| 1 (header) | 5 | `H` \| `<yyyymmdd run date>` \| `IRS_Valuation_<val_date>-00001.csv` \| `00001` \| `KPMG` |
| 2 (field names) | 49 | column labels in exact spec order |
| 3..N+2 (trades) | 49 | one row per priced valuation |
| N+3 (footer) | 49 | `T` \| `<n_trades>` \| blanks \| column-letter sums |

**Field sources** (49 columns total, A..AW):

| Output field | Column | Source |
|---|---|---|
| Trade Reference Number | A | always blank |
| Internal Reference Number | B | always blank |
| Quantum Deal Number | C | `td.quantum_deal_number` |
| Oracle Entity Code | D | `td.oracle_entity_code` |
| Notional Currency | E | `td.notional_currency` |
| As of Date | F | `val_date` |
| Clean price | G | `v.clean` |
| Accrued Interest | H | `v.accrued` |
| Total Value (NPV) | I | `v.dirty` |
| DV01 | J | `v.dv01` |
| Valuation Currency | K | constant `"USD"` |
| Child Reference Number / Period Start/End/Payment | L–O | always blank |
| Maturity Date | P | `td.maturity_date` |
| Notional 1 Amount | Q | `td.notional` |
| Notional 1 Amount USD | R | `td.notional` |
| Pay Rec Status / Component Type | S–T | always blank |
| Coupon FV / Intrinsic Value FV / Time Value FV | U–W | always blank (footer sums = 0) |
| Intercompany Trade | X | `"Yes"`/`"No"` from `td.intercompany` |
| Counterparty Name (Quantum) | Y | `td.counterparty_name_quantum` |
| Current Counterparty | Z | `td.current_counterparty` |
| Entity Name (Quantum) | AA | `td.entity_name_quantum` |
| Reporting Party | AB | `td.reporting_party` |
| InternalFacing-StreetFacing | AC | always blank |
| Product | AD | constant `"IR"` |
| Sub-Product2 | AE | CME → `"OTC - Centralized (Principal)"`, else `"OTC - Bilateral"` |
| Collateral Level | AF | constant `"Fully Collateralized"` |
| Counterparty Code | AG | always blank |
| Counterparty Type | AH | CME → `"Financial Market Utility"`, else `"Bank"` |
| Counterparty Location | AI | `td.counterparty_location` |
| HCL Type | AJ | constant `"Interest Rate Swap"` |
| DA | AK | `npv` if `npv > 0` else blank |
| DL | AL | `abs(npv)` if `npv < 0` else blank |
| Asset Liability Tag | AM | `"Asset"` / `"Liability"` / blank (zero NPV) |
| Qualifying CCP / Cleared / Cash-Settled CCP | AN–AP | CME → `"Yes"`, else `"No"` |
| Deal Date | AQ | `td.deal_date` |
| Netting ID | AR | `td.netting_id` |
| Cash Flow Netting Allowed | AS | from netting DB |
| Position Netting Allowed | AT | from netting DB |
| Balance Sheet CCID | AU | 9-segment composite ID (see CCID section); blank if entity lookup misses or NPV == 0 |
| PL OCI CCID | AV | 9-segment composite ID (Natural Account `465012` regardless of sign); blank if entity lookup misses |
| Hedged Debt MTM | AW | `Short` → `−v.clean`; `Long` → hedged debt's `Clean + USD Outstanding` |

**CME-branch rule**: exact string equality `td.current_counterparty == "CME Clearing House"` (case-sensitive, no leading/trailing whitespace).

**CCID composition (cols AU / AV)** — per `CCID.xlsx`:

```
CCID = Entity-RC-NaturalAccount-SubAccount-InterEntity-InterCenter-Product-Reserve1-Reserve2
```

9 dash-joined segments. Entity = `td.oracle_entity_code`. RC looked up from `data/entity/Entity_Reference_Report.csv` (columns `Entity_Code, Default RC`). Trailing 6 segments: `000000-0000-000000-000000-000000-0000`.

| CCID | NPV > 0 (Asset) | NPV < 0 (Liability) | NPV == 0 |
|---|---|---|---|
| **Balance Sheet** (AU) | `192001` | `392001` | blank |
| **PL OCI** (AV) | `465012` | `465012` | `465012` |

**Footer sum columns:** G/H/I/J (Σ clean/accrued/dirty/dv01), Q/R (Σ notional twice), U/V/W (always 0), AK (Σ DA), AL (Σ DL), AW (Σ Hedged Debt MTM).

**Hedged Debt MTM (AW):** `Short` → `−v.clean`. `Long` → resolved via `td.quantum_deal_number` → `Deal_Numbers.csv` → `Deal_Summary_<val_date>.xlsx` (`Clean + USD Outstanding`). `hedge` is required; missing or unresolvable raises a hard per-trade error.

### IRS Netting CSV (`IRS_Netting_<val_date>-00001.csv`)

Written by `src/swaps/io_prod_netting.py` when both `netting_db` and `entity_rc` are present. Matches the KPMG IRS Netting feed spec (`Output_Format Netting.xlsx`).

**Row structure** (21 columns wide, A..U):

| Row | Contents |
|---|---|
| 1 (header) | `H` \| `<yyyymmdd>` \| `IRS_Netting_<val_date>-00001.csv` \| `00001` \| `KPMG` |
| 2 (field names) | 21 column labels |
| 3..N+2 | one row per netting_id |
| N+3 (footer) | `T` \| `<n_netting_rows>` \| sums at K/L/M/N/O |

**21 fields (A..U):**

| Col | Field | Source |
|---|---|---|
| A | Field | `"Position Netting"` |
| B | As of Date | `val_date` |
| C | Product | `"IRS"` |
| D | Entity | `"American Express Company"` |
| E | Oracle Entity Code | `netting_db[netting_id].netting_entity` |
| F | Counterparty | first trade's `current_counterparty` for the group |
| G–I | Counterparty Code, Payment Date, Maturity Date | blank |
| J | Netting ID | |
| K | Gross DA | Σ(npv for npv > 0) |
| L | Gross DL | Σ(\|npv\| for npv < 0) |
| M | Netting Amount | `min(Gross DA, Gross DL)` if `position_netting_allowed` else 0 |
| N | Net DA | `Gross DA − Netting Amount` |
| O | Net DL | `Gross DL − Netting Amount` |
| P | Counterparty Type | CME → `"FMU"`, else `"Bank"` |
| Q | Cash Flow Netting Allowed | from netting DB |
| R | Position Netting Allowed | from netting DB |
| S | Netting Entity | from netting DB |
| T | Position Netting Asset CCID | `{entity}-{rc}-192005-000000-0000-000000-000000-000000-0000` |
| U | Position Netting Liability CCID | `{entity}-{rc}-392004-000000-0000-000000-000000-000000-0000` |

Trades with a blank `netting_id` are excluded from the netting output. Netting IDs with one-sided exposure (DA only or DL only) emit a row with the zero side = 0.

**Footer sum columns:** K (Σ Gross DA), L (Σ Gross DL), M (Σ Netting Amount), N (Σ Net DA), O (Σ Net DL).

### `portfolio_<val_date>.xlsx` — the everyday view

| Tab | Contents |
|---|---|
| `Summary` | One row per trade: trade_id, notional, fixed_rate, start, maturity, clean, dirty, accrued, DV01, PV(fixed), PV(floating), par_rate, rate_diff_bp |
| `FloatingCF` | All floating-leg cashflows stacked (daily per-fixing rows), `trade_id` as leading column |
| `FixedCF` | All fixed-leg cashflows stacked, `trade_id` as leading column |
| `Curves` | SOFR + FF zero curves used (audit trail) |

### `detail/<trade_id>.xlsx` — drill-down per trade

Sheets: `Floating` (daily cashflows), `Fixed` (coupon cashflows), `FloatingByPeriod` (monthly period view).

### Floating-leg cashflow columns (per fixing row)

`run_id · val_date · run_date · git_sha · trade_id · period_start · period_end · payment_date · fixing_date · accrual_start · accrual_end · day_count · reset_rate · rate_source · implied_daily_fwd · df_to_fixing · df_to_payment · spread · compounded_coupon* · effective_coupon* · period_cashflow* · discounted_cashflow*`

`*` = filled only on the last fixing row of each period.

Semantics:
- `period_start` / `period_end` — outer payment-period bounds (constant across all rows within one period).
- `accrual_start` / `accrual_end` — per-fixing sub-interval. `day_count = (accrual_end − accrual_start).days`.
- `reset_rate` — rate applying to `[accrual_start, accrual_end)`. Source tagged as `"history"`, `"curve"`, or `"lockout"`.
- `compounded_coupon` — `(∏(1 + r_i · d_i/360) − 1) · 360 / D`. **No rounding** in this daily view; raw rate.

### FloatingCF_byPeriod columns (period view — `FloatingByPeriod` tab)

`flow_type · accrual_start · accrual_end · payment_date · period_days · day_count_fraction · notional · n_fixings · historical_product · projected_product · growth · compounded_coupon · spread · effective_coupon · payment_amount · df_to_payment · discounted_cashflow`

- `compounded_coupon` — **display-rounded to 5 dp in percent** (e.g. `5.12345%`), half-up, via `_round_pct5()`. Display only; all downstream pricing uses the raw rate.
- `effective_coupon` and `payment_amount` always carry the raw unrounded rate.

### Fixed-leg cashflow columns

`run_id · val_date · run_date · git_sha · trade_id · flow_type · accrual_start · accrual_end · payment_date · period_days · day_count_fraction · notional · coupon_rate · payment_amount · df_to_payment · discounted_cashflow`

### Parquet output

Same DataFrames written to `output/parquet/{summary,floating_cf,fixed_cf,curves}.parquet`. Adds `pyarrow` dependency. Provides immediate DuckDB query layer and clean migration path to a real DB.

---

## Debug / Test Output Sockets

Every numeric class exposes `to_debug_frame()` (or named variants) returning a fully-laid-out DataFrame:

| Class | Method | Contents |
|---|---|---|
| `ZeroCurve` | `to_debug_frame()` | Pillars: tenor, date, days, zero_rate, DF |
| `ZeroCurve` | `df_grid_debug(start, end)` | Daily DF, log_DF, implied daily fwd |
| `FixingHistory` | `to_debug_frame()` | date, rate |
| `OISFloatingLeg` | `fixings_debug(val_date)` | Per-fixing-row frame before aggregation |
| `OISFloatingLeg` | `period_breakdown(val_date)` | historical_product, projected_product, comp_rate, D |
| `OISFloatingLeg` | `accrued_debug(val_date)` | Per-period accrued breakdown |
| `FixedLeg` | `accrued_debug(val_date)` | Per-leg accrued breakdown |
| `SwapPricer` | n/a — `SwapValuation` is the debug view | |

**Debug workbook tabs** (`debug/<trade_id>_debug.xlsx`, `--debug` only):
- `SOFR_pillars`, `FF_pillars` — curve pillar audit
- `SOFR_df_grid`, `FF_df_grid` — daily DF grid from val_date to last cashflow
- `FixingsUsed` — historical fixings used
- `FloatingFixings` — per-fixing detail before compounding
- `FloatingPeriods` — per-period historical/projected products
- `FloatingCF`, `FixedCF` — final cashflows
- `Accrued` — both legs' accrued detail + `sign_in_swap` / `signed_accrued` cross-check

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
Swap Pricer/
├── schema.md
├── pyproject.toml
├── README.md
├── src/swaps/
│   ├── conventions.py           # DayCount strategies
│   ├── rate_quoting.py          # RateQuoting strategies
│   ├── calendar_us.py           # NY Fed calendar + USCalendar
│   ├── curve.py                 # ZeroCurve
│   ├── fixings.py               # FixingHistory
│   ├── schedule.py              # generate_schedule()
│   ├── notional.py              # NotionalSchedule, ConstantNotional, StepNotional
│   ├── legs/
│   │   ├── base.py              # Leg ABC
│   │   ├── fixed_leg.py
│   │   └── floating_leg_ois.py
│   ├── swap.py
│   ├── market_data.py
│   ├── validation.py            # validate_trade() — Tier 1/Tier 2
│   ├── trade_builder.py         # build_swap()
│   ├── pricer.py                # SwapPricer + SwapValuation
│   ├── netting_db.py            # NettingRow, load_netting_db()
│   ├── debt.py                  # Hedged-debt MTM lookups
│   ├── loaders/
│   │   ├── __init__.py          # CombinedTradeLoader
│   │   ├── base.py              # CurveLoader / FixingLoader / TradeLoader ABCs + TradeDef
│   │   ├── excel.py             # ExcelCurveLoader, ExcelFixingLoader
│   │   ├── dated.py             # DatedCurveLoader, DatedDFCurveLoader
│   │   ├── yaml_trades.py       # YamlTradeLoader
│   │   ├── csv_trades.py        # CsvTradeLoader (AMEX Daily IRS scheme)
│   │   └── calendar_extras.py   # load_extra_holidays()
│   ├── io_excel.py              # portfolio + per-trade detail + debug workbooks
│   ├── io_prod.py               # KPMG IRS Valuation CSV
│   ├── io_prod_netting.py       # KPMG IRS Netting CSV
│   ├── io_parquet.py
│   ├── manifest.py              # RunManifest + file_sha256()
│   ├── portfolio.py             # single-date runner
│   └── batch.py                 # parallel multi-date runner
├── data/
│   ├── curves/market_environment_<YYYY-MM-DD>.csv
│   ├── fixings/fixing_cail_USD-FEDFUNDS-ON.csv
│   ├── trades/*.yaml or *.csv
│   ├── entity/Entity_Reference_Report.csv
│   ├── entity/Netting_Database.csv
│   └── debt/Deal_Numbers.csv + Deal_Summary_<YYYY-MM-DD>.xlsx
├── output/
│   ├── valdate_<val_date>_rundate_<run_date>/
│   │   ├── IRS_Valuation_<val_date>-00001.csv  (DEFAULT — always written)
│   │   ├── IRS_Netting_<val_date>-00001.csv    (when netting_db + entity_rc present)
│   │   ├── portfolio_<val_date>.xlsx           (--debug only)
│   │   ├── detail/<trade_id>.xlsx              (--debug only)
│   │   ├── debug/<trade_id>_debug.xlsx         (--debug only)
│   │   ├── parquet/{summary,floating_cf,fixed_cf,curves}.parquet  (--debug only)
│   │   └── manifest_<val_date>.json
│   ├── batch_<UTCstamp>.log                    (batch runs only)
│   └── batch_<UTCstamp>.json                   (batch runs only)
├── tests/
└── scripts/
    ├── price_portfolio.py           # single valuation date CLI
    ├── price_portfolio_batch.py     # multi-date parallel CLI
    ├── generate_synthetic_curve.py  # synthetic SOFR/FF curves for testing
    ├── generate_synthetic_fixings.py
    ├── discount_factor_test.py      # DF calculation validation
    ├── diagnose_ccid.py             # debug CCID composition
    └── diagnose_fixings.py          # inspect fixing data
```

---

## Input Formats

**Curve — default (`market_environment` path):** `data/curves/market_environment_YYYY-MM-DD.csv`. Non-data header rows on top; col A ticker filtered by `TICKER_RE`; col B zero rate. One file holds both SOFR and FEDFUNDS interleaved.

**Curve — `--pillar-dates`:** `sofr_YYYY-MM-DD.csv` + `ff_YYYY-MM-DD.csv`. No header; col A pillar date (ISO), col B zero rate.

**Curve — `--pillar-dates-df`:** `sofr_df_YYYY-MM-DD.csv` + `ff_df_YYYY-MM-DD.csv`. Col B is the DF. Bypasses `RateQuoting`; `Pillar.zero_rate` is `NaN`.

**Fixings:** `data/fixings/fixing_cail_USD-FEDFUNDS-ON.csv`. Auto-detected 2-col or 3-col layout.

**Trades:** `*.yaml` (one file per trade) or `*.csv` (multi-trade, `#` comments skipped).

**Entity RC lookup:** `data/entity/Entity_Reference_Report.csv`. Columns `Entity_Code, Default RC`. Missing file → all CCID cells blank with a warning.

**Netting DB:** `data/entity/Netting_Database.csv`. Row 1 free-form title, row 2 headers, row 3+ data.

**Hedged Debt:** `data/debt/Deal_Numbers.csv` (IRS Deal Number → Debt Deal Number) + `data/debt/Deal_Summary_<YYYY-MM-DD>.xlsx` (Debt Deal Number → Clean + USD Outstanding).

---

## Stability Practices

- `pytest` everywhere; ~80% coverage on `legs/`, `curve.py`, `pricer.py`.
- Pinned dependencies in `pyproject.toml`.
- `ruff` + `mypy --strict` on `src/swaps/`.
- Golden-master regression catches accidental numeric drift.
- Pure CLI, no interactive prompts. Stdout logging. Non-zero exit on error. Fail-fast input validation.
- Run manifest (`manifest_<val_date>.json`) records `git_sha`, input file hashes, trade count, per-trade timings — written on every run.

### CLI flags (both `price_portfolio.py` and `price_portfolio_batch.py`)

- **No flag (default)** — writes ONLY the prod CSV (and netting CSV if applicable). No portfolio workbook, no per-trade detail, no parquet, no debug.
- **`--debug`** — writes everything: prod CSV + portfolio workbook + per-trade detail + per-trade debug + parquet.
- **Curve input mode** (mutually exclusive): `--pillar-dates` → `DatedCurveLoader`; `--pillar-dates-df` → `DatedDFCurveLoader`; default → `ExcelCurveLoader`.
- **`--entity-rc <path>`** — Entity Reference Report CSV for CCID. Default `data/entity/Entity_Reference_Report.csv`. Optional; missing → all CCID cells blank.
- **`-v` / `--verbose`** — default `ERROR` (cloud-friendly); `-v` switches to `INFO`.
- **Exit code always printed** on the final stdout line (`exit_code=<n>`), regardless of `-v`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success — all priced. `skipped(no-curve)` counts as success. |
| `1` | Hard failure — uncaught exception, or a date errored entirely. |
| `2` | CLI usage error — bad/missing args, mutex violation. |
| `3` | Partial — pricing completed but at least one trade errored. |

---

## Future: Server Deployment (TODO — not implementing now)

**Target deployment** (recommended order):
1. **AWS Batch (Fargate) + EventBridge schedule** — no instance management; native retries and CloudWatch.
2. **EC2 + cron + Docker** — simplest if curves live on a private network drive.
3. **GitHub Actions scheduled workflow** — viable if all inputs accessible from a hosted runner.

**Storage**: S3 with versioning ON; inputs snapshotted to `s3://.../inputs/<val_date>/`, outputs to `s3://.../outputs/<val_date>/`.

**Monitoring (three layers)**:
1. **Run failure alarm** — CloudWatch on non-zero exit → SNS email/SMS.
2. **Dead-man's switch** — heartbeat per successful run; alarm fires if no heartbeat by 10:00 NY.
3. **Output sanity check** — assert trade_count, no NaNs in summary, file size > N KB.

---

## Future: Database Integration (TODO — not implementing now)

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
   - `IRS_Valuation_<val_date>-00001.csv` (always)
   - `manifest_<val_date>.json`
   - With `--debug`: portfolio XLSX, detail per trade, debug per trade, parquet.
2b. `python scripts/price_portfolio_batch.py --start D1 --end D2` produces one `valdate_/rundate_` folder per date plus `batch_<UTCstamp>.{log,json}`; exit codes follow the standardized scheme.
2c. Curve-input alternates exercised: `--pillar-dates` and `--pillar-dates-df` each price the same portfolio to numerically-equivalent DFs.
2d. `-v` toggles INFO progress vs the default ERROR-only output.
3. Hand-check one swap:
   - `clean + accrued == dirty` to < 1e-8
   - Sum of fixed PV − sum of floating PV ≈ reported NPV (within sign convention)
   - DV01 sign and magnitude reasonable vs. analytic estimate
4. `--debug` flag produces per-trade debug workbooks.
5. Manifest contains git_sha, input hashes, trade count, timestamps.
