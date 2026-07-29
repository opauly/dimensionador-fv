# VRM Report SaaS — Architecture Plan

**Status:** planning doc, written before any code exists for this product.
**Goal:** take a customer's Victron VRM CSV export (later: a VRM API token),
and email them a branded results/health report — without touching Node-RED
or a Cerbo GX, and without mixing their data into Pauly & Co's own
`monitoring` schema.

This doc exists to hand context to Claude Code, which is where the actual
implementation should happen — this repo's dependency management,
`.env`/secrets, and Supabase/GCP access all belong there, not in a sandboxed
chat session.

---

## 1. What already exists (context, not to be rebuilt)

Two things in `opauly/dimensionador-fv` are directly relevant and already
work in production for Pauly & Co's own sites:

- **`reporte-solar-vrm` skill** (`vrm_parse.py`) — parses a raw VRM CSV
  export into daily energy aggregates, hourly profiles, outage events,
  alarm checks, and KPIs. Solid, tested, reusable logic — just currently
  shaped as a CLI tool with human-in-the-loop judgment calls (choosing
  `config_final_desde`, confirming `modo_operacion`, etc.).

- **`victron-monitor` subsystem** (`apps-script/`, `node-red/`, `sql/`) —
  a working fleet-monitoring pipeline: Node-RED on each Cerbo GX pushes
  daily rows into `monitoring.energy_daily` in Supabase; a Postgres
  trigger computes `daily_health`; `weeklyReport(siteId)` in Apps Script
  reads the last 7 days from Supabase, writes an AI narrative (Claude),
  builds an HTML report, converts it to PDF, and emails it.

**Key insight:** `weeklyReport(siteId)` only reads from Supabase. It has
no idea whether the data arrived via Node-RED, a CSV parser, or anything
else. The report-generation logic itself is not the bottleneck — the
ingestion path is. That's what this product actually needs to build.

**These stay untouched.** Pauly & Co's own three sites keep using
Node-RED → `monitoring` schema → Apps Script exactly as they do today.
Nothing here should require touching that pipeline, and it should not be
treated as a dependency the SaaS product relies on at runtime.

---

## 2. Isolation: separate Supabase project, not a shared schema

You floated a new JSONB table in the same project. Two separate questions
are bundled in that, worth pulling apart: **where** the new data lives,
and **how** it's shaped.

### Where: recommend a *separate Supabase project*, not a new schema in the existing one

Reasons:

- `monitoring` deliberately runs with **RLS off** — the trust model is
  "every device is mine, every key is mine." That's fine for three sites
  you installed yourself. It is the wrong trust model for hundreds of
  paying customers' data sitting in tables next to each other — you want
  proper per-tenant isolation (RLS, or at minimum strict application-layer
  scoping) from day one, and you don't want a future config mistake in
  one product to be able to touch the other's data because they share a
  project.
- Independent scaling and billing. Pauly & Co's usage pattern (three
  sites, weekly) and a SaaS product's usage pattern (hundreds of sites,
  many customers, growing) will hit different Supabase plan tiers at
  different times. Coupling them means the SaaS product's growth affects
  your own internal tooling's cost and quotas.
- If this product ever becomes its own thing — separate brand, resold,
  eventually needs its own compliance story for customers in other
  countries — starting separated avoids a painful later migration.
- The cost is one more free/low-tier Supabase project until you have
  real paying volume. Cheap insurance.

If you'd rather keep one project for now to reduce ops surface, that's
defensible too — just enforce a hard rule: a new `saas` schema, RLS
**on**, and no service-role key shared between the two schemas' code
paths. Decide this in Claude Code once you've looked at current Supabase
plan costs; either is workable, but separate project is the safer default
at "hundreds of customers worldwide" scale.

### How: typed columns, not one big JSONB blob

`monitoring.energy_daily` already made this call correctly — it's typed
columns (`pv_kwh numeric`, `min_soc numeric`, etc.), not a JSONB dump, and
JSONB is reserved for `mppt_snapshots.data` specifically because per-tracker
MPPT shape genuinely varies. That split is worth keeping:

- **Daily energy rows**: typed columns, same shape as `monitoring.energy_daily`.
  Hundreds of sites × years of daily rows is a table you'll want to
  aggregate, filter, and index by `(customer_id, site_id, date)` — JSONB
  makes every one of those queries slower and harder to write.
- **Genuinely variable data**: JSONB is the right call for things like
  per-customer branding config (logo URL, colors, contact block), or
  future per-device-model extra fields you don't want to keep migrating
  the schema for. Use it there, not as the primary storage model.

---

## 3. Schema sketch (new project, new `saas` — or default `public` — schema)

```
customers
  id, name, email, created_at, plan, branding jsonb
    (branding: logo_url, primary_color, contact_name, contact_email —
     rendered into the report template per customer)

api_keys
  id, customer_id fk, key_hash, created_at, revoked_at
    (customer_id is HOW we scope every ingestion request —
     see Section 5)

sites
  id, customer_id fk, site_id (slug, unique), display_name,
  location, country, latitude, longitude, timezone,
  pv_kwp, battery_usable_kwh, system_type, report_language,
  health_thresholds jsonb, active, created_at
    (same shape as monitoring.sites, minus anything Cerbo/Node-RED
     specific — no app_script_url, no utc_offset_hours tied to a
     device; instead a source column: 'csv_upload' | 'vrm_api')

energy_daily
  id, site_id fk, date, dump_type ('csv_upload' | 'vrm_api'),
  pv_kwh, grid_kwh, load_kwh, battery_charge_kwh, battery_discharge_kwh,
  min_soc, max_soc, avg_soc, outage_count, outage_minutes,
  min_voltage, max_voltage, min_temperature, max_temperature,
  battery_reached_float, ...
    (same columns as monitoring.energy_daily where they map cleanly;
     UNIQUE (site_id, date) so a re-upload of an overlapping CSV
     window upserts instead of duplicating)

daily_health
  (same computed-health-score trigger as monitoring — port the SQL
   function as-is, it's generic already)

reports
  id, site_id fk, period_start, period_end, generated_at,
  pdf_url, email_sent_at, status ('ok' | 'failed'), error text
    (report history — needed for support, debugging, and eventually
     billing/usage metering; monitoring has nothing like this because
     it's never needed to answer "did the client actually get their
     report" for a stranger's paid account)

ingestion_log
  id, site_id fk, source, uploaded_at, rows_written, warnings jsonb
    (equivalent of monitoring.flow_logs, but for CSV/API ingestion
     instead of Node-RED — you will want this the first time a
     customer's CSV parses "successfully" but produces a garbage report)
```

---

## 4. Ingestion pipeline

### V1 — CSV upload

```
customer uploads CSV (+ minimal site intake form: kwp, battery kWh,
DoD, modo_operacion, dates)
  → validate against expected VRM export format (reject early,
    clear error — do not silently produce a bad report)
  → run the daily-aggregation logic from vrm_parse.py's daily_table(),
    extended to also compute: per-day min/max voltage, min/max
    temperature, grid frequency/voltage min/max, battery_reached_float
    (the raw columns are already in the CSV; vrm_parse.py just doesn't
    pull them today because the existing skill's report doesn't need
    them at that granularity)
  → upsert rows into energy_daily (UNIQUE site_id+date handles re-uploads)
  → trigger report generation for that site (see Section 6)
```

### V2 — VRM API token

Same pipeline from `energy_daily` onward. Only the ingestion step changes:
customer generates a personal access token in their own VRM account
(Preferences → Integrations → Access tokens — no OAuth flow exists on
Victron's side, this is the actual mechanism), pastes it in once, and a
scheduled worker pulls `/v2/installations/{idSite}/stats` on a cadence
per active site instead of waiting for a manual upload. Store the token
encrypted at rest, scope every API call to the specific `idSite` the
customer connected (a token can see every site on that VRM account —
don't assume it's scoped to just one).

---

## 5. Auth model for ingestion

Customers never talk to Supabase directly — only your backend does,
using its own service-role-equivalent credentials. Customers authenticate
to *your* API with a per-customer API key (`api_keys` table above); your
backend resolves that key to a `customer_id`, and every query/insert is
scoped to that customer's own `site_id`s. This is the primary isolation
control — RLS in Supabase is defense-in-depth on top of it, not a
substitute for it, since your backend uses a privileged key.

---

## 6. Report generation — recommend moving off Apps Script/Gmail at this scale

The existing `weeklyReport()` logic is good and worth **porting**, not
throwing away: the AI-narrative prompt structure, the health-score
weighting, the HTML report layout are all proven. But Apps Script + Gmail
was never designed to be a multi-tenant SaaS backend, and "hundreds of
sites around the world" will run into real limits:

- Gmail/Workspace daily send quotas (order of hundreds to ~1500/day
  depending on account tier) — fine for weekly reports to 3 sites,
  not fine at real SaaS volume.
- Apps Script execution time limits (6 min per execution) and daily
  quota — a `runAllWeeklyReports()` fan-out loop that's fine for a
  handful of sites will eventually time out or throttle as the site
  count grows.
- No proper delivery observability (bounces, opens, retries) — you'll
  want that for a paid product's support workflow.
- It's not source-controlled/testable in the way the rest of this
  product should be.

**Recommendation:** port the report logic into the same backend service
that handles ingestion (Python, matching the rest of `dimensionador-fv`).
Concretely:

- `buildReportHtml()`'s HTML/CSS structure ports cleanly into a Jinja2
  template — it's already plain string-built HTML.
- `generateWeeklyNarrative()`'s Claude Sonnet call ports as-is, same
  prompt logic.
- HTML→PDF: WeasyPrint or headless-Chromium print-to-PDF, in place of
  Apps Script's built-in `getAs("application/pdf")`.
- Email: a transactional provider (Postmark/Resend/SES) instead of
  `MailApp` — proper quotas, delivery webhooks, no Workspace ceiling.
- Scheduling: a real worker/queue (Celery/RQ, or a simple cron dispatch
  job) generating reports per active site, logging into `reports` above
  instead of a single Apps Script time trigger.

This is the biggest single piece of net-new work in this plan — everything
else is closer to "adapt what exists."

---

## 7. Phased build order

1. **CSV → `energy_daily` mapper.** Pure computation, fully testable
   locally against a real exported CSV, no infra needed yet.
2. **New Supabase project + schema above.** Minimal: `customers`,
   `sites`, `api_keys`, `energy_daily`, `daily_health` (port the trigger).
3. **Ingestion endpoint** (FastAPI): upload CSV + intake form → mapper →
   upsert.
4. **Report generation service**, ported from Apps Script as described
   in Section 6 — start with just enough to prove it end-to-end for one
   pilot site (skip the 4-week trend / weather sections initially if
   that speeds up the first working version).
5. **Wire ingestion → report trigger → email**, test against one real
   pilot site/customer end to end.
6. **V2**: VRM API token ingestion, replacing manual CSV upload for
   sites that connect it; scheduled pulls.
7. **Only once real volume shows up**: `reports`/`ingestion_log` grow
   into a proper admin view, rate limiting on the ingestion API,
   per-customer usage metering for billing.

---

## 8. Open decisions to make in Claude Code

- Separate Supabase project vs. isolated schema in the existing one
  (Section 2) — recommend separate project, but check current plan
  pricing before committing.
- Backend language/framework for the new service — Python matches the
  rest of `dimensionador-fv` and lets you import `vrm_parse.py` logic
  directly; confirm that's still the preference before scaffolding.
- Transactional email provider (Postmark vs. Resend vs. SES) — pick
  based on pricing/deliverability, not covered here.
- How much of the weather/PVGIS-based solar performance ratio to keep
  in V1 vs. defer — it's a nice-to-have narrative input, not required
  for the report to be useful.
