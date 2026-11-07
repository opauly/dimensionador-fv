-- 056: a stored copy of every site's 15-minute VRM readings, and hourly weather by place.
--
-- Until now only the day's totals were kept (vrm.energy_daily); the 15-minute readings were fetched from Victron on
-- every page view and thrown away. The vrm-monitor API now fetches them, stores them here and reads its charts from
-- this copy (faster, survives Victron's own retention, lets any figure be recomputed later).
--
--   vrm.site_samples    one row per site per 15-minute slot.
--       ts              START of the slot, UTC.
--       pv_w            solar power, W (all solar chargers summed).
--       load_w          AC load, W (L1 + L2).
--       battery_w       battery power, W: positive = charging, negative = discharging.
--       soc_pct         battery state of charge, %.
--       grid_w          grid power, W: positive = import. A dedicated grid meter when the site has one, else the
--                       inverter's own AC-input reading (the two are not identical).
--       ac_in_v         AC input voltage, V (L1; L2 when L1 is not published).
--       inverter_state  Victron's raw state code for the slot, stored undecoded (no label is invented).
--       batt_v          battery voltage, V.
--       batt_temp_c     battery temperature, deg C.
--       generator_on    the generator ran during the slot (its run-time counter moved). NULL = no generator signal.
--       gap             Victron returned nothing for this slot: every reading is NULL. Marks a hole, not a zero.
--     Any reading a site does not publish is NULL, never a guessed value.
--
--   vrm.weather_hourly  one row per place per hour; sites at the same place (rounded to 0.01 deg, about 1 km) share rows.
--       ts              START of the hour, UTC.
--       ghi_wm2         sunlight on a horizontal surface (shortwave radiation), W/m2.
--       cloud_pct       cloud cover, %.
--       temp_c          air temperature, deg C.
--       rain_mm         precipitation in the hour, mm.
--
-- Backend-only, like the rest of the vrm schema: RLS on with no policies (default deny for the public API roles);
-- the service role used by the API bypasses it. Additive and idempotent.

CREATE TABLE IF NOT EXISTS vrm.site_samples (
    site_id         text        NOT NULL REFERENCES vrm.sites (site_id) ON DELETE CASCADE,
    ts              timestamptz NOT NULL,
    pv_w            real,
    load_w          real,
    battery_w       real,
    soc_pct         real,
    grid_w          real,
    ac_in_v         real,
    inverter_state  real,
    batt_v          real,
    batt_temp_c     real,
    generator_on    boolean,
    gap             boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (site_id, ts)
);

CREATE TABLE IF NOT EXISTS vrm.weather_hourly (
    lat        numeric(6, 2) NOT NULL,
    lon        numeric(7, 2) NOT NULL,
    ts         timestamptz   NOT NULL,
    ghi_wm2    real,
    cloud_pct  real,
    temp_c     real,
    rain_mm    real,
    PRIMARY KEY (lat, lon, ts)
);

ALTER TABLE vrm.site_samples   ENABLE ROW LEVEL SECURITY;
ALTER TABLE vrm.weather_hourly ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE  vrm.site_samples        IS '15-minute VRM readings per site (start of slot, UTC). gap = Victron returned nothing for the slot.';
COMMENT ON TABLE  vrm.weather_hourly      IS 'Hourly weather per place (lat/lon rounded to 0.01 deg), from Open-Meteo. ts = start of the hour, UTC.';
COMMENT ON COLUMN vrm.site_samples.battery_w IS 'Battery power, W. Positive = charging, negative = discharging.';
COMMENT ON COLUMN vrm.site_samples.grid_w    IS 'Grid power, W. Positive = import. Meter when present, else the inverter AC-input reading.';
COMMENT ON COLUMN vrm.site_samples.inverter_state IS 'Victron raw state code, undecoded.';
