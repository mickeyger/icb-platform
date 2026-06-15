# Test database setup (WO v4.34.4 §3.1)

The backend test suite + the destructive seed/reconcile scripts run against an **isolated test
database** — never the shared dev DB. This is enforced in code: `pytest` aborts at session-start, and
every DB-mutating script refuses to run, unless `DATABASE_URL` resolves to a database whose **name
ends in `_test`** (e.g. `icb_test`).

> **Why db-name, not hostname:** the dev DB, your test DB, and CI all live on `localhost`. Hostname
> can't tell them apart — the database *name* is the discriminator. The shared dev DB is `icb`; the
> test DB is `icb_test`. (See `backend/app/db_guard.py`.)

## One-time local setup

1. Create the isolated test DB (run as the `postgres` superuser, like `init.sql`):

   ```
   "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -p 5432 -f deploy\postgres\init_test.sql
   ```

   This creates `icb_test` (owned by `icb_app`, with the `icb_costings` + `icb_mes` schemas) — a
   parallel of `icb`, with isolated data.

2. Apply migrations to it:

   ```
   cd backend
   set DATABASE_URL=postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb_test   # PowerShell: $env:DATABASE_URL=...
   alembic upgrade head
   ```

## Running tests

Always run with `DATABASE_URL` pointed at `icb_test` (a real env var, which overrides `backend/.env`):

```
cd backend
set DATABASE_URL=postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb_test
python -m pytest --ignore=tests/journeys      # unit/integration
python -m pytest tests/journeys/ -v           # journeys (the uvicorn subprocess inherits DATABASE_URL)
```

If you forget, the suite **aborts immediately** with a `db-guard REFUSED` message — it will not touch
`icb`. The seed-reset (`test_seed_from_mockup_counts`) only ever truncates `icb_test`.

To (re)seed the test DB with mockup data:

```
set DATABASE_URL=postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb_test
python -m scripts.seed_from_mockup --reset
```

(The seed also calls the env-guard — it refuses to `--reset` anything but a `*_test` DB.)

## CI

CI provisions `icb_test` via `deploy/postgres/init_test.sql` and sets `DATABASE_URL` to it, so the
alembic round-trip, seed-reset, unit tests, and journey suite all run against the isolated DB. The
shared dev DB is never reachable from CI.

## The v4.27 rule, now in code

"Never run a destructive operation against the shared dev DB" used to be a discipline. After v4.34.4
it's a code gate: there is **no override flag** — to run tests/seed you *must* point at a `*_test`
database. This closes the contamination vector that orphaned cards from jobs in the 14–15 June session.
