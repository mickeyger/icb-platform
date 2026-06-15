-- ICB Platform — PostgreSQL ISOLATED TEST database bootstrap (WO v4.34.4 §3.1)
-- Creates the `icb_test` database (same role + same two schemas as `icb`) so the test
-- suite + destructive seed/reconcile scripts run against an isolated DB, NEVER the shared
-- dev DB. The db-name guard (app/db_guard.py) refuses any destructive op unless DATABASE_URL
-- resolves to a `*_test` database — this script provides the one the suite is allowed to touch.
--
-- Run ONCE as a superuser (the default `postgres` account):
--
--   "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -p 5432 -f deploy\postgres\init_test.sql
--
-- Then point your shell at it before running tests:
--   DATABASE_URL=postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb_test
-- (and run `alembic upgrade head`). See docs/testing/setup.md. CI does this automatically.

\set ON_ERROR_STOP on

-- 1. Application login role (idempotent — same role as the dev DB).
DO
$$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'icb_app') THEN
      CREATE ROLE icb_app LOGIN PASSWORD 'icb_app_dev';
   END IF;
END
$$;

-- 2. Isolated test database owned by the app role (conditional-create idiom).
SELECT 'CREATE DATABASE icb_test OWNER icb_app'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'icb_test')
\gexec

-- 3. Switch in and create the two schemas (identical layout to `icb`).
\connect icb_test

CREATE SCHEMA IF NOT EXISTS icb_costings AUTHORIZATION icb_app;
CREATE SCHEMA IF NOT EXISTS icb_mes       AUTHORIZATION icb_app;

-- 4. Privileges + default search_path (matches init.sql; the app's connect-listener also sets it).
GRANT ALL ON SCHEMA icb_costings, icb_mes TO icb_app;
ALTER ROLE icb_app IN DATABASE icb_test SET search_path = icb_costings, public;

\echo 'ICB TEST bootstrap complete: database icb_test, schemas icb_costings + icb_mes (run alembic upgrade head next)'
