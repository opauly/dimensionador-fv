-- 070: industrial three-phase load profiles from eGauge meters, sibling of the VRM fleet tables (vrm.site_samples).
--
-- The VRM fleet is residential/commercial single-phase; industrial plants on a three-phase service need their own measured
-- load shapes (zero-export self-consumption, minimum daytime load, peak/average). These tables hold eGauge exports the same
-- way vrm.site_samples holds VRM readings, so the wizard can replay a real plant against the climate history.
--
--   vrm.egauge_sites            one row per metered plant (registry; not tied to vrm.customers / vrm.sites on purpose:
--                               these are reference plants, not monitored subscribers).
--   vrm.egauge_samples          one row per plant per 15-minute reading, whole-plant figures.
--       ts                      eGauge's own "Date & Time" converted from the plant's local time to UTC. Whether the stamp is
--                               the start or the end of the 15-minute interval is not confirmed (at most a 15 min offset).
--       usage_kw                total consumption, kW.
--       generation_kw           on-site generation, kW (0 when the plant has no solar).
--       v_l1 / v_l2 / v_l3      line-to-neutral voltage per phase, V.
--       v_l12 / v_l23 / v_l31   line-to-line voltage, V.
--   vrm.egauge_circuits_hourly  hourly mean kW of every sub-meter (boards, chambers, machines): {"Camara #3": 10.9, ...}.
--                               Kept hourly, not 15-min, to stay small; used to calibrate load factors by equipment type.
--
-- Backend-only like the rest of the vrm schema: RLS on with no policies; the service role bypasses it. Additive, idempotent.

CREATE TABLE IF NOT EXISTS vrm.egauge_sites (
    site_id     text        PRIMARY KEY CHECK (site_id ~ '^[a-z0-9][a-z0-9-]*$'),
    name        text        NOT NULL,
    company     text,
    phases      smallint    NOT NULL DEFAULT 3 CHECK (phases IN (1, 2, 3)),
    nominal_v_ll real,
    timezone    text        NOT NULL DEFAULT 'America/Costa_Rica',
    lat         numeric(6, 2),
    lon         numeric(7, 2),
    has_pv      boolean     NOT NULL DEFAULT false,
    first_ts    timestamptz,
    last_ts     timestamptz,
    notes       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS vrm.egauge_samples (
    site_id        text        NOT NULL REFERENCES vrm.egauge_sites (site_id) ON DELETE CASCADE,
    ts             timestamptz NOT NULL,
    usage_kw       real,
    generation_kw  real,
    v_l1           real,
    v_l2           real,
    v_l3           real,
    v_l12          real,
    v_l23          real,
    v_l31          real,
    PRIMARY KEY (site_id, ts)
);

CREATE TABLE IF NOT EXISTS vrm.egauge_circuits_hourly (
    site_id  text        NOT NULL REFERENCES vrm.egauge_sites (site_id) ON DELETE CASCADE,
    ts       timestamptz NOT NULL,
    kw       jsonb       NOT NULL,
    PRIMARY KEY (site_id, ts)
);

ALTER TABLE vrm.egauge_sites            ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.egauge_samples          ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.egauge_circuits_hourly  ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE  vrm.egauge_sites           IS 'Metered industrial plants (eGauge) used as three-phase load references.';
COMMENT ON TABLE  vrm.egauge_samples         IS '15-minute whole-plant eGauge readings (ts = eGauge stamp converted to UTC; interval edge unconfirmed).';
COMMENT ON TABLE  vrm.egauge_circuits_hourly IS 'Hourly mean kW per sub-meter, as a jsonb object keyed by the meter name.';
COMMENT ON COLUMN vrm.egauge_samples.generation_kw IS 'On-site generation, kW; 0 when the plant has no solar.';
