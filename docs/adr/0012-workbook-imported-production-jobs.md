# ADR 0012 — Workbook-imported production jobs (relaxed calc invariant)

- **Status:** Accepted
- **Date:** 2026-06-03
- **Work order:** v4.21 (Phase 2D-2)

## Context

v4.13 modelled `icb_mes.production_jobs` as **1:1 with an accepted costing calculation**:
`calculation_record_id` was `NOT NULL UNIQUE` with a cross-schema FK to
`icb_costings.calculations` (RESTRICT). That encodes the new-system flow: *a quote is
accepted → a production job is created*.

v4.21 imports the **real ICB order book** from the ENTERPRISE PLANNING workbook (186
active jobs). These are live shop-floor jobs keyed by 5-digit ICB job numbers; they
**predate the platform and have no originating costing calculation** in `icb_costings`
(only 6 quote calcs exist there). The 1:1-with-calc invariant cannot hold for them.

A second wrinkle: `production_jobs` carries **no native customer/description/value** — the
list/detail/board reads derive those by joining through the calculation
(`calc → customer`, selling from `result_json`). A job with no calc would render blank.

## Decision (WO v4.21 §0.1, BA-locked)

Migration **0006** relaxes the invariant **additively**:

- `production_jobs.calculation_record_id` → **NULLABLE** (UNIQUE kept; Postgres UNIQUE
  permits multiple NULLs, so many workbook jobs coexist while quote-born jobs still can't
  share a calc). The cross-schema FK is unchanged — NULLs simply bypass it.
- `+ source` (`'quote'` | `'workbook'`, default `'quote'`).
- `+ carrier columns` `customer_name`, `description`, `selling_zar`, populated for workbook
  jobs. Quote-born jobs leave them NULL and keep deriving from the calc join.
- **Read-path** (`services/production_jobs._base_select`, `schemas.to_list_item`/`to_detail`,
  `services/planning._job_ref`) now **LEFT-joins** the calculation and **falls back to the
  carriers** when the calc is absent. The list/detail schemas' `calculation_record_id`
  becomes `Optional[int]`.

Quote-born jobs (the v4.13–v4.19 accept flow) are **behaviourally unchanged** — they still
set `calculation_record_id`, default `source='quote'`, and derive customer/selling from the
calc; the carriers stay NULL.

## Consequences

- `production_jobs` is the **unified spine** for both quote-born and workbook-imported jobs.
- **Where workbook jobs surface:** the **Planning Board** reads `production_jobs` (LEFT-joins
  the calc), so workbook jobs appear there. They do **not** appear in the **Costings
  dashboard**, which is calculations-spine (ADR/v4.19) — a workbook job has no calc to merge
  on. Making the two job-origins visually distinguishable (5-digit job no. + no wizard
  history vs `Q-XXXXX` + full history) is **deferred to v4.22** (BA carry-forward #3).
- **Validation classes differ (BA carry-forward #2):** the v4.20 "replay-delta" check
  (recompute a quote and compare to its stored total, ADR 0011) **does not apply** to
  workbook jobs — they have no calculation to replay. Phase 2E (v4.22) must treat
  workbook-imported and quote-born jobs as separate validation classes.
- The deferred `calculations` column-drop slides `0006+ → 0007+` (ADR 0005 updated).
- The cross-schema FK list (`CROSS_SCHEMA_FKS`) is unchanged; the FK still enforces RI for
  non-NULL `calculation_record_id`.
- A `NOT NULL` rollback (downgrade) requires clearing workbook jobs first.

## Alternatives rejected

- **Synthetic stub calculations** per workbook job — pollutes the costing spine with
  non-quote rows.
- **A separate `icb_mes.orderbook_jobs` table** — fragments the model; every MES screen and
  the v4.14 API read `production_jobs` and would need rewiring.
- **A `customer_id` cross-schema FK** instead of a denormalized `customer_name` — adds a
  third cross-schema FK, and only 44% of workbook customer names match the migrated customer
  master (name-format drift), so a hard link would reject most rows. Denormalized text
  carriers display correctly regardless; a resolved link can come later.
