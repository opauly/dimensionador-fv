-- Migration 042: vrm.get_marketing_stats()
--
-- Backs the public marketing page's animated stats banner (2026-09-04,
-- Oscar's request: "counting numbers... real sums... as counting up") —
-- sites monitored, installed kWp, and cumulative kWh tracked, platform-wide
-- (not scoped to paying subscribers specifically: as of this migration
-- there are 15 active sites, all under Pauly & Co.'s own portfolio account,
-- and zero active sites yet under the one real self-serve customer —
-- "systems monitored" is the honest claim today, not "trusted by our
-- subscribers"). See lib/server/db/marketingStats.ts for the Next.js side.
--
-- A real SQL aggregate rather than fetching every vrm.sites/energy_daily
-- row into the app to sum client-side — cheap today (15 sites, ~535
-- energy_daily rows) but energy_daily only grows, and Supabase's hosted
-- PostgREST has aggregate functions (`select=pv_kwh.sum()`) disabled on
-- this project (confirmed live: PGRST123 "Use of aggregate functions is
-- not allowed"), so a plain REST call can't do this SUM on its own — an
-- RPC function is the straightforward way to get one real SUM without
-- turning on a project-wide PostgREST setting for a single vanity banner.
--
-- Idempotent: CREATE OR REPLACE — safe to run twice.

CREATE OR REPLACE FUNCTION vrm.get_marketing_stats()
RETURNS TABLE (
  sites_monitored bigint,
  installed_kwp   numeric,
  kwh_tracked      numeric
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    (SELECT COUNT(*) FROM vrm.sites WHERE active = true) AS sites_monitored,
    (SELECT COALESCE(SUM(pv_kwp), 0) FROM vrm.sites WHERE active = true) AS installed_kwp,
    -- Lifetime total, not scoped to currently-active sites: a site that was
    -- monitored in the past (later deactivated) still contributed real
    -- tracked energy — "tracked so far" is a cumulative claim, not a
    -- snapshot of today's fleet.
    (SELECT COALESCE(SUM(pv_kwh), 0) FROM vrm.energy_daily) AS kwh_tracked;
$$;

COMMENT ON FUNCTION vrm.get_marketing_stats() IS
  'Aggregate-only (COUNT/SUM, never a per-site or per-customer row) platform totals for the public marketing page''s stats banner. Safe to call with no session — see lib/server/db/marketingStats.ts, which deliberately never imports lib/server/db/admin.ts for this reason.';

GRANT EXECUTE ON FUNCTION vrm.get_marketing_stats() TO service_role;
