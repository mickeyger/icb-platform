# ADR 0015 — Chassis-record lifecycle (VIN-anchored, multi-cycle, local-FS photos)

- **Status:** Accepted
- **Date:** 2026-06-07
- **Work order:** v4.28 (Phase 3 §4.2 — Chassis module; closes Phase 2C Flag C + Flag E, carried since v4.16)

## Context

The legacy source for chassis is **`Book1 TRUCK REGISTER 2026.xlsx`** — a wide, single-row-header
sheet (~1037 rows × 112 cols). WO v4.22 loaded it **verbatim** into `icb_mes.chassis_register`
(321 rows, 17 hoisted columns + the full row as `raw_row_json`) to get the data in-system without
modelling it. That flat shape is the system of record's shape, and it has hard limits:

- **One row = one chassis, but a returning chassis is modelled as positional column pairs.** A
  chassis that comes back for a second body / repair gets `date_received_2 / vcl_2 / date_left_2 /
  dcl_2` columns — **capped at two visits**. A third visit has nowhere to go.
- **VIN (`vehicle_id_no`) is unreliable as stored:** sometimes blank (67 rows), sometimes duplicated
  across rows (the same chassis entered twice), sometimes the row is `CANCELLED` (3 rows).
- **No photos, no checklists, no relational queries.** The workshop's book-in / dispatch inspection
  happens on paper (`JOB INSPECTION & SIGN OFF SHEETS`); nothing links to the register.

v4.28 replaces the register **as the operational model** (the flat table is retained for rollback)
with a normalized, VIN-anchored lifecycle that supports an open-ended number of workshop visits,
per-event checklists, and photos.

## Decision (WO v4.28 §0, BA-locked)

### Three tables — asset / events / photos
- **`icb_mes.chassis_records`** — the physical asset. **`vin` is `UNIQUE`** and is the identity
  anchor. (The workbook's `job_number` changes per visit; the VIN does not — so the VIN, not the job
  number, is the stable key across a chassis's life.) Carries the descriptive fields (customer, make,
  model, …), a `status` (`received` → `in_workshop` → `dispatched`), and a **`source`** tag
  (`register` | `manual` | `mock`) for provenance + idempotent re-seeding.
- **`icb_mes.chassis_lifecycle_events`** — one row per inspection event, FK → `chassis_records`
  (`ON DELETE CASCADE`). `(chassis_record_id, cycle_number, event_type)` is **`UNIQUE`**.
- **`icb_mes.chassis_photos`** — FK → `chassis_lifecycle_events` (`ON DELETE CASCADE`); stores a
  relative filesystem path + metadata (original filename, content-type, size, uploader).

### A "cycle" = one workshop visit; VCL opens it, DCL closes it
- **`event_type` is a short string `'VCL'` / `'DCL'`** (NOT a DB enum) — `VCL` = *vehicle check-in /
  book-in* (`date_received`), `DCL` = *dispatch / check-out* (`date_left`).
- **VCL opens a fresh cycle:** `cycle_number = max(existing cycles) + 1`. **DCL closes the highest
  open cycle** (a cycle with a VCL but no DCL); if none is open, DCL is a **422** ("capture a VCL
  first"). A duplicate VCL/DCL in the same cycle is a **409** (the `UNIQUE` constraint, surfaced as a
  friendly error). Capturing a VCL sets status `in_workshop`; a DCL sets `dispatched`.
- This **replaces the workbook's fixed `_1` / `_2` columns with an open-ended cycle count** — a
  chassis can return any number of times, each visit a new cycle, with the full earlier history
  preserved.

### Checklists are DATA, served from the API (Workshop-refine placeholder)
- The VCL (9-item) and DCL (7-item) checklists ship as **`CHASSIS_CHECKLIST_TEMPLATES`** served from
  `GET /api/chassis-records/checklists` and rendered by the form from that response — **not
  hard-coded in the UI.** They are an explicit **Workshop-refine placeholder** (the real inspection
  sheets weren't available at build time). Each captured event stores its answers in
  `checklist_json` (**JSONB**). A future micro-WO can move the templates to an admin-owned table
  **without touching code** — the UI already reads them as data.

### Photos behind a single filesystem seam
- Photos are written to the **local filesystem** under
  `backend/uploads/chassis/{record}/{cycle}/{event_type}/{photo_id}-{filename}` via
  **`app/services/file_store.py`** — the **only** module that touches the filesystem. It carries a
  `TODO(§5.3 / v4.31)` marker: the swap to a file-store abstraction (S3 / MinIO) replaces the two
  functions there and nothing else. `backend/uploads/` is git-ignored.

### Job ↔ chassis link via an in-migration FK
- `production_jobs.chassis_record_id` (nullable) links a job to its chassis. It is declared as a
  **plain `Integer` column on the model + the FK created in migration 0012 (guarded by name),
  `ON DELETE RESTRICT`** — NOT a `ForeignKey` on the model. This reuses the convention established in
  v4.27 (pj ↔ generated_boms) and v4.23 (demand → OITM): defining cross-cutting FKs in the migration
  keeps `Base.metadata.create_all` order-independent (no import/creation cycle) and keeps the
  idempotent inspector-guarded migration round-trip (upgrade→downgrade→upgrade) green. `RESTRICT`
  means a chassis with jobs attached can't be deleted out from under them. **No chassis↔job linking
  UI ships in v4.28** (§0) — the column + FK are the data foundation.

### Translation, not migration of meaning
- A one-shot **idempotent** script, `backend/scripts/translate_chassis_register.py`
  (`delete source='register'` then reload), reads `chassis_register` and:
  **skips null-VIN (67) + `CANCELLED` (3)**, **merges duplicate VINs** (a repeated VIN appends a
  cycle rather than creating a second record), and **explodes each `_1` / `_2` column pair** into
  VCL/DCL events. Result: **321 register rows → 250 chassis_records / 492 lifecycle events.** The
  legacy `chassis_register` table and the `chassis_data_json` blob are **kept for rollback** (not
  dropped in v4.28).

## Consequences

- **Open-ended visits** (vs the workbook's 2-cycle cap); **photos + checklists** now live in-system;
  **relational queries** (by VIN / customer / status, cycle counts) replace flat-row scanning.
- **Flag C (relational chassis model) and Flag E (chassis-ETA gate + un-tick) are CLOSED** — both
  carried since v4.16. The planning chassis-ETA gate logic (`eta_gate_reason` in `services/planning`,
  enforced in `schedule` / `move`, bypassed once `chassis_received_at` is set) is **unchanged**;
  v4.28 only adds the **un-tick endpoint** (`DELETE /api/production-jobs/{id}/chassis-received`,
  `production.chassis_received`) that clears the receipt and thereby **re-enables** the gate after a
  mistaken tick.
- **Permissions** (migration 0013, DB-backed): `chassis.create` / `chassis.update` / `chassis.vcl` /
  `chassis.dcl`. Granted: **planner → all four**; **production → update / vcl / dcl** (mapping the
  Workshop role to `production` and the PM role to `planner`). Admin is the code-level wildcard.
- **CI / dev seeding:** the real workbook isn't in CI, so `seed_from_mockup` seeds **4 synthetic
  `source='mock'` chassis** (`seed_v4_28_chassis_mock`, table-guarded) covering every UI shape
  (closed cycle / open cycle / two-cycle history / no-events) so the chassis list + the Playwright
  chassis journey have data. `source` tagging keeps the mock, register, and manual sets independently
  idempotent.
- **Status is derived from the last event, not free-typed** — the service sets it on capture, so it
  can't drift from the event history.

## Reused pattern — in-migration FKs for cross-schema / create_all-cycle targets (WO §7.7)

This ADR is also the recorded home for the **cross-schema-FK + independent-ETL** pattern that has
recurred across v4.23 / v4.27 / v4.28 (it never got its own ADR):

- **The rule:** a foreign key is declared as a **plain `Integer` column on the model + a named FK
  created in the migration** (guarded by name in the idempotent block) — *instead of* a model-level
  `ForeignKey` — whenever the FK would either (a) create a `create_all` ordering cycle
  (pj ↔ generated_boms, v4.27) or (b) target an autogenerate-excluded schema
  (demand → `icb_sap.OITM`, v4.23). `env.py` name-guards these (`_CROSS_SCHEMA_FK_NAMES`) so
  `alembic check` doesn't try to reconcile them.
- **The v4.27 OITM-UPSERT corollary:** ADR 0013 **deferred** the `demand_lines → icb_sap.OITM` FK
  because both sides reloaded via independent **TRUNCATE+RELOAD** ETLs — truncating OITM
  cascade-nuked demand. v4.27 changed the inventory loader to **UPSERT + soft-delete** (rows are
  updated/inserted in place and flagged inactive, never truncated). With OITM rows no longer
  disappearing under demand, the deferred FK becomes **safe to add and `VALIDATE`** in a follow-on
  micro-WO, provided the loaders stay coordinated (OITM populated before demand — empirically proven
  by running the loader twice with demand unchanged in v4.27). The FK-as-app-layer-check stays the
  interim guard.

## Alternatives rejected

- **Keep the flat `chassis_register` as the model** — caps visits at two, can't hold photos /
  checklists, and forces positional-column parsing on every read. Retained only for rollback.
- **`event_type` as a DB enum** — adding a future event kind (e.g. an interim inspection) would need
  a migration; a short validated string is extensible without one.
- **Cycle as a separate `chassis_cycles` table** — a cycle has no attributes of its own beyond its
  number; an integer on the event keeps the model two-deep (record → event) instead of three, and
  the open/closed state derives from "VCL without a DCL" rather than a stored flag that can drift.
- **Photos as BYTEA in Postgres** — bloats the DB + backups and couples binary storage to the
  relational store; a filesystem path behind one seam keeps the S3/MinIO swap (§5.3 / v4.31) a
  two-function change.
- **A model-level `ForeignKey` for `production_jobs.chassis_record_id`** — would reintroduce a
  `create_all` ordering dependency; the in-migration named FK keeps creation order-independent and
  the round-trip green (the reused pattern above).
