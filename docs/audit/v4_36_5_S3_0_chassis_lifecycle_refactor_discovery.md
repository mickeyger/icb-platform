# v4.36.5 Chassis Lifecycle Refactor — §3.0 Discovery & Synthesis

> **Status:** Discovery complete (3 parallel subagents per §0.11). **§3.1 is GATED on 4 BA decisions below** —
> they determine the shape of migration `0028`. NO code, NO migration applied yet.
> **Base:** `feat/v4.36.5-chassis-lifecycle` @ `fd0b94e` (= `origin/main`). **Author:** CA4.

---

## 0. Headline

§3.0 found two **blockers** and a **premise re-scope** that change the sprint before any code:

1. **BLOCKER — "production edits own-assigned chassis" has no ownership column to check.** Neither `chassis_records` nor `production_jobs` has an assigned-user FK; assignment lives only on `tasks`/`work_orders` (many-per-job, ambiguous), and `'expected'` stubs/orphans have no job link at all. The headline authz rule is **unspecifiable** as written.
2. **BLOCKER — the drop-gate must live at the SERVICE chokepoint, not the router.** Chassis writes are service-to-service side-effects (Pre-Job submit + Planning-ack write `chassis_records` fields directly, bypassing the chassis router). A router-level 409 gate would either not fire or break the legit auto-create pipeline.
3. **PREMISE re-scope — 2 of the 4 named surfaces don't edit chassis at all.** QC writes *nothing* to chassis (its WO example workflow is fictional); Active Jobs / Job Card is *already* read-only with a Chassis-page link. The one true premise risk is **Planning-Ack**, where a hard redirect would break the planner's core intake loop.

The refactor's intent is sound; it's not implementable as written until #1 and #3 are decided.

---

## 1. Alembic chain pre-check (§0.17) — **0028 confirmed**

- **Current head = `0027`** (`backend/alembic/versions/0027_feedback_submissions.py`, `revision="0027"`, `down_revision="0026"`). Clean linear chain `0001→…→0027`, single head, nothing chains off 0027 yet.
- **My migration `0028` declares** `revision="0028"`, `down_revision="0027"` (bare zero-padded revision-id strings, not filenames).
- **`icb_mes` table count = 36** (`backend/tests/test_smoke.py:96` `assert n == 36`). If `0028` adds `chassis_records_audit`, **bump 36→37 in the model-introduction commit** (§0.16). Ownership/lock columns are ALTERs → no table-count change.
- ⚠ **WO doc inconsistency:** §0.2/§0.17 say `0028` (correct, matches the chain); §1/§2/§3/§4/§5/§6/§7 + the appendix still say `0029` (stale draft). **0028 is authoritative** — please standardize the WO. (No `0029` can exist yet; head is 0027.)
- No chain contention: CA1 v4.36c (`0029` off my `0028`, kickoff Mon 29 Jun) confirms head before committing; CA5 v4.37 needs no migration.

---

## 2. Real chassis-write map (the predicate) — gate at the chokepoint

Chassis-attribute mutation already funnels through `services/chassis.py`. The job is to gate by **source**, not by surface.

| Path | Where | Disposition |
|---|---|---|
| Chassis page Add / Edit / late-VIN | `create_chassis` / `update_chassis` / `capture_vin` (`services/chassis.py:217/324/438`) | **KEEP** — the master editor |
| Admin Merge / soft-delete / restore / retrofit-link | `services/chassis_merge.py`, `chassis.py:378/401` | **KEEP** (admin; the *sanctioned VIN-correction path* — the app's own copy points users here, `ChassisDetail.tsx:370`) |
| Bay lifecycle (status only) | `/assembly`,`/body-attached`,`/move-to-awaiting-qa`,`/return-to-parking` → status chokepoints | **EVENT-ONLY — exempt** (these ARE the workflow; do not sweep "status" into the edit gate) |
| **Pre-Job auto-create + sync** | `services/prejob_cards.py:98-175` writes `ch.make`/`ch.vin` directly on the stub it owns | **GATE at chokepoint** (system source, field-restricted) |
| **Planning-Ack propagation** | `services/production_jobs.py:406-445` writes **11 chassis fields directly** (`job_number`,`vin`,`dealer_id`,`make`,`customer_name`,…) — bypasses `update_chassis` | **biggest target** — route through chokepoint as `source="planning_ack"` |

**Catch — `chassis_eta` is NOT on `chassis_records`.** It lives on `ProductionJob` (`models/mes:113-115`). The "edit ETA" gate must target the production-job ETA write, not chassis_records.

**Predicate correction (Subagent C):** the WO's 4-surface list is **over-inclusive** (QC + Active Jobs edit no chassis) AND **under-inclusive** (misses Admin Merge, Find-Orphan, and the server-side Pre-Job/Planning-ack propagations). Re-scope around *"who writes `chassis_records` columns"* — the central editor `update_chassis`/`capture_vin`, with peripheral writers = Pre-Job, Planning-ack, Admin merge/orphan, lifecycle chokepoints. **Not** QC, **not** the read-only job card.

---

## 3. Premise check (§0.18) — per surface

| Surface | Verdict | Detail |
|---|---|---|
| **QC** (`QcFinalCheck.tsx`) | ✅ no work — **WO premise false** | Mock-only screen; writes nothing to chassis. "QC updating chassis status" workflow **does not exist**. Drop from scope. |
| **Active Jobs / Job Card** (`JobCardSections.tsx`) | ✅ ~no work | Already declares read-only + already links `Open Chassis page →`. Live state already matches the goal. |
| **Pre-Job card fields** (`PreJobCardModal.tsx`) | ✅ out of scope (with care) | Edits `chassis_make_model`/`vin` on the **PrejobCard**, not `chassis_records` (propagates at submit). These are *card* attributes; don't grey them or card-authoring breaks. |
| **Planning bay drags** (`BayModelLanes.tsx`) | ✅ exempt | Lifecycle *events* (status), route through chokepoints. Carve out explicitly. |
| **Planning-Ack panel** (`PlanningAckPanel.tsx`) | ⚠ **PREMISE RISK** | The planner captures **ETA (required — gates the Acknowledge button)** + VIN/make/dealer/customer in one ack gesture; the chassis may be a just-minted stub. A hard redirect breaks the core intake loop. **Recommend: keep inline, write through the central chassis service (it mostly does), lock only attested fields.** It already uses the shared `ChassisFieldsForm` — small change, not a rebuild. |

**Silent-deferral lever (§0.10/§0.20):** the read-only affordance is **centralized** — `ChassisFieldsForm.tsx` is the one shared chassis-field component (Chassis page + Planning-ack). Add an `editLocus="Chassis page"` hint to its `Locked` renderer **once** → every surface inherits the greyed-pencil + "Edit on Chassis page" tooltip the WO mandates (vs a silent-disabled input = a §0.10 defect). Also convert two existing silent no-ops to visible messages: the adopt-path make/VIN drop (`prejob_cards.py:154-163`) and the ack VIN skip — extend the ADR 0026 H6 / 0027 "no silent no-op" posture, don't regress it.

---

## 4. Blockers & design items (Subagent B, code-grounded)

- **BLOCKER 1 — ownership model.** `chassis_records` has no owner FK (`models/mes:752-803`); `ProductionJob` has no assignee FK (`:63-108`); assignment is on `tasks`/`work_orders` (many-per-job); stubs/orphans have no job link. "Production edits own" is undefinable → fail-open (IDOR) or fail-closed (production can't fix stubs). **Decision needed (Q1).**
- **BLOCKER 2 — gate at `update_chassis`, not the routers.** Enforce via a shared `_apply_chassis_fields(rec, data, actor, source)` with a `source` flag: `chassis_page` → role/ownership-gated; `planning_ack`/`system_autocreate` → allowed, field-restricted. Audit every `ChassisRecord(` / `chassis.<col>=` / `setattr(chassis` site against the allowlist. (This is the correct approach — I'll build it this way unless you object.)
- **HIGH — 409 redirect contract needs a frontend change.** `lib/api.ts:53` parses only `body.detail` and throws it away; `ApiError` is string-only. The `{redirect_to, reason}` payload **can't reach the UI** until `ApiError` carries the JSON body. Then the client must navigate **only** after an allowlist check: `reason==='chassis_records_master' && /^\/chassis\/\d+$/.test(redirect_to)`. Server builds `redirect_to=f"/chassis/{rec.id}"` from the trusted id (never user input) → no open-redirect.
- **HIGH — optimistic lock.** `update_chassis` is read→setattr→commit with no version/`If-Match` and no `with_for_update`. Concentrating all edits on one page **raises** contention (two planners, or planner + ack sync) → silent last-write-wins. Add a `version` column (or `If-Match` on `updated_at`) → 409 "edited by someone else, reload". (Affects the `0028` shape.)
- **MEDIUM — audit retention.** Whichever option, name a retention/archive policy now (the existing `ProductionJobAudit` has none). A dedicated table prunes/partitions cleanly; JSONB-on-`chassis_records` bloats the hot row (read on every Chassis-page load).
- **LOW — status validation.** `ChassisRecordUpdate.status` is free-text, no DB CHECK, flows through the setattr loop. Once the Chassis page is sole editor exposing status, a typo desyncs every status-keyed derivation. Recommend: keep generic PATCH from writing `status` at all (status moves only via lifecycle chokepoints), or 422 on unknown.

---

## 5. Audit-table recommendation → **dedicated `chassis_records_audit` table** (if audit ships)

Per-field history (chassis_id, field, old, new, edited_by, ts) is inherently row-per-change — a table indexes it; JSONB doesn't. It keeps unbounded history **off** the hot `chassis_records` row, and is a near-mechanical clone of the established `ProductionJobAudit` (migration `0023`) pattern (cross-schema `user_id` SET-NULL FK, snapshot `user_name`, `(chassis_id)`+`(created_at)` indexes). Cost: the smoke 36→37 bump (§0.16). JSONB (the v4.38 `status_history` precedent) is right for a low-volume single row, not a high-cardinality master table. Audit is "optional" per the WO — **decision needed (Q3).**

## 6. Role-filter pattern (continue v4.36b)
Service-layer role filter as a **code constant** (`services/visual_integrity.py:111-129`), NOT new permission keys (a permissions migration would collide with the held `0028`). `user_can`/`require_perm` in `deps.py:104-142`; admin bypasses. Mirror for chassis edit (`edit_any` admin/planner vs `edit_own` production) once Q1 settles the ownership source.

---

## 7. Decisions (BA, 2026-06-25) — RESOLVED → §3.1 unblocked

1. **Production edit (Q1) → admin/planner edit; production READ-ONLY.** No ownership column; `0028` skips the assignee FK. Production keeps its existing bay/lifecycle status events; no attribute edit, no IDOR surface.
2. **Planning-Ack (Q2) → keep INLINE** (write through the central chassis service + lock attested fields). NOT a hard redirect — preserves the planner intake loop (ETA gates Acknowledge).
3. **Audit (Q3) → ship the dedicated `chassis_records_audit` table now** (clone of ProductionJobAudit/0023). Smoke 36→37 in the model-introduction commit (§0.16).
4. **Scope trim (Q4) → CONFIRMED.** QC + Active Jobs drop out (no chassis edits); Pre-Job *card* fields stay (card attrs, not chassis). Budget → the chokepoint gate, Planning-Ack, Admin Merge/Find-Orphan exceptions, and the centralized `ChassisFieldsForm` affordance.

**Locked `0028` shape** (`down_revision="0027"`): (a) NEW `chassis_records_audit` table — `chassis_id` FK (CASCADE), `field_name`, `old_value`, `new_value`, `edited_by_user_id` (cross-schema SET-NULL FK like ProductionJobAudit), `edited_by_name` (snapshot), `created_at`; indexes `(chassis_id)` + `(created_at)`. (b) ALTER `chassis_records` ADD `version Integer NOT NULL DEFAULT 0` (optimistic lock). **Smoke 36→37** (the new table). No ownership/permissions column.

**§3.1 plan:** migration `0028` (above) + a shared `_apply_chassis_fields(rec, data, actor, source)` chokepoint in `services/chassis.py` — `source="chassis_page"` role-gated (admin/planner `edit_any`; production blocked → 409 + redirect payload); `source="planning_ack"`/`"system_autocreate"` allowed + field-restricted. Route `record_planning_ack`'s 11 direct writes through it; emit an audit row per changed field. Optimistic-lock compare in `update_chassis` (stale `version` → 409 reload). Keep `status` off the generic PATCH. Frontend (§3.3): extend `ApiError` to retain the 409 JSON body + allowlist `/^\/chassis\/\d+$/`; add the "Edit on Chassis page" affordance to `ChassisFieldsForm`'s `Locked` renderer (one change, all surfaces).

### Click-to-verify
- Branch — `git -C C:/Users/micge/Documents/icb-platform-v4.36.5 status` → `feat/v4.36.5-chassis-lifecycle` @ `fd0b94e`
- Alembic head — `ls backend/alembic/versions | tail -1` → `0027_feedback_submissions`; `rg "down_revision" backend/alembic/versions` → nothing chains off 0027
- ETA-not-on-chassis — `models/mes/__init__.py:113-115` (`chassis_eta` on ProductionJob)
- QC writes nothing — `rg "api(Patch|Post).*chassis" frontend/src/screens/QC` → 0 hits
- Gate target — `services/production_jobs.py:406-445` (11 direct chassis-field writes)
- 409 contract gap — `frontend/src/lib/api.ts:50-58` (only `detail` retained)

*Generated 2026-06-25 for the v4.36.5 §3.0 checkpoint. §3.1 held pending the 4 decisions above.*
