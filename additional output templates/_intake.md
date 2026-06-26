# Additional Outputs — Master Intake

> Coding-time reference only (this whole dir is reference; it will NOT ship).
> Consolidates `frequency and channel.xlsx` (registry) + `output instructions.xlsx`
> (per-item NL prose) + per-item format Excels into one spec to code from.

## Status legend
`CODED` · `LOCKED` (ready to code) · `DRAFT` (ingested, open Qs) ·
`PLACEHOLDER` (emit empty/blank file for now) · `SKIP` (ignore for now) ·
`DISCUSS` (needs a design discussion before coding).

---

## Global conventions

### Frequencies (which val_dates / runs trigger an item)
- **daily** — any supplied val_date.
- **month-end** — last **calendar** day of month (`is_month_end`). Weekend/holiday
  EOM: valued as-of the calendar EOM, curve sourced from previous business day
  (`month_end_curve_date`); fixings carry preceding bday forward.
- **quarter-end** — last calendar day of Mar/Jun/Sep/Dec (⊂ month-end; independent predicate).
- **Once** — NOT calendar-driven. Triggered by a CLI flag naming newly-added swap
  id(s): `--new-deal-<swapid>` (multiple allowed). All `Once` items run ONLY for
  the named new id(s), in addition to whatever else is due. (Supersedes the earlier
  withdrawal of "Once".)
- **Monthly** — appears on items 6 & 8. OPEN: is "Monthly" the same as "month-end"
  (last calendar day), or a different cadence? **Needs confirmation.**

### Channels (UPDATED 2026-06-26 — supersedes "email parallel to output/")
- **SFTP** → this run's dated folder `output/valdate_<date>_..._ver_<NNNNN>/`
  (alongside the IRS Valuation feed).
- **EMAIL** → `email/` SUBFOLDER inside that same dated run folder.
- Cross-run lookups (Treasury "Total Value Change" prior-month file) scan the
  `output/` root recursively.

### Run model (UPDATED 2026-06-26 — SINGLE RUN)
- Additional outputs are emitted by the SAME `price_portfolio.py` run as the
  IRS Valuation/Netting feeds — ONE run, reusing the in-memory priced data (no
  repricing). Wired via `Portfolio.run` → `additional_outputs.integration.emit_for_run`.
- Triggering = ALWAYS ON, schedule-gated (each item's frequency decides).
- `Once` items gated by `--new-deal <id>` (repeatable) on `price_portfolio.py`.
- Standalone `scripts/additional_outputs.py` still exists for ad-hoc/testing
  (reprices independently; writes to its `--out-dir` as run_dir).

### Envelopes (per-item, NOT uniform)
- Raw input files (Month End Data); **KPMG IRS-Valuation H/T header+footer feed**
  (Treasury, Payment Report — reuse `io_prod` envelope); **Excel workbook**
  (Payment Schedule, Day 1, Attribution); empty placeholder (AmexIntExp).

### Input-schema setup (one-time, coding phase only — NOT at runtime)
- **`floating_index`** added to `TradeDef` + template as first floating-leg field
  (DONE). Per Treasury-report instruction: add the `Index` input field only if
  missing, during coding/setup — never mutate the input file during valuation or
  report production. The Treasury/`Index` column queries from this field.
  ⚠ Value format differs: our template sample = `USD-FEDFUNDS-ON`; Treasury sample
  shows `USD-Federal Funds-H.15-OIS-COMPOUND`. Confirm the exact string to store/emit.

---

## Registry (from `frequency and channel.xlsx`)
| # | Item (filename pattern) | Frequency | Channel | Status |
|---|--------------------------|-----------|---------|--------|
| 1 | Month End Data | Month End | Email | **CODED** |
| 2 | Hedge Summary | Month End | SFTP | **SKIP** (tomorrow) |
| 3 | `American Express <Mon DD, YYYY> Treasury Valuation Report` | Month End | SFTP | **CODED** (assumptions to confirm) |
| 4 | `KPMG_AMEX_Payment_Report <Mon DD, YYYY>` | Daily | SFTP | **CODED** (past-month incl.) |
| 5 | `<swap deal id> Swap Payment Schedule` | Once | SFTP | **CODED** (assumptions to confirm) |
| 6 | `AmexIntExp <yyyy.mm.dd>` | Monthly | Email | **PLACEHOLDER** (tomorrow) |
| 7 | `<swap deal id> mm.dd.yyyy - Day 1 Valuations` | Once | Email | **CODED** (assumptions to confirm) |
| 8 | `Attribution from <yyyy-mm-dd> to <yyyy-mm-dd>.xlsx` | Monthly | Email | **DISCUSS** (tomorrow) |

**Engine** (all read-only reuse of the pricer; default output path untouched):
`src/swaps/additional_outputs/{base,priced,envelope,helpers,month_end_data,
treasury_valuation,payment_report,swap_payment_schedule,day1_valuations,registry}.py`
+ CLI `scripts/additional_outputs.py` (`--val-date`, `--new-deal` repeatable, `--all`).
`priced.py` reprices via the same loaders/`build_swap`/`SwapPricer`, pairing each
TradeDef↔SwapValuation. `envelope.py` = generic IRS-Valuation H/T feed writer.

**Payment Report (#4) — RESOLVED (no limitation).** `cashflows()` iterates the full
schedule and keeps `payment_amount` on past-paid periods, so payments earlier in the
month than the run date ARE included. Past settlements are computed from the realized
fixing record (`rate_source='history'`) + the contractual fixed rate, not from a
forward valuation. Verified: a swap with a 2026-03-16 settlement shows that row in the
Mar-31 report (fixed 402,777.78 / floating 273,346.85 / net 129,430.93).

**Day 1 (#7) — PV01 + split DV01 implemented** (the sample row has them). `priced.leg_risk`
computes PV01 = PV of a 1bp fixed-leg annuity, and per-leg DV01 (fixed+floating == total,
same bump/sign convention as `SwapPricer._dv01`). Verified reconciliation. Floating PV01
left blank per the sample; Spot Exchange / Cash Accrued blank/0 per the sample.

**Decisions made (confirm)** — see per-module docstrings for the full list:
freq display map (3M→Quarterly…); Internal Reference Number = raw deal id;
Total Value = clean+accrued; Treasury Total-Value-Change diffs prior month's file in
SFTP dir (blank if none); footer sums monetary cols; feed dates mm/dd/yyyy, Excel ISO;
Day1 Key Rate=par rate; per-leg clean = signed pv_fixed / pv_floating; Once items keyed
by `--new-deal` raw id.

---

## Items

### 1. Month End Data — `CODED`
See `_intake_month_end_data.md`. Engine `src/swaps/additional_outputs/` + CLI
`scripts/additional_outputs.py`. 327 tests green. (Header-stripped extract of the 2
used USD curves + verbatim fixings copy → `email/`.)

### 2. Hedge Summary — `SKIP`
Instruction: "skip this item for now." No further detail provided.

### 3. Treasury Valuation Report — `DRAFT`  (tab KPMG_AMEX_Treasury_Valuation)
- Envelope: **same header/footer as IRS Valuation feed**. One row per **all IRS positions**.
- Format file: `Treasury Report.xlsx` (20 cols). Column → source:

| Col | Source / rule |
|-----|---------------|
| Internal Reference Number | IRS deal id |
| Product | constant `Reverse Swap` (all rows) |
| Hedged Item | blank |
| Counterparty | `debt_counterparty` |
| Clearing House | constant `CME Clearing House` |
| Trade Date / Effective Date / Maturity Date | IRS input |
| Hedged Item Notional | IRS notional |
| Total Value Change | Total Value minus **previous month's Treasury report** Total Value (matched by deal id). If no prior report in the output folder → blank |
| DV01 | valuation DV01 |
| Clean Price | valuation clean |
| Accrued Interest | valuation accrued |
| Total Value | valuation total value |
| Floating Pmt Frequency | human-readable freq from IRS input (e.g. `Quarterly`) |
| Index | from `floating_index` input field |
| Current Spread | IRS `floating_spread` |
| Fixed Pmt Frequency | human-readable freq from IRS input (e.g. `Semi-annually`) |
| Fixed Rate | IRS fixed rate |
| Notional | IRS notional |

- OPEN: frequency display mapping (`3M`→Quarterly, `6M`→Semi-annually, `1Y`→Annually, `1M`→Monthly…) — confirm table. `Total Value Change` requires reading the prior month's emitted report — confirm match key & folder.

### 4. KPMG Payment Report — `DRAFT`  (tab KPMG_AMEX_Payment_Report)
- Envelope: **same header/footer as IRS Valuation feed**. Frequency **Daily**.
- Row filter: only IRS positions **with a payment sometime during that month**;
  no payment in the month ⇒ omit the row.
- Format file: `Payment Report.xlsx` (18 cols). Column → source:

| Col | Source / rule |
|-----|---------------|
| Internal Reference Number | IRS deal number |
| Product | constant `Reverse Swap` |
| Description | blank |
| Notional | IRS input |
| Start/End Accrual Date | IRS input (fixed leg) |
| Number of Days … fixed leg | computed day count |
| Fixed Payment | payment amount if applicable |
| Start/End Accrual Date (Floating) | blank |
| Number of Days … floating leg | computed day count |
| Floating Payment | payment amount if applicable |
| Net Payment | net payment occurring in the month |
| Payment Date | if applicable |
| Counterparty | `debt_counterparty` |
| Index Rate / Current Spread / All-In-Rate | blank |

- OPEN: "Daily" freq but month-scoped payment filter — define "that month" relative
  to val_date (current calendar month of val_date?). Net Payment "happened in this month".

### 5. Swap Payment Schedule — `DRAFT`  (tab Swap Payment Schedule)
- Frequency **Once** → gated by `--new-deal-<swapid>` flag (multiple ids ok); runs
  only for the named new id(s).
- Envelope: **Excel**, per `Payment Schedule.xlsx` (14 cols). Full per-leg schedule:
  interleaved fixed-leg rows (Start/End Date, Notional, Swap Rate, Payment Date) and
  floating-leg rows (Floating Start/End Date, Notional, Rate Fixing Date, Spread,
  Payment Date). "Leave cols that are currently empty" (Fixed Payment, Index Rate,
  Floating Interest Rate, Floating Payment, Net Amount, etc.) blank for now.
- Cols: Start Date, End Date, Floating Start Date, Floating Period End Date, Notional,
  Swap Rate, Fixed Payment(blank), Rate Fixing Date, Index Rate(blank), Spread,
  Floating Interest Rate(blank), Floating Payment(blank), Net Amount(blank), Payment Date.

### 6. AmexIntExp — `PLACEHOLDER`
"pass this output for now; just produce an empty file as a space holder." Emit an
empty file named `AmexIntExp <yyyy.mm.dd>` to `email/`. Monthly.

### 7. Day 1 Valuations — `DRAFT`  (tab Day 1 valuation)
- Frequency **Once** (new deal), channel Email, **Excel** per `Day 1 Valuations.xlsx`.
- Structure (single workbook):
  1. **Summary block**: Key Rate, DV01, PV01, Clean Price, MTM Accrued Interest,
     Cash Accrued Interest, Total Value, Timestamp, Value Date, Valuation Currency.
  2. **Fixed vs Floating leg summary** (side by side): DV01, PV01, Clean Price,
     MTM/Cash Accrued, Total Value, Spot Exchange.
  3. **Per-leg cashflow detail**:
     - Fixed: Start, End, Payment Date, Notional, Fixed Rate, Discount Factor, CF FV, CF PV.
     - Floating: Start, End, Fixing Date, Payment Date, Notional, Forward Rate, Spread,
       Discount Factor, CF FV, CF PV.
  - "Information summarized, split fixed vs float, then cashflow detail **as produced
    in debugging**." → maps closely to the existing per-trade debug workbook.
- OPEN: confirm Key Rate / PV01 / Spot Exchange definitions vs current pricer outputs.

### 8. FVH Attribution — `DISCUSS` + `PLACEHOLDER`
- Excel, tabs **`IR Total Value`** and **`IR Clean Price`**, each over all IRS entries.
- Attribute period-over-period changes to valuation drivers (rates/curve, carry/time,
  spread, etc.). Monthly, Email. Filename `Attribution from <yyyy-mm-dd> to <yyyy-mm-dd>.xlsx`.
- Instruction: **start a Claude discussion to confirm the attribution approach** before
  building. Create a **blank placeholder** for now.

---

## Cross-cutting open questions
1. **"Monthly" vs "Month End"** — define "Monthly" (items 6, 8).
2. **Frequency display map** (3M→Quarterly, etc.) for Treasury report.
3. **`Index` value string** — exact format to store in input / emit (`USD-FEDFUNDS-ON`
   vs `USD-Federal Funds-H.15-OIS-COMPOUND`).
4. **Treasury `Total Value Change`** — prior-month report lookup: match key + folder + first-month behavior.
5. **Payment Report month scope** for a Daily report; payment/Net-Payment detection.
6. **`--new-deal-<id>` flag** — exact CLI shape + how a "new" id maps to a trade row.
7. **Filename date formats** per item (`Mon DD, YYYY`, `yyyy.mm.dd`, `mm.dd.yyyy`, `yyyy-mm-dd`).
8. **Attribution approach** (item 8) — full design discussion.
9. Several items reuse pricer internals (schedules, cashflows, DV01, accrued) — wiring
   the additional-outputs engine to the priced portfolio is the shared dependency; today
   the engine is standalone (Month End Data needs no pricing).
