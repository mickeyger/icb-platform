# ADR 0016 — Chassis-state read-bridge, ack capture on the job surface, and per-role journey testing

- **Status:** Accepted
- **Date:** 2026-06-07
- **Work order:** v4.29 (Phase 3 §4.0 — Upstream Stabilisation Sweep; fixes D1–D6 found in user testing)

## Context

User testing on 7 Jun 2026 found four P0 defects in stages marked LIVE on the process-flow diagram
(Costings → Pre-Job → Planning Ack → Planning Board). §3.0 live reproduction **invalidated the two
leading BA hypotheses** (D1 + D2 were assumed to be a third CSRF/raw-fetch gap — but the SPA has
exactly one `fetch()`, the `lib/api` chokepoint; every mutation already carries the CSRF header). The
real causes were backend logic/data bugs, and one (D3) showed the WO's prescribed fix could not work
as written. This ADR records the load-bearing decisions.

## Decision

### 1. Chassis-state read-bridge — `chassis_records` is the source of truth (D3)

v4.28 (migration 0012) added `production_jobs.chassis_record_id` + the FK to `chassis_records`, but
**never populated it** — §3.0 found it `NULL` for all 182 jobs. The de-facto chassis↔job link was the
business string `chassis_records.job_number == production_jobs.job_number`. The WO's read-bridge
(§0.3) JOINs via the FK, which would have returned `NULL` for every job.

- **Migration 0014 backfills `chassis_record_id`** from the `job_number` match (latest chassis_record
  per job_number when one recurs across cycles) and **indexes the column**
  (`ix_production_jobs_chassis_record_id`) — Postgres does not auto-index a FK's referencing column.
  The backfill is a one-way data repair; downgrade drops only the index.
- **Read precedence (the bridge):** the planning reads compute `chassis_received_signal` as the
  **latest VCL (book-in) event date** for the job's linked chassis_record (authoritative), falling
  back to the legacy `production_jobs.chassis_received_at` column when no VCL exists (transitional,
  back-compat). A `chassis_received_source` of `'vcl' | 'legacy' | null` drives the cell tooltip. A
  **DCL** (dispatch) event is explicitly **not** a receipt signal.
- **`production_jobs.chassis_received_at` is DEPRECATED-as-write** (a DB `COMMENT` + a model comment
  say so). It is retained as a read fallback for legacy rows; new chassis-received state flows through
  the chassis lifecycle event path (VCL), not direct writes to the column.

### 2. Acknowledge captures ETA + chassis data on the job surface, not the legacy calc route (D2)

The Planning ack "Acknowledge receipt" button did nothing. Cause: a **status-source deadlock**. The
v4.19 React flow advances the *production_job* status, but the legacy `POST
/api/calculations/{id}/chassis-eta` endpoint (v4.2) gates on the *calculation* status being
`'planning'`. An ack candidate's calc is still `'accepted'` (only its job is `pre_job_confirmed`), so
step-1 chassis-eta returned **409**, which `handleApiError` re-throws — aborting the two-call ack
before the planning-ack ran. And the guard could never be satisfied: status only becomes `planning`
*after* the ack.

- **`POST /api/production-jobs/{id}/planning-ack` now captures the chassis ETA AND the rich chassis
  data** (VIN / model / dealer / tail-lift / in-house BOM) onto the production job
  (`chassis_data_json`), in one step on the pj surface. The SPA's live ack flow calls only this; the
  legacy calc `/chassis-eta` endpoint runs in **mock mode only** (offline-demo local state). This
  aligns chassis capture with the v4.19 pj-centric lifecycle and removes the status-source mismatch.

### 3. Chassis-ETA gate — presence rule + RETAINED within-week guard (D4, §0.4 revised)

The gate (`services/planning.eta_gate_reason`) was a date-window gate, not the presence gate §0.4
described: a job with neither receipt nor ETA was schedulable (symptom #1), while an ETA beyond the
target week was blocked. §0.4-as-written would have made it presence-only (dropping the within-week
guard). **BA decision (Michael, 7 Jun): keep the within-week guard.** The gate now BLOCKS iff:
`not received AND (no ETA OR ETA after the target week)`; `received` (the D3 signal — VCL event or
legacy column) bypasses it. Verified as a 5-case matrix in `test_v4_29_upstream_fixes.py`. This
**revises §0.4** of the WO from the presence-only rule to presence + within-week.

### 4. Per-role journey testing is the standing pattern from v4.29 onward

D1–D4 shipped because every v4.13–v4.28 journey test was happy-path-as-admin; per-role views and
cross-module data sync were never exercised. The fix is structural, not one-off:

- The demo autologin (`POST /api/mes/autologin`) accepts an optional `username` (honoured only in
  demo mode, behind the existing origin guard), so a single server boot mints **any role per browser
  context**. The journey harness gains `role_session()` (mirroring `admin_session()`) + a seeded
  `role_users` fixture.
- **Every affected flow ships admin + per-role journeys** (Costings retry, Pre-Job ack, Planning
  drag, Chassis link). This becomes the standing rule (Testing Strategy v1.1): a new journey covers
  each role that can reach the surface, not just admin.

## Consequences

- The chassis-received signal is now correct on the board even when the legacy column is empty (the
  common case for VCL-captured chassis). Other modules that *wrote* `chassis_received_at` should move
  to the VCL path; reads are already covered by the precedence rule.
- `accept_calculation` defaults a `NULL` `calc.branch_id` to the active branch / JHB (D1) — a related
  data-quality gap (some A-series MES-native calcs were created without a branch). The upstream
  A-series creation path that leaves `branch_id` NULL is worth a follow-up.
- The legacy calc `/chassis-eta` endpoint is now dead on the live path; a later WO can remove it once
  the offline demo no longer depends on it.
- Bay sort (D5) and the contiguous week range (D6) are backend concerns (`build_board`), not frontend
  — the WO had pointed at the frontend; the fixes landed server-side where the order/range originate.
