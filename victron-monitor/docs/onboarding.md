# Onboarding a New Site

## Prerequisites

- Victron Cerbo GX with Node-RED installed (Venus OS)
- Access to the shared Supabase project (`monitoring` schema — see [../README.md](../README.md))
- Google Apps Script Web App deployed and URL available
- Anthropic API key (for weekly report narrative generation)
- The shared project's Supabase REST URL (`https://<project-ref>.supabase.co/rest/v1`) and anon
  public key — both are needed twice: as Node-RED environment variables (Step 2) and as Apps
  Script Script Properties (Step 3)

> ⚠️ **Do not copy these from the repo's `.env`.** That file holds the *Streamlit app's*
> credentials, and neither of them is what a Cerbo wants:
>
> | | Repo `.env` | What Node-RED / Apps Script need |
> |---|---|---|
> | URL | `https://<ref>.supabase.co` (no suffix) | `https://<ref>.supabase.co/rest/v1` |
> | Key | `SUPABASE_SERVICE_ROLE_KEY` | the **anon / public** key |
>
> Take the anon key from the Supabase dashboard → **Project Settings → API** (newer projects
> label it `sb_publishable_…`). The service_role key bypasses RLS completely — on a customer's
> Cerbo it would hand anyone with editor access the whole database, including `public.clients`.
> The anon key is what the `monitoring` schema's grants are built around.

---

## Step 1 — Supabase: insert the site row

Since migration 006, the site row **is** the config. Node-RED fetches most of its
settings (specs, thresholds, Apps Script URL, timezone) from here at startup — so
onboarding is primarily a database insert, not a flow edit.

```sql
INSERT INTO monitoring.sites
  (site_id, display_name, owner, location, country, latitude, longitude,
   pv_kwp, battery_usable_kwh, timezone, utc_offset_hours, commissioned_at,
   report_language, app_script_url, system_type)
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
    'https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec',  -- this site's Apps Script web app
    'hybrid'                   -- 'grid_zero' | 'off_grid' | 'hybrid'
);
```

`health_thresholds` is not listed above — it defaults to the standard threshold set
(see migration 010, which recalibrated `batteryCyclesHigh`/`Mid` to 10.0/7.0 — hybrid and
off-grid systems are *designed* to cycle daily, so the old 1.5/1.0 flagged healthy systems).
Only override it for a site that genuinely needs different scoring, and only the keys that
differ — the function merges your JSON over the defaults:

```sql
UPDATE monitoring.sites
SET health_thresholds = health_thresholds || '{"socLowWarning": 25}'::jsonb
WHERE site_id = 'your-site-id';
```

### Link the site to its customer

`client_id` (migration 007) is what makes the weekly report go to the actual customer.
Leave it NULL and `monitoring.get_report_email()` returns nothing, so Apps Script silently
falls back to the internal `proyectos@paulyco.com` address:

```sql
-- Find the client first:
--   SELECT id, name, email FROM public.clients WHERE name ILIKE '%<customer>%';
UPDATE monitoring.sites SET client_id = '<client-uuid>' WHERE site_id = 'your-site-id';
```

No new Supabase project is needed — every site lives in the same `monitoring` schema, distinguished by `site_id`.

---

## Step 2 — Node-RED: set the Supabase environment variables (once per Cerbo)

**Do this before importing the flow.** Neither the REST URL nor the anon key is stored in
the flow JSON — `Project Config` reads both from Node-RED environment variables, so an
exported flow never carries a credential. Miss this and every Supabase call builds a URL
starting with `undefined/`, and `Merge Site Config` sits on yellow `Using local fallback config`.

In the Cerbo's Node-RED editor: Menu (☰) → Settings → Environment tab → **+ add**, twice:

| Name | Type | Value |
|---|---|---|
| `SUPABASE_URL` | string | `https://<project-ref>.supabase.co/rest/v1` (note the `/rest/v1` suffix) |
| `SUPABASE_ANON_KEY` | **credential** (padlock icon) | the shared project's anon public key |

`SUPABASE_ANON_KEY` must be type `credential`, not `string` — that's what keeps it out of
exports and backups. If your Node-RED predates 3.1 and has no Environment tab, set both in
`settings.js` instead (`process.env.SUPABASE_URL = '...'`).

---

## Step 3 — Apps Script: set the Script Properties

The weekly report reads `monitoring.energy_daily` / `monitoring.sites` straight from Supabase
rather than from the Sheets tabs, so the Apps Script project needs the same two values.
`getSupabaseConfig_()` throws on the first weekly run if they're missing.

Apps Script editor → **Project Settings → Script Properties → Add script property**:

| Property | Value |
|---|---|
| `SUPABASE_URL` | `https://<project-ref>.supabase.co/rest/v1` |
| `SUPABASE_ANON_KEY` | the shared project's anon public key |

One Apps Script deployment currently serves every site — if you're reusing the existing
deployment (the normal case), its properties are already set and there's nothing to do here.

---

## Step 4 — Node-RED: import the flow

1. Open Node-RED on the Cerbo GX (`http://<cerbo-ip>:1880`)
2. Hamburger menu → Import → paste contents of `node-red/victron_monitor_v1p8.json`
3. Deploy — **Full** (only on first import)

---

## Step 5 — Set the site identity in Project Config

Double-click the `Project Config` node. With DB-driven config (migration 006), you only
need to set the bootstrap values — everything else is fetched from `monitoring.sites`
at startup by the "Fetch Site Config" node chain:

```javascript
siteId:          "your-site-id",   // must match monitoring.sites.site_id — this is the lookup key
supabaseUrl:     env.get('SUPABASE_URL'),      // from the Step 2 environment variable
supabaseAnonKey: env.get('SUPABASE_ANON_KEY'), // from the Step 2 credential env var

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

> **Never hardcode the URL or the anon key here** — both come from the Node-RED Global
> Environment Variables set in Step 2, via `env.get()`.

---

## Step 6 — Re-select Victron input node measurements

⚠️ **Critical** — Victron input node measurement dropdown selections are NOT preserved in JSON exports. After import, every Victron input node shows a blank measurement and produces no data until manually configured.

There are approximately 49 Victron input nodes. For each one:
1. Double-click the node
2. Select the correct **Device** and **Measurement** from the dropdowns
3. Click Done

Refer to the node name (e.g. `Battery SOC`, `PV Power`, `Battery Voltage`) to identify the
correct measurement path. Note the naming in v1p8: the per-tracker solar-charger nodes are
`MPPT1 T0(S1) voltage` … `MPPT2 T3(N/A) yield_today` (not `SC0`/`SC1`), and `Battery SOC` is
a **victron-input-system** node, not a battery node. The full node-by-node measurement table
is in `Victron_Monitor_Deployment_Checklist.docx` §4.

---

## Step 7 — Deploy Modified Nodes

After editing `Project Config` and all Victron input nodes:
- Deploy → **Modified Nodes**

This preserves flow context (accumulator state) while applying all changes.

---

## Step 8 — Verify

1. Check the **Merge Site Config** node status — within ~5 seconds of deploy it should show green `Config synced: <site name>`. Yellow `Using local fallback config` means the fetch failed (check `siteId` matches a `monitoring.sites` row, and that Step 2's two environment variables are set).
2. Check `Energy Data` node status — should show live PV, Load, SOC values within 30 seconds
3. Run a manual inject (set `testing=true, _isManual=true`) — confirm a row appears in Google Sheets and in `monitoring.energy_daily`, and that `monitoring.daily_health` gets a matching computed row (the DB trigger populates it automatically)
4. Check `monitoring.flow_logs` — should show one `HTTP_RESPONSE` row with `isDailySummary=true, willReset=false, testing=true`
5. Wait for the 23:55 AUTO inject — confirm `willReset=true` in `flow_logs` and correct daily values in both Sheets and Supabase
6. Confirm `SELECT monitoring.get_report_email('your-site-id')` returns the customer's address — NULL means `client_id` was never linked and the weekly report will go to the internal fallback

If any Supabase write returns HTTP 406 `Invalid schema: monitoring`, see the troubleshooting note in [../README.md](../README.md#troubleshooting) — it's almost always a missing `Content-Profile`/`Accept-Profile: monitoring` header, or the Node-RED flow needing an explicit Deploy click.

---

## Notes

- **Never use Deploy → Full** after initial setup — always use Modified Nodes or Modified Flows to preserve flow context
- **Manual injects** (`_isManual=true`) are non-destructive — they snapshot current accumulator state without resetting it
- **`monitoring.flow_logs`** is your first diagnostic tool — query it whenever daily values look wrong
- **Every write node must send `Content-Profile: monitoring`**, and every read must send `Accept-Profile: monitoring` — this project's tables are not in the default `public` schema
- **Config is DB-driven** (migration 006) — to change a site's specs, thresholds, Apps Script URL, etc., update its `monitoring.sites` row; the flow picks it up at next startup (or next periodic fetch, if enabled). No flow redeploy needed for config changes.
- **`system_type` drives report content** (migration 009) — it defaults to `hybrid`, so an off-grid or grid-zero site left at the default gets grid-dependence and outage cards that don't apply to it. Set it explicitly in the Step 1 INSERT.
- **`daily_health` is computed in Postgres** — a trigger on `energy_daily` inserts runs `monitoring.compute_daily_health()`, which reads that site's `health_thresholds`. This is separate from the Google Sheets "DailyHealth" tab that Apps Script still maintains.
