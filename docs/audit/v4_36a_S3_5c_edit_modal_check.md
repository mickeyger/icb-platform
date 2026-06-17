# v4.36a §3.5c — Edit Chassis modal symmetry: §3.0 mini-discovery + as-shipped

**Method note.** Per the 16-Jun standing rule, discovery ran as a parallel-subagent Workflow
(`v436a-s35c-edit-discovery`, 3 readers → synthesis) rather than a single sweep. A second Workflow
(`v436a-s35c-adversarial-review`, 3 skeptic lenses → judge) reviewed the diff before commit. This note
records what surfaced; it is not a code dump.

## Discovery synthesis (confirmed reuse + two corrections)

- **Edit modal location — CORRECTION.** The Edit modal is `EditChassisModal` in
  `frontend/src/screens/Chassis/ChassisDetail.tsx` (rendered when `editing` is true), **not**
  `ChassisList.tsx` (that file holds the *create* modal). The spec's "likely ChassisList.tsx — confirm"
  resolved to ChassisDetail.tsx.
- **Service chokepoint.** `update_chassis(db, record_id, payload, who)` in `backend/app/services/chassis.py`
  — a blind `setattr` loop over `ChassisRecordUpdate`. **Only two callers exist** (the PATCH endpoint
  `chassis_records.py` + one unit test), so hardening this single function is safe and complete — exactly
  the ADR-0024 chokepoint. The router relies on the global `ChassisIntegrityError` handler in `main.py`,
  so raising 409/422 from the service is sufficient (no router try/except).
- **Link detection.** "Linked" is authoritative **only** from `production_jobs.chassis_record_id`. There
  is no back-pointer column and no serializer exposed it, so `get_detail` now runs
  `select(ProductionJob).where(chassis_record_id == id)` and fills `linked_job_id/number/customer`.
  `chassis_records.job_number` is free-text/non-unique legacy provenance — **never** a linkage key.
- **Reuse primitives (all existing).** `/api/production-jobs/unlinked`, `/{id}/chassis-prefill`,
  `chassis_integrity.validate_job_link` / `validate_customer_consistency` / `ChassisIntegrityError`,
  `_job_customer_name`, and create_chassis's atomic FK-link pattern (`flush → job.chassis_record_id =
  rec.id → commit`). Frontend `UnlinkedJob` / `ChassisPrefill` / `VIN_PROVENANCE` / `VIN_RE` / `FilledBadge`
  were **local + unexported** in ChassisList.tsx → lifted to `chassisShared.tsx` so create + edit can't drift.

## As shipped (commit c79efcf)

| Chassis FK state | Job field |
|---|---|
| Linked | read-only display + "Linked to Job X (Customer Y). To swap, use admin Merge Chassis." |
| Unlinked | dropdown from `/unlinked`; select → atomic FK link + stamp `job_number` from the job |
| Legacy orphan (free-text job_number, no FK) | dropdown (treated as unlinked) + "Unlinked provenance: … — pick a job to create a real link" |

Customer auto-populates from the selected job (auto-filled badge), restored on de-select. §0.9 consistency
enforced at the chokepoint, incl. the adversarial-review must-fix: **clearing Customer on a linked chassis
is a 409** (it used to short-circuit the check and wipe the stored name).

## Inv-safety (from the review judge — "fix-then-ship", one major fixed pre-commit)

The link branch only ever does a **NULL→value** FK write, so it cannot strand a chassis (Inv3-safe); it
refuses a job already taken (409) and a soft-deleted chassis (409). `get_detail`'s back-ref query matches
`update_chassis`'s, so the frontend `isLinked` flag can't invert. Inv1/Inv2 are keyed on
`calculation_record_id`, untouched.

## §0 DEVIATION FLAGGED — VIN on the Edit modal (open, needs a ruling)

The §3.5c spec lists a VIN field on the Edit modal (conforming → read-only; legacy non-conforming →
editable-to-correct; NULL → editable). **The Edit modal has no VIN field today** — by design:

- `ChassisRecordUpdate` has **no `vin`** (the schema comment is explicit: VIN is write-once, guarded
  server-side to a NULL→value transition only).
- VIN capture is a **separate** path — `CaptureVinModal`, shown only while `vin IS NULL`, stamping
  `vin_source='chassis_page_manual'`.
- Locked decision **#3 / §0.3**: VIN write-once immutability; **wrong VIN → admin Merge Chassis** (§3.6).

So "conforming → read-only" and "NULL → editable" are already satisfied by the existing architecture
(modal shows VIN read-only in its title; Capture VIN handles NULL→value). The conflict is the **legacy
non-conforming → editable in the Edit modal** clause: that would open an **inline stored-VIN rewrite**
path, which §0.3 + lock #3 deliberately route through admin **Merge Chassis (§3.6)**. The §3.5b
"legacy-editable" refinement applied to a *create input* (no committed VIN yet); applying it to a *stored*
VIN is a different thing. **Pending BA ruling** (asked at checkpoint) before adding/withholding a VIN field.

## Deferred (real but pre-existing / raw-API-only — for ADR 0026 / v4.36b, not §3.5c)

1. `update_chassis` still blind-accepts `status` (raw-API-only; the modal never sends it). Operator allowlist.
2. No DB UNIQUE index on `production_jobs.chassis_record_id` (shared by create / body_attached / prejob /
   edit writers) — migration-level backstop for the check-then-set race.
3. `deleted_at` guard currently only on the link branch (editing a tombstone is meaningless, not corrupting).
