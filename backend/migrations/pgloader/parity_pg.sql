-- WO v4.20 — exact per-table row counts for the icb_costings schema (PG side of the
-- parity report). \gexec runs each generated COUNT(*) so the output is clean
-- `table|count` lines. Re-runnable: psql ... -f parity_pg.sql
\pset format unaligned
\pset fieldsep '|'
\pset tuples_only on
SELECT format('SELECT %L AS t, count(*) AS c FROM icb_costings.%I', tablename, tablename)
FROM pg_tables
WHERE schemaname = 'icb_costings'
ORDER BY tablename
\gexec
