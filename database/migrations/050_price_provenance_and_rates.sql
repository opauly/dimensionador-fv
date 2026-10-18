-- 050: price provenance for catalog items + per-Wp service rates + proforma import log.
--
-- 1. Every catalog table gets price_updated_at / price_source so the Admin
--    tables and the wizard's Costos step can show "last updated" and where the
--    price came from (typically a supplier proforma).
-- 2. service_defaults gets cost_per_wp ($ per quoted Wp). When set, the wizard
--    pre-fills that line as cost_per_wp x quoted kWp x 1000 instead of the flat
--    unit_cost_usd (mounting structure, labor, electrical materials).
-- 3. price_imports logs each applied proforma upload (who/what/when + lines).
-- 4. Seeds: accessories line (flat), optional $0 lines (lodging, battery
--    cabinet), per-Wp rates from the María José Castro project, provenance for
--    the catalog prices corrected on 2026-10-17.
--
-- Additive and idempotent (safe to re-run).

ALTER TABLE panels             ADD COLUMN IF NOT EXISTS price_updated_at timestamptz, ADD COLUMN IF NOT EXISTS price_source text;
ALTER TABLE inverters          ADD COLUMN IF NOT EXISTS price_updated_at timestamptz, ADD COLUMN IF NOT EXISTS price_source text;
ALTER TABLE batteries          ADD COLUMN IF NOT EXISTS price_updated_at timestamptz, ADD COLUMN IF NOT EXISTS price_source text;
ALTER TABLE charge_controllers ADD COLUMN IF NOT EXISTS price_updated_at timestamptz, ADD COLUMN IF NOT EXISTS price_source text;
ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS price_updated_at timestamptz, ADD COLUMN IF NOT EXISTS price_source text;

ALTER TABLE service_defaults
    ADD COLUMN IF NOT EXISTS cost_per_wp numeric,
    ADD COLUMN IF NOT EXISTS price_updated_at timestamptz,
    ADD COLUMN IF NOT EXISTS price_source text;

CREATE TABLE IF NOT EXISTS price_imports (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier     text,
    doc_number   text,
    doc_date     date,
    filename     text,
    storage_path text,
    kwp          numeric,
    discount_applied boolean NOT NULL DEFAULT false,
    lines        jsonb NOT NULL DEFAULT '[]'::jsonb,
    summary      jsonb NOT NULL DEFAULT '{}'::jsonb,
    applied_at   timestamptz NOT NULL DEFAULT now()
);

-- Provenance for the catalog prices set from the real María José Castro proformas.
UPDATE panels SET price_updated_at = '2026-08-18', price_source = 'HCG proforma 180-2026'
 WHERE model IN ('JAM72S30-620/MR', 'SUN600-66MDH12RS');
UPDATE inverters SET price_updated_at = '2026-08-18', price_source = 'HCG proforma 180-2026'
 WHERE model = 'MultiPlus-II 48/5000/70-95';
UPDATE inverters SET price_updated_at = '2026-07-14', price_source = 'Nundi proforma N021-2026'
 WHERE brand = 'Fronius' AND model = 'Primo 10.0-1';
UPDATE batteries SET price_updated_at = '2026-08-18', price_source = 'HCG proforma 180-2026'
 WHERE model = 'Fidus';
UPDATE monitoring_devices SET price_updated_at = '2026-08-18', price_source = 'HCG proforma 180-2026'
 WHERE model = 'Ekrano GX';

-- Per-Wp rates (María José Castro, 9.6-9.92 kWp). Labor/materials are
-- placeholders from her cost sheet until real project expenses replace them.
UPDATE service_defaults SET cost_per_wp = 0.055156, price_updated_at = '2026-08-18',
       price_source = 'HCG proforma 180-2026 (rieles/clamps, 9.6 kWp)'
 WHERE item = 'Estructura de montaje';
UPDATE service_defaults SET cost_per_wp = 0.3528, price_updated_at = now(),
       price_source = 'Hoja de costos María José Castro, 9.92 kWp (marcador)'
 WHERE item = 'Mano de obra';
UPDATE service_defaults SET cost_per_wp = 0.1512, price_updated_at = now(),
       price_source = 'Hoja de costos María José Castro, 9.92 kWp (marcador)'
 WHERE item = 'Materiales eléctricos';

-- Accessories: flat per system (Lynx Power In, energy meter, comms cables, fuses).
INSERT INTO service_defaults (item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled, sort_order, system_types, markup_eligible, price_updated_at, price_source)
SELECT 'Accesorios', 'Accessories', 910.0, 0.13,
       'Lynx Power In, medidor de energía, cables de comunicación y fusibles MEGA',
       'Lynx Power In, energy meter, communication cables and MEGA fuses',
       true, 26, ARRAY['off_grid','hybrid'], true, '2026-08-18', 'HCG proforma 180-2026'
WHERE NOT EXISTS (SELECT 1 FROM service_defaults WHERE item = 'Accesorios');

-- Optional lines, $0 by default.
INSERT INTO service_defaults (item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled, sort_order, system_types, markup_eligible)
SELECT 'Estadía', 'Lodging', 0.0, 0.13, 'Hospedaje del equipo de instalación', 'Installation crew lodging', true, 55, NULL, true
WHERE NOT EXISTS (SELECT 1 FROM service_defaults WHERE item = 'Estadía');

INSERT INTO service_defaults (item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled, sort_order, system_types, markup_eligible)
SELECT 'Mueble de baterías', 'Battery cabinet', 0.0, 0.13, 'Gabinete para banco de baterías', 'Battery bank cabinet', true, 56, ARRAY['off_grid','hybrid'], true
WHERE NOT EXISTS (SELECT 1 FROM service_defaults WHERE item = 'Mueble de baterías');
