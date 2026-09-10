-- Migration 047: auto-create a property for every new site (Phase 10 follow-up)
--
-- Sites get inserted into monitoring.sites/vrm.sites through paths that never touch
-- this Streamlit app at all — Node-RED provisioning, the VRM Portal sync — so a "click
-- this button" step (tools/site_properties_db.py:seed_properties_from_unlinked_sites())
-- can never reliably run for every new site. A trigger is the one place this is
-- guaranteed to fire regardless of which system inserted the row.
--
-- Same safe default as the manual seed function: 1 new site = 1 new property, named
-- after the site. Merging it into an existing property (e.g. a 6th meter for an
-- existing client) still requires a human decision — that's what "Propiedades
-- existentes" in Configurar propiedades is for; this trigger only removes the "did
-- anyone remember to create a property for this" step, never the judgment call.
--
-- BEFORE INSERT, not AFTER: sets NEW.property_id directly so the row is written once,
-- correctly, rather than inserted then updated.
--
-- Idempotent to re-run: CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS before
-- each CREATE TRIGGER, since Postgres has no CREATE TRIGGER IF NOT EXISTS.

CREATE OR REPLACE FUNCTION public.auto_create_site_property()
RETURNS trigger AS $$
DECLARE
  v_property_id uuid;
BEGIN
  IF NEW.property_id IS NULL THEN
    INSERT INTO public.site_properties (name)
    VALUES (COALESCE(NEW.display_name, NEW.site_id))
    RETURNING id INTO v_property_id;
    NEW.property_id := v_property_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_auto_create_site_property ON monitoring.sites;
CREATE TRIGGER trg_auto_create_site_property
  BEFORE INSERT ON monitoring.sites
  FOR EACH ROW EXECUTE FUNCTION public.auto_create_site_property();

DROP TRIGGER IF EXISTS trg_auto_create_site_property ON vrm.sites;
CREATE TRIGGER trg_auto_create_site_property
  BEFORE INSERT ON vrm.sites
  FOR EACH ROW EXECUTE FUNCTION public.auto_create_site_property();
