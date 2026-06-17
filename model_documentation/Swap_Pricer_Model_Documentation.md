---
title: "Model Documentation: Fed Funds Fixed–Float Swap Pricer"
subtitle: "USD Interest Rate Swap Daily Mark-to-Market Valuation Model"
date: "Valuation Model Documentation"
---

<!--
  SOURCE OF TRUTH for this document.
  Generate the Word version with:
      pandoc Swap_Pricer_Model_Documentation.md \
        -o Swap_Pricer_Model_Documentation.docx \
        --toc --toc-depth=3
  LaTeX math ($...$ / $$...$$) is converted to native, editable Word equations.
  Sections marked "[To be completed]" are intentional manual fill-in points.
-->

# 1. Table of Contents

*The table of contents is generated automatically by the document
converter (Pandoc `--toc`) and appears here in the Word version. It is
kept in sync with the numbered section headings below.*

---

# 2. Executive Summary

This document describes the **Fed Funds Fixed–Float Swap Pricer**, a daily
mark-to-market (MTM) valuation model for a portfolio of approximately thirty
USD interest rate swaps in which the firm pays or receives a fixed coupon
against a floating leg referencing the Effective Federal Funds Rate (EFFR),
compounded daily in arrears.

The model produces, for each trade and for each valuation date, the swap's
**clean value, accrued interest, dirty value (net present value, "NPV"),** and
**DV01** (the sensitivity of value to a one-basis-point parallel shift in
interest rates), together with full supporting cash-flow detail. Valuation uses
a **dual-curve** framework: a SOFR Overnight Index Swap (OIS) zero curve is used
for discounting, while a separate Fed Funds zero curve is used to project future
floating-rate fixings. Where a swap is designated as a hedge of a fixed-rate
debt instrument, the model also values that underlying debt in-process and
reports its mark-to-market.

The model's outputs feed two production deliverables — the **IRS Valuation** and
**IRS Netting** feeds — in the precise column format required by the downstream
accounting and reporting process. Modeling conventions (day counts, business-day
adjustments, schedule generation, compounding, and accrual) are configured
per-leg to mirror Bloomberg SWPM, and valuation results reconcile to Bloomberg
and to Chatham Financial benchmarks.

The model is implemented in Python and is designed for daily production use, with
a full audit trail (run manifest, input hashing, and per-trade error capture) and
a regression ("golden-master") test harness to detect unintended changes in
valuation behavior.

---

# 3. Introduction

## 3.1 Purpose

The model exists to produce a daily, defensible mark-to-market valuation of the
firm's portfolio of USD fixed-versus-floating interest rate swaps, for accounting
and risk-reporting purposes. It replaces and consolidates manual or
spreadsheet-based valuation steps with a single, reproducible, version-controlled
calculation engine.

## 3.2 Scope

The model covers:

- USD single-currency fixed-vs-float interest rate swaps.
- A **floating leg** referencing EFFR (overnight Fed Funds), with daily fixings
  compounded in arrears over each accrual period.
- A **fixed leg** with per-trade payment frequency and day-count convention.
- **Dual-curve valuation:** SOFR OIS discounting with Fed Funds projection.
- Per-trade computation of clean / accrued / dirty value, DV01, par rate, and
  per-leg present values.
- In-process valuation of hedged fixed-rate **debt** for trades flagged as long
  hedges, used to report Hedged Debt MTM.
- Production output in the **IRS Valuation** and **IRS Netting** feed formats,
  plus optional debug and reconciliation artifacts.

The model does **not** cover: non-USD or cross-currency swaps; basis swaps;
optionality (caps, floors, swaptions); credit valuation adjustments (CVA/DVA/FVA);
or curve construction/bootstrapping (zero curves are supplied as inputs, not
solved by this model).

## 3.3 Intended Use and Users

The model is intended for daily production valuation runs and for ad-hoc
reconciliation and analysis. Primary users are the valuation, accounting, and
risk functions that consume the production feeds and the supporting cash-flow
detail.

---

# 4. Model Theory

## 4.1 Model Output

For each trade and valuation date $t_v$, the model computes the following primary
outputs:

| Output | Symbol | Meaning |
|---|---|---|
| **Clean value** | $V_{clean}$ | Mark-to-market value excluding accrued interest. |
| **Accrued interest** | $A$ | Interest accumulated in the current period(s) but not yet paid, netted across legs. |
| **Dirty value / NPV** | $V_{dirty}$ | Present value of all remaining cash flows; the swap's full mark-to-market. |
| **DV01** | $\mathrm{DV01}$ | Change in value for a +1bp parallel shift of the rate environment. |

These satisfy the identity, exactly, at every valuation date:

$$V_{dirty} = V_{clean} + A.$$

A positive dirty value denotes a net asset (the firm is owed value); a negative
dirty value denotes a net liability.

The model also reports the following secondary/analytical outputs:

- **$PV_{fixed}$, $PV_{floating}$** — the present value of each leg individually,
  before netting.
- **Par rate** — the fixed rate that would set the swap's NPV to zero under
  current market conditions.
- **Rate difference (bp)** — the contract fixed rate less the par rate, in basis
  points.
- **Hedged Debt MTM** — for hedge trades, the mark-to-market of the underlying
  debt (see Section 4.2.6).

The production outputs are delivered as two CSV feeds (IRS Valuation, 49 columns;
IRS Netting, 21 columns), whose complete field-by-field derivation is documented
in the accompanying attachments *IRS_Valuation_Output_Map.xlsx* and
*IRS_Netting_Output_Map.xlsx*.

Each feed filename and its header carry a 5-digit **submission version**
(e.g. `IRS_Valuation_<val_date>-00001.csv`). The version is a sequence number
per as-of date and data source: the model auto-increments it past any prior run
for the same valuation date (so re-issuing a feed for an as-of date yields
`00002`, `00003`, …), and it can be set explicitly when a specific submission
number is required. The same stamp labels the run's output folder, so every
artifact from a run is traceable to its submission version.

## 4.2 Model Methodology

### 4.2.1 Valuation Framework

Valuation is performed under a **dual-curve** framework. Future cash flows are
discounted on the **SOFR OIS** zero curve, while floating-rate fixings are
projected from a separate **Fed Funds** zero curve. Each curve is supplied as a
set of continuously-compounded ACT/360 zero rates at standard tenor pillars;
discount factors at intermediate dates are obtained by **log-linear
interpolation of discount factors on a calendar-day axis**, applied identically
to both curves.

Let $DF_{S}(\cdot)$ denote a SOFR discount factor and $DF_{F}(\cdot)$ a Fed Funds
discount factor.

### 4.2.2 Fixed Leg

For each fixed-leg accrual period $k$ with day-count fraction $\tau_k$ (computed
under the leg's day-count convention), notional $N$, and fixed rate $R_{fix}$,
the coupon is

$$C_k = N \cdot R_{fix} \cdot \tau_k,$$

and the present value of the fixed leg, summed over all periods whose payment
date $p_k$ falls after the valuation date, is

$$PV_{fixed} = \sum_{k:\, p_k > t_v} C_k \cdot DF_{S}(p_k).$$

### 4.2.3 Floating Leg: OIS Compounding

The floating leg accrues by compounding the overnight Fed Funds rate daily over
each accrual period $[T_s, T_e]$ (compounding in arrears). For each accrual day
$i$ the model applies an overnight rate $r_i$ for $d_i$ calendar days (a Friday
fixing typically carries $d_i = 3$ over the weekend; weekends and holidays are
not skipped but carry the preceding business day's rate). The compounded period
rate is

$$R_{comp} = \left( \prod_{i:\, f_i < t_v} \left(1 + r^{hist}_i \frac{d_i}{360}\right)
\times \prod_{i:\, f_i \ge t_v} \left(1 + r^{fwd}_i \frac{d_i}{360}\right) - 1 \right)
\cdot \frac{360}{D},$$

where:

- $f_i$ is the fixing date for accrual day $i$, and $t_v$ the valuation date;
- $r^{hist}_i$ is the realized EFFR fixing (from the historical fixings file) for
  dates before $t_v$;
- $r^{fwd}_i$ is the curve-implied simple ACT/360 forward rate for dates on or
  after $t_v$,
  $$r^{fwd}_i = \left( \frac{DF_{F}(f_i)}{DF_{F}(f_{i+1})} - 1 \right) \cdot \frac{360}{d_i};$$
- $D = T_e - T_s$ is the total number of calendar days in the period.

The product is always evaluated day-by-day (no endpoint discount-factor
shortcut), so historical and projected sub-periods are treated consistently. The
period floating coupon is $N \cdot (R_{comp} + s) \cdot \tau$ where $s$ is the
optional floating spread, and the leg PV discounts each period coupon on the SOFR
curve at its payment date. A **lockout** feature, if specified, freezes the last
$L$ applied rates at the value of the $(L+1)$-th-to-last fixing.

### 4.2.4 Swap Value, Accrued, and Clean

The dirty value is the netted present value of the two legs, signed by the
trade's pay/receive direction:

$$V_{dirty} =
\begin{cases}
PV_{floating} - PV_{fixed}, & \text{if the firm pays fixed},\\[4pt]
PV_{fixed} - PV_{floating}, & \text{if the firm receives fixed}.
\end{cases}$$

Accrued interest $A$ is the netted sum of each leg's accrual from the current
period start through the valuation date. The model uses an **inclusive**
day-count for accrual — both the accrual start and the valuation date are
counted — so that compounding/day-count runs to $\min(t_v, T_e)$ inclusive. This
deviates intentionally from Bloomberg SWPM's end-exclusive convention (a window
is one day longer here) and is the convention that reconciles to Chatham
Financial. The clean value follows from the identity $V_{clean} = V_{dirty} - A$.

### 4.2.5 DV01

DV01 is computed by **full revaluation (bump-and-reprice)**, not a closed-form
sensitivity. A single +1bp parallel shift ($\Delta = 10^{-4}$) is applied
simultaneously to **both** the SOFR discount curve and the Fed Funds projection
curve, and the swap is repriced:

$$\mathrm{DV01} = V_{dirty}^{\,base} - V_{dirty}^{\,bumped(+1\text{bp})}.$$

A **positive DV01 means the position loses value when rates rise**. Realized
historical fixings are held fixed across the bump — only projected future rates
and discount factors move. Matured trades carry $\mathrm{DV01} = 0$.

### 4.2.6 Par Rate and Hedged Debt

The **par rate** is the fixed rate $R^{*}$ that solves $V_{dirty}(R^{*}) = 0$
under current market data; the reported rate difference is
$(R_{fix} - R^{*})$ expressed in basis points.

For trades designated as a **long hedge (LH)**, the model values the hedged
fixed-rate **debt** in-process using the same fixed-leg cash-flow model
(principal exchanged at maturity), discounted on the **Fed Funds curve plus a
credit/discount spread** (`debt_discount_spread`), and signed from the obligor's
perspective (so the debt value is a liability). The reported **Hedged Debt MTM**
is the debt's clean value plus its outstanding notional. For a **short hedge
(SC)**, the Hedged Debt MTM is the negative of the swap's clean value.

## 4.3 Rationale for Key Modeling Choices

| Choice | Decision | Rationale |
|---|---|---|
| **Discount vs. projection curve** | SOFR discounts; Fed Funds projects (no separate basis curve). | Reflects the post-LIBOR collateral-discounting standard while preserving the Fed Funds index economics of the floating leg; avoids over-parameterization where no basis is observed. |
| **Curve interpolation** | Log-linear on discount factors, calendar-day axis, identical for both curves. | Produces smooth, positive, arbitrage-consistent discount factors between pillars; applying one rule to both curves keeps discounting and projection mutually consistent. |
| **OIS compounding via daily product** | Every period is compounded day-by-day from individual fixings/forwards; no endpoint-DF shortcut. | Treats historical and projected sub-periods identically and matches the contractual daily-compounding mechanism exactly, including weekend/holiday day-weighting and lockout. |
| **Missing historical fixing** | Hard per-trade failure (trade recorded as an error; portfolio run continues). | Silent fallbacks (carry-forward, substitution, period-skip) can hide real gaps and produce plausible-looking but wrong values; a visible error is safer than a wrong number. Any softer policy must be an explicit opt-in. |
| **Inclusive accrual day-count** | Both accrual start and valuation date counted (one day longer than Bloomberg SWPM). | Chosen to reconcile to Chatham Financial, the governing benchmark for accrued interest; the deviation from Bloomberg is documented and intentional. |
| **DV01 by full revaluation** | +1bp parallel dual-curve bump-and-reprice (forward difference). | Robust and convention-agnostic; for linear OIS swaps the one-sided bias at 1bp is negligible, and the method needs no separate analytic sensitivity to maintain. |
| **Per-leg, Bloomberg-matched conventions** | All conventions (roll, adjust, calendars, day count, frequency, delay) configured per leg with Bloomberg SWPM vocabulary and defaults. | Lets each trade reproduce its Bloomberg/confirmation terms exactly; omitting optional fields reproduces standard OIS conventions. |
| **In-process hedged-debt valuation** | LH debt valued from inline trade fields each run rather than from an external feed. | Keeps debt marks synchronized with the swap valuation and removes dependence on a fragile external file hand-off. |

## 4.4 Hedge Effectiveness Testing

*[To be completed manually.]*

---

# 5. Model Data

*Key data sources are listed below as headings. Detailed descriptions to be
completed manually.*

## 5.1 Market Curve Data

Daily vendor export (`market_environment_YYYY-MM-DD.csv`) filtered to USD SOFR
and Fed Funds overnight zero-rate pillars; alternative dated-pillar and
discount-factor input formats are also supported.

*[Detail to be completed manually.]*

## 5.2 Historical Fixings Data

Daily published EFFR (Fed Funds overnight) fixings
(`fixing_cail_USD-FEDFUNDS-ON.csv`), one row per business day.

*[Detail to be completed manually.]*

## 5.3 Trade Definition Data

Per-trade economic terms, per-leg conventions, production reference fields, and
the hedged-debt block (YAML per trade or multi-trade CSV).

*[Detail to be completed manually.]*

## 5.4 Reference and Lookup Data

Entity reference report (entity code → Default RC, for CCID construction) and the
netting database (netting-group rules and entity information).

*[Detail to be completed manually.]*

---

# 6. Implementation Approach

## 6.1 Language and Libraries

The model is implemented in **Python (≥ 3.10)**. Numerical work uses **NumPy** and
**pandas**; market and trade inputs are read from CSV/YAML (**PyYAML**); outputs
are written to Excel (**openpyxl**) and **Parquet** (**pyarrow**). Development
tooling includes **pytest** (tests), **ruff** (linting), and **mypy** (type
checking). The package is installable (`pip install -e .`) with a clean
`src`-layout and no heavyweight quant-library dependency.

## 6.2 Architecture and Design Patterns

The engine is organized around small, composable objects: `ZeroCurve`,
`FixingHistory`, per-leg classes (`FixedLeg`, `OISFloatingLeg`), a `Swap`, a
`MarketData` snapshot, and a `SwapPricer` that produces a `SwapValuation` result
record. Three concerns are isolated behind **pluggable strategy interfaces** so
that new conventions or input sources are additions rather than edits to the
pricer:

- **`RateQuoting`** — rate ↔ discount-factor conversion (continuous/simple,
  ACT/360 or ACT/365).
- **`DayCount`** — year-fraction conventions (ACT/360, ACT/365F, 30/360, 30E/360,
  ACT/ACT-ISDA).
- **`*Loader`** — input abstraction for curves, fixings, and trades.

## 6.3 Convention Engine and Schedule Generation

Conventions are modeled **per leg** using Bloomberg SWPM vocabulary
(business-day adjustment, effective/payment-date adjustment, roll convention with
end-of-month rule, accrual "adjust" mode, calculation/reset/payment calendars,
payment delay, reset lag, lockout). A central `generate_schedule` routine
produces accrual periods (forward/backward generation, EOM snapping, stub
placement), storing both adjusted and unadjusted boundaries so the day-count can
use whichever the leg's settings require. A two-tier validation layer accepts any
input, raises hard errors on impossible combinations, and records soft warnings
(combinations Bloomberg would gray out) in the run manifest.

## 6.4 Loaders and Input Abstraction

Curves, fixings, and trades are each loaded through an abstract loader interface
with concrete implementations selected at runtime (e.g. vendor-export curves vs.
dated-pillar vs. discount-factor inputs; YAML vs. CSV trades). All curve loaders
handle the non-business month-end edge case by sourcing pillar values from the
previous business day's file while keeping the curve anchored at the valuation
date.

## 6.5 Output Writers

Production feeds are written by dedicated writers: `io_prod` (49-column IRS
Valuation CSV) and `io_prod_netting` (21-column IRS Netting CSV), matching the
KPMG feed specifications exactly. Each run is placed in a self-contained,
versioned output folder (`valdate_<date>_rundate_<date>[ BBG]_ver_<NNNNN>`); the
runner derives the submission version by scanning for prior runs of the same
as-of date and data source and incrementing, or honors an explicit override, and
threads that single stamp into the folder name, the feed filenames, and the feed
header rows. Optional debug artifacts — a portfolio Excel workbook, per-trade
detail and debug workbooks, a hedged-debt summary, and Parquet dumps — are
produced under explicit flags (`--debug-loan`, `--debug-full`) and are off by
default.

## 6.6 Batch Execution

A batch runner prices multiple valuation dates in parallel using a process pool;
each date is priced in an isolated worker that rebuilds its own loaders, writes
its own self-contained output folder, and reports a status (`ok` / `partial` /
`error` / `skipped`). A batch-level log and JSON summary are written at the output
root.

## 6.7 Reproducibility, Audit, and Testing Harness

Every run emits a **manifest** recording a run UUID, valuation and run dates, the
git commit hash, SHA-256 hashes of all input files, per-trade timings, and any
warnings or errors — a complete audit trail of inputs and outcomes. Per-trade
errors are captured (the run ends `partial`) rather than aborting the whole
portfolio. A **golden-master regression** test pins valuation output against a
baseline so that any change in numerical behavior is surfaced explicitly.

---

# 7. Model Testing

*[To be completed manually. Subsection scaffolding below.]*

## 7.1 Curve Interpolation

*[To be completed manually.]*

## 7.2 Calendar Generation

*Convention/adjustment settings, calendar-generation settings, schedule roll/EOM
behavior, and related tests.*

*[To be completed manually.]*

## 7.3 Valuation Compared Against Benchmarks

*Reconciliation to Bloomberg SWPM and Chatham Financial.*

*[To be completed manually.]*

---

# 8. Assumptions and Limitations

## 8.1 Key Assumptions

- **Dual-curve, no basis:** SOFR discounts and Fed Funds projects, with no
  separately calibrated SOFR/Fed Funds basis curve.
- **Supplied curves:** zero curves are taken as model inputs; curve construction
  / bootstrapping is out of scope.
- **Collateralization:** trades are treated as fully collateralized for
  discounting purposes (no CVA/DVA/FVA).
- **Curve quoting:** input pillar rates are continuously-compounded ACT/360 zero
  rates; discount factors interpolate log-linearly on a calendar-day axis.
- **Floating reset:** the floating leg fixes in arrears on EFFR; weekends and
  holidays carry the preceding business day's overnight rate.
- **Inclusive accrual:** accrued interest uses an inclusive day-count that
  reconciles to Chatham Financial rather than Bloomberg's end-exclusive count.
- **USD-only book:** all trades and reporting are in USD.
- **Hedged debt:** for LH trades, the debt's maturity equals the swap's maturity
  and its valuation coupon is the debt coupon net of the floating spread,
  discounted on Fed Funds plus a credit/discount spread.

## 8.2 Key Limitations

- **Linear products only:** no optionality (caps/floors/swaptions), no CVA/DVA/FVA,
  and no cross-currency or basis swaps.
- **Parallel DV01 only:** rate sensitivity is reported as a single +1bp parallel
  dual-curve bump; no key-rate/bucketed sensitivities or cross-gamma are produced.
- **One-sided bump:** DV01 uses a forward difference; the bias is negligible at
  1bp for linear swaps but is not a central difference.
- **Hard dependency on complete fixings:** a missing historical EFFR fixing fails
  the affected trade rather than estimating a substitute.
- **Termination/reset simplifications:** the maturity date is rolled under the
  leg's business-day-adjustment rule (no separate termination-date adjustment),
  and the floating reset uses a lookback lag only (no observation-shift variant).
- **No curve calibration / market validation** of supplied inputs beyond format
  and required-field checks.

---

# 9. Governance, Policies, and Controls

*[To be completed.]*

---

# 10. Deployment of the Model

*[To be completed.]*

---

# 11. Ongoing Monitoring Plan

*[To be completed.]*
