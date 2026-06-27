# v4.36c §3.0 — Kenny QC + Dispatch (MVP) — Discovery Synthesis

**Sprint:** WO v4.36c (Kenny QC + Dispatch MVP) · **Ship target:** Sat 4 Jul 2026 · **CA:** CA1
**Base:** `main` @ `fd0b94e` (alembic head `0027`) · **Branch:** `feat/v4.36c-kenny-qc-dispatch`

## Method note (§0.13 / §0.14)
Three parallel subagents ran the §3.0 mini-discovery:
- **Subagent A** — scope/codebase map + §0.18 alembic chain pre-check + §0.19 smoke-bump audit.
- **Subagent B** — adversarial review (security, edge cases, race conditions).
- **Subagent C** — silent-deferral audit (§0.12) + §0.20 premise-vs-predicate on every §1 item.

CA1 then re-verified the two findings that the subagents conflicted on, against git ground truth (the alembic claim) and the deeper auth mechanism. This synthesis reconciles all three + the CA1 verification. Every claim is `file:line`-grounded.

---

## §1 — Alembic chain pre-check (§0.18) — **#1 BA coordination item**

**Ground truth (CA1-verified):**
- `main` head = `0027` (`backend/alembic/versions/0027_feedback_submissions.py`); chain 0023→0027. No 0028 on main.
- **CA4 v4.36.5 §3.0 is committed** (`92f2a68` on `origin/feat/v4.36.5-chassis-lifecycle`, "discovery + synthesis", 25 Jun 15:58) and **claims migration 0028**, but **no `0028` migration FILE exists on any ref** — CA4's §3.1 is "gated on 4 BA decisions" (per the engagement ledger), so the migration is planned-but-unbuilt. CA4 ships **~1 Aug**.
- v4.36c ships **4 Jul** — *before* CA4.

**The trap:** "no `0028` file exists yet" ≠ "0028 is free." CA4 has *claimed* 0028 in committed discovery — the same own-by-claim situation as the v4.36b §3.5 0027 collision. But the WO's planned sequencing (§0.2/§5: "CA4 holds 0028, v4.36c takes 0029") assumed CA4 ships/builds first. **They don't** — they're pre-§3.1 and ship a month later.

**Why v4.36c=0029 is NOT viable:** alembic requires the `down_revision` parent to exist before a migration can apply. A v4.36c `0029` with `down_revision="0028"` cannot `upgrade head` until CA4's 0028 exists (~1 Aug) → v4.36c would be **blocked past its 4 Jul ship date**.

**RECOMMENDATION (BA to ratify + coordinate with CA4):** v4.36c takes **`0028`, `down_revision="0027"`** (migration order follows *ship* order — v4.36c ships first). CA4, being pre-§3.1 and unbuilt, rebases their claim to **`0029`** (a one-line `down_revision` change for them). This unblocks v4.36c's date and avoids the double-0028 collision **only if BA coordinates the swap with CA4 before v4.36c commits its migration.** This is the mandatory §0.18 cross-CA surface — do not commit the migration until CA4 confirms the swap.

*(WO internal inconsistency noted: §0.2/§5 say 0029; §2/§3.1 say 0028. Resolved above by ship-order, not by either WO number verbatim.)*

---

## §2 — Premise corrections (§0.16 / §0.20) — WO-vs-code mismatches, all 3 subagents concur

These are code-grounded corrections where the WO's premise does not match the codebase. Per §0.16 (ratify-default on code-grounded reasoning), surfaced for BA ratification.

### 2a. §0.8 / §1.10 / §4 — "WeasyPrint Pre-Job PDF infrastructure" is **WRONG**
- `requirements.txt:7-8`: *"weasyprint → not present… reportlab/pypdf is the active PDF path."* The only `import weasyprint` (`exports.py:461-463`) **raises `RuntimeError("WeasyPrint is not installed.")` by design.**
- The actual Pre-Job PDF is **reportlab**: `app/services/prejob_pdf.py:1` (*"reportlab — the house PDF path; no weasyprint"*) → `render_prejob_pdf(...) -> bytes`, served via `RawResponse(media_type="application/pdf")` (`routers/prejob_cards.py:103-116`).
- `app/pdf/builder.py` (cited in §0.8/§1.10) **does not exist.**
- **Correction:** build the collection note as `app/services/customer_collection_pdf.py` modeled on `prejob_pdf.py` (reportlab `SimpleDocTemplate`, reuse `_esc`), served via the `RawResponse` pattern. **The §4 "Pango version mismatch" risk row is moot** (no WeasyPrint/Pango in play).

### 2b. §1.4 / §0.22 — `chassis_records.status` is **not an enum**; `'dispatched'` is **zero-migration**
- `models/mes/__init__.py:771` → `status = Column(String(24), …)`. Allowed values are in a **comment** (`:772-774`) and **already list `dispatched`**. File header (`:26-27`) says VARCHAR is used *"to avoid native PG ENUM churn in migrations."*
- Frontend already maps it: `CHASSIS_STATUS_STYLE.dispatched` (`types.ts:93`), `ChassisList` filter (`:52`), `JobCardSections.tsx:264`.
- **Correction:** §1.4 needs **no migration and no DDL** — adding `'dispatched'` is the same code-only value-add as v4.35's `'awaiting_qa'`. **Strike §1.4 from migration scope;** the migration carries only the 3 new tables.

### 2c. §0.4 / §1.11 — role/permission mechanism is **mis-described** (Subagents B+C; CA1-confirmed)
- §0.4 says "role-to-permission mapping is a module-level constant, not DB-table." **In this codebase, write-authorization is DB-table-driven**: `user_can` joins `RolePermission`→`Permission` by role (`deps.py:87-113`); the catalogue is `database.PERMISSION_CATALOGUE` (`:1726+`); chassis WRITE routes gate on **permission keys** via `require_permission("chassis.assembly_assign")` etc. (`routers/chassis_records.py:124,132,143,153`).
- The v4.36b `_ROLE_GROUPS` precedent §0.4 cites (`visual_integrity.py:111`) is a **read-display filter** on `require_user`-only endpoints — **not a write gate.** There is no generic `require_role()` factory.
- **Correction / decision needed:** the codebase-native way to gate the QC **writes** (signoff, per-category verdict) and the admin defect-categories CRUD is **permission keys** (`qc.inspect`, `qc.signoff`) seeded into `PERMISSION_CATALOGUE` + granted to a new `qc_inspector` role — exactly as `chassis.assembly_assign` is seeded (`alembic 0016:51-52`). v4.36c **already adds a migration** (the 3 tables), so seeding qc.* keys there is cheap + consistent → **§0.4's "no permissions migration" is moot.** The alternative (an explicit in-handler `if role not in {…}: 403`) is a deliberate divergence. **Recommend: permission keys (native pattern).** Either way, defect-categories CRUD = `require_admin` (every admin DDM router is, `routers/admin/__init__.py`).

### 2d. §0.19 — held-migration smoke-bump mechanism is **FALSE for this repo** (Subagent A)
- §0.19 assumes CI runs `Base.metadata.create_all()` (so model registration alone bumps the table count). **It does not:** `create_all()` was removed (`database.py:944-948`); CI builds the test DB via `alembic upgrade head` (`.github/workflows/ci.yml:76-81`); `test_smoke.py:66-67` counts **real migration-created** tables in `icb_mes`.
- **Correction:** the `test_smoke.py` count and the migration that creates the tables are **coupled** here. Bumping the smoke count on model-registration *before* the migration applies turns **CI red**. Correct sequencing: **the `test_smoke.py` 36→39 bump ships in the SAME commit as the 0028 migration** (not the model-introduction commit). Model registration in `models/mes/__init__.py` alone does nothing for the count.

### 2e. §1.15 — "new column" on the Planning Board is the **wrong layout model** (Subagents A+C)
- The board uses **full-width stacked zones**, not columns: `AwaitingQAZone` is a `<Card className="col-span-2">` (full width) below the 2-col Parking/Assembly row (`BayModelLanes.tsx:387,645-731`).
- **Correction:** the Dispatch zone is a **third full-width zone** below Awaiting QA, a near-copy of the `AwaitingQAZone` block (`:641-731`, `data-testid="awaiting-qa-zone"`), fed by a new `list_dispatched` + `GET /api/chassis-records/dispatched` + a `dispatched` array in `useBayModel`. Dispatch is **NOT a `BayState`** (`types.ts:109` — the 6-state bay machine has no `dispatched` member); it's a chassis zone like QA.

---

## §3 — Schema-shaping decisions (must precede §3.1 migration)

### 3a. **Inspection-cycle discriminator is MISSING** (Subagents B+C) — highest-impact schema decision
§1.2 `qc_inspections (chassis_id, category_id, verdict, notes)` has **no cycle key**, but §1.7 says "idempotent within inspection cycle" and §1.8 fail→`awaiting_qa` allows **re-inspection**. Without a cycle discriminator, a re-inspection's per-category write **overwrites the prior (failed) cycle's row** → destroys the immutable audit trail (§0.6 violation) and makes "one row per category per cycle" (§1.2) impossible.
- **Decision:** add `cycle_number` to `qc_inspections` + `qc_signoffs`, populated from the chassis's current lifecycle cycle (`_latest_cycle`, `chassis.py:793-795`; mirrors `chassis_lifecycle_events.cycle_number`). §1.7 overwrite scoped to `(chassis_id, category_id, cycle_number)`. This also enables the unique-index idempotency backstops below.

### 3b. Sign-off completeness — **enforce server-side** (§0.12/§0.17; Subagent B E2)
§3.2 gates the sign-off button client-side ("all categories have a verdict"). The **endpoint must enforce it too** (the codebase's "backend is source of truth, UI surfaces the 409" posture, `chassis.py:973-974`): on signoff, count distinct verdicted `category_id` in the open cycle vs `COUNT(*) FROM defect_categories WHERE is_active` → 422 if `<`. Definition: **active-at-signoff** categories; form re-fetches categories on load.

### 3c. Mid-inspection category change + immutable record (Subagent B E3)
Admin renames/deactivates a category while Kenny is mid-form. **Denormalize `category_name` onto the `qc_inspections` row at record time** so the immutable record preserves what Kenny saw (rename-safe, §0.6-faithful). Completeness keys on active-at-signoff categories.

### 3d. §1.9 DELETE vs §3.3 "deactivate not delete" — **WO contradiction** (Subagent B E4)
§1.9 lists `DELETE`; §3.3 says "not delete — preserve audit trail." A hard delete of a category referenced by `qc_inspections.category_id` orphans/destroys audit. **Resolve: the DELETE route soft-deactivates (`is_active=False`); never hard-delete a referenced category** (mirror `soft_delete_chassis`'s FK-guard refuse, `chassis.py:415-428`).

### 3e. §1.16 — customer PDF persistence is **unspecified** (Subagent C)
reportlab returns bytes in-memory; a later "download when `status='dispatched'`" link needs a source. **Decide:** (a) persist the bytes (file_store, à la `file_store.save_chassis_photo` `chassis.py:1052`) + link fetches that, or (b) regenerate on-demand from the immutable `qc_signoff` row. **Recommend (b)** (regenerate) — simplest, no new storage, and the signoff row is immutable so the PDF is reproducible.

---

## §4 — Adversarial findings (Subagent B) — security / edge / race

| ID | Finding | Sev | Mitigation (mirror) |
|----|---------|-----|---------------------|
| S1 | Double sign-off / replay → 2 signoff rows, 2 status flips, 2 PDFs | HIGH | status-precondition-as-idempotency-key (`if status != 'awaiting_qa': 409`, mirror `record_moved_to_awaiting_qa` `chassis.py:878`) + partial unique index on `qc_signoffs(chassis_id, cycle_number)` |
| S2 | IDOR — any qc_inspector writes verdict/signoff on any `chassis_id` | MED-HIGH | server-side `db.get`→404, `deleted_at`→409, `status != 'awaiting_qa'`→422 (mirror precondition stack `chassis.py:873-890`). MVP: any qc_inspector may inspect any awaiting_qa chassis (no per-inspector ownership) — **state it explicitly** (the §0.20 premise on `inspector_user_id`) |
| S3 | /api/qc/* writes have no role-gate precedent; §0.4 conflict | HIGH | permission keys (§2c) + `require_admin` on defect-categories CRUD; journey test asserts non-qc_inspector → 403 |
| S4 | Immutability (§0.6) drift risk | MED | no UPDATE endpoint + §1.7 refuses post-signoff (409 "start a new inspection", mirror `clear_panels_arrived` `chassis.py:1029`) + test asserts no mutation after signoff |
| E1 | Bodiless chassis at awaiting_qa → dispatched + customer PDF | MED | defensive `_has_event(body_attached, cycle)` in signoff (`chassis.py:798`) |
| E2 | Signoff with incomplete verdicts (UI-gated only) | HIGH | §3b server-side completeness check |
| E5 | fail→re-inspect overwrites prior cycle's rows | HIGH | §3a cycle discriminator |
| R1 | Two inspectors signing off same chassis concurrently | HIGH | **`with_for_update()` row-lock** — mirror `record_planning_ack` (`production_jobs.py:355`), **NOT** the lock-free chassis transitions (which have no lock + no unique constraint — CA1 confirmed) |
| R2 | Concurrent per-category writes / lost update | MED | §1.7 as single-statement UPSERT on `(chassis_id, category_id, cycle_number)` (mirror `assign_assembly_bay` UPSERT `chassis.py:579-586`) |
| R3 | Signoff racing CA4 v4.36.5 master-record edits | MED-HIGH | every `chassis_records` row-mutator takes `with_for_update()` — **CA4 coordination item** (alongside the alembic swap) |

**§1.8 fail-loop premise (Subagent C):** fail→`awaiting_qa` returns the chassis to Kenny's own inbox, indistinguishable from never-inspected unless the failed `qc_signoff` persists AND the inbox surfaces "failed Nx". Acceptable MVP debt **only if** the fail audit row is retained + the inbox shows prior-fail state. Confirm or accept as explicit debt.

---

## §5 — Silent-deferral audit (§0.12; Subagent C) — **CLEAN, no third instance**
No new workflow-critical `if not X: return` defect found. The two prior catches remain reversed with "do not restore" guards (`prejob_cards.py:140-144`, `production_jobs.py:264-269`). The awaiting_qa ingestion + transition + zone-render paths raise (never silently drop) a QC-relevant case. **One note for §3.5:** `useBayModel.refresh` swallows ALL errors into empty `mock` mode (`useBayModel.ts:67-73`) — a new dispatch-zone fetch added to the same `Promise.all` must be resilient, or a dispatch hiccup blanks the QA zone too.

---

## §6 — Reuse map (what to mirror, file:line)
- **Status value-add** ('dispatched'): transition chokepoint `record_moved_to_awaiting_qa` (`chassis.py:860`); list service `list_awaiting_qa` (`:902`); KPI already counts dispatched (`production_jobs.py:524`); frontend pill/filter already present (`types.ts:93`, `ChassisList.tsx:52`).
- **Dispatch zone**: `AwaitingQAZone` block (`BayModelLanes.tsx:641-731`) + `GET /awaiting-qa` (`chassis_records.py:60`) + `useBayModel` `awaitingQa` array.
- **Admin DDM**: flat-CRUD resource like `fridge-units` (`adminResources.ts:121-140`) — add a `ResourceConfig` + append to `ADMIN_ORDER:180`; **no `AdminModule.tsx`/`App.tsx` edit, no custom screen.** Backend: mirror `routers/admin/fridge_units.py` (`require_admin`) → new `routers/admin/defect_categories.py`, register in `main.py`.
- **PDF**: `app/services/prejob_pdf.py` (reportlab) + `RawResponse` serve (`prejob_cards.py:103-116`).
- **Role filter (reads)**: `_ROLE_GROUPS` module constant (`visual_integrity.py:111`) for narrowing QC read responses; **permission keys** for writes (`require_permission`, seed in `PERMISSION_CATALOGUE`).
- **Concurrency**: `record_planning_ack` `with_for_update()` (`production_jobs.py:355`) — the ONE locked-transition precedent.
- **Immutable record shape**: `SignOff` model (`models/mes/__init__.py:196-210`) + append-only `ProductionJobAudit` (`:287`).
- **AgeingPill** on awaiting_qa age: `AgeingPill.tsx:9` (already documents `awaiting_qa_stale green=3/amber=6/red=7`); the `awaiting_qa_stale` flag already exists with remediation text "Kenny inspection priority (v4.36c)" (`visual_integrity.py:75-77`).

## Other notes
- **Smoke baseline:** `test_smoke.py:96` asserts `36` → bumps to `39` (+3 tables), **in the migration commit** (§2d). Stale "=32" docstring (`:58-62`) worth fixing same commit.
- **qc_inspector reachability:** `/admin/*` React routes gate on `isAdmin` (`AdminModule.tsx:33`). For the §3 click-through ("qc_inspector → /admin/qc accessible, other admin restricted"), `/admin/qc` needs a carve-out OR qc_inspector design — **§3.2 decision.**
- **User-role assignment:** `routers/users.py:86-87,107-108` hardcodes the assignable role whitelist to `user|full|admin` — there's no API path to assign `qc_inspector`. §3.7 seeds Kenny via DB; a second inspector needs the whitelist extended (decide in §3.1).
- **v4.36d Cockpit stash present** (untracked `frontend/src/screens/Planning/cockpit/`) — §3.5 dispatch-zone work coordinates with v4.36d per §4 risk row.
- **§5 CA4 constraint honored:** v4.36c adds NO columns to `chassis_records` (only the FK-linked `qc_inspections.chassis_id` / `qc_signoffs.chassis_id` + the zero-migration status value).

---

## §7 — Decisions for BA ratification (before §3.1 fires)

1. **Alembic (§1 above):** v4.36c takes **0028 off 0027** (ships first); **BA coordinates CA4 to move their claim to 0029** before v4.36c commits the migration. (Alternative 0029-off-CA4-0028 blocks the 4 Jul ship.)
2. **Role/permission (§2c):** ratify **permission keys** (`qc.inspect`/`qc.signoff` in `PERMISSION_CATALOGUE`, seeded in the 0028 migration) + new `qc_inspector` role — accepting that §0.4's "no permissions migration" premise was wrong (there's a migration anyway). Defect-categories CRUD = `require_admin`.
3. **Premise corrections (§2a/2b/2e):** ratify reportlab (not WeasyPrint) PDF; strike §1.4 from migration (status is VARCHAR, value already present); Dispatch = full-width zone (not "column").
4. **Schema shape (§3a–3e):** ratify the **cycle_number** discriminator on `qc_inspections`/`qc_signoffs`; server-side completeness check; denormalized `category_name`; DELETE→soft-deactivate; PDF regenerate-on-demand.
5. **Concurrency (R1/R3):** ratify `with_for_update()` on the signoff transition (copy `record_planning_ack`, not the lock-free transitions) + the CA4 coordination that chassis_records mutators lock.
6. **§1.8 fail-loop:** confirm failed `qc_signoff` persists + inbox surfaces prior-fail, or accept the loop as explicit MVP debt.
7. **§0.19 correction:** ratify that the smoke bump (36→39) ships in the **migration commit**, not the model-introduction commit (create_all is removed; CI is migration-built).

## Click-to-Verify (this phase)
§3.0 is discovery only — **no routes/UI changed.** Verifiable artifact: this document (`docs/audit/v4_36c_S3_0_kenny_qc_dispatch_discovery.md`). Next phase (§3.1) will list `/api/qc/*` + the migration for click-verify.

---
*Subagent transcripts available on request (A: scope/alembic; B: adversarial; C: premise-vs-predicate). CA1 re-verified the alembic claim (git) and the auth mechanism (deps.py/PERMISSION_CATALOGUE) where the subagents diverged.*
