# ADR 0009 — Materials reference tables (MES catalogue / stock / suppliers)

- **Status:** Accepted
- **Date:** 2026-06-02
- **Work order:** v4.15 (Phase 2B-2)

## Context
The Materials / Buying / Stores screens need a materials **catalogue**
(description, supplier, lead_days, last_price, abc_class, dept), current **stock
positions**, and a **supplier** master. WO v4.15 §0.1 locked option (A): add the
reference tables to `icb_mes` and read the catalogue from `icb_costings.materials`
by `sap_code`, with the caveat to reuse an existing `icb_costings.suppliers` if one
exists.

Discovery against the (live-equivalent) dev DB reshaped (A):
1. **No `icb_costings.suppliers` exists** — checked `information_schema` across all
   schemas. So `icb_mes.suppliers` is the system of record.
2. **`icb_costings.materials` cannot drive the screens** — it is empty in dev
   (populated only by the Excel import), it lacks `abc_class` / `dept` / `lead_days`
   (which the dashboard filters + urgency math require), and the mockup's 12 demo
   `sap_code`s do not match the real 200+ trailer codes. So the catalogue must be
   seeded into `icb_mes`, not read from costing.

## Decision
- Migration `0004` adds three **additive** `icb_mes` tables, all seeded from
  `icb_materials_data.json`: **`mes_materials`** (catalogue master), **`stock_positions`**
  (current SAP stock, one row per sap_code), **`suppliers`** (master).
- **Table is named `mes_materials`, NOT `materials`.** The connection `search_path`
  is `icb_mes, icb_costings, public`; a bare `icb_mes.materials` would SHADOW the
  schema-less costing `Material` model (which emits unqualified `materials`) and
  break `/calculator`. The ORM class is `MesMaterial` (which also avoids a
  class-name clash with costing's `Material` in the shared declarative registry).
- **Catalogue is self-contained in `icb_mes`.** `GET /api/mes-materials` reads
  `mes_materials ⋈ stock_positions`, and keeps the §4.5 cross-schema join as an
  **optional LEFT JOIN** to `icb_costings.materials ON sap_code` for future
  reconciliation — surfaced as `costing_price_per_unit` (null until codes align).
- **API prefix is `/api/mes-materials`, NOT `/api/materials`.** The costing
  materials admin already owns `/api/materials` (+ `/api/materials/{mat_id}` and
  bulk-price routes); reusing it would shadow the MES routes. The other five
  resources keep their WO-named prefixes.
- **`po_suggestions.jobs_impacted`** (Q3) is a real JSONB column, seeded from the
  mockup (not derived) — the PO Suggestion Queue renders it directly.
- **`GET /api/suppliers`** (Q4) is a 12th endpoint — the table exists and the PO
  screen needs the supplier list + contact person.
- **raise-PR** (Q2 / §0.4) keeps the lock: single-id, `pr_number = f"PR-{seq}"`,
  SAP mocked. (The mockup's bulk + numeric SAP PR number reconciles in v4.17.)

## Consequences
- One table beyond §0.1's "stock_positions + suppliers" (the dedicated
  `mes_materials`), justified by the discovery above. ADR 0005's deferred
  column-drop renumbers to `0005+` (migration `0004` is now taken).
- The cross-schema join pattern (ADR 0006/0008) is preserved but **demoted to
  enrichment**: the MES screens no longer depend on the costing catalogue.
- Two materials surfaces coexist by design — costing `/api/materials` (admin) and
  MES `/api/mes-materials` (catalogue + stock) — fully independent.
