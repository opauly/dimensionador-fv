# Victron Monitor

Professional-grade fleet monitoring for Victron Energy systems.
Built by **Pauly y Compañía** — designed to scale across multiple client sites as a paid subscription service.

As of **2026-07-13**, this project lives inside the [Pauly&Co Solar Design Tool](../CONTEXT.md) repository and shares its Supabase project — see [Shared Supabase Project](#shared-supabase-project) below. It was previously a standalone repo (`opauly/victron-monitor`).

---

## Architecture

```
Cerbo GX (Node-RED)
    │
    ├── POST daily summary, alarms, grid events → Google Apps Script Web App
    │       └── Writes to Google Sheets (DailySummary, AlarmEvents, GridLost, ACInput)
    │           └── Generates weekly HTML-to-PDF report via Claude API
    │
    └── POST energy data, events, snapshots, logs → Supabase (PostgreSQL)
            schema: monitoring
            ├── sites              — one row per monitored installation
            ├── energy_daily       — daily accumulated energy + health metrics
            ├── daily_health       — computed health score per site per day
            ├── mppt_snapshots     — 15-min per-tracker MPPT JSONB snapshots
            ├── alarm_events       — alarm state changes
            ├── grid_events        — grid lost/restored transitions
            ├── ac_input_events    — AC input source transitions
            ├── flow_logs          — persistent Node-RED diagnostic log
            └── fleet_summary      — view joining sites + energy_daily + daily_health
```

---

## Stack

| Layer | Technology |
|---|---|
| Device | Victron Cerbo GX (Venus OS) |
| Flow engine | Node-RED |
| Inverter | Victron Quattro |
| Solar | Victron MPPT charge controllers |
| Battery | Pylontech |
| Reporting | Google Apps Script Web App |
| Database | Supabase (PostgreSQL) — shared with Pauly&Co Solar Design Tool |
| AI narrative | Anthropic Claude API |

---

## Repository Structure

```
victron-monitor/
├── node-red/
│   └── victron_monitor_v1p6.json          # Node-RED flow export (live version)
├── apps-script/
│   └── Victron_Events_App_Script_v1p6.js  # Google Apps Script web app (live version)
├── sql/
│   └── schema.sql                         # Reference copy of the monitoring schema
├── docs/
│   └── onboarding.md                      # How to onboard a new site
└── mockups/
    └── victron_weekly_report_redesign_mockup.html
```

Source of truth for the schema is [`../database/migrations/004_add_monitoring_schema.sql`](../database/migrations/004_add_monitoring_schema.sql) at the repo root — `sql/schema.sql` here is a portable reference copy, kept manually in sync.

---

## Shared Supabase Project

Victron Monitor and the Pauly&Co Solar Design Tool now run on **one Supabase project** (`https://qqorjwnlawhlmrmxxgdb.supabase.co`), split by schema:

- `public` — solar design tool (proposals, projects, equipment catalog, tariffs)
- `monitoring` — Victron fleet telemetry (this project)

This means:
- **No RLS** on `monitoring` tables — same trust model the solar tool already used (RLS off, access via schema-level `GRANT`s). See the bottom of `sql/schema.sql` for the exact grants.
- **`monitoring` must stay in Settings → API → Data API → Exposed schemas**, alongside `public`.
- **Every REST request needs a schema header** — PostgREST doesn't route by URL path. Writes (POST/PATCH) need `Content-Profile: monitoring`; reads (GET) need `Accept-Profile: monitoring`. Every write node in `node-red/victron_monitor_v1p6.json` already sets this.
- Node-RED authenticates with the shared project's `anon` key (not `service_role`) — deliberately, since the key sits in plaintext on physical field hardware and a lower-privilege key limits blast radius if it leaks.
- Onboarding a new site does **not** require a new Supabase project — insert a row into `monitoring.sites` (see [`docs/onboarding.md`](docs/onboarding.md)).

---

## Onboarding a New Site

See [`docs/onboarding.md`](docs/onboarding.md) for full steps. Summary:

1. Insert a row into `monitoring.sites` in the shared Supabase project
2. Import `node-red/victron_monitor_v1p6.json` to the site's Cerbo GX
3. Edit the `Project Config` node — update `site`, `siteId`, `appScriptUrl`, `supabaseUrl`, `supabaseAnonKey`, `batteryUsableKWh`, `pvKwp`, `utcOffsetHours`, `mpptControllers`
4. Re-select measurements on all Victron input nodes (~49 nodes — measurement selections are not preserved in JSON export)
5. Deploy — Modified Flows

---

## Key Design Principles

- **Generic by design** — editing one `Project Config` node + inserting one SQL row onboards a new site
- **No full re-imports** — changes are applied via Node-RED UI (Modified Nodes deploy) to preserve flow context and Victron input node measurement selections
- **Accumulator continuity** — `energyData` in flow context accumulates power integration all day; only resets on successful AUTO daily summary POST (`_isDailySummary=true`)
- **PV yield resilience** — MPPT `Yield Today` resets to 0 at sunset; `lastPvYield` in flow context tracks the daily peak and serves as fallback at 23:55
- **Non-destructive manual injects** — `_isManual=true` flag prevents accumulator reset during diagnostic testing
- **Persistent diagnostics** — `flow_logs` table captures every HTTP response and accumulator reset with exact timestamps

---

## Deploy Modes

| Mode | Use when | Effect on flow context |
|---|---|---|
| Modified Nodes | Editing existing function node code | Preserved ✅ |
| Modified Flows | Adding new nodes or wires | **Wiped** ⚠️ |
| Full | Full re-import | **Wiped** ⚠️ |

---

## Google Apps Script

Deploy `apps-script/Victron_Events_App_Script_v1p6.js` as a Web App:
- Execute as: **Me**
- Who has access: **Anyone**
- Always deploy via **Manage deployments → pencil icon → New version** to preserve the URL

---

## Diagnostic Queries

```sql
-- Today's flow log
SELECT ts, event, level, data
FROM monitoring.flow_logs
WHERE site_id = 'your-site-id'
  AND ts > now() - interval '24 hours'
ORDER BY ts ASC;

-- Daily summary history
SELECT date, dump_type, pv_kwh, load_kwh, battery_reached_float, pv_yield_kwh_mppt
FROM monitoring.energy_daily
WHERE site_id = 'your-site-id'
ORDER BY date DESC
LIMIT 30;

-- Recent alarms
SELECT "timestamp", alarm, severity
FROM monitoring.alarm_events
WHERE site_id = 'your-site-id'
ORDER BY "timestamp" DESC
LIMIT 50;

-- Fleet-wide summary (all sites, latest days first)
SELECT * FROM monitoring.fleet_summary LIMIT 30;
```

---

## Troubleshooting

**`HTTP 406: {"code":"PGRST106", ... "message":"Invalid schema: monitoring"}`**

One of, in order of likelihood:
1. The Node-RED flow has unsaved changes — click **Deploy** in the editor. Exporting/editing the flow JSON does not deploy it to the running Cerbo device.
2. `monitoring` isn't checked under Settings → API → Data API → Exposed schemas in the Supabase dashboard.
3. PostgREST's schema cache hasn't refreshed yet after an exposure change — run `NOTIFY pgrst, 'reload config';` in the SQL Editor, or as a last resort, Settings → General → Restart project.
4. The write node is missing the `Content-Profile: monitoring` header (or a read is missing `Accept-Profile: monitoring`).

**`HTTP 401/403` on any Supabase request**

Check the `Project Config` node's `supabaseAnonKey` matches the shared project's current anon public key (Settings → API), and that `monitoring.sites`/etc. still have the grants from the bottom of `sql/schema.sql` applied — new schemas are not auto-granted to `anon`/`authenticated` the way `public` is.
