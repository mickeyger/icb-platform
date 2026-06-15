# UAT — Integrity Lockdown (WO v4.34.4) — v1.0

Infrastructure WO: there is no new UI to click through. This is an **operator/BA verification runbook**
— the steps prove the dev DB is now defensible. Most checks are *negative path* (things refusing the
shared dev DB) and are runnable locally; the *positive path* (the suite green on `icb_test`) is verified
by CI. Run from `backend/` with the venv active. The shared dev DB is `icb`; the test DB is `icb_test`.

> All "REFUSED" outcomes below are the point of the WO — a refusal is a PASS.

## UAT-1 — pytest cannot run against the shared dev DB (§3.1)

With `DATABASE_URL` pointing at the shared dev DB (`…/icb`):

```
python -m pytest -q
```

**Expected (PASS):** the session aborts immediately, before any test runs, with:
`[db-guard] REFUSED: pytest must run against an isolated test database … resolves to 'icb' …`

## UAT-2 — reconcile scripts refuse the shared dev DB (§3.2, Tier 1)

Against `…/icb`:

```
python -m scripts.backfill_prejob_calc_status --dry-run
python -m scripts.backfill_prejob_job_anchor --dry-run
```

**Expected (PASS):** both refuse with `[db-guard] REFUSED … must run against an isolated test database`
and exit non-zero — **before** any DB read/write. (`--dry-run` is gated too.)

## UAT-3 — scoped seeds require confirmation on the shared dev DB (§3.2, Tier 2)

Against `…/icb`, non-interactively (e.g. piped):

```
echo "" | python -m scripts.seed_v4_28_chassis_mock
```

**Expected (PASS):** `[env-guard] REFUSED … would write to the shared dev DB … non-interactively.`
A deliberate run is still possible with `ICB_ALLOW_SHARED_DB_WRITE=1` (or an interactive `y`).

## UAT-4 — additive seeds announce their target (§3.2, Tier 3)

Against `…/icb` (note: this DOES seed — run only when intentionally seeding the dev DB):

```
python -m scripts.seed_dealers --dry-run
```

**Expected:** prints `[env-guard] seed_dealers: writing to NON-TEST DB (host=localhost db=icb) …` and
proceeds (additive/idempotent — never blocks).

## UAT-5 — read-only integrity health-check (§3.3)

Safe to run against the shared dev DB (SELECT-only):

```
python -m scripts.health_check
```

**Expected (PASS):** prints the three invariant counts and
`[health-check] CLEAN — all three invariants hold.` (exit 0). On the Phase-2 baseline this is clean.
If it ever reports violations, recovery is **manual / BA-gated** against a snapshot — never an automatic
reconcile on `icb`.

## UAT-6 — local test DB setup works (§3.1, positive path)

One-time, as the `postgres` superuser, then point `DATABASE_URL` at `icb_test`:

```
psql -U postgres -f deploy/postgres/init_test.sql
set DATABASE_URL=postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb_test
alembic upgrade head
python -m pytest -q            # the guard now PASSES; suite runs isolated
```

**Expected (PASS):** the suite runs (no db-guard abort), touching only `icb_test`. See
`docs/testing/setup.md`. **CI performs this automatically on every push/PR.**

## UAT-7 — CI runs isolated (§3.1)

On the PR, the CI job "build & test" provisions `icb_test` (`init_test.sql`), runs the alembic
round-trip, the seed-reset, the unit suite and the Playwright journeys — all against `icb_test`.

**Expected (PASS):** CI green on both ubuntu + windows; the new tests
`test_db_guard.py` and `test_v4_34_4_integrity_lockdown.py` pass.

---

**Sign-off:** _______________________  **Date:** ____________
