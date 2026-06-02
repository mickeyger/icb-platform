-- ================================================================
-- Migration 006: skin_formulas, skin_formula_ingredients,
--                skin_formula_items tables + seed data
--                + bill_of_materials skin FK columns
--
-- Run this ONLY if the app code has NOT been deployed yet.
-- If the app is already deployed and restarted, these tables
-- and columns will already exist — this script is safe to re-run
-- (CREATE TABLE IF NOT EXISTS / INSERT IGNORE / ALTER IGNORE).
-- ================================================================

-- Step 1: create tables
CREATE TABLE IF NOT EXISTS skin_formulas (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(200) NOT NULL UNIQUE,
    description VARCHAR(500),
    is_active   TINYINT(1) DEFAULT 1,
    sort_order  INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS skin_formula_ingredients (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    name             VARCHAR(200) NOT NULL UNIQUE,
    sap_code         VARCHAR(100),
    price_standard   DOUBLE DEFAULT 0.0,
    price_kzn        DOUBLE DEFAULT 0.0,
    is_active        TINYINT(1) DEFAULT 1,
    sort_order       INT DEFAULT 0,
    sap_item_code_id INT DEFAULT NULL,
    CONSTRAINT fk_sfi_sap FOREIGN KEY (sap_item_code_id)
        REFERENCES sap_item_codes(id) ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS skin_formula_items (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    formula_id    INT NOT NULL,
    ingredient_id INT NOT NULL,
    qty_per_m2    DOUBLE DEFAULT 0.0,
    sort_order    INT DEFAULT 0,
    CONSTRAINT fk_sfitem_formula    FOREIGN KEY (formula_id)
        REFERENCES skin_formulas(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_sfitem_ingredient FOREIGN KEY (ingredient_id)
        REFERENCES skin_formula_ingredients(id) ON DELETE CASCADE ON UPDATE CASCADE
);

-- Step 2: seed skin_formulas
INSERT IGNORE INTO skin_formulas (id, name, description, is_active, sort_order) VALUES
  (1, '450CSM-450', 'Single skin 450 CSM laminate', 1, 10),
  (2, '450CSM-300', 'Single skin 300 CSM laminate', 1, 20),
  (3, '900CSM-450-1', 'Double skin 450 CSM interior sheet for RTT', 1, 30),
  (4, '600CSM-450', 'Medium skin 450 CSM laminate', 1, 40),
  (5, '600CSM-300', 'Medium skin 300 CSM laminate', 1, 50),
  (6, '1350CSM', 'Heavy skin 450 CSM exterior sheet for RTT', 1, 60),
  (7, '900CSM-450-0', 'Double skin 450 CSM exterior sheet', 1, 70),
  (8, '900CSM-300', 'Double skin 300 CSM laminate', 1, 80),
  (9, 'INTERNAL KICK PLATE LAMINATION', 'Kick plate internal lamination with pigment', 1, 90),
  (10, 'INTERNAL LAMINATION', 'Internal surface lamination with 300 CSM', 1, 100),
  (11, '450 CSM ONLY', '450 CSM laminate without gelcoat', 1, 110),
  (12, 'FINAL COAT', 'Final coat — resin, aerosil and pigment', 1, 120),
  (13, 'COMBO FLOOR MATT', 'Floor lamination with 600 Twirl 300 CSM', 1, 130);

-- Step 3: seed skin_formula_ingredients
INSERT IGNORE INTO skin_formula_ingredients (id, name, sap_code, price_standard, price_kzn, is_active, sort_order) VALUES
  (1, '59 GELCOAT', 'RES/GELCOAT/WHITE', 47.0, 46.87, 1, 10),
  (2, '282 RESIN', 'RES/ORTHO_LAM/282', 44.05, 30.48, 1, 20),
  (3, '450CSM', 'RES/CSM/450', 31.7, 20.72, 1, 30),
  (4, '300CSM', 'RES/CSM/300', 31.7, 20.72, 1, 40),
  (5, 'M50 CATALYST 1', 'RES/BUTANOX/M50', 124.5, 46.3, 1, 50),
  (6, 'M50 CATALYST 2', 'RES/BUTANOX/M50', 124.5, 46.3, 1, 60),
  (7, 'M50 CATALYST', 'RES/BUTANOX/M50', 124.5, 46.3, 1, 70),
  (8, 'P939 GREY PIGMENT', 'RES/PIGMENT/GREY', 99.1, 75.69, 1, 80),
  (9, 'AEROSIL POWDER', 'RES/CABOSIL_FUME_SIL', 115.0, 78.0, 1, 90),
  (10, '600TWIRL 300CSM', 'RES/TWIRL/300', 42.0, 42.0, 1, 100);

-- Step 4: seed skin_formula_items (recipe rows)
INSERT IGNORE INTO skin_formula_items (id, formula_id, ingredient_id, qty_per_m2, sort_order) VALUES
  (1, 1, 1, 0.75, 10),
  (2, 1, 2, 0.99, 20),
  (3, 1, 3, 0.45, 30),
  (4, 1, 5, 0.015, 40),
  (5, 1, 6, 0.044, 50),
  (6, 2, 1, 0.75, 10),
  (7, 2, 2, 1.035, 20),
  (8, 2, 4, 0.45, 30),
  (9, 2, 5, 0.015, 40),
  (10, 2, 6, 0.046, 50),
  (11, 3, 1, 0.75, 10),
  (12, 3, 2, 1.98, 20),
  (13, 3, 3, 0.9, 30),
  (14, 3, 5, 0.015, 40),
  (15, 3, 6, 0.044, 50),
  (16, 4, 1, 0.75, 10),
  (17, 4, 2, 1.32, 20),
  (18, 4, 3, 0.6, 30),
  (19, 4, 5, 0.015, 40),
  (20, 4, 6, 0.044, 50),
  (21, 5, 1, 0.75, 10),
  (22, 5, 2, 1.38, 20),
  (23, 5, 4, 0.6, 30),
  (24, 5, 5, 0.01125, 40),
  (25, 5, 6, 0.0345, 50),
  (26, 6, 1, 0.75, 10),
  (27, 6, 2, 2.97, 20),
  (28, 6, 3, 1.35, 30),
  (29, 6, 5, 0.015, 40),
  (30, 6, 6, 0.044, 50),
  (31, 7, 1, 0.75, 10),
  (32, 7, 2, 1.98, 20),
  (33, 7, 3, 0.9, 30),
  (34, 7, 5, 0.015, 40),
  (35, 7, 6, 0.044, 50),
  (36, 8, 1, 0.75, 10),
  (37, 8, 2, 2.07, 20),
  (38, 8, 4, 0.9, 30),
  (39, 8, 5, 0.01125, 40),
  (40, 8, 6, 0.0345, 50),
  (41, 9, 3, 0.9, 10),
  (42, 9, 2, 1.98, 20),
  (43, 9, 7, 0.0396, 30),
  (44, 9, 8, 0.198, 40),
  (49, 11, 2, 1.035, 10),
  (50, 11, 3, 0.45, 20),
  (51, 11, 5, 0.01125, 30),
  (52, 11, 6, 0.0345, 40),
  (53, 12, 2, 0.7, 10),
  (54, 12, 9, 0.07, 20),
  (55, 12, 8, 0.07, 30),
  (56, 13, 2, 1.08, 10),
  (57, 13, 10, 1.0, 20),
  (58, 13, 6, 0.018, 30),
  (59, 10, 4, 0.3, 10),
  (60, 10, 2, 0.72, 20),
  (61, 10, 7, 0.0144, 30),
  (62, 10, 8, 0.072, 40);

-- Step 5: link sap_item_code_id on ingredients (requires 005 SAP seed to have run first)
UPDATE skin_formula_ingredients sfi
JOIN sap_item_codes sap ON sap.item_code = sfi.sap_code
SET sfi.sap_item_code_id = sap.id
WHERE sfi.sap_item_code_id IS NULL AND sfi.sap_code IS NOT NULL AND sfi.sap_code != '';

-- Step 6: add skin formula FK columns to bill_of_materials
ALTER TABLE bill_of_materials
    ADD COLUMN skin_formula_id     INT DEFAULT NULL,
    ADD COLUMN skin_formula_region VARCHAR(20) DEFAULT 'standard',
    ADD CONSTRAINT fk_bom_skin FOREIGN KEY (skin_formula_id)
        REFERENCES skin_formulas(id) ON DELETE SET NULL ON UPDATE CASCADE;
-- NOTE: if the app was already deployed, this ALTER will fail with errno 1060
-- (duplicate column) — that is harmless, the columns already exist.

-- Verify
SELECT COUNT(*) AS `skin_formulas (expect 13)`      FROM skin_formulas;
SELECT COUNT(*) AS `ingredients   (expect 10)`      FROM skin_formula_ingredients;
SELECT COUNT(*) AS `recipe rows   (expect 58)`      FROM skin_formula_items;
SELECT COUNT(*) AS `sap links     (expect 9)`       FROM skin_formula_ingredients WHERE sap_item_code_id IS NOT NULL;
SHOW COLUMNS FROM bill_of_materials LIKE 'skin_formula_id';