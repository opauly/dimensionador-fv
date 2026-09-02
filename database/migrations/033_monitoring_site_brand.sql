-- Migration 033: monitoring.sites.brand
-- Lets the Dimensionador "Clientes" linker (pages/05_admin.py's
-- `_client_sites_linker()`) tag each site by equipment manufacturer once it
-- merges monitoring.sites alongside vrm.sites — vrm.sites needs no such
-- column since VRM Portal only exists for Victron gear, so every one of its
-- rows is "Victron Energy" by construction.
--
-- Deliberately NO column default. Every one of the 25 current
-- monitoring.sites rows genuinely is Victron/Cerbo-GX hardware (migration
-- 004's own origin: "Migrates the Victron/Node-RED fleet-monitoring
-- tables"), so backfilling them to 'Victron Energy' below is a fact about
-- today's data, not a default policy — nothing in this repo currently
-- inserts a new monitoring.sites row, but a DEFAULT would silently mislabel
-- the day something does (e.g. a future Fronius install added without the
-- inserter explicitly setting brand). Requiring every future insert to
-- state its brand keeps that mistake from being possible.

ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS brand text;

UPDATE monitoring.sites SET brand = 'Victron Energy' WHERE brand IS NULL;

ALTER TABLE monitoring.sites
  ALTER COLUMN brand SET NOT NULL;
