-- Migration 011: manual pre-Phase-10 import of the maintenance register's sites
--
-- Feeds the 22 real installations from `Registro de mantenimientos FV.xlsx`
-- (Proyectos FV sheet) into monitoring.sites, ahead of the full Phase 10 build
-- (PHASES.md). Lori Pickett's 3 existing rows (vista-atenas-lp-m1/m2/m3) are
-- deliberately excluded and untouched.
--
-- Does NOT include (left for Phase 10 proper):
--   - property_id linkage (public.site_properties doesn't exist yet; column is
--     added here so it doesn't need a second ALTER later, but stays NULL)
--   - maintenance visit history (the per-year Fecha/Monto columns in the xlsx)
--   - credentials (public.site_credentials doesn't exist yet)
--   - geocoded latitude/longitude (left NULL — fill in manually per the
--     -- TODO comment on each row; PHASES.md flags a real bug in the existing
--     geocode_cr() helper for "San Isidro, Heredia" specifically, so don't
--     trust that helper for this one row even once Phase 10 automates the rest)
--
-- Safe to re-run: every INSERT is guarded by WHERE NOT EXISTS.

-- ============================================================
-- 1. Schema: new columns on monitoring.sites + on_grid system_type
-- ============================================================

ALTER TABLE monitoring.sites ADD COLUMN IF NOT EXISTS property_id     uuid;
ALTER TABLE monitoring.sites ADD COLUMN IF NOT EXISTS panel_count     int;
ALTER TABLE monitoring.sites ADD COLUMN IF NOT EXISTS inverter_count  int;
ALTER TABLE monitoring.sites ADD COLUMN IF NOT EXISTS battery_count   int;
ALTER TABLE monitoring.sites ADD COLUMN IF NOT EXISTS monitoring_urls text[];

-- Drop and recreate the system_type CHECK constraint by looking up its actual
-- name rather than assuming one, since migration 009 added it unnamed.
DO $$
DECLARE
  c_name text;
BEGIN
  SELECT con.conname INTO c_name
  FROM pg_constraint con
  JOIN pg_class rel ON rel.oid = con.conrelid
  JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
  WHERE nsp.nspname = 'monitoring'
    AND rel.relname = 'sites'
    AND con.contype = 'c'
    AND pg_get_constraintdef(con.oid) ILIKE '%system_type%';

  IF c_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE monitoring.sites DROP CONSTRAINT %I', c_name);
  END IF;
END $$;

ALTER TABLE monitoring.sites
  ADD CONSTRAINT sites_system_type_check
  CHECK (system_type IN ('grid_zero', 'off_grid', 'hybrid', 'on_grid'));

-- ============================================================
-- 2. Clients: create the 11 real customers missing from public.clients
--    (confirmed live 2026-07-18: only 'Oscar Pauly' exists today)
-- ============================================================

INSERT INTO public.clients (name)
SELECT 'Bryan Gutiérrez'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Bryan Gutiérrez');

INSERT INTO public.clients (name)
SELECT 'Fundación Rahab'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Fundación Rahab');

INSERT INTO public.clients (name)
SELECT 'Manuel Mayorga'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Manuel Mayorga');

INSERT INTO public.clients (name)
SELECT 'Karen Montealegre'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Karen Montealegre');

INSERT INTO public.clients (name)
SELECT 'Karol Álvarez'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Karol Álvarez');

INSERT INTO public.clients (name)
SELECT 'Asoamazon'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Asoamazon');

INSERT INTO public.clients (name)
SELECT 'María Lía Artavia'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'María Lía Artavia');

INSERT INTO public.clients (name)
SELECT 'The Rainforest Lab'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'The Rainforest Lab');

INSERT INTO public.clients (name)
SELECT 'Roberto Villalobos'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Roberto Villalobos');

INSERT INTO public.clients (name)
SELECT 'Rebeca Ruiz'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Rebeca Ruiz');

INSERT INTO public.clients (name)
SELECT 'Isaac Cerdas'
WHERE NOT EXISTS (SELECT 1 FROM public.clients WHERE name = 'Isaac Cerdas');

-- ============================================================
-- 3. Sites: insert the 22 non-Lori-Pickett installations
--    latitude/longitude left NULL — fill in manually, see location column
-- ============================================================

-- Bryan Gutiérrez (Bryan Gutiérrez) — Naranjo, Alajuela
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'bryan-gutierrez', 'Bryan Gutiérrez', 'Bryan Gutiérrez',
  (SELECT id FROM public.clients WHERE name = 'Bryan Gutiérrez'),
  'Naranjo, Alajuela', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Naranjo, Alajuela"
  NULL, 'America/Costa_Rica', '2020-12-15', 'es',
  12.0, 1.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'bryan-gutierrez');

-- Fundación Rahab (Fundación Rahab) — Central, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'fundacion-rahab', 'Fundación Rahab', 'Fundación Rahab',
  (SELECT id FROM public.clients WHERE name = 'Fundación Rahab'),
  'Central, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Central, San José"
  NULL, 'America/Costa_Rica', '2021-10-15', 'es',
  18.0, 1.0, NULL, ARRAY['https://egauge57384.egaug.es/5F2E0/classic.html', 'https://ennexos.sunnyportal.com/13673613/dashboard'], 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'fundacion-rahab');

-- Manuel Mayorga (Manuel Mayorga) — Barva, Heredia
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'manuel-mayorga', 'Manuel Mayorga', 'Manuel Mayorga',
  (SELECT id FROM public.clients WHERE name = 'Manuel Mayorga'),
  'Barva, Heredia', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Barva, Heredia"
  NULL, 'America/Costa_Rica', '2022-01-26', 'es',
  18.0, 1.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'manuel-mayorga');

-- Karen Montealegre (Karen Montealegre) — Santa Ana, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'karen-montealegre', 'Karen Montealegre', 'Karen Montealegre',
  (SELECT id FROM public.clients WHERE name = 'Karen Montealegre'),
  'Santa Ana, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Santa Ana, San José"
  10.64, 'America/Costa_Rica', '2021-11-10', 'es',
  24, 1.0, 20.0, ARRAY['https://vrm.victronenergy.com/installation/156868/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'karen-montealegre');

-- Karen Montealegre (Guarda) (Karen Montealegre) — Santa Ana, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'karen-montealegre-guarda', 'Karen Montealegre (Guarda)', 'Karen Montealegre',
  (SELECT id FROM public.clients WHERE name = 'Karen Montealegre'),
  'Santa Ana, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Santa Ana, San José"
  NULL, 'America/Costa_Rica', '2025-08-19', 'es',
  NULL, 2.0, 2.0, ARRAY['https://vrm.victronenergy.com/installation/820959/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'karen-montealegre-guarda');

-- Karen Montealegre (Portón) (Karen Montealegre) — Santa Ana, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'karen-montealegre-porton', 'Karen Montealegre (Portón)', 'Karen Montealegre',
  (SELECT id FROM public.clients WHERE name = 'Karen Montealegre'),
  'Santa Ana, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Santa Ana, San José"
  0.55, 'America/Costa_Rica', '2024-02-26', 'es',
  1.0, 1.0, 1.0, NULL, 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'karen-montealegre-porton');

-- Hugo Aguilar (Karol Álvarez) — Corredores, Puntarenas
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'hugo-aguilar', 'Hugo Aguilar', 'Karol Álvarez',
  (SELECT id FROM public.clients WHERE name = 'Karol Álvarez'),
  'Corredores, Puntarenas', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Corredores, Puntarenas"
  NULL, 'America/Costa_Rica', '2024-07-24', 'es',
  4.0, 4.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'hugo-aguilar');

-- Apartamento papás KA (Karol Álvarez) — Corredores, Puntarenas
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'apartamento-papas-ka', 'Apartamento papás KA', 'Karol Álvarez',
  (SELECT id FROM public.clients WHERE name = 'Karol Álvarez'),
  'Corredores, Puntarenas', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Corredores, Puntarenas"
  NULL, 'America/Costa_Rica', '2024-09-26', 'es',
  4.0, 4.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'apartamento-papas-ka');

-- Bernal Espinoza (Karol Álvarez) — Corredores, Puntarenas
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'bernal-espinoza', 'Bernal Espinoza', 'Karol Álvarez',
  (SELECT id FROM public.clients WHERE name = 'Karol Álvarez'),
  'Corredores, Puntarenas', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Corredores, Puntarenas"
  NULL, 'America/Costa_Rica', '2025-01-25', 'es',
  5.0, 5.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'bernal-espinoza');

-- Kattia Álvarez (Karol Álvarez) — Corredores, Puntarenas
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'kattia-alvarez', 'Kattia Álvarez', 'Karol Álvarez',
  (SELECT id FROM public.clients WHERE name = 'Karol Álvarez'),
  'Corredores, Puntarenas', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Corredores, Puntarenas"
  NULL, 'America/Costa_Rica', '2025-01-25', 'es',
  5.0, 5.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'kattia-alvarez');

-- Karol Álvarez (Neily) (Karol Álvarez) — Corredores, Puntarenas
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'karol-alvarez-neily', 'Karol Álvarez (Neily)', 'Karol Álvarez',
  (SELECT id FROM public.clients WHERE name = 'Karol Álvarez'),
  'Corredores, Puntarenas', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Corredores, Puntarenas"
  NULL, 'America/Costa_Rica', '2022-07-01', 'es',
  14.0, 1.0, NULL, ARRAY['https://egauge76108.egaug.es/616DC/classic.html', 'https://www.solarweb.com/PvSystems/PvSystem?pvSystemId=7b670856-6789-49ec-9626-92723eeada60'], 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'karol-alvarez-neily');

-- Karol Álvarez (Belén) (Karol Álvarez) — Belén, Heredia
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'karol-alvarez-belen', 'Karol Álvarez (Belén)', 'Karol Álvarez',
  (SELECT id FROM public.clients WHERE name = 'Karol Álvarez'),
  'Belén, Heredia', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Belén, Heredia"
  NULL, 'America/Costa_Rica', '2025-06-24', 'es',
  9.0, 1.0, NULL, ARRAY['https://www.solarweb.com/PvSystems/PvSystem?pvSystemId=38e805bb-6285-4913-9b4e-88e6c7f5b3ca'], 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'karol-alvarez-belen');

-- Asoamazon (Asoamazon) — Montes de Oca, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'asoamazon', 'Asoamazon', 'Asoamazon',
  (SELECT id FROM public.clients WHERE name = 'Asoamazon'),
  'Montes de Oca, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Montes de Oca, San José"
  NULL, 'America/Costa_Rica', '2024-02-12', 'es',
  24.0, 1.0, NULL, ARRAY['https://www.solarweb.com/PvSystems/PvSystem?pvSystemId=aabffc6c-119a-4490-bcc4-b5b991be52f0'], 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'asoamazon');

-- Hacienda Zurquí (María Lía Artavia) — San Isidro, Heredia
-- NOTE: see PHASES.md Phase 10 — do NOT trust geocode_cr()'s city-only
-- fallback for this location, it resolves "San Isidro" to Pérez Zeledón.
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'hacienda-zurqui', 'Hacienda Zurquí', 'María Lía Artavia',
  (SELECT id FROM public.clients WHERE name = 'María Lía Artavia'),
  'San Isidro, Heredia', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "San Isidro, Heredia" (NOT Pérez Zeledón)
  NULL, 'America/Costa_Rica', '2023-11-20', 'es',
  16.0, 1.0, NULL, ARRAY['https://egauge92041.egaug.es/64E77/classic.html'], 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'hacienda-zurqui');

-- The Rainforest Lab (The Rainforest Lab) — Montes de Oca, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'the-rainforest-lab', 'The Rainforest Lab', 'The Rainforest Lab',
  (SELECT id FROM public.clients WHERE name = 'The Rainforest Lab'),
  'Montes de Oca, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Montes de Oca, San José"
  NULL, 'America/Costa_Rica', '2025-06-19', 'es',
  16.0, 1.0, NULL, ARRAY['https://www.solarweb.com/PvSystems/PvSystem?pvSystemId=cfe513b9-5d17-4017-899b-504ead7b0fbc'], 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'the-rainforest-lab');

-- Roberto Villalobos (Roberto Villalobos) — Santa Ana, San José
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'roberto-villalobos', 'Roberto Villalobos', 'Roberto Villalobos',
  (SELECT id FROM public.clients WHERE name = 'Roberto Villalobos'),
  'Santa Ana, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Santa Ana, San José"
  NULL, 'America/Costa_Rica', '2025-10-25', 'es',
  17.0, 2.0, 3.0, ARRAY['https://vrm.victronenergy.com/installation/855465/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'roberto-villalobos');

-- Rebeca Ruiz (Casita) (Rebeca Ruiz) — Liberia, Guanacaste
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'rebeca-ruiz-casita', 'Rebeca Ruiz (Casita)', 'Rebeca Ruiz',
  (SELECT id FROM public.clients WHERE name = 'Rebeca Ruiz'),
  'Liberia, Guanacaste', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Liberia, Guanacaste"
  9.44, 'America/Costa_Rica', '2024-12-16', 'es',
  16.0, 4.0, 6.0, ARRAY['https://vrm.victronenergy.com/installation/524935/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'rebeca-ruiz-casita');

-- Rebeca Ruiz (Apartamento) (Rebeca Ruiz) — Liberia, Guanacaste
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'rebeca-ruiz-apartamento', 'Rebeca Ruiz (Apartamento)', 'Rebeca Ruiz',
  (SELECT id FROM public.clients WHERE name = 'Rebeca Ruiz'),
  'Liberia, Guanacaste', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Liberia, Guanacaste"
  4.72, 'America/Costa_Rica', '2024-12-18', 'es',
  8.0, 2.0, 3.0, ARRAY['https://vrm.victronenergy.com/installation/523804/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'rebeca-ruiz-apartamento');

-- Rebeca Ruiz (Casona) (Rebeca Ruiz) — Liberia, Guanacaste
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'rebeca-ruiz-casona', 'Rebeca Ruiz (Casona)', 'Rebeca Ruiz',
  (SELECT id FROM public.clients WHERE name = 'Rebeca Ruiz'),
  'Liberia, Guanacaste', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Liberia, Guanacaste"
  8.8, 'America/Costa_Rica', '2025-07-05', 'es',
  16.0, 2.0, 3.0, ARRAY['https://vrm.victronenergy.com/installation/793865/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'rebeca-ruiz-casona');

-- Rebeca Ruiz (Cabaña) (Rebeca Ruiz) — Liberia, Guanacaste
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'rebeca-ruiz-cabana', 'Rebeca Ruiz (Cabaña)', 'Rebeca Ruiz',
  (SELECT id FROM public.clients WHERE name = 'Rebeca Ruiz'),
  'Liberia, Guanacaste', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Liberia, Guanacaste"
  7.26, 'America/Costa_Rica', '2025-07-12', 'es',
  12.0, 4.0, 2.0, ARRAY['https://vrm.victronenergy.com/installation/797584/dashboard'], 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'rebeca-ruiz-cabana');

-- Rebeca Ruiz (Portón cabaña) (Rebeca Ruiz) — Liberia, Guanacaste
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'rebeca-ruiz-porton-cabana', 'Rebeca Ruiz (Portón cabaña)', 'Rebeca Ruiz',
  (SELECT id FROM public.clients WHERE name = 'Rebeca Ruiz'),
  'Liberia, Guanacaste', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Liberia, Guanacaste"
  NULL, 'America/Costa_Rica', '2025-11-07', 'es',
  1.0, 1.0, 1.0, NULL, 'hybrid'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'rebeca-ruiz-porton-cabana');

-- Isaac Cerdas (Isaac Cerdas) — Zapote, San José
-- NOTE: source xlsx has no "Fecha instalación" for this row (real data gap,
-- not an import bug) — commissioned_at is left NULL.
INSERT INTO monitoring.sites
  (site_id, display_name, owner, client_id, location, country,
   latitude, longitude, pv_kwp, timezone, commissioned_at, report_language,
   panel_count, inverter_count, battery_count, monitoring_urls, system_type)
SELECT
  'isaac-cerdas', 'Isaac Cerdas', 'Isaac Cerdas',
  (SELECT id FROM public.clients WHERE name = 'Isaac Cerdas'),
  'Zapote, San José', 'CR',
  NULL, NULL,  -- TODO: latitude, longitude for "Zapote, San José"
  NULL, 'America/Costa_Rica', NULL, 'es',
  12.0, 3.0, NULL, NULL, 'grid_zero'
WHERE NOT EXISTS (SELECT 1 FROM monitoring.sites WHERE site_id = 'isaac-cerdas');

-- Unique clients referenced: 11

-- ============================================================
-- 4. Coordinate fill-in — run section 1-3 first, then come back and
--    replace the NULL, NULL pairs below as you look each one up.
--    Grouped by shared location so duplicates are obvious.
-- ============================================================

-- Naranjo, Alajuela
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'bryan-gutierrez';

-- Central, San José
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'fundacion-rahab';

-- Barva, Heredia
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'manuel-mayorga';

-- Santa Ana, San José (3 sites, same coordinates)
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id IN
  ('karen-montealegre', 'karen-montealegre-guarda', 'karen-montealegre-porton');

-- Corredores, Puntarenas (5 sites, same coordinates)
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id IN
  ('hugo-aguilar', 'apartamento-papas-ka', 'bernal-espinoza', 'kattia-alvarez', 'karol-alvarez-neily');

-- Belén, Heredia
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'karol-alvarez-belen';

-- Montes de Oca, San José (2 sites, same coordinates)
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id IN
  ('asoamazon', 'the-rainforest-lab');

-- San Isidro, Heredia — NOT Pérez Zeledón, double-check on the map before saving
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'hacienda-zurqui';

-- Santa Ana, San José (Roberto Villalobos — separate property from Karen Montealegre's)
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'roberto-villalobos';

-- Liberia, Guanacaste (5 sites, same coordinates)
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id IN
  ('rebeca-ruiz-casita', 'rebeca-ruiz-apartamento', 'rebeca-ruiz-casona', 'rebeca-ruiz-cabana', 'rebeca-ruiz-porton-cabana');

-- Zapote, San José
UPDATE monitoring.sites SET latitude = NULL, longitude = NULL WHERE site_id = 'isaac-cerdas';
