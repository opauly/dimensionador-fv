-- 063: physical dimensions of the equipment, for the workshop plan ("plano de taller").
-- Values come from the manufacturer datasheets Oscar supplied (2026-11-12). Additive and idempotent.
--
-- Convention (front view, as the unit hangs on the wall):
--   width_mm  = left to right
--   height_mm = top to bottom
--   depth_mm  = how far it sticks out of the wall
-- Panels keep their own width_m / height_m columns.
-- Left NULL on purpose (no datasheet loaded yet): SmartSolar MPPT 150/70, Pylontech US5000, Fronius Smart Meter 63A-3,
-- Fronius Smart Meter WR 100-600 V-3, Victron VM-3P75CT, Lynx Power In / Distributor.

ALTER TABLE inverters           ADD COLUMN IF NOT EXISTS width_mm  numeric;
ALTER TABLE inverters           ADD COLUMN IF NOT EXISTS height_mm numeric;
ALTER TABLE inverters           ADD COLUMN IF NOT EXISTS depth_mm  numeric;
ALTER TABLE inverters           ADD COLUMN IF NOT EXISTS weight_kg numeric;

ALTER TABLE batteries           ADD COLUMN IF NOT EXISTS width_mm  numeric;
ALTER TABLE batteries           ADD COLUMN IF NOT EXISTS height_mm numeric;
ALTER TABLE batteries           ADD COLUMN IF NOT EXISTS depth_mm  numeric;
ALTER TABLE batteries           ADD COLUMN IF NOT EXISTS weight_kg numeric;

ALTER TABLE charge_controllers  ADD COLUMN IF NOT EXISTS width_mm  numeric;
ALTER TABLE charge_controllers  ADD COLUMN IF NOT EXISTS height_mm numeric;
ALTER TABLE charge_controllers  ADD COLUMN IF NOT EXISTS depth_mm  numeric;
ALTER TABLE charge_controllers  ADD COLUMN IF NOT EXISTS weight_kg numeric;

ALTER TABLE monitoring_devices  ADD COLUMN IF NOT EXISTS width_mm  numeric;
ALTER TABLE monitoring_devices  ADD COLUMN IF NOT EXISTS height_mm numeric;
ALTER TABLE monitoring_devices  ADD COLUMN IF NOT EXISTS depth_mm  numeric;
ALTER TABLE monitoring_devices  ADD COLUMN IF NOT EXISTS weight_kg numeric;

-- Inverters ----------------------------------------------------------------------------------------------------------
-- MultiPlus-II 120 V datasheet (h x w x d): 48/3000/35-50 = 572 x 277 x 147 mm, 19 kg; 48/5000/70-95 = 676 x 330 x 164 mm, 32 kg.
UPDATE inverters SET width_mm = 277, height_mm = 572, depth_mm = 147, weight_kg = 19
 WHERE brand = 'Victron Energy' AND model = 'MultiPlus-II 48/3000/35-50';
UPDATE inverters SET width_mm = 330, height_mm = 676, depth_mm = 164, weight_kg = 32
 WHERE brand = 'Victron Energy' AND model = 'MultiPlus-II 48/5000/70-95';
-- Quattro 3-10 kVA 120 V datasheet (h x w x d): 48/10000 = 572 x 488 x 344 mm, 58 kg.
UPDATE inverters SET width_mm = 488, height_mm = 572, depth_mm = 344, weight_kg = 58
 WHERE brand = 'Victron Energy' AND model = 'Quattro 48/10000/140-100/100 120V';
-- Fronius Primo US datasheet (w x h x d, inches converted to mm): 3.8-8.2 = 16.9 x 24.7 x 8.1 in, 47.29 lb; 10.0-15.0 = 20.1 x 28.5 x 8.9 in, 82.5 lb.
UPDATE inverters SET width_mm = 429, height_mm = 627, depth_mm = 206, weight_kg = 21.5
 WHERE brand = 'Fronius' AND model IN ('Primo 6.0-1', 'Primo 8.2-1');
UPDATE inverters SET width_mm = 511, height_mm = 724, depth_mm = 226, weight_kg = 37.4
 WHERE brand = 'Fronius' AND model = 'Primo 10.0-1';

-- Batteries ----------------------------------------------------------------------------------------------------------
-- Fidus datasheet: 638 (W) x 137 (D) x 370 (H) mm, 45 kg. Wall mounted lying down, so 638 wide x 370 high.
UPDATE batteries SET width_mm = 638, height_mm = 370, depth_mm = 137, weight_kg = 45
 WHERE brand = 'Pylontech' AND model = 'Fidus';

-- Charge controllers -------------------------------------------------------------------------------------------------
-- SmartSolar 250/70-100 VE.Can datasheet (h x w x d): 250/100 (Tr) = 216 x 295 x 103 mm, 4.5 kg.
UPDATE charge_controllers SET width_mm = 295, height_mm = 216, depth_mm = 103, weight_kg = 4.5
 WHERE brand = 'Victron Energy' AND model = 'SmartSolar MPPT 250/100';
-- SmartSolar MPPT RS datasheet (h x w x d): 450|200 = 487 x 434 x 146 mm, 13.7 kg.
UPDATE charge_controllers SET width_mm = 434, height_mm = 487, depth_mm = 146, weight_kg = 13.7
 WHERE brand = 'Victron Energy' AND model = 'SmartSolar MPPT RS 450/200';

-- Monitoring ---------------------------------------------------------------------------------------------------------
-- Cerbo GX datasheet (h x w x d): 78 x 154 x 48 mm (wall or DIN rail).
UPDATE monitoring_devices SET width_mm = 154, height_mm = 78, depth_mm = 48
 WHERE brand = 'Victron Energy' AND model = 'Cerbo GX';
-- Ekrano GX datasheet (h x w x d, without connectors and mounting accessories): 124 x 187 x 29.8 mm.
UPDATE monitoring_devices SET width_mm = 187, height_mm = 124, depth_mm = 29.8
 WHERE brand = 'Victron Energy' AND model = 'Ekrano GX';
