# WO v4.36a §3.0 — Chassis Integrity Discovery Report (audit trail)

> 3-subagent discovery per the 16-Jun standing rule. Run as a Workflow (subagents A validation-gap, B
> pattern-reuse, C adversarial + synthesis) against the post-v4.35 base (branch
> `feat/v4.36a-chassis-integrity`). A + C hit transient API 500s on the first pass and were re-run as
> parallel agents; all three perspectives + a synthesis are reflected. BA ratified the resolutions
> 16-Jun (two `AskUserQuestion` decisions). Persisted retrospectively for the audit trail.

## The three documented gaps — CONFIRMED at current file:line
- **PJ** — `_auto_create_chassis` passed `vin=None` (`prejob_cards.py:140`); the card VIN never reached
  `chassis_records.vin`; no format/uniqueness check.
- **AJ** — silent-swallow on VIN clash (`production_jobs.py:336-340`); `dealer_id` cast `int()` with no
  `is_dealer` check; `chassis_model` arbitrary string; no VIN format.
- **AC** — VIN unique ✅ but no format (`vin[:32]`, `chassis.py:175`); `job_number` free-text
  (`schemas/chassis.py:69`); `dealer_id` absent; `make` not required; **never set
  `production_jobs.chassis_record_id`** (the MICKEYTEST gap).

## Additional findings
- A **4th blind write path** — `update_chassis` (`chassis.py:210-219`) `setattr`s every field (incl.
  free-text `status`/`job_number`) with no validation. (Noted; route through the service in a follow-up.)
- **No VIN format validation exists anywhere** today — all paths only `.strip()[:32]`.
- **`capture_vin`** (`chassis.py:222-249`) is the correct write-once + 409-on-clash reference.
- **Atomicity:** AC must build on `create_expected_chassis` (flush; caller commits), NOT `create_chassis`
  (commits internally) — else chassis-insert and FK-update split across txns → partial-failure orphan.
- **`record_body_attached`** already auto-links `job.chassis_record_id` (`chassis.py:577`) under the
  planner-attested-VIN swap rule — any merge/relink must coexist with it.

## Decisive answers to the 3 BA concerns
1. **`deleted_at` vs `status='merged_into:{id}'`** → **`deleted_at` (nullable ts) + `merged_into_id`**, NOT
   a status sentinel (a sentinel poisons ~6 status-equality reads incl. `find_anchorless_chassis`). →
   **Migration 0025 IS needed.**
2. **Merge-into-placeholder vs v4.34.4 invariants** → **YES, Inv3.** An FK-swap that abandons a `status='expected'`
   placeholder makes it anchorless (dirties health-check) and can dangle the card link. **Resolution:
   update-in-place** (no FK move); reserve true FK-swap for admin Merge (re-points both job+card FKs, then
   soft-deletes the loser). Re-point, never delete a job (RESTRICT FK keeps Inv1/Inv2 clean).
3. **§0.11 orphan filter coverage** → **NO** — `created_via='manual_chassis_menu'` misses real orphans
   (unlinked `in_workshop`/`in_assembly`, PJ/AJ placeholders) and false-positives on fresh pending + merged
   rows. **Resolution:** unify with `find_anchorless_chassis` (one definition), drop the `created_via` gate
   (display-only), widen beyond `expected`, add `deleted_at IS NULL`.

## §0 deviations + rulings (BA-ratified 16-Jun)
- **D-VIN (ratified):** strict 17-char ISO-3779 enforced **new-write-only + NULL-exempt** (never re-validate
  stored rows); demo reseeded to conformant VINs in §3.7 + a read-only lint of non-conforming existing rows.
  (All current seed VINs + `MICKEYTEST123456` fail the regex.) NOTE: existing test fixtures that create via
  the validated path must use conforming 17-char VINs.
- **D1 (ratified):** `chassis_integrity` raises a domain `ChassisIntegrityError(ServiceError)` carrying
  422/409, mapped by a global app exception handler (not the absent "InvariantViolation").
- **D-merge (ratified):** re-point + soft-delete (`deleted_at`+`merged_into_id`), never hard-delete;
  swap-then-tombstone; clear the loser VIN before reuse (UNIQUE).
- **Orphan filter unify (ratified):** replaces `find_anchorless_chassis` → re-run the demo seed health gate
  after §3.2 (the highest regression-risk item).

## Process footnote (for ADR 0026)
- **Execution-environment-unavailable-mid-checkpoint:** report state explicitly as "written / verified
  pending" rather than waiting silently or assuming verification will pass. (Surfaced live when the platform
  command-safety classifier had a transient outage during the §3.3/§3.4 checkpoint.)
