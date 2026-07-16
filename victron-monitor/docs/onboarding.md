# Onboarding a New Site

## Prerequisites

- Victron Cerbo GX with Node-RED installed (Venus OS)
- Access to the shared Supabase project (`monitoring` schema — see [../README.md](../README.md))
- Google Apps Script Web App deployed and URL available
- Anthropic API key (for weekly report narrative generation)

---

## Step 1 — Supabase: insert the site row

Since migration 006, the site row **is** the config. Node-RED fetches most of its
settings (specs, thresholds, Apps Script URL, timezone) from here at startup — so
onboarding is primarily a database insert, not a flow edit.

```sql
INSERT INTO monitoring.sites
  (site_id, display_name, owner, location, country, latitude, longitude,
   pv_kwp, battery_usable_kwh, timezone, utc_offset_hours, commissioned_at,
   report_language, app_script_url)
VALUES (
    'your-site-id',            -- slug, no spaces, e.g. 'client-name-m1'
    'Your Site Display Name',
    'Owner Name',
    'Location',
    'CR',
    9.969576,                  -- latitude
    -84.405197,                -- longitude
    19.36,                     -- total PV kWp
    41.04,                     -- usable battery kWh
    'America/Costa_Rica',      -- IANA timezone
    -6,                        -- UTC offset hours
    '2025-10-04',              -- commissioned date
    'en',                      -- 'en' or 'es'
    'https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec'  -- this site's Apps Script web app
);
```

`health_thresholds` is not listed above — it defaults to the standard threshold set.
Only override it for a site that genuinely needs different scoring, e.g. a smaller
battery bank that naturally cycles more:

```sql
UPDATE monitoring.sites
SET health_thresholds = health_thresholds || '{"batteryCyclesHigh": 2.0}'::jsonb
WHERE site_id = 'your-site-id';
```

No new Supabase project is needed — every site lives in the same `monitoring` schema, distinguished by `site_id`.

---

## Step 2 — Node-RED: import the flow

1. Open Node-RED on the Cerbo GX (`http://<cerbo-ip>:1880`)
2. Hamburger menu → Import → paste contents of `node-red/victron_monitor_v1p7.json`
3. Deploy — **Full** (only on first import)

---

## Step 3 — Set the site identity in Project Config

Double-click the `Project Config` node. With DB-driven config (migration 006), you only
need to set the bootstrap values — everything else is fetched from `monitoring.sites`
at startup by the "Fetch Site Config" node chain:

```javascript
siteId:          "your-site-id",   // must match monitoring.sites.site_id — this is the lookup key
supabaseUrl:     "https://<shared-project-ref>.supabase.co/rest/v1",  // shared across all sites
supabaseAnonKey: env.get('SUPABASE_ANON_KEY'),                        // from Node-RED credential env var

mpptControllers: [   // hardware wiring — stays local (tied to the Victron input nodes)
    {
        instance: 0,
        name: "MPPT 450/200 #1",
        trackers: [
            { index: 0, name: "S1", active: true },
            { index: 1, name: "S2", active: true },
            { index: 2, name: "S3", active: true },
            { index: 3, name: "N/A", active: false }
        ]
    }
    // add more controllers as needed
],
```

The remaining fields (`site`, `pvKwp`, `batteryUsableKWh`, `timezone`, `utcOffsetHours`,
`reportLanguage`, `appScriptUrl`, `healthThresholds`) may still be present as a **fallback**
for resilience if Supabase is unreachable at startup, but the `monitoring.sites` row is the
source of truth and overrides them once fetched.

> **Never hardcode the anon key here** — it comes from the Node-RED Global Environment
> Variable `SUPABASE_ANON_KEY` (type `credential`) via `env.get()`. See [../README.md](../README.md).

---

## Step 4 — Re-select Victron input node measurements

⚠️ **Critical** — Victron input node measurement dropdown selections are NOT preserved in JSON exports. After import, every Victron input node shows a blank measurement and produces no data until manually configured.

There are approximately 49 Victron input nodes. For each one:
1. Double-click the node
2. Select the correct **Device** and **Measurement** from the dropdowns
3. Click Done

Refer to the node name (e.g. `SOC`, `PV Power`, `Battery Voltage`) to identify the correct measurement path.

---

## Step 5 — Deploy Modified Nodes

After editing `Project Config` and all Victron input nodes:
- Deploy → **Modified Nodes**

This preserves flow context (accumulator state) while applying all changes.

---

## Step 6 — Verify

1. Check the **Merge Site Config** node status — within ~5 seconds of deploy it should show green `Config synced: <site name>`. Yellow `Using local fallback config` means the fetch failed (check `siteId` matches a `monitoring.sites` row, and the anon key/URL).
2. Check `Energy Data` node status — should show live PV, Load, SOC values within 30 seconds
3. Run a manual inject (set `testing=true, _isManual=true`) — confirm a row appears in Google Sheets and in `monitoring.energy_daily`, and that `monitoring.daily_health` gets a matching computed row (the DB trigger populates it automatically)
3. Check `monitoring.flow_logs` — should show one `HTTP_RESPONSE` row with `isDailySummary=true, willReset=false, testing=true`
4. Wait for the 23:55 AUTO inject — confirm `willReset=true` in `flow_logs` and correct daily values in both Sheets and Supabase

If any Supabase write returns HTTP 406 `Invalid schema: monitoring`, see the troubleshooting note in [../README.md](../README.md#troubleshooting) — it's almost always a missing `Content-Profile`/`Accept-Profile: monitoring` header, or the Node-RED flow needing an explicit Deploy click.

---

## Notes

- **Never use Deploy → Full** after initial setup — always use Modified Nodes or Modified Flows to preserve flow context
- **Manual injects** (`_isManual=true`) are non-destructive — they snapshot current accumulator state without resetting it
- **`monitoring.flow_logs`** is your first diagnostic tool — query it whenever daily values look wrong
- **Every write node must send `Content-Profile: monitoring`**, and every read must send `Accept-Profile: monitoring` — this project's tables are not in the default `public` schema
- **Config is DB-driven** (migration 006) — to change a site's specs, thresholds, Apps Script URL, etc., update its `monitoring.sites` row; the flow picks it up at next startup (or next periodic fetch, if enabled). No flow redeploy needed for config changes.
- **`daily_health` is computed in Postgres** — a trigger on `energy_daily` inserts runs `monitoring.compute_daily_health()`, which reads that site's `health_thresholds`. This is separate from the Google Sheets "DailyHealth" tab that Apps Script still maintains.
