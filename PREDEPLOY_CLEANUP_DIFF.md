# Pre-Deploy Cleanup — Diff Log

> Branch: `predeploy_cleanup`
> Side note for future rebasing. Not final — we'll deal with it later.

This branch = `main` + the curated strip recorded below. When advancing onto a
newer `main`, `git rebase main` replays these deletions automatically; this file
is the canonical record of **what** the strip removes so future rebases are easy.

After rebasing, do an **incremental pass**: delete any *new* dev artifacts the
feature branch added that match the categories below, and refresh the content
files (`USER_MANUAL.md` / `README.md`) for any new outputs.

Generated from:

```
git diff --name-status main predeploy_cleanup
```

## Deleted — reference workbooks (dev-only)
- `CCID.xlsx`
- `CCID_Netting.xlsx`
- `Convention_Reference.xlsx`
- `Output_Format Netting.xlsx`
- `Output_Format.xlsx`

## Deleted — dev/design docs
- `DEV_ARTIFACTS.md`
- `OPEN_QUESTIONS.md`
- `deployment_writeup.md`
- `diagrams.md`
- `questions.md`
- `schema.md`

## Deleted — `model_documentation/` (source artifacts, not shipped)
- `model_documentation/IRS_Netting_Output_Map.xlsx`
- `model_documentation/IRS_Valuation_Output_Map.xlsx`
- `model_documentation/Swap_Pricer_Model_Documentation.docx`
- `model_documentation/Swap_Pricer_Model_Documentation.md`
- `model_documentation/generate_output_maps.py`

## Deleted — dev scripts & one-off diagnostics
- `build_convention_ref.py`
- `scripts/diagnose_ccid.py`
- `scripts/diagnose_fixings.py`
- `scripts/discount_factor_test.py`
- `scripts/generate_synthetic_curve.py`
- `scripts/generate_synthetic_fixings.py`

## Deleted — dev-only tests
- `tests/test_golden_master.py`

## Content changes (NOT mechanical deletions — re-apply/refresh by hand)
- `README.md` — edited (M)
- `USER_MANUAL.md` — added (A); update for any new outputs
