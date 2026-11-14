-- 068: Chint NXW1-5 surface distribution box (the "centro de carga Chint DC 5 espacios") for the workshop plan, from Oscar (2026-11-13).
-- Overall width 184 mm, depth 108 mm; mounting-hole centres 102.8 mm (width) x 136 mm (height). The overall height is NOT in the source: 136 mm is
-- the hole spacing, so the real box is a little taller (some retailers list ~135 x 125 x 108 mm) -> height left as 136 and marked to confirm.
-- Same front-view convention as 063 / 064 (width left-right, height top-bottom, depth out of the wall). Idempotent.
INSERT INTO fixed_equipment_dimensions (key, name, width_mm, height_mm, depth_mm, notes)
VALUES ('chint_dc_5', 'Centro de carga Chint NXW1-5 (DC, 5 espacios)', 184, 136, 108,
        'Ancho 184 mm y fondo 108 mm; centros de montaje 102.8 x 136 mm. El alto total no viene en la fuente: 136 mm es la distancia entre agujeros, el alto real puede ser algo mayor (POR CONFIRMAR).')
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, width_mm = EXCLUDED.width_mm, height_mm = EXCLUDED.height_mm, depth_mm = EXCLUDED.depth_mm,
       notes = EXCLUDED.notes, updated_at = now();
