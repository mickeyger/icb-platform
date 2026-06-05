# ADR 0005 — MES schema split + move-with-view

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.13 (Phase 2A)

## Context
The MES domain (jobs, work orders, sign-offs, planning, stores) needs its own
tables. The post-acceptance sign-off / planning / chassis fields currently live
on `icb_costings.calculations` (the costing/quote table) but are MES concerns.
They must move without breaking any reader during the transition.

## Decision
- Create 12 tables in a new `icb_mes` schema (one PostgreSQL database, two schemas).
- `icb_mes.production_jobs` is 1:1 with a costing via a cross-schema FK to
  `icb_costings.calculations.id` (NOT NULL, UNIQUE, ON DELETE RESTRICT).
- Move ALL **18** MES-lifecycle columns (the live table had 18, not the 7 the
  spec named) from `calculations` to `production_jobs`, plus a new `accepted_at`.
- A backward-compat view `icb_costings.v_calculation_records_legacy` reconstructs
  the original 32-column shape (14 staying columns from `calculations` + the 18
  moved columns sourced from `production_jobs`), so readers of the old shape keep
  working.
- **Naming correction:** the actual table is `calculations`; the spec's
  `calculation_records` is only the SQLAlchemy class name and does not exist in
  PostgreSQL.

## Consequences
- Migration `0003` creates the tables, copies the data (a no-op on the empty dev
  DB; real at the future prod migration), and creates the view. It does **not**
  drop the columns from `calculations`.
- A follow-up migration (**`0007+`**), after a clean UAT week, drops the 18 columns
  from `calculations`. The view already reads the moved columns from
  `production_jobs`, so it survives that drop unchanged.
  **Removal target: after ≥4 weeks clean UAT (Plan §10 Q-UC-04) — ~2026-07-01.**
  **Renumber:** migration `0004` was taken by the v4.15 Materials/Buying/Stores
  tables (ADR 0009), `0005` by the v4.16 branch-NOT-NULL + permission seed + PR
  sequence (ADR 0010), and `0006` by the v4.21 workbook-jobs migration (nullable
  calculation FK + `source`/carrier columns, ADR 0012), so this column-drop slides
  to the next free revision (`0007+`).
- `CalculationRecord` still declares the 18 columns until that drop migration.
