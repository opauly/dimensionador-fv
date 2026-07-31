-- Migration 013: grid export on `vrm` sites
--
-- Some hybrid/ESS systems feed surplus back to the grid. The data path already
-- handled this: `System overview::Grid L1/L2` goes negative when exporting,
-- `victron/vrm_csv.py` splits that into `grid_export_kwh`, and migration 012
-- already created that column. What was missing is a per-site statement that
-- exporting is expected, so the report knows whether to show it.
--
-- (The energy_daily ALTER below is a no-op on a database that ran 012; it is
-- kept only so this file is self-sufficient.)
--
-- Found on a real export (VRM installation 793865, El Encino Casona):
-- 1,138 kWh exported vs 324 kWh imported over 81 days — 26,022 negative
-- samples. Not an edge case for that site; it is most of its grid interaction.
--
-- `grid_kwh` deliberately keeps meaning IMPORT ONLY, matching what Node-RED
-- writes into `monitoring.energy_daily`. Redefining it as net would silently
-- change every historical comparison and break the shared report reader, which
-- is the one thing this architecture is built to avoid.

ALTER TABLE vrm.energy_daily
  ADD COLUMN IF NOT EXISTS grid_export_kwh numeric;

-- Whether this site is expected to export. Drives whether the report shows
-- export figures at all: on a site that never exports, an always-zero row is
-- noise, and on one that does, omitting it hides a third of the story.
ALTER TABLE vrm.sites
  ADD COLUMN IF NOT EXISTS exports_to_grid boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN vrm.energy_daily.grid_kwh IS
  'Grid IMPORT only, matching monitoring.energy_daily. Export is grid_export_kwh.';
COMMENT ON COLUMN vrm.energy_daily.grid_export_kwh IS
  'Energy exported to the grid (integrated from negative grid power).';
COMMENT ON COLUMN vrm.sites.exports_to_grid IS
  'Site is expected to feed surplus back to the grid; shows export in the report.';
