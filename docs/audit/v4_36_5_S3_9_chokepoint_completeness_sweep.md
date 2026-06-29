# v4.36.5 §3.9 — Chassis-chokepoint completeness sweep (the audit-of-completeness artifact)

**Method (the lesson banked).** A "single chokepoint / all writes go through `_apply_chassis_fields`" claim is a *completeness* claim — only as true as the absence of bypasses. Three prior passes hunted by named site and each missed leaks. This sweep hunts by **mechanism**: grep every direct assignment to a field in `_AUDITED_FIELDS` across `backend/`, then classify *each* match. The artifact below lists every match — routed, excluded, and false-positive — so completeness is explicit, not "trust me."

`_AUDITED_FIELDS` = {vin, vin_source, job_number, customer_name, contact_person, telephone, make, model, description, status, notes, dealer_id, tail_lift_code, body_gap_mm}.

**Grep proof of closure (post-§3.9):**
```
grep -rnE "\.status\s*=\s*['\"](dispatched|expected_orphaned|in_assembly|awaiting_qa|in_workshop|received)['\"]" \
  backend/app/services backend/app/routers | grep -v "_apply_chassis_fields" | grep -viE "job\.|calc\.|card\.|p\.status|evt\."
→ (zero matches)
```

## A. Chassis-attribute writes ROUTED through the chokepoint

| Site | Field(s) | `source` | Phase |
|---|---|---|---|
| `services/chassis.py` `update_chassis` | all (PATCH) | `chassis_page` | §3.1 |
| `services/production_jobs.py:444` `record_planning_ack` | 11 fields | `planning_ack` | §3.1 / §3.8(actor_id) |
| `services/chassis.py` `capture_vin` | vin, vin_source | `chassis_page` | §3.8 |
| `services/chassis.py` `capture_event` (VCL/DCL) | status, body_gap_mm | `vcl` / `dcl` | §3.8 |
| `services/chassis.py` `assign_assembly_bay` | status | `assembly_assign` | §3.8 |
| `services/chassis.py` `record_moved_to_awaiting_qa` | status | `moved_to_awaiting_qa` | §3.8 |
| `services/chassis.py` `return_chassis_to_parking` | status | `return_to_parking` | §3.8 |
| `services/chassis.py` `create_chassis` placeholder-adoption | vin, vin_source, make, customer_name, dealer_id, status | `stub_adoption` | §3.8 |
| `services/prejob_cards.py` `_auto_create_chassis` (both sync sites) | make, body_gap_mm, vin, vin_source | `pre_job_card` | §3.8 |
| **`services/qc.py:200` `signoff` PASS** | **status → dispatched** | **`qc_passed`** | **§3.9** |
| **`services/prejob_cards.py:653` `_release_auto_created_chassis`** | **status → expected_orphaned** | **`unlink_card`** | **§3.9** |
| **`services/integrity.py:169` `reconcile_anchorless_chassis`** | **status → expected_orphaned** | **`reconcile_orphaned`** (system actor) | **§3.9** |

Structural lifecycle ops (merge / soft_delete / restore) are audited at the **event** level via `_audit_chassis` (`source=merge|soft_delete|restore`), per ADR 0030 decision 5.

## B. Direct writes EXCLUDED — with rationale (B1 are chassis-domain side-effects; B2 are not chassis records)

**B1 — structural-op side-effects (audited at the event level; not independent edits):**
- `services/chassis.py:499` — `rec.notes += "[soft-deleted …]"` inside `soft_delete_chassis`. The delete IS audited (`deleted_at` + `deletion_reason` rows); this notes-marker is a human-readable echo of `deletion_reason`. *Could* be routed for strict zero-direct-writes — flagged for your call; left excluded as redundant.
- `services/chassis_merge.py:189` — `winner.job_number = sj.job_number` inside `merge_chassis`. The merge IS audited (the loser's `merged_into_id` row, `source=merge`); this is provenance-reconciliation on the survivor, a side-effect of the audited merge. Same "could route" flag.

**B2 — not a ChassisRecord (false positives the field-grep surfaces):**
- `services/chassis.py:659` — `evt.notes = notes` (a `ChassisLifecycleEvent`, not the chassis row).
- `integrity.py:132`, `prejob_cards.py:410/463/605/615/672`, `production_jobs.py:216/235/446/450`, `po_suggestions.py:61/77/128`, `calculator.py:1081/1106`, `routers/pre_job_card.py:90/116/233/238` — all `calc.status` / `card.status` / `job.status` / `p.status` (CalculationRecord / PrejobCard / ProductionJob / POSuggestion), not chassis records.

## C. Fresh-create — inherently excluded

`ChassisRecord(...)` constructor kwargs in `create_chassis` (fresh path), `create_expected_chassis`, and the seed scripts are *creations*, not edits — recorded by `created_by` + the row's existence; auditing 10+ NULL→value rows per create would be noise (ADR 0030 decision-1 / the BA's §3.8 ratification). These don't match the `.field =` grep and are listed for completeness only.

## Disposition

All chassis-attribute **edits** and all chassis **status transitions** now route through `_apply_chassis_fields`. The B1 structural side-effects are the only direct writes to audited fields remaining, and each is audited at its parent event; they are flagged for a route-or-keep decision. Tests: §3.9 adds `test_qc_signoff_dispatch_audited`, `test_unlink_card_orphan_audited`, `test_reconcile_orphan_audited`, `test_retrofit_link_fail_closed` + two tightenings (gate suite 14→18).
