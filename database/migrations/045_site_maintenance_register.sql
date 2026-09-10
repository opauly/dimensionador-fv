-- Migration 045: Phase 10 — Site Register & Preventive Maintenance Scheduler
--
-- monitoring.sites already carries most of what migration 011 (a smaller prep step)
-- inserted: property_id, panel_count, inverter_count, battery_count, monitoring_urls,
-- real client_id links, real geocoded latitude/longitude for all 16 current rows. This
-- migration adds the pieces migration 011 explicitly deferred to "Phase 10 proper":
-- the site_properties/site_credentials/maintenance_visits tables, and a property_id
-- column on vrm.sites — because a live check (2026-09-07) found 9 of the original 22
-- xlsx sites now live only in vrm.sites, moved there by an unrelated monitoring/vrm
-- duplicate-site consolidation that shipped after migration 011 was written. A register
-- that only reads monitoring.sites would silently miss those 9 real properties.
--
-- No FK from site_properties/site_credentials to monitoring.sites or vrm.sites — a
-- property (or its credentials) can link to a site in EITHER schema, and this schema
-- must stay dumpable into its own project the same way vrm.sites.public_client_id
-- already is a soft pointer with no FK for the identical cross-boundary reason.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + ADD COLUMN IF NOT EXISTS — safe to run twice.

-- Deliberately no client_id or location column here. Both are fully derivable from
-- whichever monitoring.sites/vrm.sites rows are linked via property_id (their own
-- client_id/public_client_id and location) — storing a copy would mean re-syncing it
-- on every site link/unlink AND on every client re-link done elsewhere (e.g.
-- pages/05_admin.py's _client_sites_linker(), which has no idea this table exists),
-- and any missed path silently goes stale. Deriving it live in
-- database/site_properties_db.py:list_properties()/get_property_bundle() instead
-- means there's nothing to keep in sync — it's correct by construction. A property
-- with no linked site yet simply has no client/location until one is linked.
CREATE TABLE IF NOT EXISTS public.site_properties (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name                        text NOT NULL,
  maintenance_interval_days   int NOT NULL DEFAULT 365,
  created_at                  timestamptz DEFAULT now()
);

-- service_role only — never GRANTed to anon, same trust boundary as public.clients.
CREATE TABLE IF NOT EXISTS public.site_credentials (
  site_id      text NOT NULL,
  schema_name  text NOT NULL CHECK (schema_name IN ('monitoring', 'vrm')),
  credentials  text,
  notes        text,
  PRIMARY KEY (site_id, schema_name)
);

CREATE TABLE IF NOT EXISTS public.maintenance_visits (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id   uuid REFERENCES public.site_properties(id) ON DELETE CASCADE,
  visit_date    date NOT NULL,
  amount_usd    numeric(10,2),
  technician    text,
  notes         text,
  created_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_maintenance_visits_property_id
  ON public.maintenance_visits(property_id);

ALTER TABLE vrm.sites ADD COLUMN IF NOT EXISTS property_id uuid;
-- monitoring.sites.property_id already exists (migration 011) — nothing to add there.

-- Mirrors monitoring.compute_daily_health()'s pattern: one function, one status,
-- consistent with calculations/maintenance.py:compute_status()'s Python equivalent
-- used by the list view (see that module's docstring for why both exist).
CREATE OR REPLACE FUNCTION public.get_property_maintenance_status(p_property_id uuid)
RETURNS TABLE (next_due_date date, status text) AS $$
DECLARE
  v_last_visit date;
  v_interval   int;
  v_fallback   date;
  v_base       date;
BEGIN
  SELECT maintenance_interval_days INTO v_interval
  FROM public.site_properties WHERE id = p_property_id;

  IF v_interval IS NULL THEN
    RETURN;
  END IF;

  SELECT MAX(mv.visit_date) INTO v_last_visit
  FROM public.maintenance_visits mv
  WHERE mv.property_id = p_property_id;

  IF v_last_visit IS NULL THEN
    -- Never visited — fall back to the earliest commissioned_at among linked sites,
    -- across both schemas, exactly like calculations/maintenance.py's Python version.
    SELECT MIN(commissioned_at) INTO v_fallback
    FROM monitoring.sites WHERE property_id = p_property_id;

    IF v_fallback IS NULL THEN
      SELECT MIN(commissioned_at) INTO v_fallback
      FROM vrm.sites WHERE property_id = p_property_id;
    END IF;
  END IF;

  v_base := COALESCE(v_last_visit, v_fallback);
  IF v_base IS NULL THEN
    RETURN;  -- no visit and no commissioned_at anywhere — nothing to compute yet
  END IF;

  next_due_date := v_base + (v_interval || ' days')::interval;
  status := CASE
    WHEN next_due_date < CURRENT_DATE THEN 'overdue'
    WHEN next_due_date < CURRENT_DATE + 30 THEN 'due_soon'
    ELSE 'up_to_date'
  END;
  RETURN NEXT;
END;
$$ LANGUAGE plpgsql STABLE;
