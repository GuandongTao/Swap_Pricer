# Plan: Fed Funds Fixed-Float Swap Pricer

## Context

Build a daily mark-to-market pricer in Python for a portfolio of ~30 USD fixed-vs-float interest rate swaps where:

- **Floating leg**: Effective Fed Funds (EFFR) daily fixings, compounded **in arrears** per accrual period.
- **Fixed leg**: periodic coupons; payment frequency and day-count vary per trade.
- **Discounting**: SOFR OIS zero curve (dual-curve setup: SOFR discounts, FF projects).

Outputs: clean / dirty / accrued / DV01 per trade plus full cashflow detail, exported to Excel **and** Parquet. Development is local first; no GitHub until a first stable draft is ready. Working directory: `F:\Projects - Github\Swaps`.

---

## Bloomberg-Matched Convention Schema — branch `feature/bloomberg-convention-match`

This branch rewrites the convention model to mirror Bloomberg SWPM leg
settings. **Every convention is per-leg; the only shared (trade-level) fields
are economic terms.** Supersedes the per-leg-roll rows in *Resolved
Conventions* below where they conflict.

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
| OIS period coupon | Derived from two endpoint DFs (curve-implied), not by re-compounding daily forwards. Daily implied forward is displayed as an audit column. |
| Past vs. future fixings | Split at val_date: historical product × curve-implied product |
| Month-end on weekend/holiday | When `val_date` is the **last calendar day of its month** *and* a non-business day (NY_FED), no market data is published for it. All three curve loaders source the curve from the **previous business day's file** (`calendar_us.month_end_curve_date` → `prev_business_day`, one `Preceding`-style hop skipping weekends + holidays) while the `ZeroCurve` stays **anchored at `val_date`**. Effect vs. the previous-business-day's own run: identical SOFR/FF zero-rate pillars, but every DF re-anchors forward 1–2 days and accrual runs 1–2 extra days — there is no other moving part (one nuance: the just-realized fixing on the prev-close date becomes *historical* rather than curve-projected). The portfolio runner emits a WARNING and records `manifest.warnings[]` when this fires (visible on stdout under `-v`; always in the manifest). **No further roll-back**: the previous-business-day file is *required* — a missing one raises `MissingPreviousCloseError` (a `RuntimeError`, deliberately **not** a `FileNotFoundError`, so batch treats it as a hard error rather than a benign `skipped(no-curve)` weekend). Ordinary (non-month-end) weekends/holidays are unaffected and still `skip`. Dated loaders (`--pillar-dates`/`-df`) carry absolute pillar dates, so the 1–2 day re-anchor drops any pillar landing on/before `val_date`. |
| Missing historical fixings | **Hard fail per trade** — `OISFloatingLeg._resolved_rate` raises `ValueError` if `fixing_date < val_date` and `FixingHistory.get(d)` is `None`. The Portfolio runner catches it, records the trade in `manifest.errors[]`, and continues with the remaining trades; the run ends `status="partial"`. Rationale: safer than silent fallbacks (carry-forward, front-end-rate substitute, period-skip) which can hide gaps in real history and produce wrong PV that looks plausible. Any softer policy must be an explicit opt-in flag, not the default. |
| Principal exchange | Per-leg toggle via trade YAML/CSV: `fixed_principal_exchange` and `floating_principal_exchange`, each accepting `none` (default) \| `start` \| `end` \| `both`. Sign convention: `start` row pays out `-notional` at `start_date`; `end` row receives `+notional` at the final payment date (= `maturity + payment_delay_bdays`). Discounted via SOFR DF on the payment date. Past flows (`< val_date`) carry NaN DF and zero discounted cashflow, so a `start` flow on an in-progress trade contributes nothing to PV (matches user expectation that "doesn't impact us unless we are pricing at start"). The leg-side sign combined with the swap-level `pay_fixed` flag routes the cashflow to the correct side of `dirty`. Cashflow tables gain a `flow_type` column (`coupon` / `principal_start` / `principal_end`) for easy filtering. |
| Fixed leg freq + DC | Per-trade; supports ACT/360, ACT/365F, 30/360, 30E/360, ACT/ACT-ISDA |
| Payment delay | Per-trade `payment_delay_bdays` (default 0); shifts cash date only |
| Lockout | Per-trade `lockout_bdays` (default 0); last N fixings frozen at the (N+1)th-to-last value |
| Calendars | Per-trade `fixing_calendar` and `payment_calendar` (separate fields) |
| Roll conventions | Six per-leg roll fields override `business_day_convention` selectively. `business_day_convention` is a **fallback only** — it controls a role only when that per-leg field is left blank. Accepted values: `None` / `NoAdjust`, `Following`, `ModifiedFollowing` (default), `Preceding`, `ModifiedPreceding`, `Nearest`. **Fixed leg**: `fixed_spot_roll` (rolls the unadjusted effective date), `fixed_accrual_roll` (rolls each accrual end), `fixed_pay_roll` (rolls each payment date). **Floating leg**: `floating_accrual_roll`, `floating_pay_roll`, `floating_fixing_roll`. Each blank-falls-back to `business_day_convention`. If all six per-leg rolls are populated, `business_day_convention` is functionally unused for that trade. ⚠️ Note: `floating_fixing_roll`, when left blank, falls back to `business_day_convention` rather than to the OIS-standard `Preceding`; this only matters when `floating_fixing_lag_bdays > 0`. When floating accrual/pay rolls differ from fixed, the floating leg gets its own rebuilt schedule. |
| Floating fixing lookback | Per-trade `floating_fixing_lag_bdays` (int, default 0). For each accrual sub-day, the observation date is shifted back by N business days on `fixing_calendar`, then rolled by `floating_fixing_roll`. Lag = 0 reproduces the original "rate set in advance" behavior (fixing date = accrual day). |
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

## DV01 Methodology (reference)

DV01 is the position's **loss for a +1bp parallel shift of the rate environment**, computed by full revaluation (bump-and-reprice), not by an analytic/closed-form sensitivity.

**Bump definition.** A single `+1bp` (`BUMP = 1e-4`) parallel shift is applied to **both** curves simultaneously:
- the **SOFR discount curve** (`md.discount_curve.bumped(+1bp)`), and
- the **FF projection curve** (`md.projection_curve.bumped(+1bp)`).

This is a *parallel* bump — every pillar moves by the same +1bp, not a key-rate / per-tenor bucket. It is a *dual-curve* bump — discounting and forward projection move together, so the reported number is the total rate sensitivity, not an isolated discount-curve or forward-curve sensitivity. (Per-curve and key-rate decompositions are a future extension, not v1.)

**Computation.**
```
DV01 = PV_base − PV_bumped
```
where `PV` is the signed dirty PV under the trade's sign convention:
- `pay_fixed=True`  → PV = PV(float) − PV(fixed)
- `pay_fixed=False` → PV = PV(fixed) − PV(float)

The bumped PV is obtained by rebuilding the swap with its floating leg repointed at the bumped projection curve (`floating.with_projection_curve(bumped_proj)`) and repricing against a `MarketData` carrying both bumped curves (same `val_date`, same `fixings`).

**Sign convention.** A **positive DV01 means the position loses value when rates rise** (`PV_base − PV_bumped > 0`). It is reported as the loss under the up-bump, consistent with the `pay_fixed` sign convention above.

**Properties / caveats.**
- One-sided (forward-difference) bump, not a central difference; bias is `O(bump)` and negligible at 1bp for linear OIS swaps.
- Fixings are held fixed across the bump — only projected (future) rates and discount factors move; historical compounded amounts are unchanged.
- Matured trades carry `dv01 = 0` (set explicitly by the portfolio runner; they are never repriced).
- Bump size is configurable via `SwapPricer(bump_size=...)`; default `1e-4`.

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
- **`SwapPricer`** — `price(swap, market_data) → SwapValuation`. Also `dv01(swap, market_data)` via a parallel +1bp bump of **both** the SOFR discount and FF projection curves, reported as the loss `PV_base − PV_bumped` (see *DV01 Methodology* above).
- **`SwapValuation`** *(dataclass)* — `clean, dirty, accrued, dv01, fixed_cf: DataFrame, floating_cf: DataFrame` + identifying columns (see DB-readiness).

### Loaders (input abstraction)

- **`CurveLoader`** *(ABC)* — `load(val_date, curve_name) → ZeroCurve`. Three concrete implementations selected by CLI flag (mutually exclusive):
  - `ExcelCurveLoader` *(default; no flag)* — reads the production `market_environment_YYYY-MM-DD.csv`; converts zero rates to DFs via `RateQuoting` (default `ContinuousACT360`).
  - `DatedCurveLoader` *(`--pillar-dates`)* — reads two no-header CSVs per val_date, `sofr_YYYY-MM-DD.csv` and `ff_YYYY-MM-DD.csv` (col A pillar date ISO, col B zero rate decimal). Bypasses `tenor_to_date`; same `RateQuoting` is still applied to convert rates → DFs.
  - `DatedDFCurveLoader` *(`--pillar-dates-df`)* — reads `sofr_df_YYYY-MM-DD.csv` and `ff_df_YYYY-MM-DD.csv` (col A pillar date ISO, col B = **discount factor**). Bypasses `RateQuoting` entirely; supplied DFs feed straight into the log-linear interpolation pipeline. `Pillar.zero_rate` is `NaN` (no quoting convention was applied — honest signal in the debug frame). DV01 bumping on this path uses continuous-ACT/360 equivalence at the DF level: `DF_new = DF · exp(−δ · days / 360)`.
  - All three produce a `ZeroCurve` with identical downstream behaviour; the constructor path differs only in how DFs are obtained. Ports for DB/API later.
- **`FixingLoader`** *(ABC)* — `ExcelFixingLoader`, `DataFrameFixingLoader`.
- **`TradeLoader`** *(ABC)* — `YamlTradeLoader`, `DataFrameTradeLoader`.

**Input formats (production, only formats supported — legacy synthetic formats retired 2026-05-15):**

- **Curve — default (`market_environment` path)** — `data/curves/market_environment_YYYY-MM-DD.csv` (ISO date, dashes; one conceptual sheet `in`). Has a few non-data header rows on top (`Name`/`Date`/`Property` in col A) and many interleaved irrelevant pillars (other currencies, EQ/FX/VOL tickers). `ExcelCurveLoader` resolves the file by ISO `val_date` in the filename and filters column A by `TICKER_RE` (`^IR\.USD-(SOFR|FEDFUNDS)-ON\.ZERORATE-([0-9A-Z]+)\.MID$`) — header rows and foreign pillars drop out automatically; col B is the zero rate. A shared row iterator handles `.csv` (and `.xlsx` for ad-hoc `load_from_file`) so the col-A filter is identical across paths. The old `CurvesYYYYMMDD.xlsx` pattern is no longer supported.
- **Curve — `--pillar-dates` (dated rate pillars)** — two no-header CSVs per val_date in `data/curves/`: `sofr_YYYY-MM-DD.csv` (discount) and `ff_YYYY-MM-DD.csv` (projection). Col A pillar date (ISO), col B zero rate (decimal). No ticker filtering; every non-empty row is a pillar.
- **Curve — `--pillar-dates-df` (dated discount factors)** — `sofr_df_YYYY-MM-DD.csv` and `ff_df_YYYY-MM-DD.csv`. Same shape as `--pillar-dates` but col B is the DF (positive, typically ≤ 1). Bypasses `RateQuoting`.
- **Fixings** — `data/fixings/fixing_cail_USD-FEDFUNDS-ON.csv`; `ticker,date,rate` content identical to the old `fedfunds.csv` (no special handling). `ExcelFixingLoader` already auto-detects this layout.

Synthetic generators (`scripts/generate_synthetic_curve.py`, `generate_synthetic_fixings.py`) now emit these production formats directly. Curve/fixing files normalize to the same in-memory `ZeroCurve` / `FixingHistory`, so nothing downstream of the loaders changed.

### Portfolio & output

- **`Portfolio`** — takes loaders + a list of trade ids; iterates, prices each, writes outputs. One run is self-contained in its own folder `<out_dir>/valdate_<val_date>_rundate_<run_date>/` (folder name embeds **both** the valuation date and the execution/run date, so reruns for different business days stay distinct and a same-day rerun is idempotent). Single-date and batch runs share this identical layout.
- **`io_excel`** — writes portfolio workbook + per-trade detail workbooks (see Output section).
- **`io_parquet`** — same frames also dumped to Parquet for downstream automation / DB load.
- **`batch.run_batch(val_dates, …)`** — fans several valuation dates across a `ProcessPoolExecutor` (pricing is CPU-bound). Each date is an independent `Portfolio.run` writing its own `valdate_<val_date>_rundate_<run_date>/` folder with the **normal daily summary** (no aggregate summary replaces it); one bad date can't sink the batch (returns a per-date `BatchResult`). Loaders are rebuilt inside each worker so nothing unpicklable crosses the process boundary. **Each worker configures logging to stdout** so the same detailed per-trade progress as a single-date run is emitted (lines prefixed `[val=<date>]` for attributability under parallelism). A date with **no published zero-rate curve** (typically a weekend/holiday — `FileNotFoundError` from the curve loader) is classified **`skipped`** (a WARNING, *not* an `error`) and does **not** fail the batch exit code; statuses are `ok` / `partial` / `error` / `skipped`. In addition, one overarching `batch_<UTCstamp>.log` (+ `.json`) is written at the `out_dir` root — outside all the per-run folders — with totals `ok=… partial=… error=… skipped(no-curve)=…` for single-file auditability.

### Class count

~20 classes total, half of them strategy variants. Three pluggable axes — `RateQuoting`, `DayCount`, `*Loader` — so new conventions or input sources are subclass additions, not pricer edits.

---

## Output Layout

Every run (single-date *or* one date within a batch) is self-contained under
`output/valdate_<val_date>_rundate_<run_date>/`. **By default (no flag) the
run writes ONLY the prod CSV (`IRS_Valuation_<val_date>-00001.csv`).** Passing
`--debug` flips every other artifact on (portfolio workbook + per-trade detail
+ per-trade debug + parquet). The default workbooks are now opt-in to keep
nightly cloud runs lean. A batch additionally drops `batch_<UTCstamp>.log`
and `batch_<UTCstamp>.json` at the `output/` root. Full layout under
`--debug`:

```
output/
├── valdate_<val_date>_rundate_<run_date>/
│   ├── IRS_Valuation_<val_date>-00001.csv  (ALWAYS, even without --debug)
│   ├── portfolio_<val_date>.xlsx          (only with --debug)
│   ├── detail/<trade_id>.xlsx             (only with --debug)
│   ├── debug/<trade_id>_debug.xlsx        (only with --debug)
│   ├── parquet/{summary,floating_cf,fixed_cf,curves}.parquet (only with --debug)
│   └── manifest_<val_date>.json
├── batch_<UTCstamp>.log                   (batch runs only)
└── batch_<UTCstamp>.json                  (batch runs only)
```

### Production CSV (`IRS_Valuation_<val_date>-00001.csv`)

Sole default output. Matches the KPMG IRS-valuation feed spec
(`Output_Format.xlsx`). Written by `src/swaps/io_prod.py::write_prod_csv`.

**Encoding**: UTF-8 (no BOM). **Version stamp**: hard-coded `"00001"` per
spec (file is not yet in production; consumer has not requested an
auto-increment scheme).

**Row structure** (49 columns wide, A..AW):

| Row | Cells | Contents |
|---|---|---|
| 1 (header) | 5 | `H` \| `<yyyymmdd run date — today>` \| `IRS_Valuation_<val_date>-00001.csv` \| `00001` \| `KPMG` |
| 2 (field names) | 49 | column labels in exact spec order — see `PROD_FIELDS` in `io_prod.py` |
| 3..N+2 (trades) | 49 | one row per priced valuation (matured trades still emitted with pricing = 0) |
| N+3 (footer) | 49 | `T` \| `<n_trades>` \| blanks \| column-letter sums at G/H/I/J, Q/R, U/V/W, AK/AL, AW |

**Field sources** (49 columns total, A..AW):

| Output field | Column | Source |
|---|---|---|
| Trade Reference Number | A | always blank ("Not Required") |
| Internal Reference Number | B | always blank |
| Quantum Deal Number | C | `td.quantum_deal_number` (template) |
| Oracle Entity Code | D | `td.oracle_entity_code` (template) |
| Notional Currency | E | `td.notional_currency` (template) |
| As of Date | F | `val_date` (CLI) |
| Clean price | G | `v.clean` |
| Accrued Interest | H | `v.accrued` |
| Total Value (NPV) | I | `v.dirty` |
| DV01 | J | `v.dv01` |
| Valuation Currency | K | constant `"USD"` |
| Child Reference Number / Period Start/End/Payment | L–O | always blank |
| Maturity Date | P | `td.maturity_date` |
| Notional 1 Amount | Q | `td.notional` |
| Notional 1 Amount USD | R | `td.notional` (book is USD-only — same value) |
| Pay Rec Status / Component Type | S–T | always blank |
| Coupon FV / Intrinsic Value FV / Time Value FV | U–W | always blank (footer sums = 0) |
| Intercompany Trade | X | `"Yes"`/`"No"` from `td.intercompany` (bool) |
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
| Deal Date | AQ | `td.deal_date` (trade date — distinct from `start_date`) |
| Netting ID | AR | `td.netting_id` |
| Cash Flow Netting Allowed | AS | `td.cash_flow_netting_allowed` |
| Position Netting Allowed | AT | `td.position_netting_allowed` |
| Balance Sheet CCID | AU | 9-segment composite ID (see CCID section below); blank if entity lookup misses or NPV == 0 |
| PL OCI CCID | AV | 9-segment composite ID (Natural Account `465012` regardless of sign); blank if entity lookup misses |
| Hedged Debt MTM | AW | `v.pv_fixed` (PV of fixed leg under SOFR DF — equates to the hedged-debt fair value) |

**CME-branch rule**: an **exact** string equality
`td.current_counterparty == "CME Clearing House"` triggers all five
CME-cleared output values (Sub-Product2 / Counterparty Type / QCCP /
Cleared / Cash-Settled CCP). Anything else — including `"CME"`,
`"CME Clearing house"`, leading/trailing whitespace, or different casing —
routes to the Bank / OTC-Bilateral branch. This is deliberate: a fuzzy match
would silently bucket typos into the wrong cleared status. The expected
string is documented in `_template.csv.sample`.

**CCID composition (cols AU / AV)** — per `CCID.xlsx`:

```
CCID = Entity-RC-NaturalAccount-SubAccount-InterEntity-InterCenter-Product-Reserve1-Reserve2
```

9 dash-joined segments. Entity = `td.oracle_entity_code`. RC is looked up
from the **Entity Reference Report** (`data/entity/Entity_Reference_Report.csv` by
default; columns `Entity_Code, Default RC`). The trailing 6 segments are
zero-padded defaults: `000000-0000-000000-000000-000000-0000`.

Natural Account varies by CCID type and Asset/Liability sign:

| CCID | NPV > 0 (Asset) | NPV < 0 (Liability) | NPV == 0 |
|---|---|---|---|
| **Balance Sheet** (AU) | `192001` | `392001` | blank (matches blank Asset Liability Tag) |
| **PL OCI** (AV) | `465012` | `465012` | `465012` |

If the entity code is blank or missing from the lookup table, **both** CCID
fields are emitted blank — no half-built id ever leaves the writer. The
lookup file path is overridable per-run via `--entity-rc <path>`; the file
itself is optional (missing file → all CCID cells blank, with a warning).

Example for `oracle_entity_code = "1000"`, RC `100008`, asset trade:
```
AU = 1000-100008-192001-000000-0000-000000-000000-000000-0000
AV = 1000-100008-465012-000000-0000-000000-000000-000000-0000
```

**Footer sum specification** (drawn directly from `Output_Format.xlsx`,
column letters cross-checked against the 49-field order):

| Col | Field | Notes |
|---|---|---|
| A | `"T"` (literal) | |
| B | `n_trades` | matured trades count |
| G | Σ `clean` | |
| H | Σ `accrued` | |
| I | Σ `dirty` | |
| J | Σ `dv01` | |
| Q, R | Σ `notional` (twice) | |
| U, V, W | 0 | columns are always blank; sums are always 0 (sanity tripwire) |
| AK | Σ `DA` (positive NPVs only) | |
| AL | Σ `DL` (Σ \|npv\| over negative NPVs — positive total) | |
| AW | Σ `pv_fixed` | hedged-debt total |

All other cells in the footer row are blank strings.

### Template inputs feeding the prod CSV

`_template.csv.sample` carries 13 new optional columns to the right of the
existing 34 pricing columns. They are sourced 1:1 by the prod writer:
`quantum_deal_number`, `oracle_entity_code`, `notional_currency`,
`intercompany` (bool → Yes/No), `counterparty_name_quantum`,
`current_counterparty`, `entity_name_quantum`, `reporting_party`,
`counterparty_location`, `deal_date`, `netting_id`,
`cash_flow_netting_allowed`, `position_netting_allowed`. Blank cells → blank
output cells. `intercompany` parses via the same boolean rule as
`pay_fixed` (`true`/`false`/`yes`/`no`/`1`/`0`). `deal_date` is the **trade
date** (when the swap was struck), distinct from `start_date` (effective
date) — the two typically differ by ~2 business days.

### `valdate_<val_date>_rundate_<run_date>/portfolio_<val_date>.xlsx` — the everyday view

| Tab | Contents |
|---|---|
| `Summary` | One row per trade: trade_id, notional, fixed_rate, start, maturity, clean, dirty, accrued, DV01, PV(fixed), PV(floating), par_rate, rate_diff_bp |
| `FloatingCF` | All floating-leg cashflows stacked, `trade_id` as leading column |
| `FixedCF` | All fixed-leg cashflows stacked, `trade_id` as leading column |
| `Curves` | SOFR + FF zero curves used (audit trail) |

### `valdate_<val_date>_rundate_<run_date>/detail/<trade_id>.xlsx` — drill-down per trade

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
│   ├── io_excel.py           # portfolio + per-trade detail + debug workbooks
│   ├── io_prod.py            # KPMG prod CSV (default output)
│   ├── io_parquet.py
│   ├── manifest.py           # run manifest writer
│   ├── portfolio.py          # single-date runner (valdate_/rundate_ folder)
│   └── batch.py              # parallel multi-date runner
├── data/
│   ├── curves/market_environment_<YYYY-MM-DD>.csv
│   ├── fixings/fixing_cail_USD-FEDFUNDS-ON.csv
│   └── trades/*.yaml
├── output/
│   ├── valdate_<val_date>_rundate_<run_date>/
│   │   ├── IRS_Valuation_<val_date>-00001.csv   (DEFAULT — always written)
│   │   ├── portfolio_<val_date>.xlsx           (--debug only)
│   │   ├── detail/<trade_id>.xlsx              (--debug only)
│   │   ├── debug/<trade_id>_debug.xlsx         (--debug only)
│   │   ├── parquet/{summary,floating_cf,fixed_cf,curves}.parquet  (--debug only)
│   │   └── manifest_<val_date>.json
│   ├── batch_<UTCstamp>.log             (batch runs only)
│   └── batch_<UTCstamp>.json            (batch runs only)
├── tests/
└── scripts/
    ├── price_portfolio.py        # one valuation date
    └── price_portfolio_batch.py  # several dates, parallel
```

---

## Workflow (implementation order)

**Block A — Foundation** *(curves, conventions, calendar, schedule)*
- `RateQuoting`, `DayCount`, `USCalendar`, `generate_schedule`, `ZeroCurve`
- Tests: DF round-trip, log-linear interp at known points, business-day rolls

**Block B — Pricing core** *(legs + pricer)*
- `FixingHistory`, `NotionalSchedule`, `FixedLeg`, `OISFloatingLeg`, `Swap`, `SwapPricer`, DV01 (dual-curve parallel +1bp bump-and-reprice; see *DV01 Methodology*)
- Tests: flat-curve sanity, par-swap test, history-split test, `clean + accrued ≈ dirty` invariant

**Block C — I/O & portfolio** *(loaders, Excel, Parquet, portfolio runner, CLI)*
- Excel + Parquet writers, `Portfolio` (per-run `valdate_/rundate_` folder), `price_portfolio.py`, sample data, manifest
- `batch.run_batch` + `price_portfolio_batch.py` — parallel multi-date runner, per-worker stdout logging, `skipped(no-curve)` WARNING status, overarching `batch_<UTCstamp>.{log,json}`
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

### CLI flags (both `price_portfolio.py` and `price_portfolio_batch.py`)

- **No flag (default)** — writes ONLY the prod CSV (see *Production CSV*
  above). No portfolio workbook, no per-trade detail, no parquet, no debug.
  This is the lean nightly-cloud-run mode.
- **`--debug`** — writes EVERYTHING: prod CSV + portfolio workbook +
  per-trade detail workbooks + per-trade debug workbooks + parquet. There is
  no middleground flag (no separate `--detail` / `--portfolio-xlsx` /
  `--parquet`); the choice is "lean prod feed" vs "full audit dump".
- **Curve input mode** (mutually exclusive argparse group; default = `market_environment` path):
  - `--pillar-dates` → `DatedCurveLoader` (rate-keyed dated pillars).
  - `--pillar-dates-df` → `DatedDFCurveLoader` (DF-keyed dated pillars; bypasses `RateQuoting`).
- **`--entity-rc <path>`** — Entity Reference Report CSV used to build the
  Balance Sheet / PL CCID strings (cols AU / AV). Default
  `data/entity/Entity_Reference_Report.csv`. File is optional: missing file → all
  CCID cells emitted blank with a startup warning. Schema: header row
  `Entity_Code,Default RC`.
- **`-v` / `--verbose`** — toggles root logger level. **Default `ERROR`**
  (cloud-friendly: only hard failures hit stdout; `manifest.warnings[]` still
  records convention warnings, no-curve skips, and matured-trade notices so
  the file record is complete). `-v` switches to `INFO` (per-trade timings,
  run folder, "===== val_date X : run START =====" worker lines,
  convention warnings, no-curve skip warnings, etc.). Applied to the parent
  process and each per-date worker in batch.
- **Exit code is always printed on the final stdout line**
  (`exit_code=<n>`), regardless of `-v`, so a quiet ERROR-only cloud run
  still surfaces it. Captures argparse's internal `SystemExit` too — a bad
  or missing CLI argument still prints `exit_code=2`.

### Exit codes (both scripts)

| Code | Meaning |
|---|---|
| `0` | Success — all priced. `skipped(no-curve)` (weekend/holiday with no published curve) counts as success and does not page. |
| `1` | Hard failure — uncaught exception, or a date errored entirely. |
| `2` | CLI usage error — argparse default (bad/missing args, mutex violation). |
| `3` | Partial — pricing completed but at least one trade errored (recorded in `manifest.errors[]`). |

Codes are stable and intended for CI/CD branching (`retry on 3`, `page on 1`, `ignore 0`). POSIX-safe positive values in `0–125`; no negatives (Python wraps `−1` to `255`); avoid `126`/`127`/`128+N` (shell-reserved). Skipped dates intentionally do not change the exit code — silence (no run at all by the scheduled time) is what should page, monitored separately.

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

1. `pytest -q` — all unit tests + golden-master green (includes
   `tests/test_io_prod.py` covering prod-CSV layout, CME branching,
   intercompany rendering, footer sums).
2. `python scripts/price_portfolio.py --val-date YYYY-MM-DD` produces, under `output/valdate_<val_date>_rundate_<run_date>/`:
   - `IRS_Valuation_<val_date>-00001.csv` (always — default output)
   - `manifest_<val_date>.json`
   With `--debug` also:
   - `portfolio_<val_date>.xlsx` with four tabs
   - `detail/<trade_id>.xlsx` per trade
   - `debug/<trade_id>_debug.xlsx` per trade
   - `parquet/*.parquet`
2b. `python scripts/price_portfolio_batch.py --start D1 --end D2` (or repeated `--val-date`) produces one `valdate_/rundate_` folder per date plus `output/batch_<UTCstamp>.{log,json}`; exit codes follow the standardized scheme (`0` ok/skipped, `1` hard error, `2` usage, `3` partial). Dates with no published curve are reported as `skipped` (WARNING) and stay at exit code `0`.
2c. Curve-input alternates exercised: `--pillar-dates` (`sofr_<date>.csv` + `ff_<date>.csv`, rates) and `--pillar-dates-df` (`sofr_df_<date>.csv` + `ff_df_<date>.csv`, DFs) each price the same portfolio to numerically-equivalent DFs (verified by round-trip tests in `tests/test_dated_curve_loader.py` and `tests/test_dated_df_loader.py`).
2d. `-v` toggles INFO progress vs the default WARNING-only output.
3. Hand-check one swap:
   - `clean + accrued == dirty` to < 1e-8
   - Sum of fixed PV − sum of floating PV ≈ reported NPV (within sign convention)
   - DV01 sign and magnitude reasonable vs. analytic estimate
4. `--debug` flag produces per-trade debug workbooks.
5. Manifest contains git_sha, input hashes, trade count, timestamps.

---

## File locations to be created

All under `F:\Projects - Github\Swaps\` — greenfield (folder will be recreated on implementation start). No existing utilities to reuse.
