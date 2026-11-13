-- 065: more equipment dimensions from the datasheets Oscar supplied (2026-11-12), same convention as 063 (front view on the wall:
-- width left-right, height top-bottom, depth out of the wall). Idempotent. Completes 063/064.
--
-- Left NULL on purpose: Fronius Smart Meter WR 100-600 V-3 (the datasheet we have is the "240 V-3 UL" one and its orientation on the wall
-- needs Oscar's confirmation), Lynx Distributor.

-- Pylontech US5000 (rack battery): 442 x 420 x 161 mm (W x D x H), 38 kg. Lies flat on the stand: 442 wide, 161 high, 420 deep.
UPDATE batteries SET width_mm = 442, height_mm = 161, depth_mm = 420, weight_kg = 38
 WHERE brand = 'Pylontech' AND model = 'US5000';

-- SmartSolar MPPT 150/70 VE.Can datasheet (h x w x d), Tr model: 185 x 250 x 95 mm, 3 kg.
UPDATE charge_controllers SET width_mm = 250, height_mm = 185, depth_mm = 95, weight_kg = 3
 WHERE brand = 'Victron Energy' AND model = 'SmartSolar MPPT 150/70';

-- Victron Energy Meter VM-3P75CT datasheet (h x w x d): 90 x 71 x 59 mm, 370 g including packaging.
UPDATE monitoring_devices SET width_mm = 71, height_mm = 90, depth_mm = 59, weight_kg = 0.37
 WHERE brand = 'Victron Energy' AND model = 'VM-3P75CT';

-- Fronius Smart Meter datasheet (UL version, 240 V-3 UL), listed as height x width x depth: 38 x 143 x 85 mm, 310 g.
-- Applied to the 63A-3 row on the assumption that it shares the housing; to be confirmed.
UPDATE monitoring_devices SET width_mm = 143, height_mm = 38, depth_mm = 85, weight_kg = 0.31
 WHERE brand = 'Fronius' AND model = 'Smart Meter 63A-3';

-- Lynx Power In: the second Victron drawing (view from below) gives the depth, 77.5 mm, and the overall width with the busbar lugs, 288 mm
-- (252 mm body + ~36 mm lugs on the left). The overall width is what takes wall space, so that is the one stored.
UPDATE fixed_equipment_dimensions
   SET width_mm = 288, height_mm = 168.8, depth_mm = 77.5,
       notes = 'Dibujos de Victron: 288 mm de ancho total (cuerpo de 252 mm + orejas de las barras ~36 mm por la izquierda), 168.8 mm de alto con las tapas de cables abajo, 77.5 mm de fondo.',
       updated_at = now()
 WHERE key = 'lynx_power_in';
