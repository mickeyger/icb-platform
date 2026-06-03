-- WO v4.20 — post-load (run as icb_app). §0.3 branch_id backfill + §0.5 sequence reset.
-- 1) Backfill branch_id = JHB on every branch-scoped icb_costings table (Phase-1 parity).
DO $$
DECLARE r record; jhb int;
BEGIN
  SELECT id INTO jhb FROM icb_costings.branches WHERE code = 'JHB';
  FOR r IN
    SELECT c.table_name FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
    WHERE c.table_schema = 'icb_costings' AND c.column_name = 'branch_id'
      AND t.table_type = 'BASE TABLE'   -- skip the v_calculation_records_legacy view
  LOOP
    EXECUTE format('UPDATE icb_costings.%I SET branch_id = %s WHERE branch_id IS NULL', r.table_name, jhb);
  END LOOP;
END $$;

-- 2) Reset every owned sequence in icb_costings to MAX(col)+1 (belt-and-suspenders to
--    pgloader's "reset sequences" — verifies none were missed).
DO $$
DECLARE r record; nextval_to bigint;
BEGIN
  FOR r IN
    SELECT s.relname AS seq, t.relname AS tbl, a.attname AS col
    FROM pg_class s
    JOIN pg_depend d  ON d.objid = s.oid AND d.deptype = 'a'
    JOIN pg_class t   ON t.oid = d.refobjid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE s.relkind = 'S' AND n.nspname = 'icb_costings'
  LOOP
    EXECUTE format('SELECT COALESCE(MAX(%I), 0) + 1 FROM icb_costings.%I', r.col, r.tbl) INTO nextval_to;
    EXECUTE format('SELECT setval(%L, %s, false)', 'icb_costings.' || r.seq, nextval_to);
  END LOOP;
END $$;
