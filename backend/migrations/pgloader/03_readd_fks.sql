-- WO v4.20 — re-add the icb_costings FK constraints after the load (run as icb_app).
-- Re-add VALID where the data satisfies the FK; fall back to NOT VALID where source
-- orphans exist (the constraint still enforces NEW writes; existing orphan rows are
-- tolerated, matching faje). Logs which FKs were re-added NOT VALID.
DO $$
DECLARE r record; novalid int := 0;
BEGIN
  FOR r IN SELECT tbl, conname, def FROM icb_costings._fk_backup LOOP
    BEGIN
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s', r.tbl, r.conname, r.def);
    EXCEPTION WHEN others THEN
      EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s NOT VALID', r.tbl, r.conname, r.def);
      novalid := novalid + 1;
      RAISE NOTICE 'NOT VALID: % on % (source orphans) — %', r.conname, r.tbl, SQLERRM;
    END;
  END LOOP;
  RAISE NOTICE 're-added % FKs (% NOT VALID)', (SELECT count(*) FROM icb_costings._fk_backup), novalid;
END $$;
DROP TABLE icb_costings._fk_backup;
