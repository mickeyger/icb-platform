-- Migration 007: Deduplicate sap_item_codes and add UNIQUE constraint
-- Run in phpMyAdmin on fajecoza_grp_costings (Ctrl+Enter)
-- Safe to run multiple times — each step checks before acting.

-- ── Step 1: Inspect duplicates ───────────────────────────────────────────────
SELECT item_code, GROUP_CONCAT(id ORDER BY id ASC SEPARATOR ', ') AS ids, COUNT(*) AS cnt
FROM sap_item_codes
GROUP BY item_code
HAVING cnt > 1;
-- Expect to see RES/GELCOAT/WHITE (and any others). Note the ids.

-- ── Step 2: Re-point ingredient FK refs from lower-id duplicate → higher-id ─
-- (safe: if the higher-id row is already the linked one, no rows change)
UPDATE skin_formula_ingredients sfi
INNER JOIN (
    SELECT item_code, MAX(id) AS keep_id
    FROM sap_item_codes
    GROUP BY item_code
    HAVING COUNT(*) > 1
) dedup
    ON sfi.sap_item_code_id IN (
        SELECT id FROM sap_item_codes
        WHERE item_code = dedup.item_code
          AND id != dedup.keep_id
    )
SET sfi.sap_item_code_id = dedup.keep_id;

-- ── Step 3: Delete the extra rows (keep MAX id for each duplicated code) ─────
DELETE sc FROM sap_item_codes sc
INNER JOIN (
    SELECT item_code, MAX(id) AS keep_id
    FROM sap_item_codes
    GROUP BY item_code
    HAVING COUNT(*) > 1
) dedup
    ON sc.item_code = dedup.item_code
   AND sc.id != dedup.keep_id;

-- ── Step 4: Add UNIQUE index if not already present ──────────────────────────
-- MySQL 8+: supports IF NOT EXISTS
-- If you're on MySQL 5.7, run the SELECT first — if it returns a row, skip this step.
SELECT COUNT(*) AS already_has_unique
FROM information_schema.STATISTICS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'sap_item_codes'
  AND NON_UNIQUE   = 0
  AND INDEX_NAME  != 'PRIMARY';

-- If the above returns 0, run this:
-- ALTER TABLE sap_item_codes ADD UNIQUE INDEX idx_sap_item_code (item_code(191));
-- (191 chars = safe prefix length for VARCHAR(200) with utf8mb4)

-- ── Verify ───────────────────────────────────────────────────────────────────
SELECT COUNT(*) AS total_codes, COUNT(DISTINCT item_code) AS unique_codes FROM sap_item_codes;
-- total_codes should equal unique_codes (no duplicates remaining)

SELECT item_code, COUNT(*) FROM sap_item_codes GROUP BY item_code HAVING COUNT(*) > 1;
-- Should return 0 rows
