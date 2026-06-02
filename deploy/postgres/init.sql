-- ICB Platform — PostgreSQL bootstrap (Phase 1, WO v4.12)
-- Creates the application role, the `icb` database, and the two schemas
-- (icb_costings + icb_mes). This is the canonical creation script.
--
-- Run ONCE as a superuser (the default `postgres` account):
--
--   "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -p 5432 -f deploy\postgres\init.sql
--
-- NOTE: this dev machine uses PostgreSQL 18 on port 5432. The password below is a
-- LOCAL-DEV placeholder; the app
-- reads its real connection string from DATABASE_URL in backend/.env. Never use
-- this password outside local development.

\set ON_ERROR_STOP on

-- 1. Application login role (idempotent).
DO
$$
BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'icb_app') THEN
      CREATE ROLE icb_app LOGIN PASSWORD 'icb_app_dev';
   END IF;
END
$$;

-- 2. Database owned by the app role. CREATE DATABASE cannot run inside a
--    transaction/DO block, so use the \gexec conditional-create idiom.
SELECT 'CREATE DATABASE icb OWNER icb_app'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'icb')
\gexec

-- 3. Switch into the new database and create the two schemas.
\connect icb

CREATE SCHEMA IF NOT EXISTS icb_costings AUTHORIZATION icb_app;
CREATE SCHEMA IF NOT EXISTS icb_mes       AUTHORIZATION icb_app;

-- 4. Privileges + default search_path (costings first, then public). Alembic's
--    version table and all costing-app tables live in icb_costings; the MES
--    schema is created now and populated in later phases.
GRANT ALL ON SCHEMA icb_costings, icb_mes TO icb_app;
ALTER ROLE icb_app IN DATABASE icb SET search_path = icb_costings, public;

\echo 'ICB bootstrap complete: role icb_app, database icb, schemas icb_costings + icb_mes'
