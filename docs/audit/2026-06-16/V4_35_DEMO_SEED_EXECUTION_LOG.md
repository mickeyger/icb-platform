# WO v4.35 §3.5 — Demo seed (snapshot → wipe → reseed) execution log

**Date:** 2026-06-16 · **Operator:** CA1 (mickeyger machine) · **Target:** shared dev/demo DB `icb` (localhost)
**Authorisation:** BA-approved Tier-2 workflow-data wipe (WO v4.35 §0.10); mandatory pre-wipe snapshot per the Phase-2 (14 Jun) pattern.

## §3.5a — Pre-wipe snapshot (MANDATORY, done FIRST)

- Tool: `pg_dump` (PostgreSQL 18.4), custom format, `--no-owner --no-privileges`.
- In-repo copy (gitignored): `backend/.db_snapshots/icb_devdb_2026-06-16_v435_prewipe.dump`
- BA-folder copy: `…/Burt Costing Model/ICB business process/db_snapshots/icb_devdb_2026-06-16_v435_prewipe.dump`
- Size: 978,842 bytes · **sha256 `49727A4D98612003E2E945212D633EA8B790C92201D90E1BADFDB1667F6CEF4D`** (both copies match).
- Integrity verified: `pg_restore --list` → 85 `TABLE DATA` entries.
- **Rollback:** `pg_restore --clean --if-exists -d icb <dump>` (as a superuser) restores the pre-wipe state.

## §3.5b/5c — Wipe + reseed (one atomic transaction)

- Script: `backend/scripts/seed_v4_35_demo_reset.py` — Tier-2 guarded (`confirm_if_shared_db`,
  `ICB_ALLOW_SHARED_DB_WRITE=1`, logged to `scripts_audit.log`). **NOT** routed through
  `seed_from_mockup._truncate_mes` (whose v4.34.4 Tier-1 guard correctly hard-refuses `icb`).
- Safety: wipe + reseed run in ONE transaction; `integrity.run_health_checks` is checked IN-SESSION
  (uncommitted) and the whole operation rolls back if any v4.34.4 invariant fails. A `--commit` flag
  gates the apply (default is DRY-RUN). Verified via dry-run before committing.
- FK-safe wipe order (§3.0 DEV-3 corrected): production_jobs_audit → tasks → photos → rework_tickets →
  sign_offs → work_orders → planning_acks → planning_slots → chassis_photos → chassis_lifecycle_events →
  bom_lines → generated_boms → demand_lines → **prejob_cards → production_jobs** → chassis_records →
  calculations. (prejob_cards + production_jobs before chassis_records + calculations — the RESTRICT chain.)

### Before → after row counts

| Table | Before | After |
|-------|-------:|------:|
| icb_costings.calculations | 22 | 12 |
| icb_mes.production_jobs | 19 | 12 |
| icb_mes.prejob_cards | 16 | 4 |
| icb_mes.chassis_records | 264 | 9 |
| icb_mes.chassis_lifecycle_events | 505 | 18 |
| icb_mes.planning_slots | 14 | 2 |
| **MASTER (preserved, unchanged)** | | |
| icb_costings.customers | 2190 | 2190 |
| icb_costings.customer_contacts | 2148 | 2148 |
| icb_mes.prejob_templates | 23 | 23 |
| icb_mes.assembly_bays | 5 | 5 |
| icb_costings.users | 6 | 6 |
| customers.is_dealer=true | 32 | 32 |

### Reseed coverage (~12 jobs, all body_attached bay states)

Pre-job pending (sales) ×2 · pre-job pending (planner) ×1 · confirmed-but-blocked ×1 (expected chassis, no
ETA) · scheduled on the vacuum lane ×2 · **in assembly awaiting attachment ×2 (AssemblyBay-2/-3 — the
"Mark body attached" demo targets)** · **body attached today ×2 (AssemblyBay-4/-5)** · post-attached /
finishing ×1 (AssemblyBay-1, attached 3 days ago) · completed/dispatched ×1. AssemblyBay-1 hosts the
finishing job; no bay is left mid-merge (panels_arrived_in_bay + Ready-to-merge are STRETCH).

### Verification

- In-session (pre-commit) `run_health_checks`: **clean=True** (Inv1=[], Inv2=0, Inv3=0).
- Post-commit independent `python -m scripts.health_check`: **CLEAN — all three invariants hold (0/0/0).**

body_attached is **phase-only** (DEV-2): logged in `chassis_lifecycle_events`; `chassis_records.status`
stays `in_assembly` post-event by design. (Runbook note for Burt: the Production Dashboard surfaces the
moment via bay tile + Assembly-tab section + KPI; the chassis page is lifecycle audit, not celebration.)
