-- WO v4.20 — drop all icb_costings FK constraints before the pgloader data load
-- (run as icb_app, the owner — no superuser needed). The defs are saved so they can
-- be re-added after the load (03_readd_fks.sql). This lets the load insert source
-- orphans (e.g. bill_of_materials.trailer_type_id=51) without RI-trigger errors,
-- which icb_app (non-superuser) cannot disable directly.
CREATE TABLE IF NOT EXISTS icb_costings._fk_backup (tbl text, conname text, def text);
TRUNCATE icb_costings._fk_backup;
INSERT INTO icb_costings._fk_backup (tbl, conname, def)
SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'icb_costings' AND c.contype = 'f';
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT tbl, conname FROM icb_costings._fk_backup LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.tbl, r.conname);
  END LOOP;
  RAISE NOTICE 'dropped % FK constraints', (SELECT count(*) FROM icb_costings._fk_backup);
END $$;
