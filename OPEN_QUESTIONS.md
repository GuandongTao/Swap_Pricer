# Open Questions — IRS Netting Output

Questions parked during the netting-output design discussion that the user
wants to revisit later. Not blockers for the first cut.

## Q2c — Netting IDs with one-sided exposure (DA only or DL only)

**Decision so far:** emit the row anyway, with `Gross DL = 0`, `Netting Amount = 0`,
`Net DA = Gross DA` (or symmetric for DL-only groups).

**Reason to revisit:** confirm this is the desired behavior for KPMG's
downstream consumer. If a netting_id has zero offsetting exposure, is a row
with `Net Amount = 0` meaningful, or noise?

## Q2e — abs-value sign convention on Gross DL / Net DL

**Decision so far:** follow the spec literally — output `Gross DL` and
`Net DL` as positive numbers (absolute value of the liability NPVs).

**Reason to revisit:** the IRS Valuation file emits `DL` as a positive
number too, but some accounting feeds want liabilities as negative. Confirm
KPMG's preference once a sample file is reviewed end-to-end.

## Q3a (note, not a question) — Source of truth for Netting Entity

Three places carry the same legal-entity code (1000 / 1021 / …):
1. `data/entity/Netting_Database.csv` — column "Netting Entity"
2. `data/entity/Entity_Reference_Report.csv` — entity rows
3. Per-trade `oracle_entity_code` in the input CSV

All three are supposed to agree. For the netting output:
- **Source used:** `Netting_Database.csv` column "Netting Entity", keyed by
  the trade's `netting_id`.
- **RC lookup:** `Entity_Reference_Report.csv`, keyed by that netting-entity
  code.

If a future divergence is suspected, cross-check the per-trade
`oracle_entity_code` against the netting-entity-by-netting_id to surface
mismatches.
