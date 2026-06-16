# ADR 0025 — Body↔Chassis Attached workflow + demo-readiness (v4.35)

- Status: Accepted
- Date: 2026-06-16
- Work Order: v4.35 — Demo Readiness + Body↔Chassis Attached Workflow (Burt demo 22-23 Jun)
- Builds on: ADR 0018 (event-derived state), ADR 0019 (uniform worksheet contract), ADR 0023 (integrity
  invariants + Tier-2 guards), ADR 0024 (chokepoint + pattern-reuse).

## Context

The MES had shipped 30+ WOs but Burt's end-user view stopped at costing → pre-job → planning. The
body↔chassis joining step — where the GRP panels meet the chassis in an assembly bay and become one
unit — was the missing keystone: without it the MES reads as paperwork automation; with it, it
represents the actual factory. Three deep-dive findings shaped the spec: Simeon's narrative stops before
the mate-up (no authoritative factory term → neutral `body_attached`); his ENTERPRISE PLANNING workbook
already encodes the state machine (CHASSIS RECEIVED → VACUUM → ASSY → ASSY COMP); and the Production
Dashboard was 70% wired but had zero representation of the join (`grep marriage|wedding` → nothing).

§3.0 discovery re-specced several assumptions against the real code (see footnotes): no
`planner_attested_chassis_at_ack` column exists; `chassis_records.status` is denormalised (written), not
derived read-only; `event_type` has no DB CHECK; the WO's wipe order would have hit RESTRICT FKs.

## Decisions

1. **Body↔chassis joining is an event, not a column (extends ADR 0018).** `body_attached` joins the
   `chassis_lifecycle_events.event_type` set (`ALLOWED_EVENT_TYPES`, app-validated — there is no DB CHECK
   to extend). The Production Dashboard's KPI, the Assembly "Body Attached (today)" section, and the
   bay-state tiles are all DERIVED from the latest events — no denormalised flag on chassis_records or
   production_jobs. No migration was needed for MUST-SHIP.

2. **`body_attached` is PHASE-ONLY for v4.35; status stays `in_assembly` (footnote A).** Recording the
   event does NOT move `chassis_records.status` (which is otherwise written eagerly). Promotion of the
   attach to a status milestone is deferred to the v4.36+ workshop-tablet WO, when real-time progress
   capture (and the two-event start/complete split) lands. For v4.35 the two attach phases are collapsed
   to one event.

3. **Two events, one merge — but only one in MUST-SHIP.** The full design is two factory drags →
   `panels_arrived_in_bay` (panels) + `assembly_assigned` (chassis) → "Ready to merge" → `body_attached`.
   MUST-SHIP ships the `assembly_assigned`-precondition + bay-click `body_attached`; the
   `panels_arrived_in_bay` event + its job-bay-events table + the Planning panel-drag + auto-merge prompt
   are STRETCH (a real new table + cross-context drag — cut cleanly if the calendar tightened).

4. **Pre-condition guards at one service chokepoint (extends ADR 0023/0024).** `record_body_attached`
   (in `services/chassis.py` — `services/production.py` doesn't exist) enforces, server-side: chassis on
   a bay (prior `assembly_assigned`), linked job `in_production`, no double-linkage, the swap rule, and
   idempotency. The router only gates the permission. Both the bay-click and any future drag path route
   through this one function.

5. **Demo-seed = snapshot → atomic invariant-gated wipe → reseed (the canonical clean-baseline).**
   `seed_v4_35_demo_reset.py` is Tier-2 guarded (never the Tier-1 `_truncate_mes`), takes a mandatory
   pg_dump first, and runs the FK-safe wipe + reseed in ONE transaction whose v4.34.4 invariants are
   checked in-session before commit (footnote E). Master data is preserved; the reseed covers all bay
   states. This is the documented controlled-clean-baseline approach (extends the Phase-2 14-Jun pattern).

## Footnotes — generalizable patterns from §3.0-§3.6

> **A. Phase vs milestone events.** When a lifecycle event marks a *phase within* a state rather than a
> transition *to* a new state, log the event but do NOT mutate the denormalised status. (`body_attached`
> is a phase within `in_assembly`; promotion to a status is a separate, later decision.)

> **B. Derive a guard from existing state before adding a column.** §0.22's swap rule was specced
> against `production_jobs.planner_attested_chassis_at_ack` — which doesn't exist. The "planner attested
> the chassis at ack" signal already lives in the data: a confirmed Pre-Job Card with a captured VIN
> (`PrejobCard.vin_number` set AND `planner_signoff_at` set). Derive the guard from that; add a column
> only when no existing state expresses the intent.

> **C. Audit tables are scoped by the entity whose state changes.** `chassis_lifecycle_events` is the
> audit for chassis events (VCL/DCL/assembly_assigned/body_attached); `production_jobs_audit` is for
> production-job transitions (the v4.34.2 revert). Don't fold one entity's events into another's audit —
> `body_attached` writes no `production_jobs_audit` row.

> **D. HTTP status split + loud idempotency.** Pre-conditions ("do X first") → **422**; conflicts with
> current state ("already done", "linked elsewhere") → **409**, each with remediation text. A repeat
> action returns 409, never a silent double-event — surfacing stale-state confusion rather than masking it.

> **E. Tier-2 shared-DB destructive discipline: snapshot + dry-run-default + atomic-invariant-gate.**
> A destructive op on a shared DB takes a verified pg_dump first; defaults to DRY-RUN (full transaction
> logic, no commit) and requires an explicit `--commit`; and wraps wipe+reseed in one transaction whose
> invariants are re-checked in-session before commit, so a bad reseed rolls back the wipe atomically
> (the snapshot is the outer net). (Sibling of the Phase-2 14-Jun snapshot-before-mutation pattern.)

> **F. Symmetric multi-surface enhancements share testid + pattern.** The chassis-VIN line ships on the
> Production worksheet *and* the Planning Board (slot cells + pool) with one `data-testid="slot-vin"` and
> the same mono/muted/hover-full/null-safe treatment — reducing UX drift and test-maintenance overhead.

## Consequences

- The demo shows a believable end-to-end factory flow with the body↔chassis join explicitly visible.
- No `/calculator` change, no `icb_sap` write, no migration (MUST-SHIP); icb_costings writes confined to
  the BA-approved demo reseed. v4.31-v4.34.2 surfaces consume-only.
- **Narrative wrinkle (runbook-documented):** because the attach is phase-only, the Chassis page still
  shows `in_assembly` after a body is attached — by design; the Production Dashboard is where the moment
  surfaces. v4.36+ promotes it to a status milestone.
- **Carried to v4.36+ housekeeping:** `seed_from_mockup` is not v4.34.4-invariant-clean on a fresh seed
  (it predates the invariants) — alongside the FK-drift, dealer-admin-CRUD, and audit-explorer backlog.

## As shipped (Click-to-verify)

- `chassis.py`: `ALLOWED_EVENT_TYPES`, `record_body_attached`, `assembly_bay_states` (4-state), VIN helpers.
- `team_worksheet.py`/`production_jobs.py`: Assembly section + `bodies_attached_today` KPI.
- `planning.py`: `_CHASSIS_VIN` on the board read.
- Endpoint: `POST /api/chassis-records/{id}/body-attached`.
- Frontend: 4-state bay tiles + KPI tile + mark-attached side-panel + Assembly section + Vac/Press 🔗 +
  slot VIN (Production + Planning).
- `scripts/seed_v4_35_demo_reset.py`; `docs/audit/2026-06-16/V4_35_DEMO_SEED_EXECUTION_LOG.md`.
- Journeys: `test_body_attached_event` / `test_assembly_tab_body_attached_section` / `test_demo_walkthrough` (+ `_v435`).
- Docs: this ADR, `docs/uat/ICB_MES_BurtDemo_v4.35_v1.0.md`, `docs/uat/ICB_MES_LiveData_Creation_Guide_v1.0.md`, runbook screenshots under `docs/screenshots/runbook/`.
- No new nav route.
