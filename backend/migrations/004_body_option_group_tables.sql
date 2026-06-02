-- ================================================================
-- Migration 004: body_option_groups + body_option_subgroups tables
--
-- Creates two new global lookup tables and adds FK columns to
-- bill_of_materials so that body-option zone names and radio-group
-- labels are stored as IDs rather than plain text strings.
--
-- Safe to re-run:
--   CREATE TABLE IF NOT EXISTS skips if tables exist.
--   ALTER TABLE ... ADD COLUMN skipped if column exists (errno 1060).
--   INSERT IGNORE skips duplicate rows.
--   UPDATE only touches rows where the ID column is NULL.
--
-- Apply on prod MySQL BEFORE or AFTER the code deploy — the new
-- code handles both FK-set and FK-null rows gracefully.
-- ================================================================

-- Step 1: create lookup tables
CREATE TABLE IF NOT EXISTS body_option_groups (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL UNIQUE,
    sort_order INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS body_option_subgroups (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    group_id   INT NOT NULL,
    name       VARCHAR(100) NOT NULL,
    sort_order INT NOT NULL DEFAULT 0,
    UNIQUE KEY uq_bog_sub (group_id, name),
    CONSTRAINT fk_bos_group FOREIGN KEY (group_id)
        REFERENCES body_option_groups(id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Step 2: add FK columns to bill_of_materials (skip if already present)
ALTER TABLE bill_of_materials
    ADD COLUMN body_option_group_id    INT DEFAULT NULL,
    ADD COLUMN body_option_subgroup_id INT DEFAULT NULL,
    ADD CONSTRAINT fk_bom_bog FOREIGN KEY (body_option_group_id)
        REFERENCES body_option_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_bom_bos FOREIGN KEY (body_option_subgroup_id)
        REFERENCES body_option_subgroups(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- Step 3: seed groups from existing distinct string values
INSERT IGNORE INTO body_option_groups (name, sort_order)
SELECT DISTINCT body_option_group, 0
FROM bill_of_materials
WHERE body_option_group IS NOT NULL AND body_option_group != '';

-- Step 4: backfill body_option_group_id
UPDATE bill_of_materials b
JOIN body_option_groups g ON g.name = b.body_option_group
SET b.body_option_group_id = g.id
WHERE b.body_option_group IS NOT NULL
  AND b.body_option_group != ''
  AND b.body_option_group_id IS NULL;

-- Step 5: seed subgroups from distinct (group, subgroup) pairs
INSERT IGNORE INTO body_option_subgroups (group_id, name, sort_order)
SELECT DISTINCT g.id, b.body_option_subgroup, 0
FROM bill_of_materials b
JOIN body_option_groups g ON g.name = b.body_option_group
WHERE b.body_option_subgroup IS NOT NULL AND b.body_option_subgroup != '';

-- Step 6: backfill body_option_subgroup_id
UPDATE bill_of_materials b
JOIN body_option_groups g    ON g.id = b.body_option_group_id
JOIN body_option_subgroups s ON s.group_id = g.id AND s.name = b.body_option_subgroup
SET b.body_option_subgroup_id = s.id
WHERE b.body_option_subgroup IS NOT NULL
  AND b.body_option_subgroup != ''
  AND b.body_option_subgroup_id IS NULL;

-- Step 7: verify — groups and subgroups seeded
SELECT 'Groups seeded' AS info, COUNT(*) AS count FROM body_option_groups
UNION ALL
SELECT 'Subgroups seeded', COUNT(*) FROM body_option_subgroups;

-- Step 8: verify BOM coverage
SELECT
    CASE WHEN body_option_group_id IS NOT NULL THEN 'group FK resolved'
         WHEN body_option_group IS NOT NULL AND body_option_group != '' THEN 'group FK missing'
         ELSE 'no group'
    END AS group_status,
    COUNT(*) AS rows
FROM bill_of_materials
GROUP BY group_status
ORDER BY group_status;
