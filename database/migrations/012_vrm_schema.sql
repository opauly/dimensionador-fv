-- Migration 012: `vrm` schema — CSV/API ingestion path for the weekly report
--
-- Second ingestion path for the Victron weekly monitoring report. `monitoring`
-- holds Pauly & Co's own Cerbo GX sites, written by Node-RED. This schema holds
-- external customers' sites, written by the Streamlit app from VRM CSV exports
-- (later: the VRM API). The report reader takes a schema name and otherwise
-- doesn't care which produced the rows.
--
-- Plan and verification results:
--   victron-monitor/docs/vrm-report-v1-implementation-plan.md
-- Mapper that produces these rows:
--   victron/vrm_csv.py
--
-- `monitoring` is NOT modified by this migration. The two schemas are
-- deliberately independent — Node-RED's path keeps working untouched, and its
-- rows stay usable as an oracle for validating this one.
--
-- Run once in the Supabase SQL Editor. Afterwards, add `vrm` to
-- Settings → API → Data API → Exposed schemas, or PostgREST will not route to
-- it (the same step `monitoring` needed — it does not route by URL path).

CREATE SCHEMA IF NOT EXISTS vrm;


-- ════════════════════════════════════════════════════════════════════
-- Customers
-- ════════════════════════════════════════════════════════════════════
-- Tenant root. Deliberately NOT public.clients: that table is Pauly & Co's own
-- CRM (people who bought a solar project), and an external VRM subscriber is a
-- different thing that may never appear there. An FK into `public` would also
-- make this schema unportable — the whole point of keeping it separate is that
-- it can be dumped into its own Supabase project later without untangling
-- cross-schema constraints first.
--
-- A customer maps to one VRM account. Their personal access token can read
-- EVERY installation on that account, which is why the token lives here (once)
-- rather than per site, and why every API call must still be scoped to the
-- specific idSite the customer connected.
CREATE TABLE IF NOT EXISTS vrm.customers (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  name                text        NOT NULL,
  -- Slug used to namespace site_ids so two customers can both have a site
  -- they'd naturally call "casa-principal".
  slug                text        NOT NULL UNIQUE
                                    CHECK (slug ~ '^[a-z0-9][a-z0-9-]*$'),
  contact_name        text,
  contact_email       text,
  country             text        DEFAULT 'CR'::text,

  -- ── VRM account identity, populated from the API ────────────────
  -- GET /v2/users/me returns the account; installations come from
  -- /v2/users/{idUser}/installations. Both are filled by the sync, not typed
  -- in by hand.
  vrm_user_id         text        UNIQUE,
  vrm_account_email   text,

  -- ── Token: reference, never the secret itself ───────────────────
  -- Points at a Supabase Vault secret (vault.create_secret(...) returns this
  -- id). A plaintext token column would put a credential that can read all of
  -- a customer's installations into every database dump, backup, and
  -- accidental SELECT *. Left NULL until the customer connects the API; the
  -- CSV-upload path never needs it.
  vrm_token_secret_id uuid,
  vrm_token_added_at  timestamptz,
  vrm_token_revoked_at timestamptz,

  plan                text        NOT NULL DEFAULT 'trial',
  active              boolean     NOT NULL DEFAULT true,
  -- Per-customer report branding (logo_url, primary_color, contact block).
  -- jsonb because it genuinely varies and shouldn't need a migration per field.
  branding            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  notes               text,
  created_at          timestamptz DEFAULT now()
);


-- ════════════════════════════════════════════════════════════════════
-- Sites
-- ════════════════════════════════════════════════════════════════════
-- Mirrors monitoring.sites minus the Cerbo/Node-RED-specific columns
-- (app_script_url, utc_offset_hours — there is no device to configure).
--
-- `site_id text` is kept as the key that child tables reference, matching
-- monitoring.sites exactly. That parity is deliberate: it's what lets one
-- reader query either schema. Slugs are namespaced with the customer's slug at
-- creation time, so global uniqueness costs nothing and cross-customer
-- collisions can't happen.
CREATE TABLE IF NOT EXISTS vrm.sites (
  id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id         uuid        NOT NULL REFERENCES vrm.customers(id) ON DELETE CASCADE,
  site_id             text        NOT NULL UNIQUE,
  -- VRM's own installation id — globally unique, and the authoritative key for
  -- API sync. Also recoverable from a CSV export's filename
  -- (`<idSite>_<n>_<name>_log_<from>_to_<to>.csv`), so the CSV path can fill it
  -- too and a site keeps one identity whichever way its data arrives.
  vrm_installation_id bigint      UNIQUE,
  display_name        text        NOT NULL,
  owner               text,
  location            text,
  country             text        DEFAULT 'CR'::text,
  latitude            numeric,
  longitude           numeric,
  -- IANA name (e.g. 'America/Costa_Rica'). Unlike monitoring, this is load
  -- bearing rather than cosmetic: see count_alarm_episodes() below.
  timezone            text        NOT NULL DEFAULT 'America/Costa_Rica',
  pv_kwp              numeric,
  battery_usable_kwh  numeric,
  commissioned_at     date,
  active              boolean     DEFAULT true,
  report_language     text        NOT NULL DEFAULT 'es'
                                    CHECK (report_language IN ('es', 'en')),
  system_type         text        NOT NULL DEFAULT 'hybrid'
                                    CHECK (system_type IN ('grid_zero', 'off_grid', 'hybrid')),
  -- How this site's data arrives. 'vrm_api' is not implemented yet (V2).
  source              text        NOT NULL DEFAULT 'csv_upload'
                                    CHECK (source IN ('csv_upload', 'vrm_api')),
  -- Same shape and defaults as monitoring.sites (post-migration 010:
  -- batteryCyclesHigh 10.0 / Mid 7.0, recalibrated because hybrid and
  -- off-grid systems are designed to cycle daily).
  health_thresholds   jsonb       NOT NULL DEFAULT '{
      "socLowAlarm": 20, "socLowWarning": 30, "socLowWatch": 40,
      "outageMinLong": 120, "outageMinMid": 30, "outageCountHigh": 5,
      "gridDepHigh": 50, "gridDepMid": 20,
      "batteryCyclesHigh": 10.0, "batteryCyclesMid": 7.0
  }'::jsonb,
  -- Soft pointer to public.clients for the case where a VRM customer also
  -- happens to be a Pauly & Co client. Deliberately NO foreign key: this schema
  -- must stay dumpable into its own project without a cross-schema constraint
  -- to untangle, and a dangling id here is harmless (it resolves to "no linked
  -- CRM record"), whereas an FK would be a hard dependency on `public`.
  public_client_id    uuid,
  notes               text,
  created_at          timestamptz DEFAULT now(),

  -- Redundant given site_id is globally unique, but states the tenancy rule
  -- explicitly and keeps it true if site_id is ever scoped per customer.
  CONSTRAINT vrm_sites_customer_site_unique UNIQUE (customer_id, site_id)
);

CREATE INDEX IF NOT EXISTS idx_vrm_sites_customer
  ON vrm.sites USING btree (customer_id);


-- ════════════════════════════════════════════════════════════════════
-- Daily energy
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.energy_daily (
  id                      bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id                 text        NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  date                    date        NOT NULL,
  dump_type               text        NOT NULL DEFAULT 'csv_upload',
  pv_kwh                  numeric,
  grid_kwh                numeric,      -- grid IMPORT, matching Node-RED
  load_kwh                numeric,
  battery_charge_kwh      numeric,
  battery_discharge_kwh   numeric,
  min_soc                 numeric,
  max_soc                 numeric,
  avg_soc                 numeric,
  outage_count            integer,
  outage_minutes          numeric,
  pv_kwp_snapshot         numeric,
  battery_kwh_snapshot    numeric,
  min_voltage             numeric,
  max_voltage             numeric,
  min_temperature         numeric,
  max_temperature         numeric,
  avg_temperature         numeric,
  pv_yield_kwh_mppt       numeric,
  min_grid_freq           numeric,
  max_grid_freq           numeric,
  min_grid_v_l1           numeric,
  max_grid_v_l1           numeric,
  min_grid_v_l2           numeric,
  max_grid_v_l2           numeric,
  pv_yield_kwh_sc0        numeric,
  pv_yield_kwh_sc1        numeric,
  grid_data_available     boolean     DEFAULT true,
  battery_reached_float   boolean     DEFAULT false,

  -- ── Not present in monitoring.energy_daily ──────────────────────
  -- Node-RED writes one complete day at a time; a CSV export starts and ends
  -- mid-day. Persisting coverage lets the report exclude partial days instead
  -- of quietly reporting them as low-generation days.
  hours_covered           numeric,
  complete_day            boolean     DEFAULT true,
  -- The CSV yields import and export separately; monitoring.grid_kwh only ever
  -- held import, so export gets its own column rather than changing that
  -- column's meaning between the two schemas.
  grid_export_kwh         numeric,

  created_at              timestamptz DEFAULT now(),

  -- The report groups rows by date and SUMS them, so a duplicate date would
  -- silently double-count generation. monitoring avoids this only by Node-RED
  -- writing once per day; a re-uploaded overlapping CSV window has no such
  -- guarantee, hence a hard constraint. Deliberately NOT keyed on dump_type:
  -- one date must have exactly one row no matter which source produced it, so
  -- re-ingesting a date via the API replaces the CSV row instead of adding to
  -- it.
  CONSTRAINT vrm_energy_daily_site_date_unique UNIQUE (site_id, date)
);

CREATE INDEX IF NOT EXISTS idx_vrm_energy_daily_site_date
  ON vrm.energy_daily USING btree (site_id, date DESC);


-- ════════════════════════════════════════════════════════════════════
-- Alarm events + daily health
-- ════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS vrm.alarm_events (
  id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id       text        NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  alarm         text,
  severity      text,
  source        text,
  "timestamp"   timestamptz,
  created_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vrm_alarm_events_site_ts
  ON vrm.alarm_events USING btree (site_id, "timestamp");

-- count_alarm_episodes() buckets events by LOCAL date. Written as
-- `("timestamp" AT TIME ZONE tz)::date = p_date` that is a function on the
-- column, so the index above can only narrow to site_id and Postgres then
-- filters every alarm row that site has ever recorded. At monitoring's scale
-- (3 sites, one row/day) that is invisible; at hundreds of sites with ~16
-- alarm events/day each it is not. An expression index makes the predicate
-- sargable.
--
-- The timezone must be a literal here — an index expression has to be
-- IMMUTABLE, and looking the site's tz up per row is not. America/Costa_Rica
-- covers every current site; customers elsewhere need their own partial index
-- (or the local_date column noted in the plan doc) before the same query is
-- fast for them.
CREATE INDEX IF NOT EXISTS idx_vrm_alarm_events_site_localdate
  ON vrm.alarm_events USING btree (
    site_id, (("timestamp" AT TIME ZONE 'America/Costa_Rica')::date)
  );

CREATE TABLE IF NOT EXISTS vrm.daily_health (
  id                    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id               text        NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  date                  date        NOT NULL,
  dump_type             text        NOT NULL DEFAULT 'csv_upload',
  health_score          integer,
  health_status         text,
  alarms_count          integer,
  min_soc               numeric,
  outage_count          integer,
  outage_minutes        numeric,
  grid_dependency_pct   numeric,
  battery_cycles        numeric,
  notes                 text,
  created_at            timestamptz DEFAULT now(),
  CONSTRAINT vrm_daily_health_site_date_type_unique UNIQUE (site_id, date, dump_type)
);


-- ════════════════════════════════════════════════════════════════════
-- Ingestion log
-- ════════════════════════════════════════════════════════════════════
-- monitoring has flow_logs for Node-RED; this is the equivalent for uploads.
-- Exists to answer "why did this customer's report look wrong" — the first
-- time a CSV parses successfully but produces nonsense, this is the only
-- record of what was actually ingested.
CREATE TABLE IF NOT EXISTS vrm.ingestion_log (
  id              bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id         text        NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  source          text        NOT NULL DEFAULT 'csv_upload',
  filename        text,
  installation_id text,
  period_start    timestamptz,
  period_end      timestamptz,
  sample_count    integer,
  rows_written    integer,
  alarm_events_written integer,
  warnings        jsonb,
  uploaded_at     timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vrm_ingestion_log_site_ts
  ON vrm.ingestion_log USING btree (site_id, uploaded_at DESC);


-- ════════════════════════════════════════════════════════════════════
-- Alarm episode counter
-- ════════════════════════════════════════════════════════════════════
-- Ported from monitoring.count_alarm_episodes() (migration 005) with one
-- deliberate change: the day boundary uses the SITE'S timezone rather than a
-- hardcoded 'America/Costa_Rica'. monitoring can hardcode it because all three
-- of its sites are in Costa Rica; this schema exists for external customers,
-- and bucketing a Chilean or Spanish site's alarms into Costa Rican days would
-- silently misattribute events near midnight.
--
-- Episode semantics are unchanged: one WARNING/ALARM through to its CLEARED;
-- oscillation between WARNING and ALARM counts as one episode, not many.
CREATE OR REPLACE FUNCTION vrm.count_alarm_episodes(p_site_id text, p_date date)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
  episodes integer := 0;
  in_episode boolean := false;
  v_tz text;
BEGIN
  SELECT COALESCE(timezone, 'America/Costa_Rica') INTO v_tz
  FROM vrm.sites WHERE site_id = p_site_id;
  v_tz := COALESCE(v_tz, 'America/Costa_Rica');

  FOR rec IN
    SELECT severity
    FROM vrm.alarm_events
    WHERE site_id = p_site_id
      AND ("timestamp" AT TIME ZONE v_tz)::date = p_date
    ORDER BY "timestamp" ASC
  LOOP
    IF (rec.severity = 'WARNING' OR rec.severity = 'ALARM') AND NOT in_episode THEN
      episodes := episodes + 1;
      in_episode := true;
    ELSIF rec.severity = 'CLEARED' THEN
      in_episode := false;
    END IF;
  END LOOP;

  RETURN episodes;
END;
$$;


-- ════════════════════════════════════════════════════════════════════
-- Health score
-- ════════════════════════════════════════════════════════════════════
-- Ported verbatim from monitoring.compute_daily_health() as it stands after
-- migration 010, with only the schema name and the system_type handling
-- changed. The scoring weights are NOT re-tuned here: a health score must mean
-- the same thing on both paths, or the shared report reader is reporting two
-- incomparable numbers under one label.
CREATE OR REPLACE FUNCTION vrm.compute_daily_health(
  p_site_id text,
  p_date date,
  p_dump_type text DEFAULT 'csv_upload'
)
RETURNS vrm.daily_health
LANGUAGE plpgsql
AS $$
DECLARE
  ed vrm.energy_daily%ROWTYPE;
  v_alarms_count integer;
  v_battery_capacity numeric;
  v_battery_cycles numeric;
  v_grid_dependency_pct numeric;
  v_min_soc numeric;
  v_outage_count integer;
  v_outage_minutes numeric;
  v_max_temperature numeric;
  v_min_voltage numeric;
  v_mppt_reached_float boolean;
  v_grid_data_available boolean;
  v_system_type text;
  v_has_battery boolean;
  v_has_grid boolean;
  v_score integer := 100;
  v_notes text[] := '{}';
  v_status text;
  v_result vrm.daily_health;

  v_defaults constant jsonb := '{
      "socLowAlarm": 20, "socLowWarning": 30, "socLowWatch": 40,
      "outageMinLong": 120, "outageMinMid": 30, "outageCountHigh": 5,
      "gridDepHigh": 50, "gridDepMid": 20,
      "batteryCyclesHigh": 10.0, "batteryCyclesMid": 7.0
  }'::jsonb;
  v_thr jsonb;

  t_soc_low_alarm       numeric;
  t_soc_low_warning     numeric;
  t_soc_low_watch       numeric;
  t_outage_min_long     numeric;
  t_outage_min_mid      numeric;
  t_outage_count_high   integer;
  t_grid_dep_high       numeric;
  t_grid_dep_mid        numeric;
  t_battery_cycles_high numeric;
  t_battery_cycles_mid  numeric;
BEGIN
  SELECT * INTO ed
  FROM vrm.energy_daily
  WHERE site_id = p_site_id AND date = p_date AND dump_type = p_dump_type
  ORDER BY id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  SELECT health_thresholds, system_type INTO v_thr, v_system_type
  FROM vrm.sites WHERE site_id = p_site_id;
  v_thr := v_defaults || COALESCE(v_thr, '{}'::jsonb);
  v_system_type := COALESCE(v_system_type, 'hybrid');

  -- Unlike monitoring (where this is still a TODO because every site is
  -- hybrid), system_type is applied here: external customers are far likelier
  -- to be off-grid or grid-zero, and scoring a battery-less system on battery
  -- cycling — or an off-grid one on grid dependency — is not a different
  -- number, it's a meaningless one.
  v_has_battery := v_system_type IN ('off_grid', 'hybrid');
  v_has_grid    := v_system_type IN ('grid_zero', 'hybrid');

  t_soc_low_alarm       := (v_thr->>'socLowAlarm')::numeric;
  t_soc_low_warning     := (v_thr->>'socLowWarning')::numeric;
  t_soc_low_watch       := (v_thr->>'socLowWatch')::numeric;
  t_outage_min_long     := (v_thr->>'outageMinLong')::numeric;
  t_outage_min_mid      := (v_thr->>'outageMinMid')::numeric;
  t_outage_count_high   := (v_thr->>'outageCountHigh')::integer;
  t_grid_dep_high       := (v_thr->>'gridDepHigh')::numeric;
  t_grid_dep_mid        := (v_thr->>'gridDepMid')::numeric;
  t_battery_cycles_high := (v_thr->>'batteryCyclesHigh')::numeric;
  t_battery_cycles_mid  := (v_thr->>'batteryCyclesMid')::numeric;

  v_alarms_count       := vrm.count_alarm_episodes(p_site_id, p_date);
  v_min_soc            := COALESCE(ed.min_soc, 0);
  v_outage_count       := COALESCE(ed.outage_count, 0);
  v_outage_minutes     := COALESCE(ed.outage_minutes, 0);
  v_battery_capacity   := COALESCE(NULLIF(ed.battery_kwh_snapshot, 0), 1);
  v_battery_cycles     := COALESCE(ed.battery_discharge_kwh, 0) / v_battery_capacity;
  v_grid_dependency_pct := CASE WHEN COALESCE(ed.load_kwh, 0) > 0
                             THEN (COALESCE(ed.grid_kwh, 0) / ed.load_kwh) * 100
                             ELSE 0 END;
  v_max_temperature    := NULLIF(COALESCE(ed.max_temperature, 0), 0);
  v_min_voltage        := NULLIF(COALESCE(ed.min_voltage, 0), 0);
  v_mppt_reached_float := COALESCE(ed.battery_reached_float, false);
  v_grid_data_available := COALESCE(ed.grid_data_available, true);

  IF v_alarms_count > 0 THEN
    v_score := v_score - LEAST(25, v_alarms_count * 5);
    v_notes := array_append(v_notes, v_alarms_count || ' alarm event(s)');
  END IF;

  IF v_has_battery THEN
    IF v_min_soc > 0 AND v_min_soc < t_soc_low_alarm THEN
      v_score := v_score - 25;
      v_notes := array_append(v_notes, 'Very low SOC');
    ELSIF v_min_soc < t_soc_low_warning THEN
      v_score := v_score - 15;
      v_notes := array_append(v_notes, 'Low SOC');
    ELSIF v_min_soc < t_soc_low_watch THEN
      v_score := v_score - 8;
      v_notes := array_append(v_notes, 'SOC below ' || t_soc_low_watch || '%');
    END IF;
  END IF;

  IF v_has_grid THEN
    IF v_outage_minutes > t_outage_min_long THEN
      v_score := v_score - 20;
      v_notes := array_append(v_notes, 'Long outage time');
    ELSIF v_outage_minutes > t_outage_min_mid THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'Moderate outage time');
    ELSIF v_outage_minutes > 0 THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Grid outage detected');
    END IF;

    IF v_outage_count > t_outage_count_high THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'Frequent outages');
    END IF;

    IF v_grid_dependency_pct > t_grid_dep_high THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'High grid dependency');
    ELSIF v_grid_dependency_pct > t_grid_dep_mid THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Moderate grid dependency');
    END IF;
  END IF;

  IF v_has_battery THEN
    IF v_battery_cycles > t_battery_cycles_high THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'High battery cycling');
    ELSIF v_battery_cycles > t_battery_cycles_mid THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Moderate battery cycling');
    END IF;

    IF v_max_temperature IS NOT NULL AND v_max_temperature > 45 THEN
      v_score := v_score - 15;
      v_notes := array_append(v_notes, 'High battery temperature (' || v_max_temperature || '°C)');
    ELSIF v_max_temperature IS NOT NULL AND v_max_temperature > 40 THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Elevated battery temperature (' || v_max_temperature || '°C)');
    END IF;

    IF v_min_voltage IS NOT NULL AND v_min_voltage < 46.0 THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'Low battery voltage (' || v_min_voltage || 'V)');
    END IF;

    IF v_mppt_reached_float = false THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Battery did not fully charge today');
    END IF;
  END IF;

  IF v_has_grid AND v_grid_data_available = false THEN
    v_notes := array_append(v_notes, 'No grid measurements recorded — verify AC input connections');
  END IF;

  -- Partial days under-report energy by construction; flag rather than
  -- penalise, so a truncated first/last day of an export doesn't look like a
  -- system fault.
  IF ed.complete_day = false THEN
    v_notes := array_append(v_notes,
      'Partial day (' || COALESCE(ROUND(ed.hours_covered, 1)::text, '?') || 'h of data)');
  END IF;

  v_score := GREATEST(0, LEAST(100, v_score));

  v_status := 'Excellent';
  IF v_score < 70 THEN v_status := 'Attention';
  ELSIF v_score < 80 THEN v_status := 'Watch';
  ELSIF v_score < 90 THEN v_status := 'Good';
  END IF;

  IF array_length(v_notes, 1) IS NULL THEN
    v_notes := array_append(v_notes, 'Normal operation');
  END IF;

  INSERT INTO vrm.daily_health
    (site_id, date, dump_type, health_score, health_status, alarms_count,
     min_soc, outage_count, outage_minutes, grid_dependency_pct, battery_cycles, notes)
  VALUES
    (p_site_id, p_date, p_dump_type, v_score, v_status, v_alarms_count,
     ed.min_soc, v_outage_count, v_outage_minutes,
     ROUND(v_grid_dependency_pct, 1), ROUND(v_battery_cycles, 2), array_to_string(v_notes, '; '))
  ON CONFLICT (site_id, date, dump_type) DO UPDATE SET
    health_score        = EXCLUDED.health_score,
    health_status       = EXCLUDED.health_status,
    alarms_count        = EXCLUDED.alarms_count,
    min_soc             = EXCLUDED.min_soc,
    outage_count        = EXCLUDED.outage_count,
    outage_minutes      = EXCLUDED.outage_minutes,
    grid_dependency_pct = EXCLUDED.grid_dependency_pct,
    battery_cycles      = EXCLUDED.battery_cycles,
    notes               = EXCLUDED.notes
  RETURNING * INTO v_result;

  RETURN v_result;
END;
$$;


-- ════════════════════════════════════════════════════════════════════
-- Trigger
-- ════════════════════════════════════════════════════════════════════
-- Same pattern as monitoring's energy_daily_health_trigger. Note this fires
-- per row: a bulk CSV ingest of 80 days runs it 80 times. That is intentional
-- (each day's score is independent), but it does mean alarm events must be
-- inserted BEFORE the energy_daily rows, or every score is computed against
-- zero alarms. The ingestion code is responsible for that ordering.
CREATE OR REPLACE FUNCTION vrm.trg_energy_daily_health()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  -- Skipped during bulk ingest; caller then runs vrm.recompute_health().
  IF COALESCE(current_setting('vrm.skip_health_trigger', true), 'off') = 'on' THEN
    RETURN NEW;
  END IF;
  PERFORM vrm.compute_daily_health(NEW.site_id, NEW.date, NEW.dump_type);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS vrm_energy_daily_health_trigger ON vrm.energy_daily;
CREATE TRIGGER vrm_energy_daily_health_trigger
  AFTER INSERT OR UPDATE ON vrm.energy_daily
  FOR EACH ROW
  EXECUTE FUNCTION vrm.trg_energy_daily_health();


-- ════════════════════════════════════════════════════════════════════
-- Access control
-- ════════════════════════════════════════════════════════════════════
-- Deliberately unlike `monitoring`, which runs RLS-off with a schema-wide
-- GRANT to `anon` because its writer is Node-RED on physical field hardware.
-- Nothing in this schema runs on a device: the only writer is this repo's
-- Streamlit app, holding the service_role key server-side. So `anon` and
-- `authenticated` get nothing at all, and RLS is enabled with NO permissive
-- policies — service_role bypasses RLS, everyone else is denied by default.
--
-- When customer-facing access is added (arch doc §5), the policies go here and
-- the app keeps using service_role — RLS is defence in depth behind
-- application-layer scoping, not a substitute for it.
-- Bulk ingest escape hatch: the AFTER-INSERT trigger fires per row, so an
-- 80-day CSV runs compute_daily_health() 80 times. Fine for one upload,
-- wasteful for a multi-site backfill. Set this to 'on' for the session, insert,
-- then recompute in bulk — the ingestion code owns that choice.
--   SET LOCAL vrm.skip_health_trigger = 'on';
CREATE OR REPLACE FUNCTION vrm.recompute_health(p_site_id text,
                                                p_from date DEFAULT NULL,
                                                p_to date DEFAULT NULL)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  r RECORD;
  n integer := 0;
BEGIN
  FOR r IN
    SELECT date, dump_type FROM vrm.energy_daily
    WHERE site_id = p_site_id
      AND (p_from IS NULL OR date >= p_from)
      AND (p_to   IS NULL OR date <= p_to)
    ORDER BY date
  LOOP
    PERFORM vrm.compute_daily_health(p_site_id, r.date, r.dump_type);
    n := n + 1;
  END LOOP;
  RETURN n;
END;
$$;


GRANT USAGE ON SCHEMA vrm TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA vrm TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA vrm TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA vrm TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA vrm GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA vrm GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA vrm GRANT EXECUTE ON FUNCTIONS TO service_role;

REVOKE ALL ON SCHEMA vrm FROM anon, authenticated;

ALTER TABLE vrm.customers      ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.sites          ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.energy_daily   ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.alarm_events   ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.daily_health   ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.ingestion_log  ENABLE ROW LEVEL SECURITY;
