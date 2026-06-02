-- Update chassis_constants qty_constant and unit_price on production
-- Generated from local costing.db on 2026-04-27
-- Run: mariadb -u fajecoza_mickeyger -p fajecoza_grp_costings < update_chassis_constants_prod.sql

START TRANSACTION;

UPDATE chassis_constants SET qty_constant=0.0,  unit_price=161.27   WHERE id=1;   -- 130x8 55C Flat Bar (length-scaled, qty/m=4)
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=1145.56  WHERE id=2;   -- 3mm Hot Rolled Sheet 1225x2450
UPDATE chassis_constants SET qty_constant=5.0,  unit_price=3046.86  WHERE id=3;   -- 5mm 350WA 3000x1500
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=2369.00  WHERE id=4;   -- 6mm 350WA 1250x2500
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=3180.00  WHERE id=5;   -- 8mm 350WA 1250x2500
UPDATE chassis_constants SET qty_constant=3.0,  unit_price=167.92   WHERE id=6;   -- 100x100x3 Square Tube
UPDATE chassis_constants SET qty_constant=12.0, unit_price=208.90   WHERE id=7;   -- 120x55 RSC
UPDATE chassis_constants SET qty_constant=18.0, unit_price=5.78     WHERE id=8;   -- 8mm Round Bar
UPDATE chassis_constants SET qty_constant=1.5,  unit_price=433.15   WHERE id=9;   -- 127x4.5 Round Tube
UPDATE chassis_constants SET qty_constant=1.5,  unit_price=825.50   WHERE id=10;  -- 219x4.5 Round Tube
UPDATE chassis_constants SET qty_constant=6.0,  unit_price=0.00     WHERE id=11;  -- 25mm Round Bar (no price in sheet)
UPDATE chassis_constants SET qty_constant=6.0,  unit_price=69.00    WHERE id=12;  -- 50x3 Round Tube
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=6531.00  WHERE id=13;  -- JOST Landing Legs
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=1838.90  WHERE id=14;  -- 1008 King Pin
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=1065.535 WHERE id=15;  -- Electrical Loom
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=267.08   WHERE id=16;  -- Mudflaps
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=0.00     WHERE id=17;  -- Electrical Plugs (no price in sheet)
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=165.00   WHERE id=18;  -- Chevron
UPDATE chassis_constants SET qty_constant=2.6,  unit_price=18.00    WHERE id=19;  -- Reflexite Tape (length-scaled, qty/m=2)
UPDATE chassis_constants SET qty_constant=1.0,  unit_price=0.00     WHERE id=20;  -- Paint (no price in sheet)

-- Verify
SELECT id, category, name, qty_per_metre, qty_constant, unit_price
FROM chassis_constants
ORDER BY id;

COMMIT;
