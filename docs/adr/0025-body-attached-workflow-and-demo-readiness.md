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

> **G. Cross-component drag without shared state: HTML5 DataTransfer + a DOM CustomEvent (§3.3b).** The
> Planning panel-drag crosses a React component boundary — the week-grid slot-cell lives in `PlanningBoard`,
> the assembly-bay drop target in `BayModelLanes` — without lifting state or adding context. The source
> writes the payload via `e.dataTransfer.setData('application/x-panel-job', jobId)` and announces drag
> start/end with a `document` `CustomEvent` (which drives the drop-target highlight on the other component);
> the target reads it in a new `onDrop` branch and **widens its `onDragOver` guard to `preventDefault()`
> for that MIME type**. Two decoupled components, one new drop semantics, zero shared store. (The single
> easiest thing to get wrong: if `onDragOver` doesn't allow the new type, the browser rejects the drop and
> it silently no-ops.)

> **H. A separate event class gets its own table + allowlist, not a widened enum (§3.3b).** Panels arriving
> in a bay is a JOB-side event, so it lives in `production_job_bay_events` with its own
> `ALLOWED_BAY_EVENT_TYPES = {panels_arrived_in_bay}` — deliberately NOT folded into the chassis-side
> `ALLOWED_EVENT_TYPES`, so a job-bay event can never slip into the `chassis_lifecycle_events` insert path
> (this is footnote C applied forward). The 6-state "ready to merge" is then *derived* by correlating the
> two event streams (`compute_bay_merge_readiness` — the single source of truth for both the tiles and the
> auto-merge prompt), never stored.

> **I. A new phase-only event creates committed state that EXISTING status-based guards can't see — audit
> them (§3.3b, found in the demo click-around).** `body_attached` and `panels_arrived_in_bay` are phase-only
> and (per the 16-Jun ruling) never advance `job.status`, so the v4.34.2 unschedule chokepoint
> (`_assert_revertible`, which keys only on status / work-orders / QC) happily reverted a job whose panels
> were in a bay and whose body was attached — orphaning the floor. Lesson: when a feature introduces
> committed state WITHOUT a status transition, every guard that authorises a reversal must be taught the new
> signal. Fix: `_assert_revertible` now also blocks on a `panels_arrived_in_bay` event for the job or a
> current-cycle `body_attached` on its chassis (both unschedule paths share the one chokepoint).

> **J. A correct-but-silent guard is a UX defect — make the non-match legible + reversible (§3.3b, demo
> click-around).** Dropping a job's panels on a bay whose chassis is a *different* job is a no-op merge
> (correct: matching is by job identity, not VIN). But it was *silent* — the bay just stayed "awaiting" with
> no reason, and the one-bay-per-job rule + the new revert guard (footnote I) left the wrong drop stranded
> until a reseed. Fix: `compute_bay_merge_readiness` exposes a `mismatch` flag (panels + chassis, different
> jobs) that drives a "⚠ Different jobs" cue naming the stray panels, plus a `DELETE
> /api/production-jobs/{id}/panels-arrived-in-bay` "move panels back" undo. Lesson: when an invariant
> *correctly* refuses an action, the refusal still has to be visible and recoverable — silence reads as a
> bug to the operator.

> **K. An affordance that can't act must not render as an actionable CTA (§3.3b, demo click-around).** The
> Production "Mark body attached" button rendered for any `awaiting_attachment` bay but `doMarkAttached`
> silently no-op'd when the occupant chassis had no linked production job (`occupant_job_id == null`) — a
> dead button. Fix: gate the actionable button on `occupant_job_id != null` and render an explanatory hint
> ("this chassis isn't linked to a production job") otherwise. Same pass widened the gate to include
> `ready_to_merge` (a panels-dragged bay), so the Production attach path matches the operator's "drag panels
> → mark attached" mental model. Rule: a control's render condition must imply its action can succeed —
> otherwise show the reason, not the button.

## Consequences

- The demo shows a believable end-to-end factory flow with the body↔chassis join explicitly visible.
- No `/calculator` change, no `icb_sap` write, no migration (MUST-SHIP); icb_costings writes confined to
  the BA-approved demo reseed. v4.31-v4.34.2 surfaces consume-only.
- **Narrative wrinkle (runbook-documented):** because the attach is phase-only, BOTH status fields stay at
  pre-attachment values after a body is attached — chassis `in_assembly` AND, with the 16-Jun loosened
  pre-condition, the job stays `planning` (the pre-condition now accepts `planning` OR `in_production` and
  deliberately does NOT auto-transition). The Production Dashboard (bay tile + KPI + Assembly section) is
  where the moment surfaces; the v4.36 QC sprint promotes the status fields.
- **Carried to v4.36+ housekeeping:** `seed_from_mockup` is not v4.34.4-invariant-clean on a fresh seed
  (it predates the invariants) — alongside the FK-drift, dealer-admin-CRUD, and audit-explorer backlog.

## As shipped (Click-to-verify)

- `chassis.py`: `ALLOWED_EVENT_TYPES`, `record_body_attached` (16-Jun: accepts `planning` OR
  `in_production`, no auto-transition), VIN helpers. **§3.3b:** `ALLOWED_BAY_EVENT_TYPES`,
  `record_panels_arrived_in_bay`, `compute_bay_merge_readiness` (single source of truth),
  `assembly_bays_utilisation` now 6-state (`empty`/`pre_assembly`/`ready_to_merge`/`awaiting_attachment`/
  `attached_today`/`post_attached`).
- `team_worksheet.py`/`production_jobs.py`: Assembly section + `bodies_attached_today` KPI.
- `planning.py`: `_CHASSIS_VIN` on the board read.
- Endpoints: `POST /api/chassis-records/{id}/body-attached`; **§3.3b** `POST
  /api/production-jobs/{id}/panels-arrived-in-bay`.
- Migration **0024** `production_job_bay_events` (mirrors 0023; cross-schema `user_id` FK in-migration).
- Frontend: 6-state bay tiles + KPI tile + mark-attached side-panel + Assembly section + Vac/Press 🔗 +
  slot VIN (Production + Planning). **§3.3b:** Planning panel-drag-to-bay (`BayModelLanes` +
  `PlanningBoard` slot-cell) + auto-merge prompt + `useRefetchOnFocus` on 3 surfaces.
- `scripts/seed_v4_35_demo_reset.py`; `docs/audit/2026-06-16/V4_35_DEMO_SEED_EXECUTION_LOG.md`.
- Journeys: `test_body_attached_event` / `test_assembly_tab_body_attached_section` / `test_demo_walkthrough`
  / **§3.3b** `test_planning_drag_to_merge` / `test_cross_page_sync` (+ `_v435`).
- Docs: this ADR, `docs/uat/ICB_MES_BurtDemo_v4.35_v1.0.md`, `docs/uat/ICB_MES_LiveData_Creation_Guide_v1.0.md`,
  runbook screenshots under `docs/screenshots/runbook/` (`capture-v435-stretch.mjs` for the §3.3b frames).
- No new nav route.
