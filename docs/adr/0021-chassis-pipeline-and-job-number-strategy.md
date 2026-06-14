# ADR 0021 — The chassis pipeline, job-number strategy, and the v4.34 ledger

- Status: Accepted
- Date: 2026-06-14
- Supersedes/extends: ADR 0015 (chassis-record lifecycle), ADR 0020 (the v4.33 pattern ledger)
- Work Order: v4.34 — Chassis Pipeline + Job Number Strategy

## Context

ADR 0015 made `chassis_records` a lifecycle entity (VCL/DCL, multi-cycle). WO v4.34 promotes it to
the **single source of truth for a chassis from its earliest capture** — not from physical receipt.
A chassis is now "expected" (a placeholder with NULL VIN) the moment a Pre-Job Card is submitted or
a Planning job is acknowledged, and the same row carries through to receive/assembly/dispatch.

In parallel, the job number moved from an opaque quote-string to a **quote-derived numeric core**
(`A32744/06/2026` → `32744`), with a controlled override path for the SAP parallel run.

The WO also surfaced a recurring theme: **the chassis page is the surface where the pipeline should
converge** — provenance, job number, VIN, dealer all belong on the chassis record, so one page
reflects the truth rather than N scattered job columns.

## Decisions

### 1. `chassis_records` from earliest capture, with honest provenance (§0.3/§0.4)

VIN is nullable (`expected` rows carry NULL; Postgres keeps NULLs out of `uq_chassis_records_vin`
natively). Two new columns — `created_via` (`pre_job_card | planning_job_create | manual_chassis_menu
| legacy_import_v4_28`) and `created_source_ref` (the quote / `Planning · Job N`) — record how and
whence each row was made. Status gains `expected` + `expected_orphaned` (values-in-comments).

### 2. One shared insert point, two touchpoints (§3.2/§3.3)

`create_expected_chassis` is the single creation path, called at Pre-Job submit and at Planning ack,
so the rows are identical by construction. Each touchpoint guards on its FK being NULL under a
`FOR UPDATE` row lock (a true idempotency key), and runs inside the caller's transaction
(`commit=False`) so the insert is atomic with its touchpoint.

### 3. Reject releases ONLY the chassis it auto-created (§3.4)

`reject()` releases the linked chassis **only** when `created_via='pre_job_card'` AND
`created_source_ref` matches this card's `_source_ref` — a foreign or manually-linked chassis is left
alone. A released chassis with no remaining job/card link goes `expected → expected_orphaned`.

### 4. `job_number` = the quote's numeric core; `id` is the PK (§0.7)

`A32744/06/2026 → 32744` (first digit run, after the letter prefix, before `/MM/YYYY`). The UNIQUE
constraint was dropped (numeric cores collide across letter prefixes); `production_jobs.id` is the
true key. Extraction is shared by `accept_calculation`, the 0020 backfill, and the seed so all three
agree.

### 5. SAP_RETIRED flag + Planning-ack override (§0.8/§0.9)

`job_number_source` (`quote_derived | sap_assigned | manual`) + `job_number_locked`. A planner may
override the number at ack (→ `sap_assigned`) during the SAP parallel run; the override is refused
when the number is `locked` or the site-level `SAP_RETIRED` flag is on (which forces quote-derived).
v4.34 ships the schema + the seeded flag; the admin UI to flip it is v4.35.

### 6. Token fallback — a per-token placeholder map (§3.6)

`_PENDING_TOKENS` became `{vin: "Pending", chassis_make_model: "Pending — to be confirmed"}`;
`build_context` always sets `chassis_make_model` so an unknown chassis reads as a clear status, not a
raw `{{token}}` or a blank.

### 7. `chassis_models` DDM — one controlled vocabulary, three surfaces (§3.7)

A read-only, seed-managed DDM (migration 0021), mirroring the `fridge_units` precedent. The shared
`ChassisModelSelect` component feeds the chassis-type dropdown on Planning ack, the Pre-Job Card, and
Chassis +New/edit — replacing a hardcoded frontend list and free-text entry. It stores the **display
string** (not the code), so `chassis_records.make` and token substitution agree everywhere. Admin
CRUD defers to v4.35.

### 8. Planning-ack sign-off integrity — lock only what was attested (§3.9 + refinements)

Once the linked Pre-Job Card is confirmed **with a chassis**, the ack locks `chassis_type` read-only.
The VIN locks **only when one was actually attested** at pre-job; if the card left it blank, the
planner captures it at ack. ETA + tail lift stay editable. (ADR 0020 fn 30 — "record the truth" —
applied to a new surface.)

### 9. The chassis record is the live truth surface (§3.9 refinements)

At ack, the job's final number (quote-derived or SAP override) and the VIN (attested, or captured at
ack) propagate onto the **linked** chassis record, so the Chassis page reflects the ack. The write is
guarded: no-op when no chassis is linked, never overwrites an existing VIN, and skips a VIN already
anchoring another chassis (the uq guard) so the ack can't fail on a clash.

### 10. Customer stays as-is; Dealer DDM deferred to v4.34.1

Investigation confirmed `customer` is already a structured FK (`customers` table + `calculations.
customer_id`, with a denormalized `chassis_records.customer_name` snapshot) — no normalization needed.
The Dealer-as-chassis-supplier DDM has **no seed source** (no Dealer column anywhere in the planning
workbook; one free-text value in the DB), so it is deferred to v4.34.1 pending a real dealer list
(see ledger #34).

## Engineering ledger — the v4.34 accumulation

*Migration & schema*
1. **Drop UNIQUE before the backfill that would trip it** — the numeric rewrite collides across letter prefixes; relax the constraint first.
2. **Data-guarded downgrades** — re-add a relaxed constraint on downgrade only if the data still satisfies it (UNIQUE iff no dupes; NOT NULL iff no NULLs).
3. **Truncate-at-write for fixed-width columns** — slice to the column width at the write; `'planning_job_create'` (19) into VARCHAR(16) is a 500.
4. **Inspector-guarded, idempotent migrations** — guard every DDL; up→down→up stays green; seed data only when empty.
5. **Document one-way backfills** — the pre-migration quote-string numbers are not restored on downgrade; say so in the docstring.

*Distributed creation & idempotency*
6. **One shared insert point for a distributed touchpoint** — `create_expected_chassis` makes both touchpoints' rows identical by construction.
7. **`FOR UPDATE` turns a guard into an idempotency key** — under READ COMMITTED the concurrent loser must re-read the terminal state before the guarded insert.
8. **Single-transaction atomicity** — `commit=False` on nested service calls so one outer commit owns the whole touchpoint.
9. **Record the truth, not the symmetry** — provenance names how the row was *actually* created, not a tidy uniform value.
10. **Delete the over-engineered path** — a VIN-adopt-at-ack added cross-job aliasing, terminal-status, and same-VIN races; `vin=NULL` dissolved all four review findings.
11. **Hard-fail the foundation, soft-fail the cosmetic** — a failed chassis insert rolls the submit back; a failed PDF snapshot does not.

*Diagnosis & flake*
12. **Instrument-to-diagnose** — wrap a flaky assertion in `expect_response` + assert status; a blind timeout becomes "chassis-records returned 401" (a session race, not slow rendering).
13. **Root-fix at the shared infra layer when symptoms cluster** — one `admin_session` autologin-wait fixed the recurring chassis-journey flake for every admin journey.

*Job-number strategy*
14. **Verify a BA observation against actual DATA before defending the code** — unit tests proving the strip correct didn't preclude a deployment/seed/data-state gap; investigate first.
15. **A consolidation can already be satisfied by an existing merge** — the display already sourced the canonical numeric; the "repoint" was a no-op once the data path was checked.
16. **Gate at the service, hint at the UI** — the backend refuses the override; the frontend hide is UX, not enforcement.
17. **Stamp a site-level flag once at the list router** — one query, set on every item, not threaded through the per-row serializer.

*Token fallback*
18. **A per-token placeholder MAP, not a boolean set** — each pending token carries its own copy.
19. **Omitted-vs-empty is a real semantic** — an absent key leaves the raw `{{token}}` visible (a spottable missing binding); a present-but-empty key resolves to the placeholder.

*Folded DDM & consolidation*
20. **Verify what a control is actually bound to** — the "Browse live catalogue" endpoint is the BOM catalogue, NOT the make/model vocabulary (a hardcoded frontend list).
21. **Size a fold against the existing precedent, not the generic estimate** — the fridge DDM has no admin CRUD, so matching it collapsed a "~1–2 day" estimate to ~0.5 day.
22. **Store the display string, not the code** — unifies the cross-surface representation and fixes the latent `chassis.make` pollution in the same touch.
23. **A hardcoded smoke-test count is a deliberate migration tripwire** — the "32 MES tables" assertion fails on every new table; the failure IS the success (it forces a schema-add acknowledgment).
24. **Preserve off-list legacy values in free-text→dropdown migrations** — render a value the DDM lacks as a transient selectable option so an edit never drops it.
25. **Three-surface UI consolidation via one shared component** — `ChassisModelSelect`: one component, three consumers, no drift possible (the React analog of `compute_kpis()` parity).
26. **Fix pre-existing fragmentation in the same touch** — the store-display unification shipped the dropdown AND reconciled the code-vs-display mismatch for free.

*Journey infrastructure*
27. **Journey signer/role dropdowns need `role_users`** — without it, `select_option(index=1)` finds no option on CI's fresh DB; also: board ack-candidate cards render only for **non-repair** costings, so filter `is_repair` when staging a board click.
28. **Validate journeys against a side-port server when the default port is busy** — boot a throwaway uvicorn on a free port with `MES_DEMO_AUTOLOGIN_USER` + `ALLOWED_ORIGINS`, point `MES_BASE` at it, run against the same dev DB.
29. **Encoding-robust assertions** — `to_contain_text("Auto")`, not the `·` glyph.

*Sign-off integrity & the live truth surface*
30. **Sign-off integrity: locking signed-off attributes downstream prevents silent attestation drift** — once Sales + Production attest a chassis, the ack can't silently rewrite it.
31. **Journey purges target their OWN marker, never a broad shared attribute** — a make-based chassis purge deleted real job-linked data (`created_by='admin'`) and tripped RESTRICT; purge by marker, and for service-created rows capture ids off the linking job + exclude still-linked ids.
32. **Lock only ATTESTED attributes, not the lock condition's neighbours** — the VIN locks only when one was captured at pre-job; an empty attested field isn't integrity to protect, and locking it blocks legitimate capture.
33. **The chassis record is the live truth surface** — acknowledged-stage data (job number, VIN) flows onto the linked chassis so one page reflects the pipeline; guard the write (no-op if unlinked, never overwrite, skip a uq clash).
34. **Don't fold an empty DDM into a WO** — a read-only seed-managed DDM with no seed and no admin CRUD is non-functional UI; wait until the data exists, not before.

## As-shipped (v4.34)

Delivered on `feat/v4.34-chassis-pipeline-job-number` (PR #25), 16 commits, CI green throughout
(both runners; 46-test Playwright journey suite):

- **Migration 0020** — provenance + nullable VIN + job-number columns + the drop-UNIQUE → numeric
  backfill + SAP_RETIRED seed. **Migration 0021** — the `chassis_models` DDM (10 seeded entries).
  Both inspector-guarded, round-trip clean.
- **Auto-create** at Pre-Job submit (§3.2) and Planning ack (§3.3); **reject release** (§3.4);
  **numeric job_number + override** (§3.5); **token fallback** (§3.6).
- **Chassis UI** (§3.7) — +New/edit (planner+admin), provenance pill, Expected / Expected(Orphaned)
  filters, and the shared `ChassisModelSelect` DDM dropdown across three surfaces.
- **Sign-off lock-down + refinements** — chassis_type locks on attestation; VIN locks only when
  attested, else captured at ack; job number + VIN propagate onto the linked chassis record.
- **Journeys** (§3.8) — `chassis_auto_create`, `chassis_reject_release`, `job_number`,
  `planning_ack_lock` (per-role, both lock paths).

**Deferred to v4.34.1:** the Dealer DDM (no seed source — needs a real dealer list).
**Deferred to v4.35:** admin CRUD for `chassis_models` (and the dealer DDM), plus the SAP_RETIRED
admin toggle.

## Consequences

- A chassis exists *before* it physically arrives, with NULL VIN — every chassis consumer must
  tolerate a null VIN (the `ChassisRecordOut.vin: Optional` fix was load-bearing).
- `job_number` is no longer unique — never key on it; `id` is the PK. Collisions across letter
  prefixes are accepted by design.
- The chassis page is now the convergence surface (provenance, job number, VIN). Future fields
  (dealer, …) follow the same propagate-at-ack pattern (#33).
- The DDM pattern (`fridge_units`, `chassis_models`) is the established shape for controlled
  vocabularies: seed-managed + read-only now, admin CRUD as a deliberate later increment — but only
  once the seed data exists (#34).
