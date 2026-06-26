# Intake — Item: Month End Data

> Coding-time reference only. Derived from `frequency and channel.xlsx` +
> `output instructions.xlsx` (tab "Month End Data"). Will not ship.

## Control / registry
| Attr | Value |
|------|-------|
| Item | Month End Data |
| Frequency | **Month End** = last calendar day of month (`is_month_end`) |
| Channel | **Email** → write to `email/` folder parallel to `output/` |
| Envelope | None — raw input-data snapshot, original file formats preserved |
| Field-list (#3) file | none (not a tabular/column output) |

## Deliverables (2 sub-items)

### 1. Used-curve extract
- **Source file**: the `market_environment_<curve_date>.csv` **actually consumed**
  in pricing — i.e. fallback-aware. `curve_date` = `month_end_curve_date(val_date)`
  when the month-end is a weekend/holiday (the preceding business day, normally the
  prior Friday), else `val_date` itself.
- **Filter**: KEEP ONLY rows matching `IR.USD-SOFR-ON.ZERORATE-*.MID` and
  `IR.USD-FEDFUNDS-ON.ZERORATE-*.MID` (the 2 curves the model uses; 96 rows in
  the 2026-03-31 sample). "2 pillars" = these 2 curve families. (Q1 ✓ extract, keep.)
- **Format**: **drop the vendor metadata header block** (`Name/Date/Property…`);
  output only the kept curve rows, otherwise byte-identical row format. (Q2 ✓)
- **Output filename**: same title as the **source file used**, i.e. timestamp of the
  curve actually consumed → `market_environment_<curve_date>.csv` (so a weekend
  month-end yields the prior-Friday-stamped name). (Q3 ✓)

### 2. Fixings input copy
- **Source**: `data/fixings/fixing_cail_USD-FEDFUNDS-ON.csv`.
- **Action**: verbatim copy, no filtering, original format/name.

## Output location
- **Flat** in `email/` (parallel to `output/`), original filenames, no `<val_date>/`
  substructure. (Q4 ✓)

## Status: LOCKED — ready to code.
