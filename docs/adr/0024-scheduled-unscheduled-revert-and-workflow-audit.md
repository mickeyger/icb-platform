# ADR 0024 — Scheduled → Unscheduled revert + workflow-state audit (v4.34.2)

- Status: Accepted
- Date: 2026-06-15
- Work Order: v4.34.2 — Gap B: Scheduled → Unscheduled Revert on the Planning Board
- Builds on: ADR 0008 (Planning Board / planning_slots), ADR 0023 (v4.34.4 integrity lockdown).

## Context

Workshop scheduling is iterative — priorities shift (chassis arrives early, a customer pushes a date, a
higher-priority job displaces a scheduled one). The Planning Board's forward flow is
Unscheduled → Scheduled → Workshop, and Michael's v4.33.1 testing flagged that a planner had no clean
way to lift a scheduled job back to Unscheduled for a reshuffle.

**§3.0 discovery reshaped the WO.** The premise ("no way back without rejecting the whole sign-off") was
already false in code: `DELETE /api/planning-slots/{slot_id}` → `services/planning.unschedule` deleted
the slot (job returns to the pool), exposed in the UI by **dragging a scheduled slot onto the
Unscheduled pool**, gated on `planning.unschedule` (planner + admin). It already preserved chassis +
sign-offs (it only deletes the slot row). The genuine gap was **guardrails + an audit trail + an
explicit reason-capturing affordance** — so v4.34.2 *hardens an existing chokepoint* rather than
building a parallel one. (The BA ratified this re-scope before §3.1.)

## Decisions

1. **Reversible scheduling state machine — on the slot, not the job lifecycle.** "Scheduled" is the
   existence of a `planning_slots` row (`status='scheduled'`); a scheduled job's
   `production_jobs.status` stays `'planning'` throughout (ADR 0008 §0.4). Revert therefore deletes the
   slot and the job re-appears in the pool (`status='planning'`, no slot). The allowed-from set is an
   **extensible whitelist** (`REVERTIBLE_JOB_STATUSES = {'planning'}`): once a job advances to
   `in_production`/`completed` it is workshop-locked for this action — terminal-for-revert, not terminal
   overall. Because the job status doesn't change, the audit's `previous_status`/`new_status` record the
   **scheduling** state (`scheduled` → `unscheduled`), not the lifecycle status.

2. **Workflow-state audit table (`icb_mes.production_jobs_audit`).** Append-only, one row per transition:
   job, `action` (extensible discriminator), previous/new scheduling-status, the deleted slot's
   placement (`previous_slot_id`/`lane`/`bay`/`week` — no FK, the slot is gone), `user_id` (+ `user_name`
   snapshot), optional `reason`, `created_at`. It is the workflow-level analogue of v4.34.4's
   `scripts_audit.log` (ADR 0023): *the same "record the privileged action" instinct, one level up.* FK
   to `production_jobs` is `ON DELETE CASCADE` to match the other job-children (work_orders,
   planning_acks); jobs have no prod delete path, so the table is append-only in practice.

3. **Affordance gating = role AND state, in tandem.** The control renders only when the user has
   `planning.unschedule` (planner/admin) **and** the job is still `'planning'` (client-side hide of the
   obvious case). The full §0.3 state rules — slot is `scheduled`, job not workshop-started (no
   `work_orders.started_at`), no QC tick (no completed `tasks` / `sign_offs`) — are **server-enforced**
   in the service, so the hidden button is never the security boundary.

4. **Chassis stays assigned on revert (and sign-offs stay valid).** Revert is a *scheduling* change, not
   an order rejection: the chassis is still ICB's and the spec is unchanged, so `unschedule` touches
   only the slot row — `production_jobs.chassis_record_id` and all sign-off records are untouched. The
   chassis is **not** released to `expected_orphaned`; the reject-sign-off path (v4.34 §0.6) remains the
   only release trigger. This deliberately keeps the v4.34.4 invariants intact (see footnote).

5. **The guarded chokepoint is the single source of truth; the new endpoint delegates to it.** The
   safety rules + audit live in `services/planning.unschedule`. Both the existing slot `DELETE`
   (drag-to-pool, no reason) and the new job-centric `POST /api/production-jobs/{id}/revert-to-unscheduled`
   (modal, optional reason ≤500) route through it — so the guards cannot be bypassed via the older path
   (see footnote). `revert_to_unscheduled` resolves the job's single slot and delegates. No same-
   transaction state read needs a `db.flush()` here (the guard reads only already-committed rows), but
   the ADR 0023 footnote applies if that changes.

## Footnotes

> **Chokepoint, not entry point.** When a guarded path is added alongside an existing unguarded one,
> retrofit the guards at the shared service-layer chokepoint rather than the new endpoint alone, or the
> unguarded path becomes the bypass vector. (Here: the §0.3 rules + audit went into `unschedule`, which
> both the drag `DELETE` and the modal `POST` call — not into the new endpoint only.)

> **Reuse established surface patterns.** Established surface patterns (the slot side-panel; pessimistic
> await→refetch) should be preferred over new paradigms unless the use case actively requires
> divergence. The revert affordance reuses the slot-click side-panel (not a bespoke modal) and the
> board's pessimistic refetch (not optimistic-with-rollback) — less surface area, less risk, less review
> burden. (BA-ratified, v4.34.2 checkpoint.)

> **v4.34.4 invariants preserved (asserted in the journey).** Revert is a slot-only delete: the job +
> card persist (Inv 1 — card⇒job), `calculations.status`/`production_jobs.status` stay `'planning'` and
> still back the lifecycle (Inv 2 — no spurious pre_job_sent boundary), and the chassis link is
> untouched (Inv 3 — no new anchorless chassis). `test_unschedule_revert_journey.py` asserts all three on
> both the modal and drag paths, plus audit-row consistency (drag → reason NULL; modal → reason text).

## As shipped (Click-to-verify)

- Migration 0023 → `icb_mes.production_jobs_audit` (round-trip CI-verified on icb_test).
- Backend: `services/planning.{unschedule,revert_to_unscheduled}` (+ `_assert_revertible`,
  `RevertNotAllowedError`), recency sort in `_unscheduled_pool`; `POST /api/production-jobs/{id}/revert-to-unscheduled`;
  `DELETE /api/planning-slots/{id}` now maps the new 409. Both gated `planning.unschedule`.
- Frontend: `LiveSlotDetail` "↩ Move back to Unscheduled" + reason textarea (≤500); drag-to-pool retained
  and now guarded. `data-job-id` on the scheduled cell (journey targeting).
- Tests: `backend/tests/journeys/test_unschedule_revert_journey.py`; `test_smoke` table-count 33→34.
- No new nav route; the affordance lives in the Planning Board slot side-panel.
