-- Migration 028: report module selection — Phase 18 Step 1 (schema only)
--
-- PLAN_PHASE18.md §1. Schema only — no vrm_api/frontend code yet (later
-- steps). Mirrors migration 026's report_schedule / default_report_schedule
-- pattern exactly: a per-site override, a per-customer default applied only
-- to new sites, NULL meaning "today's exact behavior, unchanged."
--
-- Deliberately UNLIKE migration 026's schedule columns: no
-- source='vrm_api'-only CHECK here. A CSV-uploaded site's already-ingested
-- data is just as real a basis for choosing which modules to show as a
-- live-synced site's — module selection has nothing to do with whether
-- data keeps arriving on its own, only with what's already computed for
-- the period being reported on. Only the live SCHEDULING feature needed
-- that restriction.
--
-- Nine known module ids (PLAN_PHASE18.md's Decisions section) — the CHECK
-- constraints below make any other value unrepresentable at the database
-- layer, not just rejected by the UI or the write path. KPI header / AI
-- narrative / daily bar chart are never in this list at all — they're the
-- report's fixed spine, not a selectable module.

-- ════════════════════════════════════════════════════════════════════
-- 1. vrm.sites — one new column + a CHECK on its own array contents
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.sites
  -- NULL (every site this migration touches) means "use the full default
  -- set" — every one of the 9 selectable modules renders, exactly as
  -- today. Non-NULL lists only the modules to show.
  ADD COLUMN IF NOT EXISTS report_modules text[]
    CHECK (report_modules IS NULL OR report_modules <@ ARRAY[
      'energy_mix', 'battery_health', 'grid_quality', 'events',
      'soc_chart', 'solar_performance', 'weather', 'trend', 'savings'
    ]::text[]);

COMMENT ON COLUMN vrm.sites.report_modules IS
  'PLAN_PHASE18.md §1. NULL (default — every site that existed before this migration) means every one of the 9 selectable modules renders, exactly as before this feature existed. Non-NULL lists only the modules to show. Entitlement (Growth/Fleet-installer only) is enforced by resolve_report_modules() (a later step), never by this column alone — a Starter/owner site could in principle have a non-NULL value written by a tampered request, and that function is what ignores it, not a database constraint (a CHECK cannot join against a customer''s current plan).';

-- ════════════════════════════════════════════════════════════════════
-- 2. vrm.customers — one new column, same CHECK shape
-- ════════════════════════════════════════════════════════════════════
ALTER TABLE vrm.customers
  -- Applied to a customer's NEW sites only, at creation, same rule
  -- default_report_schedule already follows (migration 026) — never
  -- retroactive to an existing site.
  ADD COLUMN IF NOT EXISTS default_report_modules text[]
    CHECK (default_report_modules IS NULL OR default_report_modules <@ ARRAY[
      'energy_mix', 'battery_health', 'grid_quality', 'events',
      'soc_chart', 'solar_performance', 'weather', 'trend', 'savings'
    ]::text[]);

COMMENT ON COLUMN vrm.customers.default_report_modules IS
  'PLAN_PHASE18.md §1. NULL by default — this migration does not change what any existing customer''s sites do. Applied by createSite() (a later step) to a NEW site only, never retroactively — the same rule default_report_schedule (migration 026) already follows.';
