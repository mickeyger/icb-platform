# Data migrations

Index of one-shot / re-runnable data migrations for the local & UAT `icb` database.
(Schema migrations live in `backend/alembic/` — this folder is for **data** loads.)

## v4.22 — Real ICB operational sources → icb_mes (Phase 2D-3)

Re-anchors `icb_mes` to the **real Production-Server workbooks**: re-points `demand_lines` to
`01 - MRP 2026.xlsx` (**390** lines, day-block layout with real job numbers in row 3), and adds
`live_daily_count` (**312**, from Live Daily Count's 6 category sheets) + `chassis_register` (**321**,
from Truck Register; 17 hoist cols + full-row `raw_row_json`). Migration **0007** (additive). The
Planning Board gains a **source badge (WB/Q) + an All/Quote-born/Workbook filter**; chassis read API at
**`/api/chassis-register`**.

- **Re-run:** `pwsh backend/scripts/import_workbook.ps1 -Backup` (now multi-source)
- **Load report:** [`v4.22-rescope-load-report.md`](./v4.22-rescope-load-report.md)
- **SAP codes are disjoint (0% match)** vs `sap_item_codes` — reconciled in **v4.23** (`icb_sap.OITM`
  + the `demand_lines.sap_code → OITM.ItemCode` FK, NOT VALID).

## v4.21 — ENTERPRISE PLANNING workbook → icb_mes (Phase 2D-2)

Loads the live operational state from `ENTERPRISE PLANNING - 2026.xlsx` into `icb_mes`
(**186 production jobs, 132 planning slots, 1564 demand lines**) + re-seeds the
Materials/Buying/Stores master data from the mockup. **One-shot** (TRUNCATE + reload).
Migration **0006** lets workbook jobs (which have no costing calculation) exist —
`production_jobs.calculation_record_id` nullable + `source` + carrier columns.

- **Re-run:** `pwsh backend/scripts/import_workbook.ps1 -Backup`
- **Load report:** [`v4.21-workbook-load-report.md`](./v4.21-workbook-load-report.md)
- **Decision record:** [`../adr/0012-workbook-imported-production-jobs.md`](../adr/0012-workbook-imported-production-jobs.md)
- **The MES dashboards are now populated** — the Planning Board shows real ICB jobs.
  Workbook jobs surface on the **Planning Board** (production-jobs-spine), **not** the
  Costings dashboard (calculations-spine — they have no calc). The Stock/Buying
  transactional tables (stock_counts / discrepancies / po_suggestions) stay empty
  (generated in-app).

## v4.20 — faje UAT catalogue → PostgreSQL (Phase 2D-1)

Replaces the mock seed in the `icb_costings` schema with the **real faje UAT catalogue**
(794 materials, 8 984 BOM rows, 2 183 customers, 5 158 SAP item codes, 6 historical
calculations, …) via **pgloader**, run from WSL. Data-only into the existing Phase-1
schema; the Jinja Cost Calculator is verified regression-free against it.

- **Scripts:** `backend/migrations/pgloader/` (5 ordered SQL/load files + 2 parity helpers).
- **Re-run:** `pwsh backend/scripts/migrate_catalogue.ps1 -Backup`
- **Parity report:** [`v4.20-parity-report.md`](./v4.20-parity-report.md) (43/43 tables match).
- **Playbook / rationale:** [`../adr/0011-mysql-to-postgres-catalogue-migration.md`](../adr/0011-mysql-to-postgres-catalogue-migration.md)
  (also the reusable faje **production-cutover** playbook).
- **Rollback:** `pg_restore --clean --if-exists --no-owner` from the pre-load
  `pg_dump -Fc` snapshot (default `~/Documents/icb_db_backups/`).

### ⚠️ Expected after v4.20 — ✅ now RESOLVED by v4.21: the MES dashboards are empty until v4.21

The migration **truncates all `icb_mes` tables** (production jobs, planning slots, stock
counts, discrepancies, PO suggestions, …) so the reloaded calculations don't orphan stale
mock production rows. This is intentional — see Phase 2D-1 §0.3. Until **WO v4.21
(workbook ETL)** repopulates the production domain, expect:

| Area | State after v4.20 |
|---|---|
| Cost Calculator (`/calculator`) | **Fully populated** — real faje catalogue |
| Costings dashboard (calculations list) | **Fully populated** — 6 real UAT quotes |
| Planning Board / production jobs | **Empty** (no accepted-job production rows yet) |
| Stores / Buying / discrepancies | **Empty** |

This is not a bug. The React app still loads and authenticates normally.

### First-boot note

On the app's first boot against the migrated DB, the idempotent `seed()` adds only the
inactive "Light" UI theme (`themes` 3→4). No catalogue, user, or settings data is touched.
