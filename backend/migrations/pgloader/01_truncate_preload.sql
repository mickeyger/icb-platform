-- WO v4.20 — pre-load clear (run as icb_app, the table owner).
-- Clears the mock seed so pgloader can data-only load the real catalogue, and
-- clears ALL mock icb_mes rows so reloaded calculations don't orphan them (§0.3).
-- The MES production dashboards are intentionally empty until v4.21 (§3.1).
-- CASCADE handles FK order; RESTART IDENTITY zeroes sequences (pgloader resets them again).
DO $$
DECLARE r record;
BEGIN
  -- icb_mes: clear everything (all mock; v4.21 reloads what's needed)
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'icb_mes' LOOP
    EXECUTE format('TRUNCATE TABLE icb_mes.%I RESTART IDENTITY CASCADE', r.tablename);
  END LOOP;
  -- icb_costings: clear the 43 in-scope tables (skip the PG-only objects + the skip-list)
  FOR r IN
    SELECT tablename FROM pg_tables
    WHERE schemaname = 'icb_costings'
      AND tablename NOT IN ('branches', 'alembic_version', 'user_sessions', 'help_request_log')
  LOOP
    EXECUTE format('TRUNCATE TABLE icb_costings.%I RESTART IDENTITY CASCADE', r.tablename);
  END LOOP;
END $$;
