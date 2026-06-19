# v4.36a.3 §3.0 — Panel-clear-on-merge-forward: discovery synthesis

**WO:** Fix the bug where a bay that held a `body_attached → moved_to_awaiting_qa` chassis still renders
"Panels in bay" + "✕ move panels back". Bundled into PR #35 (no new PR).

**Outcome of discovery: trivial confirmation of the expected reuse shape.** No surprises. Panel-side state
is **event-derived** (not column-stored), so the fix is derivation-logic-only, exactly as the WO framed it.

## Bug site (confirmed)
`compute_bay_merge_readiness` — `backend/app/services/chassis.py` (the `occ is None` branch):
```python
if occ is None:
    state = "pre_assembly" if panels_job_id is not None else "empty"   # ← BUG: ignores body_attached
```
When a body-attached chassis goes `moved_to_awaiting_qa`, its status flips to `awaiting_qa`, so
`current_occupants()` (which gates on `status=='in_assembly'`) no longer returns it → `occ is None`. But
`_panels_for_bay()` still finds the bay's `panels_arrived_in_bay` event → `panels_job_id is not None` →
state derives `pre_assembly` ("Panels in bay"). The panels were *consumed* by the body that left; the
derivation doesn't know it.

**Reproduced live** (dev server, Bay-2 / chassis 1812 / job 197): `panels(201) → body_attached(201) →
move-to-awaiting-qa(201)` ⇒ bay API returns `state="pre_assembly", occ=null, panels_job=197`; the tile
renders `"Panels in bay | Job 40301 | ✕ move panels back"`. (Live residue on icb — cleared Mon-AM reseed.)

## Surfaced facts (§3.0 checklist)
- **Panel event:** `panels_arrived_in_bay` on `ProductionJobBayEvent` (table `icb_mes.production_job_bay_events`,
  migration 0024); allowlist `ALLOWED_BAY_EVENT_TYPES = {"panels_arrived_in_bay"}` (chassis.py). **Event-derived,
  NO `bay.panels_for_job_id` column** → fix shape is derivation-only (the WO's flagged risk does not apply).
- **Panel reader:** `_panels_for_bay(db, bay_id)` (chassis.py) — pure latest-event reader; does not consider
  consumption. The consumption check belongs in the derivation (caller), not this reader.
- **body_attached reader:** `_latest_body_attached_dates(db, chassis_ids)` — only ever called with the
  *current* occupant, so it never sees the departed chassis. The fix must resolve the panels-job's chassis
  independently of `current_occupants`.
- **Move-back service:** `clear_panels_arrived(db, production_job_id)` (chassis.py) + `DELETE
  /api/production-jobs/{job_id}/panels-arrived-in-bay` (routers/production_jobs.py), gated
  `chassis.assembly_assign`. **No consumed-panels guard today** — §0.4 adds the 409.
- **`record_moved_to_awaiting_qa`** does NOT touch the panels event (correct — fix is derivation, not that
  service). Same for `record_body_attached`.
- **Frontend:** `BayModelLanes.tsx` — `pre_assembly` branch renders "Panels in bay"; `hasPanels && canAssign`
  renders the "✕ move panels back" button. §0.5 gates the button; §0.6 wants the attached bay to read as a
  merged body, not chassis+panels chips.

## Flagged concerns (answers)
1. **Panel-side state IS event-derived (not column-stored)** — confirmed. Fix is derivation + UI gating only.
2. **v4.36a.2 reverse-drag has NO unintended overlap.** `return_chassis_to_parking` is guarded on
   `_has_event(body_attached)` → a returned chassis's bay never has a `body_attached` event, so the new
   "panels consumed iff the panels-job's chassis has body_attached" gate evaluates false there → its panels
   stay loose (`pre_assembly`), D1 preserved. The fix only changes the *post-body_attached* case.

## Fix shape (for the build, pending GO)
- **Derivation (§0.3):** when resolving a bay's panels, treat them as **consumed** if the panels-job's
  chassis (`production_jobs.chassis_record_id`) has a `body_attached` event. Consumed panels ⇒ NOT loose:
  with `occ is None` the bay derives `empty` (the body+panels left to QA); with the occupant still present
  (post-attach, pre-QA) the existing `attached_today`/`post_attached` path already wins.
- **Guard (§0.4):** `clear_panels_arrived` raises 409 ("panels are part of a body in Assembly/Awaiting QA;
  cannot move back") when the target panels are consumed.
- **Frontend (§0.5/§0.6):** suppress "✕ move panels back" when the bay's panels are consumed; the attached
  bay renders the merged-body visual (reuse `attached_today`/`post_attached` styling), not a panels chip.
