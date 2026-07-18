-- Migration 009: system_type on monitoring.sites
--
-- Not every monitored site has the same architecture: hybrid (grid +
-- battery, e.g. Vista Atenas M1/M2/M3 today), off-grid (battery, no grid
-- at all), or grid-zero (grid + no battery — future, Fronius library).
-- The weekly report has grid-dependent cards (grid independence %, grid
-- quality/frequency/voltage, outages) and battery-dependent cards
-- (battery health, cycles, stress) that don't apply to every type.
--
-- Reuses the exact same vocabulary as public.proposals.system_type so
-- the whole system agrees on what these three words mean, rather than
-- inventing new terminology for the monitoring side.
--
-- Defaults to 'hybrid' (matches every current site) so existing rows
-- don't need a manual backfill.

ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS system_type text NOT NULL DEFAULT 'hybrid'
    CHECK (system_type IN ('grid_zero', 'off_grid', 'hybrid'));
