-- 064: dimensions of the fixed parts of a Victron/Fronius wall that are not in the equipment tables (Lynx, gabinete, Chint box, ...),
-- for the workshop plan ("plano de taller"). One row per part, front view as it hangs on the wall (same convention as 063).
-- Additive and idempotent. Same access setup as the other equipment tables (no RLS).
--
-- Lynx Power In: Victron drawing supplied by Oscar (2026-11-12): body 252 mm wide, 168.8 mm high including the cable covers at the
-- bottom; the two busbar lugs stick out of the LEFT side by about 37 mm more (13.5 mm lug start, scaled from the drawing). The drawing is
-- a front view, so the depth is not in it: left NULL until the datasheet is loaded.

CREATE TABLE IF NOT EXISTS fixed_equipment_dimensions (
    key        text PRIMARY KEY,
    name       text NOT NULL,
    width_mm   numeric,
    height_mm  numeric,
    depth_mm   numeric,
    weight_kg  numeric,
    notes      text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fixed_equipment_dimensions (key, name, width_mm, height_mm, depth_mm, notes)
VALUES ('lynx_power_in', 'Victron Lynx Power In', 252, 168.8, NULL,
        'Dibujo de Victron: 252 mm de cuerpo x 168.8 mm de alto (con las tapas de cables abajo). Las dos orejas de las barras salen ~37 mm más por el lado izquierdo. Fondo pendiente de ficha.')
ON CONFLICT (key) DO UPDATE
   SET name = EXCLUDED.name, width_mm = EXCLUDED.width_mm, height_mm = EXCLUDED.height_mm, depth_mm = EXCLUDED.depth_mm,
       notes = EXCLUDED.notes, updated_at = now();
