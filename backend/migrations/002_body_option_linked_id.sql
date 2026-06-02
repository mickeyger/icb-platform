-- ================================================================
-- Migration 002: body_option_linked_id
--
-- Adds a proper FK column to bill_of_materials so that the
-- "activating body option" link is stored as a material ID
-- rather than a plain text name.
--
-- Safe to re-run: ALTER TABLE is skipped if column exists (MySQL
-- returns errno 1060 which the app migration runner treats as benign).
--
-- Apply on prod MySQL BEFORE or AFTER the code deploy — data-only,
-- no schema change required at boot time beyond this ALTER.
-- ================================================================

-- Step 1: add the FK column (skip if already present)
ALTER TABLE bill_of_materials
    ADD COLUMN body_option_linked_id INT DEFAULT NULL,
    ADD CONSTRAINT fk_bol_material
        FOREIGN KEY (body_option_linked_id) REFERENCES materials(id)
        ON DELETE SET NULL ON UPDATE CASCADE;

-- Step 2: backfill — resolve string name → material ID
-- Rows whose body_option_linked value doesn't match any material
-- (e.g. group-level links like "DRD") are left as NULL and continue
-- to use the string fallback in the application.
UPDATE bill_of_materials b
JOIN materials m ON m.name = b.body_option_linked
SET b.body_option_linked_id = m.id
WHERE b.body_option_linked IS NOT NULL
  AND b.body_option_linked != ''
  AND b.body_option_linked_id IS NULL;

-- Step 3: verify — check how many rows were resolved vs unresolved
SELECT
    CASE WHEN body_option_linked_id IS NOT NULL THEN 'resolved (FK set)'
         WHEN body_option_linked IS NOT NULL AND body_option_linked != '' THEN 'unresolved (group-level or missing material)'
         ELSE 'no link'
    END AS link_status,
    COUNT(*) AS row_count
FROM bill_of_materials
GROUP BY link_status
ORDER BY link_status;

-- Step 4 (optional diagnostic): list unresolved names for review
-- These are either valid group-level links ("DRD", "SRD") or typos.
SELECT DISTINCT body_option_linked AS unresolved_name, COUNT(*) AS 'rows'
FROM bill_of_materials
WHERE body_option_linked IS NOT NULL
  AND body_option_linked != ''
  AND body_option_linked_id IS NULL
GROUP BY body_option_linked
ORDER BY body_option_linked;
