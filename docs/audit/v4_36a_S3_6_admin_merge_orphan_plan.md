# v4.36a §3.6 — admin Merge Chassis + Find Orphan: §3.0 discovery + ratified plan

**Method note.** Discovery ran as a parallel-subagent Workflow (`v436a-s36-admin-discovery`, 3 readers →
synthesis). This artifact records the BA-ratified plan (17 Jun). Build order is deliberately
least-destructive-first; each step is independently verifiable and halts safely.

## Ratifications (BA, 17 Jun)

- **Soft-delete marker = `merged_into_id` column (migration 0025), NOT a `status` sentinel.** The BA's
  pre-clarification (`status='merged_into:{id}'`) was withdrawn after CA surfaced that it re-introduces the
  hazard §3.0 rejected (poisons ~6 status-equality reads). No `status` overload, no `merge_note` column —
  `deleted_at` (when) + `merged_into_id` (what) + `updated_by` (who) is sufficient audit. A dedicated
  `chassis_audit` table is deferred to v4.36b.
  → **ADR 0026 footnote:** *Dual review (BA spec ↔ CA implementation) catches errors in both directions. CA
  must surface BA spec errors with technical reasoning when they contradict in-flight code or violate §3.0
  ratifications, not silently comply.*
- **Find Orphan = WIDE** (all live FK-anchorless chassis, any status) — catches MICKEYTEST-class `received`
  orphans that `find_anchorless_chassis`'s `status IN ('expected','expected_orphaned')` scope would miss.
  Parameterize the shared FK-anchorless predicate: admin scope wide, health-check scope narrow.
- **Event collisions → renumber** the loser's colliding cycle_numbers above the winner's max (same txn) —
  preserves history + photos; never drop.
- **Include `PATCH /{id}/restore`** (6th endpoint) — clears `deleted_at` + `merged_into_id`, guards VIN
  clash, does NOT auto-re-point FKs (operator re-links explicitly). Pairs destructive paths with reversal.
- **Permission = `require_admin`** on every endpoint (no new `chassis.merge` key → no permission migration).

## FK-repoint set (grep-confirmed complete — 3 columns + transitive photos)

| Table.column | ondelete | Merge action |
|---|---|---|
| `production_jobs.chassis_record_id` (models/mes/__init__.py:144; FK 0012:69-74) | RESTRICT | re-point loser→winner |
| `prejob_cards.chassis_record_id` (model:960; FK 0020:60-64) | SET NULL | re-point loser→winner |
| `chassis_lifecycle_events.chassis_record_id` (model:818-819) | CASCADE | re-point loser→winner |
| `chassis_photos.lifecycle_event_id` (model:844-845) | (transitive) | rides the event re-point — no separate UPDATE |

The three *different* `ondelete` behaviors (RESTRICT blocks, SET NULL silently drops, CASCADE destroys) are
exactly why §3.6 re-points + soft-deletes rather than hard-deletes. Collision hazard:
`uq_chassis_events_record_cycle_type (chassis_record_id, cycle_number, event_type)` (model:812-813) — renumber
loser cycles above winner's max before the re-point UPDATE, same txn. After re-point, stamp
`winner.job_number` from the surviving job (reuse update_chassis chassis.py:337). **Not in set** (grep-confirmed
no `chassis_records.id` FK): `production_job_bay_events`, `production_jobs_audit`, `chassis_register`.

## Orphan definition (single authoritative, unify + widen)

Orphan = LIVE chassis (`deleted_at IS NULL`) with NO live `production_jobs.chassis_record_id` AND NO live
`prejob_cards.chassis_record_id` reference. Shared predicate; `find_anchorless_chassis` keeps the narrow
status scope (health-check / `reconcile_anchorless_chassis` semantics), the admin `GET /orphans` uses the
wide scope (all statuses). The ChassisList "Expected (Orphaned)" chip stays a client-side *display* filter,
NOT the authority. A merged loser (`merged_into_id` set, `deleted_at` set) is **excluded** — deliberately
deprecated via audited admin action, a different category from an accidental orphan.

## Build order (least-destructive-first; each independently verifiable)

1. **STEP 1 — `deleted_at IS NULL` guards (SAFETY FLOOR).** `find_anchorless_chassis` (integrity.py:142) +
   `list_chassis` (chassis.py:84). `get_detail` deliberately keeps returning tombstones (direct-nav). This
   makes 0025's soft-delete substrate safe *before* any merge write lands. **Checkpoint surfaced.**
2. `GET /api/admin/chassis/orphans` + `OrphanChassisAdmin.tsx` (read-only).
3. `POST /{id}/retrofit-link` {production_job_id} — reuse the §3.5c atomic-link primitive.
4. `DELETE /{id}` {reason?} — soft-delete a genuine *junk* orphan; refuse if any live FK still points at it.
5. `GET /{loser_id}/merge-preview?winner_id=` — read-only dry-run (repoint counts, collisions, vin conflict).
6. `POST /{loser_id}/merge` {winner_id} — the destructive op, after the preview/confirm UX is wired.
7. `PATCH /{id}/restore` — reversal.

If anything goes wrong, halt at the latest verified step — never leave a destructive-but-unfinished state.

## Endpoints (all `require_admin`, new router `/api/admin/chassis`)

1. `GET /orphans` → wide FK-anchorless list. Read-only.
2. `GET /{loser_id}/merge-preview?winner_id=` → `{loser, winner, repoint_counts, event_collisions, vin_conflict, warnings}`. No mutation.
3. `POST /{loser_id}/merge` {winner_id} → validate both live (409) · renumber colliding events · re-point 3 FKs · reconcile winner.job_number · set loser deleted_at/merged_into_id/updated_by · one txn. `ChassisIntegrityError`→409/422.
4. `POST /{id}/retrofit-link` {production_job_id} → atomic link an orphan to an unlinked job (reuse §3.5c; 409 on taken job / customer mismatch).
5. `DELETE /{id}` {reason?} → soft-delete junk orphan; refuse if a live FK still references it.
6. `PATCH /{id}/restore` → clear deleted_at/merged_into_id; guard VIN clash; no auto-re-point.

## §3.8 adversarial scenarios (ratified)

- **Chain merge** A→B→C: `merged_into_id` chain resolves, no cycle.
- **Concurrent merge** (two admins, A→B and B→A): check-then-set race with no DB unique index →
  `SELECT … FOR UPDATE` is the safety net; **subagent A probes with timing-attack simulation**.
- **Merge during body_attached**: loser mid-assembly + open `body_attached` cycle event → event re-point +
  `uq_chassis_events_record_cycle_type` collision + body_attached chokepoint.
- Self-merge (winner==loser) reject; merge into soft-deleted winner reject; merge an `in_assembly` chassis
  (bay events ride the job FK); VIN-uniqueness (tombstone keeps VIN, `resolve_existing_chassis` excludes
  `deleted_at` → never re-adopts).
- **Subagent C** ("audit ALL write paths to chassis_records") confirms the merge service adds no unguarded write.

## MICKEYTEST orphans (dev DB)

Demo: cleared by the **§3.7 reseed** (canonical wipe+reseed). No separate script for the demo. Production
legacy orphans: the **§3.7 cleanup script** (Tier-2: snapshot → dry-run → `--commit` → `scripts_audit.log`)
uses the *same* `merge_chassis`/soft-delete service so script and UI stay consistent.

## Invariant safety

Inv1/Inv2 are `calculation_record_id`-keyed — unaffected by FK re-point or chassis soft-delete. Inv3
(`find_anchorless_chassis`) is the only sensitive one; the STEP 1 `deleted_at` guard fixes the
false-orphan-after-merge case and `reconcile_anchorless_chassis` + `run_health_checks` inherit it.
