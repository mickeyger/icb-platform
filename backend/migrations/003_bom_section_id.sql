-- ================================================================
-- Migration 003: bom_section_id
--
-- Adds a proper FK column to bill_of_materials so that the
-- section assignment is stored as a bom_sections.id rather than
-- a plain text name string.
--
-- Safe to re-run: ALTER TABLE is skipped if column exists (MySQL
-- returns errno 1060). UPDATE only touches rows with NULL id.
--
-- Apply on prod MySQL BEFORE or AFTER the code deploy.
-- The new code handles both FK-set and FK-null rows gracefully.
-- ================================================================

-- Step 1: add the FK column (skip if already present)
ALTER TABLE bill_of_materials
    ADD COLUMN bom_section_id INT DEFAULT NULL,
    ADD CONSTRAINT fk_bom_section
        FOREIGN KEY (bom_section_id) REFERENCES bom_sections(id)
        ON DELETE SET NULL ON UPDATE CASCADE;

-- Step 2: backfill — resolve string name → section ID
-- Rows whose bom_section value doesn't match any bom_sections row
-- are left as NULL; they still display correctly via the string column.
UPDATE bill_of_materials b
JOIN bom_sections s ON s.name = b.bom_section
SET b.bom_section_id = s.id
WHERE b.bom_section IS NOT NULL
  AND b.bom_section != ''
  AND b.bom_section_id IS NULL;

-- Step 3: verify — resolved vs unresolved breakdown
SELECT
    CASE WHEN bom_section_id IS NOT NULL THEN 'resolved (FK set)'
         WHEN bom_section IS NOT NULL AND bom_section != '' THEN 'unresolved (section name not in bom_sections)'
         ELSE 'no section'
    END AS section_status,
    COUNT(*) AS row_count
FROM bill_of_materials
GROUP BY section_status
ORDER BY section_status;

-- Step 4 (optional diagnostic): list unresolved section names
SELECT DISTINCT bom_section AS unresolved_name, COUNT(*) AS rows
FROM bill_of_materials
WHERE bom_section IS NOT NULL
  AND bom_section != ''
  AND bom_section_id IS NULL
GROUP BY bom_section
ORDER BY bom_section;
