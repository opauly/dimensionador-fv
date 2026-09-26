-- Migration 049: single-margin profit distribution for Cotizaciones (Phase 23)
--
-- Adds the one flag the new pricing model needs: which service_defaults rows get
-- marked up by the quote's overall margin, and which stay pass-through at cost.
-- See PLAN_PHASE23_PROFIT_DISTRIBUTION.md §1.1 for the full design.
--
-- Live schema confirmed 2026-09-26 via a read query against service_defaults (no raw-SQL
-- access available from this session — PostgREST only): system_types comes back as a Python
-- list for the one row that has it set (Permiso de Interconexión: ['grid_zero','hybrid']) and
-- None for the other four rows. This migration only ever assigns NULL to system_types (for the
-- new Estructura de montaje row), so it does not depend on knowing whether the underlying
-- column is text[] or jsonb — NULL is valid either way, and the existing "not r.get(
-- 'system_types') or ..." filter in gz_s7_costs.py/og_s7_costs.py already treats NULL as
-- "applies to every system type."

ALTER TABLE service_defaults ADD COLUMN IF NOT EXISTS markup_eligible boolean NOT NULL DEFAULT true;

-- Confirmed with Oscar: a flat government interconnection fee, bought and passed straight
-- through — never resold at a margin, unlike every other line item.
UPDATE service_defaults SET markup_eligible = false WHERE item = 'Permiso de Interconexión';

-- Confirmed with Oscar: "Diseño Eléctrico y Administración" stops being an unpriced residual
-- and gets a real, if estimated, cost so it participates in the uniform markup like every other
-- line instead of pricing out at $0. $300 is a placeholder only — Oscar, edit this number to
-- your actual estimated design/admin cost before running this migration.
UPDATE service_defaults SET unit_cost_usd = 300.00
  WHERE item = 'Diseño Eléctrico y Administración' AND unit_cost_usd = 0;

-- Confirmed with Oscar: "Estructura de montaje" today only exists as a hardcoded line inside
-- og_s7_costs.py:_seed_line_items() (Off-Grid/Hybrid only, never in this catalog). Folding it
-- in here, for ALL system types (system_types = NULL), is a deliberate scope expansion — Grid
-- Zero quotes get this line for the first time. The matching code change (deleting the old
-- hardcoded append, so Off-Grid/Hybrid quotes don't show it twice) is Phase 23 Step 2, not this
-- migration.
INSERT INTO service_defaults (item, item_en, unit_cost_usd, iva_pct, specs, specs_en, enabled,
  sort_order, system_types, markup_eligible)
VALUES ('Estructura de montaje', 'Mounting structure', 0, 0.13, 'Arreglo de módulos',
  'Module array', true, 25, NULL, true)
ON CONFLICT (item) DO NOTHING;
