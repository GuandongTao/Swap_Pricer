# Open Questions & Assumptions

Living list of things assumed during initial build that need confirmation before going live.
Update this file as questions are answered (move resolved items to the bottom with the answer).

---

## OPEN — please clarify

### Q1. Calendars: are `fixing_calendar` and `payment_calendar` ever different per trade?
**Currently assumed:** they are stored as two separate per-trade fields. If they're always identical, we can simplify by collapsing them into one field.
**Impact if wrong:** none for correctness — the worst case is two fields carrying the same vector. Simplification only.

### Q2. Zero-rate quoting convention on the curve Excel
**Now assumed (updated 2026-05-13):** **annual compounded ACT/360**, i.e. `DF(T) = (1 + r)^(-T / 360)`.
**Was previously:** continuously compounded ACT/360.
**File analyzed:** `Curves20260331.xlsx`. Both SOFR and FEDFUNDS zero rates are decimals (~0.036), but the file does not state the compounding convention.
**Impact if wrong:** DFs will be biased — small at short tenors, larger at long tenors. All downstream PVs shift.
**How to confirm:** ask the curve provider, or back-check one known DF (e.g., compare to Bloomberg `SWPM` or any vendor screen for `2026-03-31` curve).
**Alternatives to switch to:** `ContinuousACT360`, `SimpleACT360`, `ContinuousACT365`, `AnnualCompoundedACT365`. Change the `DEFAULT` in `src/swaps/rate_quoting.py` or pass `rate_quoting=...` to `ZeroCurve` / `ExcelCurveLoader`.

### Q3a. Tenor → pillar date convention (resolved 2026-05-13)
**Now assumed:** strict ACT/360 day math for tenor codes. `D=N`, `W=7N`, `M=30N`, `Y=360N` days from val_date. `ON=1`, `TN=2`.
**Was previously:** calendar increments (1M = +1 calendar month, 1Y = +1 calendar year).
**Effect at pillars:** an `NY` zero rate `r` discounts to exactly `(1+r)^(-N)` under annual-compounded ACT/360 (year-fraction = days/360 = N).
**Trade-off acknowledged:** some curve providers anchor pillars at calendar dates (e.g., Bloomberg market-convention tenors). If your provider's curve was built that way, DFs will be biased at the long end. Back-check one pillar against a vendor screen to confirm.

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

### Q6. NY Fed holiday calendar — is a static list acceptable for v1?
**Currently assumed:** maintain a static list of NY Fed business holidays through ~2050 in `calendar_us.py`. Refresh annually.
**Alternative:** use `pandas.tseries.holiday.USFederalHolidayCalendar` or `holidays` package.
**Impact if wrong:** a holiday omission shifts one business day on rolls, fixings, payment delays. Material at period boundaries.

### Q7. Pay-fixed vs receive-fixed — sign convention per trade
**Currently assumed:** each `Swap` has a `pay_fixed: bool` field; PV reported from that party's perspective.
**Status:** awaiting trade definitions to confirm both directions occur in the portfolio.

### Q8. Curve file naming convention — will it always be `CurvesYYYYMMDD.xlsx`?
**Currently assumed:** yes. The loader parses `val_date` from this filename pattern.
**Status:** to be confirmed; the user said the file layout will remain the same.

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
