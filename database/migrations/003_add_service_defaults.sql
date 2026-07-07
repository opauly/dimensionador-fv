-- Migration 003: service_defaults table
-- Stores admin-managed default line items for Step 7 (costs).
-- Equipment items (panels, inverters, monitoring) are sourced from equipment tables
-- and are NOT in this table. Only services/fees go here.

CREATE TABLE IF NOT EXISTS service_defaults (
  id            uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  item          text          NOT NULL,
  item_en       text          NOT NULL DEFAULT '',
  unit_cost_usd numeric(10,2) NOT NULL DEFAULT 0,
  iva_pct       numeric(4,3)  NOT NULL DEFAULT 0,   -- 0 or 0.13
  specs         text          NOT NULL DEFAULT '',
  specs_en      text          NOT NULL DEFAULT '',
  enabled       boolean       NOT NULL DEFAULT true,
  sort_order    integer       NOT NULL DEFAULT 0
);

ALTER TABLE service_defaults ADD CONSTRAINT service_defaults_item_key UNIQUE (item);

INSERT INTO service_defaults (item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled, sort_order)
VALUES
  ('Permiso de Interconexión', 'Interconnection Permit', 1000.00, 0.000,
   'Requerido por el Reglamento de Generación Distribuida',
   'Required by the Distributed Generation Regulation', true, 10),
  ('Diseño Eléctrico y Administración', 'Electrical Design & Management', 0.00, 0.130,
   'Estudios preliminares, diseño eléctrico, inspección del sitio y gestión',
   'Preliminary studies, electrical design, site inspection and management', true, 20),
  ('Mano de obra', 'Labor', 0.00, 0.130,
   'Instalación y costos relacionados con la obra',
   'Installation and costs related to the project', true, 30),
  ('Materiales eléctricos', 'Electrical materials', 0.00, 0.130,
   'Materiales eléctricos y montaje solar',
   'Electrical materials and solar mounting', true, 40),
  ('Transporte de equipo', 'Equipment transport', 0.00, 0.130,
   'Transporte e instalación de equipo en sitio',
   'Equipment transport and on-site delivery', true, 50)
ON CONFLICT (item) DO NOTHING;
