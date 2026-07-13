-- Migration 004: monitoring schema
-- Migrates the Victron/Node-RED fleet-monitoring tables from a separate Supabase
-- project into this one, under their own schema so they stay isolated from the
-- proposal/project tables in `public`.

CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.sites (
  id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id             text        NOT NULL UNIQUE,
  display_name        text        NOT NULL,
  owner               text,
  location            text,
  country             text        DEFAULT 'CR'::text,
  latitude            numeric,
  longitude           numeric,
  pv_kwp              numeric,
  battery_usable_kwh  numeric,
  timezone            text,
  commissioned_at     date,
  active              boolean     DEFAULT true,
  created_at          timestamptz DEFAULT now(),
  report_language     text        DEFAULT 'en'::text
);

CREATE TABLE IF NOT EXISTS monitoring.energy_daily (
  id                      bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id                 text        NOT NULL,
  date                    date        NOT NULL,
  dump_type               text        NOT NULL DEFAULT 'AUTO'::text,
  pv_kwh                  numeric,
  grid_kwh                numeric,
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
  created_at              timestamptz DEFAULT now(),
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
  battery_reached_float   boolean     DEFAULT false
);

CREATE TABLE IF NOT EXISTS monitoring.daily_health (
  id                    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id               text        NOT NULL,
  date                  date        NOT NULL,
  dump_type             text        NOT NULL DEFAULT 'AUTO'::text,
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
  CONSTRAINT daily_health_site_date_type_unique UNIQUE (site_id, date, dump_type)
);

CREATE TABLE IF NOT EXISTS monitoring.ac_input_events (
  id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id             text        NOT NULL,
  event               text,
  source              text,
  previous_state      text,
  new_state           text,
  "timestamp"         timestamptz,
  duration_minutes    numeric,
  created_at          timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring.alarm_events (
  id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id       text        NOT NULL,
  alarm         text,
  severity      text,
  source        text,
  "timestamp"   timestamptz,
  created_at    timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring.grid_events (
  id                  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id             text        NOT NULL,
  event               text,
  previous_state      text,
  new_state           text,
  "timestamp"         timestamptz,
  duration_minutes    numeric,
  created_at          timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS monitoring.mppt_snapshots (
  id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id       text        NOT NULL,
  "timestamp"   timestamptz NOT NULL,
  data          jsonb       NOT NULL,
  created_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_monitoring_mppt_snapshots_site_time
  ON monitoring.mppt_snapshots USING btree (site_id, "timestamp" DESC);

CREATE TABLE IF NOT EXISTS monitoring.flow_logs (
  id          bigint      PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  site_id     text        NOT NULL,
  ts          timestamptz NOT NULL DEFAULT now(),
  event       text        NOT NULL,
  level       text        NOT NULL DEFAULT 'info'::text,
  data        jsonb
);

CREATE INDEX IF NOT EXISTS idx_monitoring_flow_logs_site_ts
  ON monitoring.flow_logs USING btree (site_id, ts DESC);

CREATE OR REPLACE VIEW monitoring.fleet_summary AS
SELECT
  s.site_id,
  s.display_name,
  s.owner,
  s.location,
  s.country,
  s.pv_kwp,
  s.battery_usable_kwh,
  ed.date,
  ed.dump_type,
  ed.pv_kwh,
  ed.grid_kwh,
  ed.load_kwh,
  ed.battery_charge_kwh,
  ed.battery_discharge_kwh,
  ed.min_soc,
  ed.max_soc,
  ed.avg_soc,
  ed.outage_count,
  ed.outage_minutes,
  ed.min_voltage,
  ed.max_voltage,
  ed.min_temperature,
  ed.max_temperature,
  ed.avg_temperature,
  ed.pv_yield_kwh_sc0,
  ed.pv_yield_kwh_sc1,
  ed.pv_yield_kwh_mppt,
  ed.battery_reached_float,
  ed.min_grid_freq,
  ed.max_grid_freq,
  ed.min_grid_v_l1,
  ed.max_grid_v_l1,
  ed.min_grid_v_l2,
  ed.max_grid_v_l2,
  ed.grid_data_available,
  round(ed.grid_kwh / NULLIF(ed.load_kwh, 0::numeric) * 100::numeric, 1) AS grid_dependency_pct,
  round(ed.battery_discharge_kwh / NULLIF(s.battery_usable_kwh, 0::numeric), 3) AS battery_cycles,
  dh.health_score,
  dh.health_status,
  dh.alarms_count,
  dh.notes
FROM monitoring.energy_daily ed
JOIN monitoring.sites s ON s.site_id = ed.site_id
LEFT JOIN monitoring.daily_health dh
  ON dh.site_id = ed.site_id AND dh.date = ed.date AND dh.dump_type = ed.dump_type
WHERE s.active = true
ORDER BY ed.date DESC, s.display_name;
