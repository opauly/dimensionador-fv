-- English spec for the mounting-structure service line: "Module array" read oddly on an English quote.
-- (Already applied to the live database on 2026-11-10; kept here so a fresh database gets the same text.)
UPDATE service_defaults
SET specs_en = 'Roof mounting structure'
WHERE item = 'Estructura de montaje' AND specs_en = 'Module array';
