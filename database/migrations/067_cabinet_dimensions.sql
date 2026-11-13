-- 067: the standard gabinete 50x40x20 for the workshop plan, from Oscar (2026-11-12): it hangs UPRIGHT ("de pie"), so 50 cm high,
-- 40 cm wide, 20 cm deep. These are the nominal sizes of the list line (comment "POR CONFIRMAR MEDIDA"); the exterior size of the real
-- box can be a little larger. Idempotent.
INSERT INTO fixed_equipment_dimensions (key, name, width_mm, height_mm, depth_mm, notes)
VALUES ('gabinete_50x40x20', 'Gabinete 50x40x20', 400, 500, 200,
        'Va de pie: 500 mm de alto x 400 mm de ancho x 200 mm de fondo (medida nominal; POR CONFIRMAR MEDIDA exterior).')
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, width_mm = EXCLUDED.width_mm, height_mm = EXCLUDED.height_mm, depth_mm = EXCLUDED.depth_mm,
       notes = EXCLUDED.notes, updated_at = now();
