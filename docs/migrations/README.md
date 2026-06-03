# Data migrations

Index of one-shot / re-runnable data migrations for the local & UAT `icb` database.
(Schema migrations live in `backend/alembic/` — this folder is for **data** loads.)

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

### ⚠️ Expected after v4.20: the MES dashboards are empty (until v4.21)

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
