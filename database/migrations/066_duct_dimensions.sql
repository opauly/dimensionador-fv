-- 066: the wall duct ("ducto") for the workshop plan, from Oscar (2026-11-12): 4 x 4 inch section (101.6 x 101.6 mm). Its LENGTH is not fixed:
-- it is the length of the whole row of solar equipment plus the gabinete (calculated by the plan), so width_mm stays NULL.
-- Idempotent.
INSERT INTO fixed_equipment_dimensions (key, name, width_mm, height_mm, depth_mm, notes)
VALUES ('ducto_4x4', 'Ducto 4x4 pulgadas', NULL, 101.6, 101.6,
        'Sección de 4x4 pulgadas (101.6 x 101.6 mm). El largo no es fijo: es el largo de todos los equipos solares de la fila + el gabinete (lo calcula el plano).')
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, width_mm = EXCLUDED.width_mm, height_mm = EXCLUDED.height_mm, depth_mm = EXCLUDED.depth_mm,
       notes = EXCLUDED.notes, updated_at = now();
