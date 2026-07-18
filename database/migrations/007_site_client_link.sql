-- Migration 007: link monitoring.sites to public.clients
-- Lets the weekly Victron report be emailed to the actual customer
-- (public.clients.email) instead of the internal proyectos@paulyco.com
-- address, without exposing the client list to the anon key.

ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS client_id uuid REFERENCES public.clients(id);

-- ────────────────────────────────────────────────────────────
-- get_report_email — SECURITY DEFINER, narrow on purpose.
-- Returns only the linked client's email for one site, or NULL if
-- unlinked. Does NOT expose public.clients to anon in any other way —
-- anon has no SELECT grant on that table, only EXECUTE on this
-- function. A caller can ask "what's the email for this site_id" and
-- nothing else; they can't enumerate clients or read phone/notes.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION monitoring.get_report_email(p_site_id text)
RETURNS text
LANGUAGE sql
SECURITY DEFINER
SET search_path = monitoring, public
AS $$
  SELECT c.email
  FROM monitoring.sites s
  JOIN public.clients c ON c.id = s.client_id
  WHERE s.site_id = p_site_id;
$$;

GRANT EXECUTE ON FUNCTION monitoring.get_report_email(text) TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA monitoring GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;

-- ────────────────────────────────────────────────────────────
-- Link the existing site(s) to their client.
-- Vista Atenas LP M1/M2/M3 all belong to Lori Pickett (monitoring.sites.owner).
-- Confirm/replace this once you know the matching public.clients.id.
-- ────────────────────────────────────────────────────────────
-- Find the client id first:
--   SELECT id, name, email FROM public.clients WHERE name ILIKE '%Pickett%';
-- Then link all three sites:
--   UPDATE monitoring.sites SET client_id = '<client-uuid>'
--   WHERE site_id IN ('vista-atenas-lp-m1', 'vista-atenas-lp-m2', 'vista-atenas-lp-m3');
