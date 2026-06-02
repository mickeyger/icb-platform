-- migrations/008_taping_blocks.sql
-- Creates taping_blocks and taping_block_items tables, adds taping_block_id to bill_of_materials.
-- Run in phpMyAdmin on fajecoza_grp_costings.

-- ── Step 1: Verify tables don't exist ─────────────────────────────────────────
SHOW TABLES LIKE 'taping_blocks';
SHOW TABLES LIKE 'taping_block_items';

-- ── Step 2: Create taping_blocks table ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS taping_blocks (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(200) NOT NULL UNIQUE,
    description VARCHAR(500),
    size_mm     INT,
    is_active   TINYINT(1) NOT NULL DEFAULT 1,
    sort_order  INT NOT NULL DEFAULT 0
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ── Step 3: Create taping_block_items table ───────────────────────────────────
CREATE TABLE IF NOT EXISTS taping_block_items (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    block_id         INT NOT NULL,
    item_name        VARCHAR(200) NOT NULL,
    sap_code         VARCHAR(100),
    sap_item_code_id INT,
    length           FLOAT NOT NULL DEFAULT 0,
    width            FLOAT NOT NULL DEFAULT 0,
    m2               FLOAT NOT NULL DEFAULT 0,
    price_per_unit   FLOAT NOT NULL DEFAULT 0,
    price_source     VARCHAR(10) NOT NULL DEFAULT 'standard',
    quantity         FLOAT NOT NULL DEFAULT 1,
    sort_order       INT NOT NULL DEFAULT 0,
    FOREIGN KEY (block_id) REFERENCES taping_blocks(id) ON DELETE CASCADE,
    FOREIGN KEY (sap_item_code_id) REFERENCES sap_item_codes(id) ON DELETE SET NULL
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- ── Step 4: Add taping_block_id to bill_of_materials ─────────────────────────
SHOW COLUMNS FROM bill_of_materials LIKE 'taping_block_id';
-- If empty result above, run:
ALTER TABLE bill_of_materials
    ADD COLUMN taping_block_id INT NULL,
    ADD CONSTRAINT fk_bom_taping_block
        FOREIGN KEY (taping_block_id) REFERENCES taping_blocks(id) ON DELETE SET NULL;

-- ── Step 5: Verify ────────────────────────────────────────────────────────────
SHOW COLUMNS FROM bill_of_materials LIKE 'taping_block_id';
SELECT COUNT(*) AS taping_block_rows FROM taping_blocks;
SELECT COUNT(*) AS taping_block_item_rows FROM taping_block_items;

-- NOTE: Data is seeded automatically by _bootstrap_taping_blocks() on app startup.
-- Touch tmp/restart.txt after running this script to reload the app.
