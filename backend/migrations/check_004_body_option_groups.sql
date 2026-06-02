-- ================================================================
-- VERIFICATION: Migration 004 — body_option_groups + subgroups
-- Run this in phpMyAdmin after applying 004_body_option_group_tables.sql
-- No information_schema queries — all checks use SHOW or direct SELECT.
-- ================================================================

-- ── CHECK 1: Tables exist ─────────────────────────────────────
-- Expected: body_option_groups listed
SHOW TABLES LIKE 'body_option_groups';
-- ✔ Should return 1 row

-- Expected: body_option_subgroups listed
SHOW TABLES LIKE 'body_option_subgroups';
-- ✔ Should return 1 row

-- ── CHECK 2: FK columns exist on bill_of_materials ────────────
-- Expected: body_option_group_id and body_option_subgroup_id in the list
SHOW COLUMNS FROM bill_of_materials LIKE 'body_option_group_id';
-- ✔ Should return 1 row: int, YES, NULL

SHOW COLUMNS FROM bill_of_materials LIKE 'body_option_subgroup_id';
-- ✔ Should return 1 row: int, YES, NULL

-- ── CHECK 3: Groups seeded ────────────────────────────────────
-- Expected: 6 groups (DRD, FLOOR, FRONT, ROOF, SIDES, SRD)
SELECT id, name FROM body_option_groups ORDER BY name;
-- ✔ 6 rows

SELECT COUNT(*) AS `Total groups (expect 6)` FROM body_option_groups;

-- ── CHECK 4: Subgroups seeded ─────────────────────────────────
-- Expected: 28 subgroups total
SELECT COUNT(*) AS `Total subgroups (expect 28)` FROM body_option_subgroups;

-- Breakdown per group
SELECT g.name AS `Group`, COUNT(s.id) AS `Subgroup count`
FROM body_option_groups g
LEFT JOIN body_option_subgroups s ON s.group_id = g.id
GROUP BY g.id, g.name
ORDER BY g.name;

-- ── CHECK 5: BOM group FK backfill ────────────────────────────
-- Expected: 812 resolved, 0 missing (no row labelled 'PROBLEM')
SELECT
    CASE
        WHEN body_option_group_id IS NOT NULL                          THEN 'OK: group FK resolved'
        WHEN body_option_group IS NOT NULL AND body_option_group != '' THEN 'PROBLEM: string set but no FK'
        ELSE 'OK: no group (normal rows)'
    END AS `Status`,
    COUNT(*) AS `Row count`
FROM bill_of_materials
GROUP BY 1
ORDER BY 1;
-- ✔ 'PROBLEM' row should be absent or 0

-- ── CHECK 6: BOM subgroup FK backfill ────────────────────────
-- Expected: 626 resolved, 0 missing (no row labelled 'PROBLEM')
SELECT
    CASE
        WHEN body_option_subgroup_id IS NOT NULL                             THEN 'OK: subgroup FK resolved'
        WHEN body_option_subgroup IS NOT NULL AND body_option_subgroup != '' THEN 'PROBLEM: string set but no FK'
        ELSE 'OK: no subgroup (normal rows)'
    END AS `Status`,
    COUNT(*) AS `Row count`
FROM bill_of_materials
GROUP BY 1
ORDER BY 1;
-- ✔ 'PROBLEM' row should be absent or 0

-- ── CHECK 7: All body option rows have group FK ───────────────
-- Expected: Missing = 0
SELECT
    COUNT(*)                              AS `Total body option rows (expect 812)`,
    SUM(body_option_group_id IS NOT NULL) AS `With group FK    (expect 812)`,
    SUM(body_option_group_id IS NULL)     AS `Missing group FK (expect 0)`
FROM bill_of_materials
WHERE is_body_option = 1;

-- ── ALL CLEAR when ────────────────────────────────────────────
-- CHECK 1 → both SHOW TABLES return 1 row each
-- CHECK 2 → both SHOW COLUMNS return 1 row each
-- CHECK 3 → 6 groups: DRD, FLOOR, FRONT, ROOF, SIDES, SRD
-- CHECK 4 → 28 subgroups total
-- CHECK 5 → no 'PROBLEM' row
-- CHECK 6 → no 'PROBLEM' row
-- CHECK 7 → Missing group FK = 0
