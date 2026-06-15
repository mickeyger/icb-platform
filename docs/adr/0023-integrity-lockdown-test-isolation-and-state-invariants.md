# ADR 0023 — Integrity Lockdown: test-DB isolation, script guards & pipeline state-invariants (v4.34.4)

- Status: Accepted
- Date: 2026-06-15
- Work Order: v4.34.4 — Integrity Lockdown (the first pure-infrastructure WO)
- Supersedes nothing; hardens the operating posture established since v4.27.

## Context

On 14–15 June 2026 the shared dev database (`icb`) — the one Michael demos against — was repeatedly
contaminated. Root cause: the **full backend test suite was run against the shared dev DB**, and that
suite includes the destructive `test_seed_from_mockup_counts`, whose `seed_from_mockup --reset` path
runs `TRUNCATE icb_mes.* RESTART IDENTITY CASCADE`. Because `_MES_TABLES` truncates `production_jobs`
but not `prejob_cards`/`chassis_records`, re-seeding orphaned confirmed Pre-Job Cards from their jobs
and left `calculations.status` strays — which then re-triggered the §0.21 legacy sign-off UI fallback
that Michael saw "reappear". The damage was repeatedly masked with ad-hoc reconcile scripts.

The v4.27 rule — *"restore real data after any full backend test suite run"* — was a discipline, and
disciplines get violated. The BA halted forward work and mandated: a read-only forensic audit (Phase 1,
done — b36946a), a BA-approved clean baseline (Phase 2, done — reset-in-place, 15 Jun PM), then this
process lockdown (Phase 3). The brief: **make the dev DB permanently defensible in code, not in
discipline.**

§3.0 discovery (corroborated by adversarial verification) re-specced three of the original asks:

- **Test isolation must be a separate test DATABASE, not SQLAlchemy `schema_translate_map` or
  transaction-rollback.** icb_costings models are schema-LESS (they rely on the connect-time
  `SET search_path` listener in `database.py`), and icb_mes models pin `{'schema': 'icb_mes'}`; Alembic
  deliberately doesn't pin `version_table_schema`. A translate-map would have to rewrite all of that and
  still wouldn't isolate the seed-reset's raw `TRUNCATE` SQL. A parallel `icb_test` database isolates
  everything, including raw SQL.
- **The guard keys on db-NAME, not hostname.** Dev, every test DB, and CI all live on `localhost` — the
  hostname can't discriminate. The database *name* can (`icb` vs `*_test`).
- **Invariant 2 is re-scoped** to a calc.status invariant + reconciler (the real card-delete endpoint
  stays deferred — ADR 0020 §63-69 — so there's nothing yet to hang a live revert on).
- **Invariant 3 is re-scoped** to a detect/reconcile health-check, NOT a creation block: the original
  "block anchorless chassis" would break legitimate early-capture flows and mistargets the cause. The
  `chassis_record_id` FK stays `ON DELETE RESTRICT` (mig 0012).

## Decisions

1. **Isolated test database + a hard pytest session guard (§3.1).** A new `app/db_guard.py` is the
   single source of truth (`resolve_db_name` / `is_test_db` / `assert_test_db`, keyed on db-name).
   `tests/conftest.py`'s `pytest_sessionstart` aborts the **entire** session (no collection, no
   fixtures, no journey subprocess) with a `pytest.UsageError` unless `DATABASE_URL` resolves to a
   `*_test` database. `deploy/postgres/init_test.sql` provisions `icb_test`; CI (`ci.yml`) points
   `DATABASE_URL` at it and bootstraps it, so the alembic round-trip, seed-reset, unit and journey
   suites all run isolated. **There is no override flag — by design.** This is the v4.27 rule, in code.

2. **Three-tier environment guard on every DB-mutating script (§3.2).** `scripts/_environment_guard.py`
   (over `db_guard`) is called at each script's entry point, matched to blast radius:
   - **Tier 1 `require_test_db`** — HARD refuse unless `*_test`, no override: the two TRUNCATE-all
     scripts (`seed_from_mockup._truncate_mes`, `import_workbook._truncate`) and the two reconcilers
     (`backfill_prejob_calc_status`, `backfill_prejob_job_anchor`). *"No reconcile scripts on the shared
     dev DB, ever."*
   - **Tier 2 `confirm_if_shared_db`** — scoped delete / CASCADE re-import / in-place rewrite: allowed
     on dev only after explicit confirmation (`ICB_ALLOW_SHARED_DB_WRITE=1` or an interactive `y`); fails
     safe otherwise. (the version-named catalogue seeds, `translate_chassis_register`,
     `import_inventory_to_sap_mock`, `normalize_template_tokens`.)
   - **Tier 3 `announce_target`** — additive/idempotent seeds: announce only (`seed_dealers`,
     `seed_fridge_units`, `seed_medical_waste_template`, `import_prejob_templates`).
   Guards sit at the CLI entry (or the TRUNCATE statement), so internal composition (e.g. the seed
   calling `ensure_jobs_for_carded_calcs`) and a fresh-empty-DB bootstrap are unaffected. Full matrix:
   `docs/scripting/environment_guard.md`. **Tier 2 is the residual risk surface** (fat-finger `y` /
   stale `ICB_ALLOW_SHARED_DB_WRITE`), so every Tier-2 confirm that allows a scoped-destructive op
   against a non-test DB is appended to `backend/scripts_audit.log` (operator, UTC timestamp, script,
   args, env-flag value, target — gitignored, best-effort). (BA ask, post-merge-review.)

3. **Three service-layer state-machine invariants (§3.3)** — new `app/services/integrity.py`:
   - **Invariant 1 — a confirmed Pre-Job Card always anchors a production_job.**
     `assert_confirmed_card_anchored` is a hard, transaction-rolling assertion wired into
     `prejob_cards.sign_off` (after `_ensure_anchor_job`). A confirmed card with no job is invisible to
     Planning's ack pool — now the confirm fails loudly and atomically rather than shipping that state.
   - **Invariant 2 — calc.status reflects what the lifecycle backs.** `derive_calc_status` is the SOT
     card/job→status mapping; `reconcile_calc_status` advances forward, and with `allow_revert=True`
     walks a stray back DOWN to what's actually backed (floor `accepted`, never `declined`). The revert
     is the net-new capability, exercised by the reconciler + tests, ready for a future card-delete path.
   - **Invariant 3 — no 'expected' chassis lingers anchorless.** `find_anchorless_chassis` (READ-ONLY)
     detects expected/expected_orphaned chassis with no live job/card link; `reconcile_anchorless_chassis`
     only ever marks `expected`→`expected_orphaned` (forward, reversible). Never blocks creation, never
     deletes.
   `run_health_checks` aggregates all three as a SELECT-only report; `scripts/health_check.py` exposes
   it (safe to run against the shared dev DB — it only reads).

4. **Repo hygiene (§3.4).** `.gitignore` now excludes DB dumps (`*.dump`, `backend/.db_snapshots/` —
   folding in the Phase-1 audit pattern) and the local-only generated/source artifacts `.uat-gen/`,
   `emails/`, `transcripts/` (same off-repo policy as `latest documents/`). `docs/screenshots/journeys/`
   stays deliberately tracked (committed deliverables). A `scripts/_archive/` landing place +
   `docs/scripting/archive_policy.md` establish how retired one-shot scripts are pruned later (a
   deliberate standalone change — no scripts moved here, since moving changes import paths).

5. **Recovery stays manual / BA-gated / snapshot-reversible.** Auto-recovery reconcile scripts are
   excluded from the dev DB **permanently** (Tier 1). The detectors above only *surface* problems
   (read-only); fixing them is a human decision, taken against a `pg_dump` snapshot, never an automatic
   script run on `icb`. The `ON DELETE RESTRICT` FK on `production_jobs.chassis_record_id` is kept — we
   do not delete our way out of inconsistency.

6. **Verification posture: positive path on CI, negative path locally.** `icb_app` is a non-superuser
   (ADR 0011) and the superuser password is local-only, so `icb_test` can't be created in a dev session
   — the positive path (suite green on `icb_test`) is **CI-verified**. The negative path (everything
   refusing the shared dev DB) is verified locally and is the acute-risk reduction.

### Pattern note — same-transaction reads under `autoflush=False`

> Service-layer invariants that read state set within the same transaction must call `db.flush()`
> before the read. `SessionLocal` is configured with `autoflush=False`, so pending inserts/updates are
> not visible to subsequent queries within the same session until explicitly flushed. The Invariant 1
> (confirmed-card-anchored) implementation flushes before assertion. Future invariant work must follow
> the same pattern.

(Recorded because this exact gotcha produced a CI-only regression during this WO: the Invariant-1
assertion queried for the just-added anchor job before it was flushed, saw `None`, and wrongly raised
HTTP 500 — fixed by flushing first. The first CI run caught it; the fix touched only the new assertion.)

## Consequences

- The destructive vector is closed at two layers: pytest can't run against `icb` at all, and even a
  manual `seed_from_mockup --reset` / reconciler invocation against `icb` refuses before any SQL.
- Local development gains a one-time setup step (create `icb_test`, point `DATABASE_URL` at it) —
  documented in `docs/testing/setup.md`. Forgetting it produces an immediate, explanatory abort, not
  silent contamination.
- The integrity module gives the project a vocabulary (and a health-check) for the three pipeline
  consistency rules, so future work has a place to assert them instead of rediscovering them in a demo.
- No `/calculator` change, no `icb_sap` write, no migration; icb_costings writes are confined to the
  Invariant-2 reconcile path. v4.31–v4.34.1 surfaces are untouched.

## As shipped (Click-to-verify)

- New module: `backend/app/db_guard.py`; new service: `backend/app/services/integrity.py`.
- New scripts: `backend/scripts/_environment_guard.py`, `backend/scripts/health_check.py`.
- Guards wired into 15 mutating scripts + `tests/conftest.py`.
- CI: `.github/workflows/ci.yml` → `icb_test` + bootstrap step; `deploy/postgres/init_test.sql`.
- Tests: `backend/tests/test_db_guard.py`, `backend/tests/test_v4_34_4_integrity_lockdown.py`.
- Docs: this ADR, `docs/testing/setup.md`, `docs/scripting/environment_guard.md`,
  `docs/scripting/archive_policy.md`, `docs/uat/ICB_MES_UAT_Integrity_Lockdown_v1.0.md`.
- No new UI route or nav surface (infrastructure WO).
