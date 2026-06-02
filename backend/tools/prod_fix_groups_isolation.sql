-- ============================================================
-- PROD FIX v2: Isolate trailer 51 body_option_groups
-- Uses INSERT IGNORE + name-lookup to handle unique-name constraint.
-- ============================================================
SET foreign_key_checks = 0;

-- ── Step 1: Restore original names of groups 22-27 ──────────────────
-- Reads body_option_group TEXT column from other trailers (unchanged
-- by the migration) to reverse the ON DUPLICATE KEY UPDATE rename.
UPDATE body_option_groups g
INNER JOIN (
    SELECT body_option_group_id, MIN(body_option_group) AS orig_name
    FROM bill_of_materials
    WHERE trailer_type_id != 51
      AND body_option_group_id IN (22,23,24,25,26,27)
      AND body_option_group IS NOT NULL
    GROUP BY body_option_group_id
) src ON src.body_option_group_id = g.id
SET g.name = src.orig_name;
-- Safe no-op for any group that had no other-trailer rows.

-- ── Step 2: Get-or-create groups for trailer 51 ──────────────────────
-- INSERT IGNORE skips if the name already exists (unique constraint).
-- SET then captures whichever row actually holds that name.

INSERT IGNORE INTO body_option_groups (name, sort_order) VALUES ('Door type', 0);
SET @g22 = (SELECT id FROM body_option_groups WHERE name='Door type');

INSERT IGNORE INTO body_option_groups (name, sort_order) VALUES ('DOOR TYPE', 0);
SET @g23 = (SELECT id FROM body_option_groups WHERE name='DOOR TYPE');

INSERT IGNORE INTO body_option_groups (name, sort_order) VALUES ('FLOOR TYPE', 0);
SET @g24 = (SELECT id FROM body_option_groups WHERE name='FLOOR TYPE');

INSERT IGNORE INTO body_option_groups (name, sort_order) VALUES ('FLOOR TYPE TOPPING', 0);
SET @g25 = (SELECT id FROM body_option_groups WHERE name='FLOOR TYPE TOPPING');

INSERT IGNORE INTO body_option_groups (name, sort_order) VALUES ('FLOOR THICKNESS', 0);
SET @g26 = (SELECT id FROM body_option_groups WHERE name='FLOOR THICKNESS');

INSERT IGNORE INTO body_option_groups (name, sort_order) VALUES ('INSULATION', 0);
SET @g27 = (SELECT id FROM body_option_groups WHERE name='INSULATION');

-- ── Step 3: Wire bom_section_id + parent_option_master_id on new groups ─
UPDATE body_option_groups SET bom_section_id = 40 WHERE id = @g26;

-- FLOOR TYPE TOPPING and FLOOR THICKNESS are sub-areas of 24MM WISA TRANS FLOOR
UPDATE body_option_groups SET parent_option_master_id = (
    SELECT MIN(b.id) FROM bill_of_materials b
    JOIN materials mat ON mat.id = b.material_id
    WHERE b.trailer_type_id=51 AND b.is_body_option=1 AND mat.name='24MM WISA TRANS FLOOR'
) WHERE id IN (@g25, @g26);

-- Clear parent_option_master_id from the OLD shared groups
-- (only clears if old IDs differ from the new ones we captured above)
UPDATE body_option_groups
  SET parent_option_master_id = NULL
  WHERE id IN (25,26) AND id NOT IN (@g25, @g26);

-- ── Step 4: Re-wire trailer 51 BOM body_option_group_id ─────────────
UPDATE bill_of_materials SET body_option_group_id = @g22 WHERE trailer_type_id=51 AND body_option_group_id=22;
UPDATE bill_of_materials SET body_option_group_id = @g23 WHERE trailer_type_id=51 AND body_option_group_id=23;
UPDATE bill_of_materials SET body_option_group_id = @g24 WHERE trailer_type_id=51 AND body_option_group_id=24;
UPDATE bill_of_materials SET body_option_group_id = @g25 WHERE trailer_type_id=51 AND body_option_group_id=25;
UPDATE bill_of_materials SET body_option_group_id = @g26 WHERE trailer_type_id=51 AND body_option_group_id=26;
UPDATE bill_of_materials SET body_option_group_id = @g27 WHERE trailer_type_id=51 AND body_option_group_id=27;

-- ── Step 5: Verification ─────────────────────────────────────────────
-- A) What group IDs does trailer 51 now use? (should only be the new ones)
-- SELECT DISTINCT body_option_group_id, body_option_group
-- FROM bill_of_materials WHERE trailer_type_id=51 AND body_option_group_id IS NOT NULL
-- ORDER BY body_option_group_id;
--
-- B) Confirm captured IDs (print @g22..@g27)
-- SELECT @g22 AS g22, @g23 AS g23, @g24 AS g24, @g25 AS g25, @g26 AS g26, @g27 AS g27;
--
-- C) Groups 22-27 should have their original (restored) names
-- SELECT id, name, parent_option_master_id FROM body_option_groups WHERE id BETWEEN 22 AND 27;

SET foreign_key_checks = 1;
-- END