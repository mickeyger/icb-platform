# ADR 0028 — Kenny QC + Dispatch: the QC chokepoint, derived verdicts, DB-keyed authz (v4.36c)

- Status: Accepted
- Date: 2026-06-27
- Work Order: v4.36c — Kenny QC + Dispatch (MVP) (Phase 3 of the v4.36 trilogy; ship 4 Jul 2026)
- Builds on: ADR 0025 (event-derived state + the body_attached → awaiting_qa chokepoint this extends),
  ADR 0023 (integrity invariants + Tier-2 demo-reset discipline), ADR 0016 (DB-keyed permissions +
  per-role journey testing), ADR 0027 (visual-integrity `AgeingPill`, reused in the QC inbox),
  ADR 0015 (chassis lifecycle + the `_latest_cycle` this deliberately does NOT reuse), ADR 0011
  (`icb_test` not locally provisionable → DB/journey tests execute on CI).

## Context

v4.36a/b made the floor state correct and visible up to `awaiting_qa`: a body is attached, the chassis
moves off its bay into the Awaiting-QA queue. But the queue had **no consumer** — nothing turned "awaiting
QA" into "released to the customer". v4.36c adds the **QC chokepoint**: Kenny opens an inbox of chassis
awaiting QA, runs a five-category inspection, and signs off. A **pass** transitions the chassis to
`dispatched` and makes a customer collection note available; a **fail** returns it to the queue for
re-inspection, the QC attempt counter incrementing. This is an MVP by design — one inspector role, a flat
five-category form, an immutable sign-off, a summary PDF — narrow so it ships for the 4 Jul Burt/Deon demo
and the 10 Jul Phase-1 launch.

The sprint ran in parallel with CA4's v4.36.5 (chassis-record audit) and CA5's v4.37 (native cost calc) on
the shared repo + `icb` DB, so two through-lines shaped it beyond the feature: **alembic ship-order
coordination** (a migration number is assigned by SHIP order, not start order — §0.18; v4.36c ships first so
it takes `0028` off `0027`, and CA4's `0029` re-points its `down_revision` to `0028`) and **lane separation**
(no `App.tsx` / `TopNav` / `Layout` contention). Twenty §0 locks framed it; §3.0 discovery re-specced several
premises against the real code (`docs/audit/v4_36c_S3_0_kenny_qc_dispatch_discovery.md`). Every decision
below was ratified at a §8 checkpoint — the footnote ledger records the code-grounded corrections that
compounded along the way.

## Decisions

1. **The QC sign-off is a single, locked, status-promoting chokepoint.** One write — `POST /api/qc/signoff/{chassis}` — is the only door from `awaiting_qa` to `dispatched`. It runs under `with_for_update()` on the chassis row (mirroring `record_planning_ack`, the one prior locked-transition precedent — NOT the lock-free chassis transitions), so two concurrent sign-offs serialise and the double-sign-off backstop (a unique `(chassis_record_id, cycle_number)` on `qc_signoffs`) never has to fire on a race. The sign-off is **immutable**: there is no edit/delete path; a wrong verdict is corrected by a *new* QC cycle, not by mutating history. Per-category verdicts (`POST .../category/{id}`) are an UPSERT (`on_conflict_do_update` on the cycle key) so re-clicking a category within an open cycle is idempotent, but the service **refuses any verdict write once the cycle is signed off** (409/422).

2. **`cycle_number` is the QC-attempt counter, NOT the chassis lifecycle cycle.** A chassis's `_latest_cycle` (ADR 0015 — VCL/DCL booking cycles) does not advance on a QC fail, so the QC domain keeps its own counter: `cycle_number = 1 + max(qc_signoffs.cycle_number for the chassis)`. A fail sign-off closes cycle *n* and the next inspection opens cycle *n+1*; the inbox shows `failed Nx`. Conflating the two would mis-count (a re-inspection is not a re-booking) and couple two independent state machines. This was the first ratified §3.0 design call.

3. **`overall_verdict` is DERIVED from the per-category verdicts, never inspector-supplied.** The sign-off computes `overall_verdict = 'fail'` iff ANY active category is `fail`, else `'pass'` — Kenny never picks an overall result. This makes the outcome deterministic and **eliminates a whole UX defect class** ("click pass-overall while a category is still failed"). The per-category verdicts are the single source of truth; the sign-off completeness check (every active category must carry a verdict, else 422) runs server-side, not in the form.

4. **Authorization is DB-keyed (`require_permission` + migration-seeded grants), not a module constant.** The §0.4 premise — "gate on a module-level role constant" — was corrected at §3.0 §2c against the codebase-native pattern: writes gate on `require_permission("qc.inspect")` / `require_permission("qc.signoff")`, whose keys + role grants are seeded **in migration 0028** (the 0016 precedent — a permission ships with the feature it gates; `INSERT ... ON CONFLICT DO NOTHING` so it survives `_bootstrap_permissions`, which is additive-only and never deletes). Grants: `qc.inspect` → `qc_inspector` / `planner` / `production`; `qc.signoff` → `qc_inspector` only; `admin` is a code-level wildcard. The dispatch-zone read gates on `require_user` (shared planning data, not a QC write). For QC, the permission gate is the **single load-bearing layer** — contrast the v4.36.5 chassis-edit case (ADR 0030), where a service role-gate sits ON TOP of a permission that `production` also holds; there, the role-gate is load-bearing. When reusing this pattern, verify *which* layer actually blocks (see `[[feedback-verify-permission-grants]]`).

5. **The defect-category taxonomy is admin-editable, so the audit snapshots the name and soft-deactivates.** Categories are a flat-CRUD admin DDM (`/admin/defect-categories`, `require_admin`); the five defaults are migration-seeded (`created_by='migration_0028'`). Two consequences follow: (a) `qc_inspections.category_name` is **denormalized at record time** — a write-time snapshot — so renaming or retiring a category never rewrites history (the same principle as CA4's audit `edited_by_name`, ADR 0030 / `[[feedback-audit-denormalize-name-snapshot]]`); and (b) DELETE **soft-deactivates** (`is_active=False`, 204) rather than hard-deleting — the `category_id` FK is `RESTRICT`, and inactive categories must survive for historical inspections while dropping out of the active form.

6. **The inspection form is a query-param view (`?chassis=`), not a new route.** `/admin/qc` is one screen with two views: no param → the inbox, `?chassis={id}` → the inspection form. This keeps QC inside the existing `/admin/:resource` dispatcher — **no `App.tsx` route edit** (lane separation) and, deliberately, **no new path segment** that would re-introduce the v4.38.1 deep-link 404 trap (a fresh sub-route needs routing + the auth-guard deep-link handling). The lesson was applied preemptively at §3.2.

7. **The customer collection note is summary-only and regenerated on demand.** The PDF (reportlab — the house path; WeasyPrint is not installed; `prejob_pdf.py` is the reuse model) carries VIN / customer / body type + dimensions / inspection date / inspector + **one** "inspection passed — released for collection" line + a signature block. It **excludes** the per-category breakdown, defect notes, and the inspector's role (§0.8): defect detail is internal, and the admin-editable taxonomy must not leak into a customer document as an implied commitment. There are **no stored bytes** — `collection_note_pdf` regenerates from the immutable pass sign-off each request (404 if the chassis is gone, 409 before a pass exists).

8. **The dispatch FEED ships in v4.36c; the dispatch ZONE is deferred to v4.36e.** `list_dispatched` + `GET /api/qc/dispatched` (gated on `require_user`) ship and are CI-proven. The Planning-Board dispatch *zone* (rendering that feed) deterministically destabilised seven planning-board journeys ("slot-cell not stable" — a flex-layout coupling: the bay-model column squeezes the `flex-1` week grid). Rather than guess-and-check blind (the journeys can't run locally, ADR 0011), the zone is deferred to **v4.36e** to land against the v4.36d Cockpit layout (not the about-to-be-replaced one), with a Playwright **trace-upload** added as engagement infrastructure to kill the local-blind-spot. The dispatched chassis is therefore reachable in v4.36c via the feed endpoint and its Chassis-detail "Download collection note" link, but renders on no Planning-Board surface yet. See `[[feedback-blind-debug-get-traces]]`.

9. **Schema: three `icb_mes` tables in migration 0028, smoke-count bump in the migration commit.** `defect_categories`, `qc_inspections`, `qc_signoffs` are model-declared and created via guarded `create_all` (the 0027 pattern); `inspector_user_id` is a plain Integer with a cross-schema FK to `icb_costings.users` created **in the migration** (`SET NULL` — a sign-off outlives a user delete). `chassis_records.status` gains `'dispatched'` as a **VARCHAR value-add only** (no DDL — the column is already free-text; §3.0 §2b). Per §0.19 (corrected for this repo: `create_all` was removed from init, so CI builds the test DB via `alembic upgrade head`), the `test_smoke.py` table-count assertion rises **in the migration commit** (36 → 39 for the three QC tables), not the model-introduction commit.

10. **Tests execute on CI (`icb_test`); the role matrix is API-level, the UI flow is a journey.** The hard db-guard refuses local non-`_test` DBs (ADR 0011), so DB-backed tests run on CI. The **role matrix** (the 0028 grants × inspect/sign-off, for `qc_inspector` / `planner` / `production` / `sales`) is asserted at the API level via `dependency_overrides[require_user]` + `require_permission` — precise and cheap. The **UI flow** (`test_qc_inspection_journey`) drives `/admin/qc` as the real `qc_inspector` role through the browser (also proving the AdminModule QC-roles carve-out lets a non-admin reach the screen): inbox → inspect → pass→dispatch+PDF, and fail→stays+cycle-increment. (A journey gotcha banked: `qc-form` doubles as the loading skeleton, so a non-retrying `.count()` must gate on a content selector past the skeleton — `[[feedback-blind-debug-get-traces]]` test-design corollary.)

## Consequences

- **The QC sign-off is the one gate** from `awaiting_qa` to `dispatched`; the collection note is the single customer artifact, always consistent with the sign-off because it is regenerated from it.
- **The flow is auditable and deterministic**: an immutable per-cycle sign-off, a derived verdict, a snapshotted category name, and a DB-keyed role model mean "who passed what, when, against which taxonomy" is answerable from the data alone.
- **One surface is deferred** (the dispatch zone — a visibility nicety, not the critical path), carrying with it the trace-upload infrastructure that benefits every future blind-journey debug.
- **The demo dataset is reproducible**: `seed_v4_36c_demo_reset.py` (extends v4.36b, leaves the migration-seeded categories untouched, idempotent via the chassis `CASCADE`) reseeds the canonical 19-chassis QC demo behind the three-gate Tier-2 discipline (snapshot → dry-run → commit; ADR 0023).

## Footnote ledger — checkpoint catches (how the engagement compounded)

Each was caught at a §8 checkpoint and corrected before the next phase; together they are the case for ratify-as-you-go.

- **§3.0 BLOCKER-1** — the "module-constant role" authz premise was wrong; the codebase is DB-keyed permissions (→ D4).
- **§3.0 BLOCKER-2** — `record_planning_ack` was the locked-transition precedent to mirror, not the lock-free chassis transitions (→ D1); the drift itself is documented in the v4.36.5 ADR 0030.
- **§3.0/§3.1 alembic chain** — coordinated **twice**: the ship-order number assignment (§0.18) and re-pointing CA4's prematurely-merged `0029` from `0027` to `0028` to keep a single linear head.
- **§3.2** — the `?chassis=` query-param chosen over a path segment, applying the v4.38.1 deep-link lesson *before* it could bite (→ D6).
- **§3.4** — an imprecise authz framing corrected against the **real** 0028 grants (read the migration, don't infer from role intent).
- **§3.5** — the dispatch zone broke the planning journeys; Option-A deferral to v4.36e rather than blind guess-and-check (→ D8), banking the "revert to green, get traces" debug discipline.
- **§3.6** — the skeleton-as-form-container catch: an informative failure (`got 0 categories`) → a one-line fix, contrasted with §3.5's silent "not stable" that needed infrastructure to even diagnose.
- **§3.7** — a **stale "dirty-chain" premise** corrected by live-state verification (0028 had genuinely applied — the `migration_0028` marker proved it — so no chain-fix was needed); then the dry-run caught an `autoflush=False` interaction (an unflushed job → one Inv2 stray) before any `--commit`. The three-gate pattern earned its keep three times in one phase.
