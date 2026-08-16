# VRM CSV Report — V1 Implementation Plan

**Status:** plan, no code written yet. Companion to
[`vrm-report-saas-architecture.md`](vrm-report-saas-architecture.md) — that doc is the
long-range product architecture; this one is the concrete first build.

**Decisions locked (2026-07-28, with the user):**

| Open question (arch doc §8) | Decision |
|---|---|
| Who operates the upload | **Internal.** A new page in this Streamlit app. No customer accounts, no `api_keys`, no login, no FastAPI service. |
| Which report | **Weekly monitoring report** — the Apps Script `weeklyReport()` output, ported to Python. Not the `reporte-solar-vrm` commissioning report. |
| Where data lives | **New schema in the existing Supabase project** (`vrm`), RLS on, service-role-only. Not a separate project. |
| Delivery | **Download in the app.** No email provider in V1. |
| Port strategy | **Schema-agnostic reader** — the Python report renders from `monitoring` *or* `vrm`, aiming to eventually retire the Apps Script report path. |
| Report window | **Ingest the CSV's full range; pick a week to render.** |
| AI narrative + health score | **Both kept.** |
| `TODO(system_type)` layout gaps | **Fixed during the port.** |

**Follow-up decisions (2026-07-28, after probing the real export — see §7):**

| Question | Decision |
|---|---|
| Site identity across schemas | The M3 export is treated as **an external customer's**: its own row in `vrm.sites`, ingested into `vrm.energy_daily`. No backfill into `monitoring`, and no attempt to reconcile it with the existing `vista-atenas-lp-m3` row. This keeps the two paths genuinely independent, which is the point of the exercise — and it means the Node-RED rows stay available as an untouched oracle. |
| Headline PV figure | **`pv_kwh`** (integrated DC-coupled power). `pv_yield_kwh_mppt` is still stored, but the report leads with `pv_kwh`. |
| Upload size | **200 MB**, set explicitly in `.streamlit/config.toml` rather than left to Streamlit's implicit default. Revisit if exports outgrow it. |
| Report-port validation | No archived Apps Script PDFs available, so validation step 2 compares the Python report's **computed KPIs** against values derived from `monitoring` data directly, not against a sent PDF. Weaker, and noted as such. |
| Alarm episodes | **Build properly in the mapper** — per-day episode counts, not a period-wide set — so `compute_daily_health()` gets a real input rather than a systematically optimistic zero. |
| Module placement | **`victron/` at the repo root**, next to `calculations/` and `proposals/`, with a pointer from `victron-monitor/README.md`. |

---

## 1. What this actually is

A second ingestion path into the same report. Today:

```
Cerbo GX → Node-RED → monitoring.energy_daily → Apps Script weeklyReport() → PDF → Gmail
```

After V1:

```
Cerbo GX → Node-RED → monitoring.energy_daily ─┐
                                                ├→ Python weekly report → PDF → download
VRM CSV export → mapper → vrm.energy_daily ────┘
```

Both paths converge on an identical row shape, so the report reader takes a schema name
and otherwise doesn't care where the data came from. The Apps Script path stays live and
untouched for your own three sites until the Python report has proven itself against them.

## 2. Two things this plan deliberately does *not* rebuild

- **`vrm_parse.py`'s CSV reading.** `load_vrm_csv()` / `tidy()` / `integrate()` already
  solve the genuinely hard part — 197 columns, a 3-row header, duplicate column names
  across devices (`Voltage` appears on several), and gap-capped power→energy integration
  (`MAX_GAP_S = 300`, so a logging outage doesn't silently inflate kWh). It gets copied
  into this repo and extended, not reimplemented.
- **The health score.** `weeklyReport()` reads `daily_health` rows fetched from Supabase
  (Apps Script line 699), *not* its own `calculateHealthScore()` — that JS function is only
  used by `appendDailyHealth()` on the Node-RED write path. The score itself lives in
  Postgres (`monitoring.compute_daily_health()`, migrations 005/010) and the arch doc is
  right that it's generic. So it ports as **SQL copied into the new schema**, and the
  Python report never re-derives it. This removes ~100 lines from the port and, more
  importantly, removes a drift risk: one scoring implementation, in one language, shared
  by both paths.

## 3. Build order

### Step 1 — CSV → daily rows mapper (pure computation, no infra)

New module `victron/csv_mapper.py` (or `calculations/vrm_csv.py` — see §6 on placement).

- Vendor `vrm_parse.py`'s `SIGNALS`, `load_vrm_csv()`, `pick()`, `tidy()`, `integrate()`,
  `find_outages()`, `merge_events()`, `check_alarms()` into this repo.
- Add a `to_energy_daily_rows(df) -> list[dict]` that emits **`energy_daily`'s column
  names**, not `daily_table()`'s Spanish ones. `daily_table()` currently produces
  `pv_kwh` / `consumo_kwh` / `red_importada_kwh` / `red_exportada_kwh` / `bat_carga_kwh` /
  `bat_descarga_kwh` / `soc_min_pct` / `soc_max_pct` — a rename plus these genuinely
  missing fields, all of which are present in the raw CSV and simply never aggregated
  per-day today:
  `avg_soc`, `min_voltage`, `max_voltage`, `min_temperature`, `max_temperature`,
  `avg_temperature`, `min_grid_freq`, `max_grid_freq`, `min_grid_v_l1`, `max_grid_v_l1`,
  `min_grid_v_l2`, `max_grid_v_l2`, `battery_reached_float`, `grid_data_available`,
  `pv_yield_kwh_mppt`.
- `outage_count` / `outage_minutes` come from bucketing `merge_events(find_outages(...))`
  by date — the parser produces events, `energy_daily` wants per-day totals.
- Validation gate: reject a file that isn't a VRM export (header shape, required signals
  present) with a clear message, **before** any rows are written. The arch doc's "do not
  silently produce a bad report" rule.
- Fully testable offline against a real CSV. **This step needs no Supabase and no UI —
  build and verify it first.**

**The mapping rules are no longer open** — they were resolved empirically against a real
export and the Node-RED flow (see §7). Implement exactly these:

| `energy_daily` field | Rule (matches Node-RED) |
|---|---|
| `grid_kwh` | Grid **import** only (`grid_w.clip(lower=0)` integrated). Export is *not* what this column holds. |
| `outage_count` / `outage_minutes` | Transitions of `System overview::Grid alarm`. **Not** `find_outages()` — see §7.3. |
| `grid_data_available` | `max_grid_v_l1 > 0` for the day. Means "grid was physically present", not "grid was used". |
| `battery_reached_float` | Solar Charger `Charge state == 'Float'` **OR** `max_soc >= 100`. The SOC clause dominates in practice. |
| `pv_yield_kwh_sc0` / `sc1` | Per-solar-charger `Yield today`, indexed **by column occurrence** — see §7.4. |
| `pv_yield_kwh_mppt` | `sc0 + sc1`. |
| `min_grid_freq` / `min_grid_v_l1` / `min_grid_v_l2` | Day min **excluding zeros** — see §7.5. |
| `min/max_voltage` | `Battery Monitor::Voltage`. |
| `min/max/avg_temperature` | `Battery Monitor::Battery temperature`. |

### Step 2 — Migration `012_vrm_schema.sql`

New `vrm` schema in the existing project, mirroring `monitoring`'s table shapes:

- `vrm.sites` — `monitoring.sites`'s columns minus the Cerbo/Node-RED-specific ones
  (`app_script_url`, `utc_offset_hours`), plus `source text CHECK (source IN
  ('csv_upload','vrm_api'))` and a `client_id` link, same as migration 007 did.
- `vrm.energy_daily` — same columns as `monitoring.energy_daily`, plus
  `UNIQUE (site_id, date)` so re-uploading an overlapping CSV window **upserts instead of
  duplicating**. (`monitoring.energy_daily` has no such constraint — it relies on Node-RED
  writing once per day. The CSV path can't assume that.)
- `vrm.daily_health` + `vrm.compute_daily_health()` + trigger — copied verbatim from
  migrations 005/010 with the schema name swapped.
- `vrm.ingestion_log` — `id, site_id, filename, uploaded_at, date_range, rows_written,
  warnings jsonb`. Cheap now, and it is the only thing that will answer "why did this
  customer's report look wrong" later.
- **RLS on** from the start (arch doc §2's hard rule), all access via `service_role` from
  the Streamlit app. Unlike `monitoring`, no anon key ever touches this schema — nothing
  here runs on field hardware.
- `vrm` must be added to Settings → API → Data API → **Exposed schemas**, and reads need
  `.schema('vrm')` on the client (confirmed working with the installed `supabase-py`
  2.31.0 — same pattern `database/monitoring_sites_db.py` already uses).

**Known gap to decide, not paper over:** `compute_daily_health()` calls
`count_alarm_episodes()`, which reads `alarm_events` — a table Node-RED populates and the
CSV path has no equivalent for. `vrm_parse.py`'s `check_alarms()` returns a set of
distinct values with no per-day episode count. Either extend the mapper to emit per-day
alarm episodes (the timestamped columns are in the CSV; it's real work but not hard), or
accept `alarm_episodes = 0` for CSV sites — in which case the health score is
systematically optimistic for those sites and the report must not claim "no alarms".
Recommend doing it properly in the mapper; flagging it here so it isn't discovered later.

### Step 3 — Schema-agnostic data layer

New `database/vrm_report_db.py`, the Python equivalent of Apps Script's
`fetchSiteRow_` / `fetchEnergyDailyRows_` / `fetchDailyHealthRows_` /
`fetchLongestOutageMinutes_` — each taking a `schema` argument (`"monitoring"` or
`"vrm"`), each filtering `dump_type = 'AUTO'` server-side (the exact filter whose absence
caused the inflated-totals bug in the Sheets version).

This is the whole "aim to replace Apps Script" bet: one reader, two sources.

### Step 4 — Report generation

New `victron/weekly_report.py` + `victron/templates/weekly_report_{es,en}.html`.

- **Aggregation** (`weeklyReport()` lines ~684–1006, ~320 lines): group by date,
  week-over-week deltas against the prior 7 days, the 4-week solar trend, min/max/avg
  rollups, grid-independence and battery-cycle math. Straight port; the trickiest part is
  that it currently re-queries Supabase five times (once per week bucket) — in Python,
  fetch the full 5-week range once and slice locally.
- **Weather** (line ~849): Open-Meteo archive API for sunshine hours / rain / cloud cover,
  feeding `solarPerformancePct`. This repo already calls Open-Meteo in
  `calculations/load_profile_off_grid.py` — reuse that client rather than writing a
  second one.
- **Narrative** (`generateWeeklyNarrative()`, ~80 lines): the prompt ports verbatim. Swap
  `UrlFetchApp` for the `anthropic` SDK already in `requirements.txt`, and keep the
  existing fail-soft behavior (a missing key or API error returns a placeholder string,
  never blocks the report).
- **Layout** (`buildReportHtml()`, ~520 lines of hand-assembled SVG with hardcoded pixel
  column math) → Jinja2 + CSS, rendered by WeasyPrint. This repo has four production PDF
  templates already (`proposals/templates/*.html`) and the brand CSS to match. This is the
  single largest piece of work in the plan.
- **`system_type` conditionals, fixed here** (the three `TODO(system_type)` sites at Apps
  Script lines 1148, 1250, 1259): a `grid_zero` site has no battery, so the Battery Health
  block and the donut's battery segment are meaningless; an `off_grid` site has no grid, so
  the Grid Independence KPI and Grid block are. In the SVG these were deferred because
  hiding a card meant recomputing a fixed 4-column row's widths by hand. In CSS grid /
  flexbox, omitting a card *is* the reflow — which is exactly why this is the cheapest
  moment to fix it, and why it matters more here than for your own sites (all currently
  `hybrid`): CSV customers are far likelier to be off-grid or grid-zero.
- `buildEmailHtml()` (~110 lines) is **not** ported in V1 — no email delivery.

### Step 5 — Streamlit page `pages/06_reportes_vrm.py`

- **Sites tab**: list/create `vrm.sites` rows. The intake form must capture what the CSV
  cannot tell us and what the report needs: `pv_kwp`, `battery_usable_kwh`, `system_type`,
  `report_language`, `timezone`, lat/lon (reuse `calculations/pvgis.py:geocode_cr()`),
  `health_thresholds`, and an optional `client_id`.
- **Upload tab**: pick a site → upload CSV → parse → **preview the parsed daily table and
  any warnings before writing anything** → confirm → upsert into `vrm.energy_daily` + write
  an `ingestion_log` row.
- **Report tab**: pick a site, pick a source schema (`vrm` / `monitoring` — the latter is
  how the Python report gets validated against your own live sites), pick the week-ending
  date from the dates actually present, generate, preview, download. Same
  generate-and-download pattern as the proposal PDFs.
- Note for the intake form: `vrm_parse.py`'s two human-in-the-loop judgment calls —
  `config_final_desde` (where commissioning tinkering ends) and `modo_operacion`
  (`respaldo` vs `autoconsumo`) — matter for the commissioning report but **not** for the
  weekly report, which has no equivalent concept. Don't carry them into V1's form; they
  come back if the commissioning report is built later.

## 4. Validation

The port has an unusually good test oracle available — use it.

1. **Mapper**: run against a real VRM CSV from a site that *also* has Node-RED data in
   `monitoring.energy_daily` for the same dates. Compare row by row. This is the only way
   to prove the CSV path produces the same numbers as the Cerbo path, and it will catch
   the §3 mapping questions empirically instead of by inspection.
2. **Report port**: render the Python report from `schema="monitoring"` for one of your
   three live sites for a week Apps Script already reported on, and diff the KPI values
   against the archived PDF. Every number must match. Layout will differ (Jinja2 vs. SVG)
   and that's expected — the numbers are the contract.
3. **`system_type`**: render the same site's data three times as `hybrid` / `off_grid` /
   `grid_zero` and confirm each layout is complete and gap-free, not just missing cards.
4. **Re-upload idempotency**: upload an overlapping CSV window twice; confirm
   `UNIQUE (site_id, date)` upserts and row count doesn't grow.
5. **Degradation**: a CSV covering only 8 days should still render — week-over-week and the
   4-week trend go blank or partial, and must not crash or silently show zeros as if they
   were measurements.

## 5. Explicitly out of scope for V1

Customer accounts, `api_keys`, RLS policies beyond "service_role only", the VRM API token
path (arch doc §4 V2), email delivery, scheduled/automated report runs, the `reports`
history table, rate limiting, usage metering, and a separate Supabase project. Every one of
these is in the arch doc and none of them is needed to produce the first correct report.

## 7. Findings from the real export (2026-07-28)

Probed against
`844478_0_VistaAtenasLPM32FloorPool_log_20260510-0000_to_20260728-1538.csv` —
`vista-atenas-lp-m3`, 139 MB, 122,841 rows, 264 columns, 2026-05-10 → 07-28 (80 days),
60 s sampling, only 2 gaps > 300 s, 79 of 80 complete days. Parses in **5.7 s**.
Devices present: `Gateway`, `VE.Bus System`, `Solar Charger`, `Battery Monitor`,
`System overview`. Missing signals vs. `vrm_parse.SIGNALS`: `load_l3_w`, `grid_l3_w`
(expected — split-phase 120/240 V, two phases), and `pv_v` (the column is
`PV Voltage on tracker N`, not `PV voltage` — remap).

### 7.1 The core feasibility question is answered: the numbers agree

Node-RED has 22 rows for this site (2026-07-06 → 07-27), overlapping the CSV. Excluding
07-06 (Node-RED's partial first day), across **21 full days**:

| Metric | mean abs Δ | max abs Δ | mean % err |
|---|---|---|---|
| `pv_kwh` | 0.487 kWh | 1.13 | 0.88% |
| `load_kwh` | 0.453 kWh | 1.06 | 1.00% |
| `battery_charge_kwh` | 0.166 kWh | 0.50 | 0.81% |
| `battery_discharge_kwh` | 0.193 kWh | 0.59 | 1.03% |
| `grid_kwh` (import) | **0.009 kWh** | 0.13 | 0.96% |
| `min_soc` | 0.048 pp | 1.0 | 0.07% |
| `max_soc` | 0.000 | 0.00 | 0.00% |

Two independent measurement paths — a Cerbo polling live D-Bus vs. an offline integration
of VRM's logged 60 s samples — landing within ~1% is the strongest available evidence that
the CSV path can feed the same report. The residual ~1% is expected: different sampling
instants, and `integrate()`'s `MAX_GAP_S` treatment of gaps.

`grid_kwh` matching to 0.009 kWh settles it as **import**, not net.

### 7.2 The site is genuinely `hybrid` — don't reclassify it

At first look this site reads as off-grid: `AC-Input = Inverting` for 117,040 of 122,841
samples (95%), `Active input = Disconnected` for 117,002, and grid power flows on only
3 of 22 days. But grid **voltage** is present on all 22 days (`max_grid_v_l1` ≈ 125 V), so
the grid is physically connected throughout. "Inverting" is normal ESS self-consumption —
the inverter supplying loads from PV/battery while the grid sits connected and unused. The
`system_type = 'hybrid'` row is correct.

### 7.3 `find_outages()` must not be used for `outage_count` / `outage_minutes`

`vrm_parse.find_outages()` flags `ac_input == Inverting OR active_input == Disconnected`
as an island event. At this site that is 95% of the period: **49 events, 111,258 minutes**,
the first one 4.3 days long. Node-RED reports **0 outages** over the same window. The
parser's definition is right for the commissioning report's "did the system ride through"
narrative and completely wrong as a grid-outage KPI.

Node-RED's actual definition (flow node `Grid Lost`) is transitions of the **`Grid alarm`**
D-Bus value: outage starts on `0 → ≥1`, ends on `≥1 → 0`, duration in minutes. That column
is in the CSV as `System overview::Grid alarm`, **encoded as text** (`Grid ok` / `Grid lost`)
rather than the numeric 0/1/2 Node-RED sees — a `pd.to_numeric()` on it silently yields an
empty series, which is an easy way to "reproduce" zero outages vacuously. Map the strings.

Applying the correct rule to the CSV: **exactly one real outage in 80 days — 2026-07-04
12:51 → 17:17, 266.3 minutes.** It falls two days *before* Node-RED's history begins, so
Node-RED reporting 0 for 07-07…07-27 is correct and the two agree. It also demonstrates the
CSV path's real value: it recovers a genuine 4.4-hour outage the Cerbo pipeline never saw.

### 7.4 Two solar chargers — `pick()` silently returns only the first

48 `Solar Charger::` column names are duplicated (two chargers on this site).
`vrm_parse.pick()` does `col.iloc[:, 0]` on a duplicate, so every per-charger signal
silently uses charger #1 alone. `pv_w` is unaffected (it comes from the
`System overview::PV - DC-coupled` aggregate), but `yield_today_kwh` / `user_yield_kwh`
undercount by roughly half. `energy_daily.pv_yield_kwh_sc0` / `sc1` exist precisely because
there are two. The mapper must select by occurrence index, not by name.

### 7.5 Grid voltage/frequency read 0 when disconnected

`Input voltage phase 1` and `Input frequency 1` report `0.00` on 2,795 samples (grid
absent), so a naive day-min gives `min_grid_v_l1 = 0`. Excluding zeros gives 99.2 V /
57.13 Hz, consistent with Node-RED's observed 100.1–112.4 V range. Exclude zeros.

### 7.6 Open items this probe did *not* close

- **Alarm episodes.** `check_alarms()` finds real ones over the period (Overload L1/L2,
  Low battery, High DC ripple, High discharge current) but returns a set of distinct values
  with no per-day count. `compute_daily_health()` needs per-day episodes. Still to build.
- **`pv_kwh` vs `pv_yield_kwh_mppt` disagree** and both are stored: 62.12 vs 64.19 on
  07-26. One is integrated DC-coupled power, the other the chargers' own counters. Which
  one headlines the report needs deciding.
- **File size.** 139 MB for 80 days. Streamlit's default `maxUploadSize` is 200 MB, so a
  ~6-month export will not upload without raising it in `.streamlit/config.toml`.
- **Battery temperature floor of 3 °C** over the period, at a site in Atenas. Probably a
  sensor dropout rather than a real reading; worth a sanity filter, and worth knowing
  before it lands in a customer-facing "min temperature" cell.

## 8. Step 1 built and verified (2026-07-28)

`victron/vrm_csv.py` implements the mapper. Parses the 139 MB / 122,841-row
reference export in **6.0 s**, emitting 80 daily rows (79 complete), 1,258 alarm
events, and 1 outage.

**Verified against Node-RED's own rows for the same site and dates** — 21 full
overlapping days, comparing `to_energy_daily_rows()` output field by field
against `monitoring.energy_daily`:

| Field | mean abs Δ | mean % err | | Field | mean abs Δ | mean % err |
|---|---|---|---|---|---|---|
| `pv_kwh` | 0.487 kWh | 0.88% | | `min_voltage` | 0.008 V | 0.02% |
| `load_kwh` | 0.453 kWh | 1.00% | | `max_voltage` | 0.007 V | 0.01% |
| `grid_kwh` | 0.009 kWh | 0.96% | | `min/max_temperature` | 0.25 °C | 1.09% |
| `battery_charge_kwh` | 0.166 kWh | 0.81% | | `min/max_grid_freq` | 0.053 Hz | 0.09% |
| `battery_discharge_kwh` | 0.193 kWh | 1.03% | | `min/max_grid_v_l1` | ~1.2 V | ~1.0% |
| `min_soc` | 0.048 pp | 0.07% | | `pv_yield_kwh_sc0` | **0.000** | **0.00%** |
| `max_soc` | **0.000** | **0.00%** | | `pv_yield_kwh_mppt` | 0.245 kWh | 0.39% |
| `avg_soc` | 0.314 pp | 0.45% | | `outage_count` / `_minutes` | **0.000** | exact |

`battery_reached_float` and `grid_data_available` agree on **21/21 days**.

`pv_yield_kwh_sc0` matching to 0.000 across every day is the specific
confirmation that per-charger column indexing (§7.4) is right — that field is
exactly what the naive name-based lookup gets wrong.

Grid voltage extremes differ by ~1% because Node-RED sees every D-Bus change
while VRM logs at 60 s, so each catches transients the other misses. Not
reconcilable, and not worth trying to.

### Alarm episodes

Emitting `alarm_events`-shaped rows and letting the ported
`count_alarm_episodes()` SQL count them keeps one definition of "episode"
across both paths. Scoring the CSV events with that algorithm and comparing
against `monitoring.daily_health.alarms_count`:

- **Exact match on 12 of the 14 days where Node-RED has alarm data**
  (2026-07-13 → 07-27); the other two differ by exactly 1 (9 vs 10, 36 vs 35),
  consistent with 60 s logging merging or missing a sub-minute flicker.
- The 07-06 → 07-12 rows where Node-RED reports 0 and the CSV finds 1–11 are
  **not disagreement**: `monitoring.alarm_events` begins at
  `2026-07-13T14:09:52` for the entire fleet, so Node-RED has no alarm history
  before then. Another case of the CSV path recovering history the Cerbo
  pipeline never captured.

**Deliberate scope limit:** `ALARM_CATEGORIES` mirrors Node-RED's taxonomy
exactly — `low_battery` and `overload`, WARNING/CLEARED only. The CSV exposes
ten further alarm columns (DC ripple, temperature, the Battery Monitor set) and
the reference export has real activity on four of them. Scoring those would make
a CSV-ingested site score systematically worse than an identically behaving
Cerbo site, since `count_alarm_episodes()` runs one shared in-episode flag over
every event row for the day. They are surfaced via `unscored_alarm_summary()`
into the ingestion warnings instead of being silently dropped. Widening this is
a cross-path decision: Node-RED has to start emitting the same categories, or
health scores stop meaning the same thing between the two paths.

## 9. Step 2 written, awaiting apply (2026-07-28)

`database/migrations/012_vrm_schema.sql` + `tools/run_migration_012.py`.
**Not applied** — schema changes to the live project are run by hand in the
Supabase SQL Editor.

Three places the port deviates from `monitoring`, each deliberate:

1. **`count_alarm_episodes()` uses the site's timezone**, not a hardcoded
   `America/Costa_Rica`. `monitoring` can hardcode it because all three of its
   sites are in Costa Rica. This schema exists for external customers, and
   bucketing a foreign site's alarms into Costa Rican days misattributes every
   event near midnight.
2. **`system_type` is applied, not deferred.** `monitoring` still carries the
   `TODO(system_type)` because every site there is `hybrid` and there was
   nothing to verify a change against. Here, battery scoring (SOC, cycling,
   temperature, voltage, float) is skipped for `grid_zero`, and grid scoring
   (outages, dependency) for `off_grid`. Scoring a battery-less system on
   battery cycling isn't a wrong number, it's a meaningless one.
3. **RLS enabled with no permissive policies, and no `anon` grant at all.**
   `monitoring` runs RLS-off with a schema-wide `anon` grant because its writer
   is Node-RED on physical field hardware. Nothing here runs on a device — the
   only writer is this app holding `service_role` server-side, and
   `service_role` bypasses RLS.

Scoring weights are **not** re-tuned. A health score has to mean the same thing
on both paths or the shared reader reports two incomparable numbers under one
label.

### Revised before applying, after a multi-tenancy review

The first draft had `vrm.sites.client_id` FK into `public.clients`. That
contradicted the isolation goal outright — it made the schema unportable to its
own Supabase project, and modelled external VRM subscribers as Pauly & Co CRM
records, which they are not. Replaced with:

- **`vrm.customers`** as the tenant root, populated from the VRM API itself
  (`/v2/users/me`, `/v2/users/{idUser}/installations`) rather than typed in.
  Carries `slug` (namespaces site_ids so two customers can both have a
  "casa-principal"), `vrm_user_id`, branding, plan, active.
- **`vrm.sites.customer_id`** NOT NULL → `vrm.customers`, plus
  `vrm_installation_id` (VRM's own globally-unique idSite — also recoverable
  from a CSV filename, so a site keeps one identity whichever path feeds it).
- **`public_client_id uuid` with no FK** — soft pointer for the case where a
  VRM customer *is* also a Pauly & Co client. A dangling id resolves to "no
  linked CRM record"; an FK would be a hard dependency on `public`.

The schema now contains **zero references to `public`** outside comments.

**Token storage:** `vrm_token_secret_id uuid` points at a Supabase Vault
secret, deliberately *not* a plaintext token column. A VRM personal access
token can read every installation on that account, and a plaintext column puts
it in every dump, backup, and accidental `SELECT *`. NULL until a customer
connects the API; the CSV path never needs it.

### Two scale defects fixed pre-emptively

Both inherited from `monitoring`, where they are invisible at 3 sites × 1
row/day and would not be at hundreds:

- `count_alarm_episodes()` filters on `("timestamp" AT TIME ZONE tz)::date`, a
  function on the column, so the plain index only narrows to `site_id` and
  Postgres filters every alarm row that site ever recorded. Added an expression
  index. Its timezone must be a literal (index expressions must be IMMUTABLE),
  so it covers Costa Rica; customers elsewhere need their own partial index or
  a stored `local_date` column.
- The health trigger fires per row — an 80-day CSV runs it 80 times. Added
  `SET LOCAL vrm.skip_health_trigger = 'on'` plus `vrm.recompute_health(site,
  from, to)` so a bulk ingest can insert first and score once.

Two constraints worth knowing before ingestion code is written:

- `UNIQUE (site_id, date)` — deliberately not keyed on `dump_type`. The report
  groups by date and *sums*, so a duplicate date silently double-counts
  generation. `monitoring` avoids this only because Node-RED writes once a day.
- The health trigger fires **per row**, so **alarm events must be inserted
  before the `energy_daily` rows**, or every score is computed against zero
  alarms. The ingestion code owns that ordering.

## 10. Steps 2–3 applied and verified end to end (2026-07-28)

Migration 012 applied; `vrm` added to Exposed schemas. All six tables reachable,
both functions callable.

Built:
- `database/vrm_report_db.py` — the schema-agnostic reader. Ports Apps Script's
  four fetch functions, plus `fetch_report_window()` which pulls the whole
  5-week span in **one** query and slices locally (the original re-queries
  Supabase seven times per report).
- `victron/ingest.py` — the write path. Customer → site → alarm events →
  daily rows → ingestion log.

The reference export was ingested as an external customer
(`Vista Atenas` / `vista-atenas-2-floor-pool`, VRM installation 844478):
**80 daily rows + 1,258 alarm events in 9.8 s.**

### The result that matters

The same reader, pointed at each schema, for the same physical site and week
(2026-07-21 → 07-27):

| | days | PV kWh | load kWh | grid kWh | independence | avg health |
|---|---|---|---|---|---|---|
| `vrm` (CSV) | 7 | 432.9 | 376.7 | 14.1 | 96.2% | 80.7 |
| `monitoring` (Node-RED) | 7 | 435.4 | 379.0 | 14.2 | 96.3% | 81.4 |

Energy agrees to **0.6%**, grid independence to **0.1 pp**. Per-day health
scores are **identical on 6 of 7 days**.

The single difference (07-21: 75 vs 80) is not a scoring bug — it's the alarm
count, 6 vs 4. The penalty is `LEAST(25, alarms × 5)`, so 4 alarms costs 20 and
6 costs the capped 25. Per-day alarm counts differ by ±3 throughout
(6/4, 7/10, 12/9, 17/19, 36/35) for the reason established in §8: VRM logs at
60 s while Node-RED sees every D-Bus transition, so each catches flickers the
other misses. Worth knowing that on days near the cap boundary this turns a
small counting difference into a 5-point score difference.

This validates the whole architecture: one reader, one set of KPI definitions,
one health function, two completely independent ingestion paths producing
matching numbers.

### Two gaps this surfaced

- **`get_longest_outage_minutes()` is approximate for `vrm`.** `monitoring` has
  `grid_events` with per-outage durations; the CSV mapper resolves outages into
  per-day aggregates and doesn't persist individual events. For `vrm` the
  function returns the largest single *day's* total — an upper bound, exact
  whenever a day had at most one outage. If the report leans on this figure,
  `vrm` needs a `grid_events` table and the mapper needs to write the events it
  already computes.
- **`week_bounds()` fixes an off-by-one in the original.** Apps Script uses
  `start = today - 7` with both bounds inclusive — an 8-day "week" that
  double-counts the boundary day between consecutive reports. This port uses a
  true 7 days, so its totals will not match an archived Apps Script PDF exactly.
  The difference is the fix, not a regression.

## 11. Step 4 built and calibrated against the reference PDF (2026-07-28)

English only for now, per decision. Files:

- `victron/report_i18n.py` — TRANSLATIONS port (EN complete, ES carried over).
- `victron/report_svg.py` — the SVG blocks from `buildReportHtml()`, coordinate
  for coordinate. Kept in Python rather than Jinja2 because these are computed
  geometry (wrapping, stacked-height measurement, dash-array arithmetic).
- `victron/templates/weekly_report.html` — the HTML/CSS shell.
- `victron/weekly_report.py` — the `weeklyReport()` computation, Open-Meteo
  weather, the Claude narrative, and WeasyPrint rendering.

### Numbers: 19/19 exact against the reference PDF

Rendering `vista-atenas-lp-m3` for 2026-07-20 → 07-26 reproduces every figure in
`Weekly Report - Vista Atenas LP M3 - 2026-07-27.pdf`: solar 393.6 kWh,
consumption 335.2, independence 95.8%, health 84/100 "Watch", best day 87.5,
6/7 full charge, lowest SOC 40%, avg temp 26.7 °C, battery stress
"Normal (3.3 cyc)", voltage 48.5–52.3 V, frequency 59.57–60.68 Hz, L1
100.1–130.0 V, L2 102.2–128.2 V, grid data 7/7, grid quality 66/100 Poor,
60 alarm episodes, 0 outages, 5/7 self-sufficient days.

### Layout: matches to within 0.5pt

Text positions across page 1 agree with the reference to ≤0.5pt, and the port
embeds exactly the same three faces (Arial, Arial-Bold, Arial-Italic).

### Three real bugs found by doing the comparison

1. **WeasyPrint does not inherit `font-family` into SVG `<text>`.** Every label
   fell back to the default sans-serif, which resolved to **Verdana** — much
   wider than Arial — so every wrapped subtitle overflowed its block, because
   the wrap width is computed in characters against Arial-ish metrics. Google's
   converter inherited Arial, which is why the original never had to say so.
   Fixed by setting `font-family` on each SVG root.
2. **The reference report's "Expected output" and "Performance ratio" are
   wrong.** It fetches weather for the *requested* 8-day range but compares it
   against 7 days of measured solar, so expected output is inflated by roughly
   a day: 571.5 kWh / 68.9% in the reference vs 481.7 kWh / **81.7%** correctly
   computed. Same root cause as the header off-by-one — the live reports are
   understating performance ratio by ~13 points.
3. **A y-axis rounding edge case in my own port** — `int(max/10)+1` rounds an
   exact multiple of 10 up a whole step where `Math.ceil` does not. Caught
   before it could bite; now uses `math.ceil`.

### Deliberate differences from the reference

- Header shows the period **actually covered** (07-20 → 07-26), not the
  requested bound (07-27).
- 4-week trend buckets are true 7-day weeks, so they differ slightly from the
  reference's 8-day buckets (e.g. 440.1 vs 471.7 for the 07-13 week).
- Narrative text differs run to run — it is a fresh Claude generation.
- `system_type` conditionals applied (§ above).

### Still to do on the report

- Spanish template (`es`) — strings are in place, layout unverified.
- `buildEmailHtml()` is not ported; V1 is download-only by decision.

## 12. Step 5 built — `pages/06_vrm_monitor.py` (2026-07-28)

Three tabs: **Sitios** (customers/sites), **Cargar CSV** (upload → preview →
ingest), **Reporte** (render from either schema, preview, download).

Verified live in the browser against the real pilot data: the Sitios table shows
the ingested customer/site, and the Reporte tab generated a report end to end
from `vrm` (437.0 kWh, 360.4 consumption, 96.1% independence, 81/100 Good,
2026-07-22 → 07-28) with a working download button and no console errors.

Design choices worth noting:

- **Preview before write.** Upload parses and shows day count, samples, alarm
  events, outages, warnings and the full daily table *before* anything is
  written. The arch doc's "do not silently produce a bad report" rule applies
  just as much to "do not silently ingest a bad CSV".
- **Week picker lists only dates that have data.** A free date input would
  happily produce an empty report for a week nobody has data for; a short week
  is warned about explicitly rather than presented as a full one.
- **The schema selector is a feature, not debug scaffolding.** Rendering the
  same site from `vrm` and `monitoring` side by side is how the two ingestion
  paths get compared, and it is how the Apps Script retirement gets validated.

Also recreated the missing `/tmp/start_dimensionador.sh` that `.claude/launch.json`
points at.

### What Apps Script still owns after this

Checked against the Node-RED flow rather than assumed. Node-RED writes **every**
Supabase table directly (`energy_daily`, `alarm_events`, `grid_events`,
`ac_input_events`, `mppt_snapshots`, `flow_logs`) — Apps Script is not in that
path. It receives a *duplicate* copy of some events purely for the Google Sheets
backup.

So Apps Script's remaining jobs are:

1. **Sheets backup writer** (`doPost` → Sheets) — deliberate human-browsable
   backup, independent of reporting.
2. **Weekly scheduling** — the Monday time-driven trigger and
   `runAllWeeklyReports()` fan-out.
3. **Email delivery** (`MailApp`) + `buildEmailHtml()`.
4. **Drive archiving** of each PDF.

Report *rendering* is fully replaced. Retiring Apps Script entirely needs 2–4
ported: a scheduler, a transactional email sender, and archive storage
(Supabase Storage is already used for proposal PDFs).

## 13. Second real site: grid export, Spanish layout, parser robustness (2026-07-29)

Findings from ingesting a second export — VRM installation 793865, El Encino
(Casona), 81 days, 164 columns (vs 264 for the first).

### Grid export is real and large

That site exported **1,138 kWh against 324 kWh imported** over 81 days — 26,022
negative `Grid L1/L2` samples. Not an edge case; it is most of its grid
interaction.

`grid_kwh` deliberately still means **import only**, matching what Node-RED
writes into `monitoring.energy_daily`. Redefining it as net would silently
change every historical comparison and break the shared reader. Export lives in
`grid_export_kwh` (already created by migration 012) and is surfaced in the
report only when the site is marked as exporting — an always-zero row on a
non-exporting site is noise, and omitting it on an exporting one hides a third
of the story.

- **Migration 013** adds `vrm.sites.exports_to_grid`.
- Upload form gains the checkbox; the report adds an "Energy exported to grid"
  row to the Events block.

### The Spanish overlap was not a font-size problem

Reported as "bigger font than the Apps Script original". Measured instead:
glyph sizes are **identical** to the reference PDF at every size (9.81, 7.88,
7.23, 6.71, 21.69 …), differing only in floating-point noise.

The real cause is text length. `info_block_svg` draws the label left-anchored
and the value right-anchored with nothing between them; SVG `<text>` neither
wraps nor shrinks, so a long pair silently overlaps. "Puntaje de calidad de red"
+ "84/100 — Fluctuaciones menores" collides where "Grid quality score" +
"66/100 — Poor" fits. **The original has the same flaw** — it only ever shipped
layouts in a language that happened to fit.

Fixed with `text_width()` / `fit_row()`: shrink label and value together until
they fit, down to a 7.0 floor, then ellipsize rather than overlap. English
output is unchanged (verified: all 19 reference figures still exact).

Two further issues the Spanish render exposed, both invisible in English:

- **Block subtitles were still English.** `ES` is built as `dict(EN, **{...})`,
  so the eight `sub*` keys never overridden silently rendered English inside an
  otherwise-Spanish report. Translated.
- **Side-by-side blocks fell out of alignment** when one subtitle wrapped to two
  lines and its neighbour to one. `two_block_row_svg` now computes a shared
  first-row baseline.

### Weather needs coordinates — and the fallback was overstating performance

Weather was unavailable because the upload tab never collected lat/long. Added
location, timezone, lat/long and a geocode button (reusing
`calculations/pvgis.py:geocode_cr`) to the upload form; `0,0` is stored as NULL
so "unknown" is distinguishable from Null Island.

Worth more than the missing weather block: without coordinates, expected output
falls back to a flat 4.5 peak-sun-hours assumption, so the "performance ratio"
becomes actual-vs-assumption and lands near 100% (that site showed **99.9%**,
which reads as a perfect system and means nothing). The report now labels it
"Expected output (estimated)" with a "no weather data — estimate only" note in
grey rather than the usual green/amber/red.

### Parser robustness

Compared the two exports: 215 vs 147 distinct columns; only 4 columns unique to
the smaller one. Changes:

- **`SIGNALS` now carries an aggregation mode.** A real bug: `_pick` returned
  only the *first* column of a duplicated name, so on a two-charger site the
  `Solar Charger::PV power` fallback would have reported **half** the
  generation. Power signals now sum across devices (`SUM`); state readings
  (SOC, voltage, temperature) take the first (`FIRST`), where summing would be
  nonsense.
- **More candidates per signal** — AC-coupled PV, `VE.Bus Output power N` as a
  load fallback, `Battery Monitor::Power`, `System overview::Battery Voltage`.
- **`load_w` is now a required signal.** It is derived from L1/L2/L3 rather
  than picked, so its absence showed up as an all-null series, not a missing
  signal — a report with zero consumption would have rendered, with grid
  independence, energy mix and performance all silently wrong.
- **Phase-3 absence no longer warns.** `load_l3_w`/`grid_l3_w` are missing on
  every split-phase site, i.e. most of them; warning about it trains the
  operator to ignore warnings.

Both exports re-verified after the change, and the first site re-checked against
the Node-RED oracle — no regression (worst-case days are the CSV's partial final
day, 15.6 h vs a full day).

## 14. Uniform row type + export-aware layout (2026-07-29)

**Row font is now uniform per report, not per row.** The first fix sized each
row independently, which fits tighter but reads as a rendering glitch — one
shrunken line beside full-size neighbours. `uniform_row_size()` now finds the
largest size at which *every* info-block row in the report fits and applies it
everywhere. Measured result: **English 9.5 (unchanged), Spanish 8.5** — Spanish
gets one consistent, slightly smaller face rather than a single odd line.
Per-row ellipsizing survives only as a floor case, for a pair that cannot fit
even at 7.0.

**Exporting sites get an export KPI instead of an outage count.** On a site that
feeds back, exported energy is the more informative headline: a grid-tied
exporting system is by definition connected, so its outage count is
near-permanently zero. The 4th KPI card becomes "Energy Exported / 79.7 kWh /
36% of generation" on a mint background when `exports_to_grid` is set.

Nothing is lost by the swap — outages remain as a row in the Events block
alongside the export total, so the number is still on the page.

**The narrative now knows about export.** Without it, Claude described a heavily
exporting week purely in terms of consumption, which reads as though the
surplus went nowhere. The prompt gains the exported kWh and its share of
generation, framed as a positive outcome rather than waste. Verified: the
Spanish narrative now opens with "generó 221.6 kWh de energía solar, exportando
79.7 kWh a la red — un resultado que refleja un sistema bien dimensionado".

English output re-verified after both changes: row size still 9.5 and every
reference figure intact.

## 15. Estimated savings — real number, no company picker anywhere (2026-07-29)

Replaced the permanent "Tariff data coming soon" placeholder. Design decided
with the user before building, three explicit choices:

1. **CR default** = blended average across all 8 seeded distributors' T-RE
   tariffs (not a single distributor like CNFL) — chosen over picking one
   company specifically to avoid bias toward any particular utility.
2. **Exported energy does not count toward savings** — only avoided grid
   purchase (`load − grid import`) does. Export compensation (net metering vs
   net billing vs none) is a policy variable that differs by country and even
   by CR distributor; modeling it without knowing the specific policy risks a
   confidently wrong number.
3. **Non-CR rate lives in the upload flow itself**, not just the Sitios tab —
   one numeric rate + a 3-item currency dropdown (CRC/USD/EUR), explicitly
   *not* a distributor/company picker.

**New files:**
- `calculations/tariff_calculator.py: estimate_blended_effective_rate_crc()`
  — averages the *result* (bill ÷ kWh) across tariffs at the same consumption
  level, not the tier structures themselves (which don't share boundaries
  across distributors, so there's no principled way to merge them directly).
- `victron/savings.py` — the country-branching logic. `country == 'CR'` runs
  the blend (process-cached 1h, confirmed all 8 seeded distributors have
  complete T-RE tiers); anything else reads `sites.savings_rate` /
  `savings_currency` (migration 014, `vrm.sites` only — `monitoring.sites`
  needs nothing new since every real site there is already Costa Rica).
  Returns `None` — never a fabricated number — when neither basis exists.

**Report integration:** the savings block reuses `single_block_row_svg()`
unchanged (two rows: amount, basis), folded into the same uniform-row-size
pass as every other block, rather than adding new SVG. Verified rendering:
CR path (₡31,772, "Average of 8 Costa Rica T-RE tariffs"), non-CR flat-rate
path ($57.78, "Configured rate"), the Spanish translation of both labels, and
the no-basis fallback (country set, no rate configured) correctly keeping the
original placeholder instead of showing anything invented.

**UI:** upload form gains País (free text, default "CR") + rate/currency
fields, with a live caption stating which of the three outcomes will apply
before the file is even processed. Mirrored into the Sitios manual-entry
form; the Sitios table gained País and "Tarifa ahorro" columns.

## 16. Off-grid savings framing, dropdown UX, reverse geocoding (2026-07-29)

Four usability fixes to the savings feature and site form, all verified live.

**Off-grid savings are labeled as hypothetical, not hidden.** An off-grid site
has no grid connection, so `load − grid import` still computes a real
avoided-purchase-equivalent volume (grid import is always 0), but calling it
"savings" without qualification implies a real bill that never existed. The
formula is unchanged; only the subtitle changes, in both the report
(`subSavingsOffGrid`) and the upload form's live caption, which reacts to the
"Tipo de sistema" selection *before* the file is even uploaded. Verified: the
caption reads "Este sitio es off-grid: no tiene conexión a la red. El reporte
mostrará el ahorro como una cifra hipotética…" the moment `off_grid` is picked.

**Zona horaria and País are now dropdowns, not free text.** Timezone uses
Python's `zoneinfo.available_timezones()` (598 entries, cached 1h) rather than
a curated list — correctness matters here since it drives both the Open-Meteo
call and CR alarm-episode day-bucketing, and IANA's list doesn't need
maintaining. País uses a new `config.COUNTRIES` dict (ISO 3166-1 alpha-2 →
Spanish name, ~60 entries + "Otro"), since no such list existed anywhere in
the repo. Both are searchable via Streamlit's built-in filter-as-you-type.

**Reverse geocoding**: `calculations/pvgis.py:reverse_geocode(lat, lng)`, new,
complementing the existing `geocode_cr()` (name → coords, CR-only) with the
opposite direction for any country, via Nominatim's `/reverse` endpoint.
Verified against real coordinates: Atenas CR → `{"location": "Atenas,
Alajuela", "country_code": "CR"}`; NYC → `{"location": "New York, New York",
"country_code": "US"}`; Null Island → `None`. Wired into the upload form as a
second button ("🌍 Coordenadas → ubicación/país") alongside the existing
forward-search one.

**A real pre-existing bug, found by testing the new button rather than by
reading the code.** Both geocode buttons write `st.session_state["up_loc"]`
etc. *after* those widgets have already rendered earlier in the same script
pass — Streamlit raises `StreamlitAPIException: cannot be modified after the
widget with key … is instantiated` for that, unconditionally. This means the
**original forward-geocode button had this exact bug all along**; it had
never actually been clicked through in a live browser check before now, only
reasoned about by pattern-matching. Fixed both with the pending-key pattern
CONTEXT.md already documents for the wizard's versioned-widget resets: a
button stages its result under a `_up_pending_*` key and reruns; a block at
the top of `tab_upload()`, which runs before any of the affected widgets are
instantiated, consumes the staged value into the widget's real key. Verified
live after the fix: both buttons work with no exception.

## 17. One button, one input, three fields — coordinates as the source of truth (2026-07-29)

The two-button layout from §16 was confusing: "Ubicación → coordenadas" only
worked for Costa Rica, "Coordenadas → ubicación/país" worked everywhere but
didn't fill timezone, and nothing made clear which button did what without
reading the tooltip. Collapsed to **one button, one direction**: coordinates
in, location + timezone + country out, worldwide.

**New dependency: `timezonefinder`.** Nominatim's reverse endpoint (checked
the raw response directly) does not return a timezone in any field. Coordinate
→ IANA timezone name is exactly what `timezonefinder` solves — offline
boundary data, no added network call or third-party API key, deterministic.
Lazy singleton (`_get_tz_finder()`), since constructing `TimezoneFinder()`
loads its data (~1–2s) and shouldn't repeat per call.

`reverse_geocode()` now combines two independent lookups — Nominatim
(location/country, can fail) and `timezonefinder` (timezone, effectively
always resolves) — into one result, each field independently optional.
Verified against four real cities on four continents: Atenas CR, New York,
Madrid, Sydney all resolved location + country + timezone correctly in one
call; Null Island correctly returned no location/country while still handing
back a nominal `Etc/GMT` (expected `timezonefinder` behaviour over open ocean,
not a bug).

**Layout now matches the actual data flow**: Latitud/Longitud first (the
input), the single "🌍 Buscar por coordenadas" button, then
Ubicación/Zona horaria/País below as the (still independently editable)
output — instead of the old order that implied Ubicación was the primary
field.

The CR-only forward search (`geocode_cr()`, text → coordinates) is removed
from this form specifically, not deleted — it's still used as-is by the
proposal wizard's own site step (`wizard/common.py`), which is unrelated to
this page and wasn't part of this change.

**A second instance of the pending-key warning**, caught by testing rather
than assumed fixed by the §16 pattern: passing both `index=` (a first-render
default) and a pre-seeded `session_state[key]` on the same selectbox call
triggers a benign but visible Streamlit warning ("created with a default
value but also had its value set via the Session State API"). Fixed by
omitting `index=` once the key is already in `session_state` — reproduced live
(the warning appeared for Madrid/`up_tz`), fixed, then re-verified with a
different city (Sydney) to confirm it wasn't a one-off.

## 18. Two real bugs from testing a coordinate the curated list never covered
(2026-07-29)

User tested Chernobyl (51.273417, 30.227378) — a real coordinate, not a
contrived edge case — and found two things simultaneously:

1. **Ubicación came back in Ukrainian** ("Київська область"), not Spanish.
   Diagnosis, not guesswork: Nominatim returns place names in the *local*
   language of whatever it finds unless `accept-language` is specified, and
   the reverse call never set it. Fixed with `accept-language: "es,en"` — the
   operator using this form reads Spanish; English is the fallback for the
   (rare) place OSM has no Spanish name for at all.
2. **País stayed "Costa Rica"** instead of switching to Ukraine. Diagnosis:
   `reverse_geocode()` correctly returned `country_code: "UA"` — confirmed by
   calling it directly — but "UA" was never in `config.COUNTRIES`, which
   §16/17 built as a curated ~64-entry list. The code path for an unrecognized
   code was a `st.warning()`, which fired but was easy to miss, silently
   leaving the wrong country selected.

**Root cause of #2 is the design, not a missing entry.** A curated list will
always have gaps against "vrm may be anywhere," and each gap fails silently
in exactly this way. Replaced the 64-country list with a near-exhaustive one
— every UN member plus common territories, **200 entries**, verified no
duplicate keys. "UA" → "Ucrania" is in it now, but so is everywhere else that
was equally likely to be missing.

**Bonus from the `accept-language` fix**: every previously-tested city now
also returns its Spanish name — "Nueva York" instead of "New York", "Sídney"
instead of "Sydney" — consistent with the rest of the app's language, not
just fixing the one broken case.

Verified live with the exact reported coordinates: Ubicación → "Óblast de
Kyiv", País → "Ucrania", no warning.

## 19. Report language in the upload form; a real grid_zero rendering bug found by
answering "does system_type actually work" honestly (2026-07-29)

**Report language was never in the upload form.** `report_language` existed
on `vrm.sites` since migration 012 and was correctly wired into the *Sitios*
manual-entry form's `LANGS` selectbox — but never into *Cargar CSV*, the path
every real site actually goes through. Every uploaded site was silently
getting whatever the column's default is. Added the same selectbox there,
threaded through `meta`/`fields` the same way `system_type` already was, and
surfaced the choice in the pre-import summary caption so the operator sees it
before saving, not after.

**A real duplicate-block bug in `grid_zero` reports, never caught because no
`grid_zero` report had ever actually been rendered.** Asked directly whether
fields differ by `system_type` — checking the code rather than recalling it
found that for `grid_zero` (grid connection, no battery), the report drew
**"Grid Quality" twice**: once as a wrong full-width fallback in the row1
slot (meant for something else, substituted there because `has_batt` is
False), and again in row2 (correctly, since `has_grid` is True). Meanwhile the
energy-mix donut — Solar vs. Grid, still meaningful with no battery — never
rendered at all for that system type.

Root cause: `row1_svg()` always pairs the donut with a *battery* info-block;
when there's no battery to pair (`has_batt=False`), the calling code
substituted a Grid Quality block instead of building a battery-less variant of
the donut row. New `energy_mix_full_svg()` — full-width, Solar/Grid only, no
battery slice or legend row (deliberately, not just a coincidentally-zero
one — a `grid_zero` site has no battery hardware at all). Verified: rendered
a real site as `grid_zero`, confirmed Grid Quality now appears exactly once
and the 2-way donut renders correctly; re-rendered the same site as its real
`hybrid` type immediately after to confirm zero regression (all 19 original
reference figures, energy mix, and Battery Health block still intact).

**On the "Incluir" field** (user question, not a bug): it is exactly what it
looks like — two operator-side toggles (`with_narrative`, `with_weather`)
skipping the Claude API call and the Open-Meteo call, useful when iterating
on a report quickly or when either service is unavailable/unwanted for a
specific pull. It was built as an operational shortcut, not as a designed
customer-personalization feature — there's no third option beyond those two,
and nothing else currently plugs into that pattern. Worth calling out as a
real idea for later (e.g. an operator toggle for which report sections a
specific customer wants to receive), but that's a proposal for future work,
not something already built for that purpose.

## 20. One placement question left open

Whether the new Python modules live under `victron-monitor/` (product-aligned, but that
directory currently holds only Node-RED/Apps Script/SQL — no Python, no `__init__.py`, and
it isn't on the Streamlit app's import path) or as `victron/` at the repo root next to
`calculations/` and `proposals/` (import-clean, matching how every other module in this
app is structured, at the cost of splitting Victron Monitor's code across two directories).

Recommend `victron/` at the repo root for the Python code, with a pointer added to
`victron-monitor/README.md`. Worth confirming before scaffolding, since it's cheap now and
annoying later.

## 21. Custom date range — plan only, not yet built (2026-07-29)

`monitoring` reports are explicitly out of scope for this: they stay the automatic fixed
1-week report they are today, no change. Everything below is `vrm` only.

Two phases, agreed with the user before writing any code:

### Phase A — arbitrary range up to 31 days (near-term)

Generalizes today's report from "exactly 7 days ending on a chosen date" to "any
operator-chosen `(start, end)` within the site's available data, capped at 31 days" — same
template, same block set, just no longer hardcoded to 7.

**Already generalizes with no work**, confirmed by reading the code, not assumed:
- Daily rows are summed / health-averaged over the window already — nothing here assumes 7.
- CR savings already scales the monthly-equivalent off `num_days`, not a literal week.

**Mechanical parameter threading:**
- `vrm_report_db.py`: `week_bounds()` (hardcoded `start = end − 6 days`) → accept an explicit
  `(start, end)` pair for the `vrm` path. `monitoring`'s call site is untouched.
- "vs prev" week-over-week comparison → "same length window, immediately preceding" instead
  of a hardcoded 7-day lookback. Trivial once the window itself is a parameter.
- `build_report_data(site_id, start, end, schema, ...)` — signature moves from `week_ending`
  to explicit bounds, `vrm` call path only.
- Reporte tab (`vrm` origin only): two date inputs instead of one, constrained to
  `get_available_dates()`'s actual min/max for that site. `monitoring` origin keeps today's
  single "Semana que termina el" picker unchanged.
- Enforce the 31-day cap in the data layer (reject, not just hide in the UI) — defense in
  depth, same reasoning as every other validation in this pipeline.

**4-week trend: unchanged, per explicit decision.** Stays a fixed 4×7-day view ending on the
report's end date, decoupled from whatever custom range was chosen for the main numbers —
still useful context regardless of what the operator picked.

**The one genuinely open piece — chart legibility beyond ~10 days:**
- `bar_chart_svg()`'s daily bars use day-of-week labels (Mon–Sun), fine for ≤7ish days,
  illegible and repetitive past that. Needs date labels for longer spans, and likely
  thinned labels (every 2nd/3rd bar) as the count climbs toward 31 — concrete thresholds
  need picking against real rendered output, not guessed once and assumed to hold.
  Bars themselves (as opposed to labels) may stay one-per-day up to 31; verify visually
  rather than assume.
  Same question for the SOC daily chart, though line/area charts tolerate more points
  better than bars.
- Copy: "Weekly Energy Report" / "WEEKLY HEALTH SCORE" / "this week" (narrative prompt) /
  "vs prev" are all literally weekly-flavored text. Open decision: genericize wording only
  for the `vrm` path (two translation-dict variants), or genericize everywhere including
  `monitoring` (one wording set — "Health Score" reads fine for an exact 7-day period too,
  and "weekly" was never load-bearing information). Leaning toward the latter for
  simplicity, not decided.

### Phase B — long-window "Overview" report (later, plan only)

Not a bigger version of the Phase A template. Past somewhere around a month, daily bars and
a daily SOC chart stop being legible *or* useful — a 3-month report should answer "is this
system trending well / is there a seasonal weak spot", not "what happened on a specific
Tuesday". Triggered when a selected/available range exceeds the Phase A cap.

**Architecture: one report generator, band-conditional blocks** — the same pattern
`system_type` already uses (`has_grid`/`has_batt` swap whole blocks in/out). Add an
`is_overview` flag the same way, threaded from `num_days > 31`.

**Blocks needing zero change** (already period-length-agnostic): KPI summary cards, the
savings block, alarm/outage counts, the 4-week trend (always its own fixed thing regardless
of band).

**Blocks that change, and the reusable primitive they all share:**
`four_week_trend_svg()` already contains the one piece of machinery Phase B actually needs —
grouping daily rows into N buckets and summing per bucket. Generalizing that from "always 4
buckets of 7 days" into "N buckets of ~7-or-~30 days spanning an arbitrary range" is the
single reusable building block behind everything below:
- Daily bar chart → weekly or monthly aggregated bars (same bucketing primitive).
- Daily SOC chart → weekly min/max SOC band instead of per-day.
- Health score → currently one averaged number for the whole window; over 3 months that
  hides real variation (a bad month buried inside an otherwise-fine quarter). Should become
  a bucketed trend line — new visual real estate, not a reworked KPI card.
- Grid dependency / battery cycling as a trend over the period — both are already computed
  per day (they feed the health score), so this is a new chart over existing numbers, not
  new computation.
- **Seasonal coverage — the likely flagship chart for "why 3 months matters".** The Off-Grid
  *proposal* wizard already has this exact concept (Step 6, monthly PVGIS-estimated
  generation vs. a flat consumption line, weakest month flagged — see this file's Phase 5
  history in `CONTEXT.md`). A VRM Overview report's version would be the same idea driven by
  *real measured* monthly PV vs. real measured monthly load — arguably more compelling than
  the proposal tool's PVGIS-estimated version, since it's a system that's actually running.
- Narrative prompt needs a genuinely different frame ("how has this system trended over the
  quarter") — a distinct prompt template, not a reworded one-week prompt.

**Scoping note that matters:** Phase B is entirely a rendering-layer feature. `fetch_report_window`
already fetches raw daily rows generically for any range; Phase B's bucketing happens
client-side in Python on data already being ingested and stored today. **No changes to the
CSV mapper, the `vrm` schema, or ingestion at all** — purely `weekly_report.py` /
`report_svg.py` / i18n.

**Open UI question, not decided:** does exceeding the Phase A cap *automatically* switch to
the Overview layout, or does the operator explicitly pick "Detallado" vs. "Resumen"? Leaning
toward automatic (the cap becomes a mode boundary, not a hard stop) — to be decided when
Phase B is actually scoped.

**Sequencing:** Phase A first (bounded, mechanical, extends what already works). Phase B
after, once Phase A's chart-legibility work has already answered some of the "how many
bars/labels actually fit" questions Phase B will hit again at a coarser granularity.

## 22. Phase B scoped — auto-switching Overview report (2026-08-14)

Phase A shipped (`feat/vrm-custom-date-range`, merged 2026-08-06): `MAX_CUSTOM_RANGE_DAYS =
31` is enforced in `database/vrm_report_db.py:fetch_report_window()` — currently a hard
`ValueError` — and `pages/06_vrm_monitor.py:tab_report()` blocks the operator's calendar pick
above it with `st.error`. This section turns Phase B from the §21 sketch into a concrete
build plan, with one decision now locked with the user:

**Auto-switch, no operator toggle.** Crossing the 31-day cap does not error and does not
present a "Detallado vs. Resumen" choice — it silently renders as the Overview layout. The
cap becomes a mode boundary, not a hard stop, exactly as §21 already leaned. Rationale: the
operator's actual decision is *what date range has the data I need*; which layout best
presents that range is a rendering-legibility fact the tool knows and the operator
shouldn't have to.

**But the tool must say which mode a given pick will produce, before the operator clicks
generate.** An invisible mode switch is worse than the current hard error — at least the
error told the operator something. `tab_report()`'s range picker (`pages/06_vrm_monitor.py`
~line 561) gets a live indicator under the calendar that updates as the picked range
changes: "Detallado (día por día) · ≤31 días" while `num_days ≤ 31`, "Resumen (Overview,
agrupado por semana/mes) · N días" once it crosses. This is the one UI requirement from this
decision — both scopes need to be visible before generation, not discovered after.

### Data layer (`database/vrm_report_db.py`)

- `fetch_report_window()`'s `if num_days > MAX_CUSTOM_RANGE_DAYS: raise ValueError` is
  deleted. Replaced with `is_overview = num_days > MAX_CUSTOM_RANGE_DAYS` added to the
  returned dict — `MAX_CUSTOM_RANGE_DAYS` keeps its name and its job, it just stops being a
  ceiling and becomes the flag's threshold.
- A new, real ceiling still has to exist — Overview mode removes the 31-day stop but the
  query and the render both need *some* bound. **Locked with the user (2026-08-15):
  `MAX_OVERVIEW_RANGE_DAYS = 183`** (~6 months) — a `ValueError` in the same place the old
  one was, for a pick past it.
- **New shared bucketing primitive.** The fixed 4-week trend already contains the logic
  Overview mode needs — group daily rows into buckets, sum/average each. Today that's
  inlined as the `for i in range(3, -1, -1)` loop directly in `fetch_report_window()`
  (lines ~223-233), hardcoded to 4 buckets of 7 days. Extract it to a standalone
  `bucket_days(rows: list[dict], start: date, end: date, bucket_len_days: int) -> list[dict]`
  that returns `{label, start, end, days, pv, load, ...}` per bucket, `[bucket_len_days ==
  7]` reproducing the existing fixed trend call exactly (regression check: re-run against
  the already-validated reference site, confirm identical output). `fetch_report_window()`
  calls it once for the always-fixed 4-week trend (unchanged) and, when `is_overview`, a
  second time over the full `[start, end]` for the Overview blocks.
- **Bucket granularity rule for Overview mode — locked with the user (2026-08-15), simpler
  than this section's first two guesses.** No weekly tier. Every Overview report — the
  entire `32`–`183`-day range, i.e. everything past the 4-week/31-day Detallado cap up to
  `MAX_OVERVIEW_RANGE_DAYS` — buckets monthly (`bucket_len_days ≈ 30`). Detallado stays
  daily through 31 days exactly as today; the moment a pick crosses that line it goes
  straight to monthly, no intermediate weekly-bucketed band. `bucket_days()` still takes
  `bucket_len_days` as a parameter (the 4-week trend keeps calling it with `7`), it's just
  that Overview's own call site always passes `~30`, never `7`. The bucket *count* this
  produces at real data volumes — as low as ~2 for a 32-day pick, up to ~6 near the cap —
  is still worth a visual check once built (same as Phase A's chart thresholds), but the
  rule itself (monthly, always, once overview) is decided, not provisional.
- `health`/`get_daily_health` and the grid/battery figures that feed the new trend blocks are
  already fetched per-day by `fetch_report_window()` for the main window — Overview mode
  buckets the same rows client-side, no new Supabase query shape.

### Rendering layer (`victron/report_svg.py`, `victron/weekly_report.py`)

`build_report_data()` threads `is_overview` from `fetch_report_window()`'s result into the
template context, the same way `system_type`'s `has_grid`/`has_batt` already gate blocks.

- **Daily bar chart / SOC chart → bucketed.** `bar_chart_svg()`'s and `soc_chart_svg()`'s
  per-day x-axis becomes per-bucket when `is_overview`: PV/load bars sum per bucket (reusing
  `four_week_trend_svg()`'s bar-pair rendering, generalized off the now-shared bucketing
  primitive rather than copied), SOC becomes a per-bucket min/max band instead of the daily
  min-line-with-annotations `soc_chart_svg()` draws today — the existing band-fill logic in
  that function (`band_fwd`/`band_rev`) already draws a min/max envelope for a full period;
  Overview mode reuses that shape per-bucket instead of per-day.
- **Health score → trend line, new block.** Today `avgHealth` is one number averaged over the
  whole window (`weekly_report.py`), which over a quarter hides a bad month inside an
  otherwise-fine one. New `health_trend_svg()` — one point per bucket, `score_colors()`
  (already used for the KPI card) coloring each point/segment. New chart, not a reworked KPI
  card; the KPI card itself stays as the period average for both modes.
- **Grid dependency / battery cycling trend, new block.** Both are already computed per day
  (they feed `compute_daily_health()`), so this is `bucket_days()` output charted, not new
  computation. One new SVG function, styled like `health_trend_svg()` — two line series
  (dependency %, cycles) rather than a new visual language.
- **Seasonal coverage — the flagship Overview chart.** `wizard/common.py:
  monthly_coverage_chart()` already exists for exactly this shape — monthly generation vs.
  monthly consumption, weakest month flagged — built for the off-grid *proposal* wizard's
  Step 6 against PVGIS-estimated generation (`wizard/off_grid.py` ~line 1719,
  `_og_monthly_coverage_and_sim()`). The Overview report's version feeds it **real measured**
  monthly PV and load from `bucket_days()` output instead of a PVGIS estimate — reuse the
  chart function itself if its input shape and rendering target (matplotlib/PNG for the
  wizard's PDF vs. this report's inline SVG pipeline) are compatible; port the visual design
  rather than the function if not. Decide which once the function's actual signature is
  read, not assumed compatible.
- **Copy genericization — resolving §21's open item.** Doing it everywhere (`monitoring`
  included), per the lean already recorded in §21: `reportTitle` "Weekly Energy Report" →
  "Energy Report", `healthScore` "Weekly Health Score" → "Health Score", `"vs prev"` → "vs
  previous period", the narrative prompt's `"this week"` → the actual period phrase already
  computed elsewhere in the file. One wording set is simpler than branching every string on
  `is_overview`, and none of it was load-bearing information — a 7-day report calling itself
  "Health Score" instead of "Weekly Health Score" loses nothing.
- **Narrative — distinct prompt, not a reworded one.** `weekly_report.py`'s narrative call
  branches on `is_overview` to a new prompt template in `report_i18n.py`: framed around
  "how has this system trended over the period" rather than a single week's events, fed the
  bucketed health/PV/load series instead of the daily ones, and reusing `_season_context()`
  unchanged (a period spanning multiple months benefits from the CR dry/rainy season fact
  even more than a single week did). Same fail-soft contract as today — a missing key or API
  error still returns a placeholder, never blocks the report.

### UI (`pages/06_vrm_monitor.py: tab_report()`)

- Remove the `num_days > MAX_CUSTOM_RANGE_DAYS` branch that currently sets `st.error` +
  `valid = False` (~lines 575-580). Replace with the live mode indicator described above,
  shown for every valid pick — not just ones that cross the boundary — so "which mode am I
  about to get" is always visible, not only surfaced as a warning past the line.
  `date_input`'s `max_value=max_d` already allows selecting the site's full data span; only
  the hard error was stopping a long pick from reaching `build_report_data()`.
  `MAX_OVERVIEW_RANGE_DAYS` becomes the new outer error case in the same spot, for the
  rare pick past even that.
- For the record, since it's the one alternative this section considered and rejected:
  an explicit "Detallado / Resumen" radio, independent of range length, was the other
  option on the table. Rejected in favor of auto (see the decision at the top of this
  section) — noted here so it isn't re-litigated later without the reasoning at hand.
- Coverage warning (`len(covered) < num_days`) stays as-is for both modes — a sparse Overview
  window is exactly as worth flagging as a sparse Detallado one, same reasoning, no new code.

### Sequencing

1. **Done (2026-08-15).** `bucket_days()` extracted into `database/vrm_report_db.py`,
   `fetch_report_window()`'s inlined anchored-from-`end` loop replaced with
   `bucket_days(rows, trend_span_start, end, 7)` — forward-from-`start` and
   anchored-from-`end` coincide exactly on the trend's fixed 28-day/7-day-bucket span, so
   no behavior changed. Verified two ways against real `vista-atenas-lp-m3` data: (1) the
   old loop reimplemented standalone and diffed bucket-for-bucket against the new function's
   output for two different end dates — identical; (2) a full `build_report_data()` +
   `render_pdf()` run end to end with no exceptions, trend still producing 4 buckets, totals
   unchanged from what §11 already validated.
2. **Done (2026-08-15).** `MAX_OVERVIEW_RANGE_DAYS = 183` added; `fetch_report_window()`'s
   old `num_days > MAX_CUSTOM_RANGE_DAYS` hard error is gone, replaced by
   `is_overview = num_days > MAX_CUSTOM_RANGE_DAYS` in the returned dict and a `ValueError`
   only past the new 183-day ceiling. `build_report_data()` threads it through as
   `isOverview` in the template context. Verified: a 7-day window still gives
   `is_overview=False` with identical output to before; a 40-day pick no longer raises and
   returns `is_overview=True`; exactly 183 days succeeds, 184 raises; a 591-day pick raises
   against the new cap with the new message. `build_report_data()` + `render_pdf()` both
   still succeed for the `is_overview=True` case — as expected, it renders as a
   Detallado-style report with daily charts stretched past their tuned range, since no
   Overview blocks exist yet (steps 3+ below); this intermediate state isn't shipped alone.
   Also re-verified through the actual UI (`Reporte` tab, `vista-atenas-2-floor-pool`,
   7-day pick): generated end to end with no console errors, numbers matching §11's
   validated reference (437.0 kWh, 96.1% independence, 81/100 health).
3. **Done (2026-08-15).** `bucket_days()` extended to also aggregate `min_soc`/`max_soc`
   per bucket (named to match `energy_daily`'s own columns, so the SOC chart's band logic
   needs no field renaming). `bar_chart_svg()` and `soc_chart_svg()` both now branch on
   `d["isOverview"]`: daily mode is byte-for-byte unchanged; overview mode reads
   `d["overviewBuckets"]` instead of `d["dailyGrouped"]`, drawing one bar-pair / one
   band-point per bucket with the bucket's own `label` on the x-axis. `weekly_report.py`
   computes `overviewBuckets` via `db.bucket_days(days, period_start, period_end, 30)` —
   always monthly, no weekly tier, per §22's locked rule — and threads it through
   `build_report_data()`'s return dict alongside `isOverview`.
   **Verified in isolation**, not live: a real environment problem surfaced mid-step (see
   below) that made the actual `.venv` unusable for a stretch, so this was verified by
   importing `victron/report_svg.py` directly with plain system Python — it has zero
   non-stdlib dependencies — and `database/vrm_report_db.py` with `supabase_client` stubbed
   in `sys.modules` (its only external dependency, called lazily, never at import time).
   Confirmed: `bucket_days()`'s new min/max/sum aggregation matches hand-computed values on
   synthetic 45-day data; daily-mode bar/SOC charts still produce one bar/point per day
   (unchanged); overview-mode charts correctly switch to bucket count (2 buckets for 45
   days, 7 for a 183-day max-cap span with a partial 3-day final bucket) with correct
   labels; a 60-day case that divides evenly into two full 30-day buckets; the 32-day
   just-past-cap case (30 + 2 days); and the 183-day max-cap case all render without
   exceptions. Not yet re-verified through a live `render_pdf()` / real WeasyPrint layout
   pass (bucket counts are small — at most 7 — comfortably inside what the daily chart was
   already tuned for up to 31 bars, so a layout regression is unlikely, but "verify visually
   rather than assume" per this doc's own standard means this is still owed once the
   environment issue below is resolved).

   **Environment issue found during this step, unrelated to the code above:** this
   project's `.venv` lives under `~/Desktop`, which syncs via iCloud Drive. Partway through
   this step, files inside it started reading back empty (`open().read()` returning 0
   bytes) while `ls`/`wc -c` kept reporting their correct original size — a stuck iCloud
   "dataless file" that isn't materializing. Confirmed *not* a sandbox-specific artifact:
   even a plain `cp` (outside any tool sandbox) produced a 0-byte copy of the affected file.
   Repeated `brctl download` passes over the whole tree fixed most of the affected files
   (the import chain got measurably further each time — `postgrest`, then deeper into
   `jwt`/`supabase_auth`) but one file, `cryptography/hazmat/primitives/asymmetric/ec.py`,
   stayed stuck at 0 bytes through several direct, targeted `brctl download` attempts.
   Free disk space is fine (17 GB), so that's not the cause. This blocks the actual
   Streamlit app (any fresh `.venv/bin/python3.9` process hits it), not just this
   verification — worth the user checking their iCloud Drive sync status directly (System
   Settings → Apple ID → iCloud → iCloud Drive, or network connectivity) since it's a
   machine-level stall, not something fixable from the command line.
4. **Built, then removed after review (2026-08-15/16).** The chart block described below
   was built and verified, but the user reviewed an actual generated report and asked for it
   removed — it wasn't something they'd asked to see, regardless of it having been in this
   plan. Removed in full (`report_svg.py:health_grid_trend_svg()` deleted, the template block
   and its render call site gone, the three now-dead i18n keys removed) in §23 below. The data
   plumbing it was built on (`bucket_health_days()`, `bucket_days()`'s grid/discharge sums,
   `overviewTrend`) stayed, because step 6's narrative prompt also depends on it — only the
   standalone visual block came out. Left the original build notes below for the record.

   New `database/vrm_report_db.py:bucket_health_days()` — same
   boundary-walking as `bucket_days()`, but over `daily_health` rows, with its own
   dedup-by-date-keep-highest-score rule (mirrors `weekly_report.py`'s existing whole-period
   logic exactly). `bucket_days()` extended to also sum `grid_kwh`/`battery_discharge_kwh`
   per bucket, so grid independence % and battery cycles can be *derived* per bucket with
   the identical formula the period totals already use — not a second definition.
   `weekly_report.py` zips the two bucket lists into `overviewTrend`
   (`{label, healthScore, gridIndependencePct, batteryCycles}`), added to
   `build_report_data()`'s return dict.

   New `report_svg.py:health_grid_trend_svg()` — one combined block covering both of this
   step's planned bullets rather than two separate chart functions: health score and grid
   independence share one 0-100 axis (both naturally percent/score-scale, so no dual axis
   needed), health dots coloured via the existing `score_colors()`, independence drawn as a
   line; battery cycles (a different unit — a count) is a per-bucket text label instead of a
   third line series, the same pattern `four_week_trend_svg()` already uses for its
   week-over-week % annotations. Two new i18n keys (`healthGridTrend`, `subHealthGridTrend`,
   `cyclesAbbr`) added to both EN and ES. Wired into the template as a new page-2 block,
   `{% if health_grid_trend_svg %}`-gated so it only ever appears when `isOverview`.

   **Verified** the same two ways as step 3: isolated (`bucket_health_days()`'s dedup+average
   checked against hand-computed values on synthetic data with duplicate-date rows, a
   missing-data bucket correctly returning `None` rather than a false zero, the chart
   rendering correctly for n=1 and for a bucket with no health score at all, ES i18n) and
   live (`vista-atenas-lp-m3`, 2026-07-06→08-14, real health/independence/cycles per bucket:
   86→84 / 95.8%→100% / 14.39→4.35 cyc; the 7-day Detallado path re-rendered
   byte-for-byte identical — 53058 bytes both before and after this step).
5. **Decided with the user (2026-08-15): option (c), skipped for V1.** Investigated first,
   see below for why — but the resolution is: no seasonal coverage chart in this version.
   Steps 6-9 shipped without it. Revisit once real `vrm` sites have accumulated enough
   history for option (a) — the true full-year view — to actually populate for more than a
   rare site; until then it would ship mostly invisible, which isn't worth the query-scope
   change from "always the report's own picked period" that option (a) requires. Revisiting
   later means re-reading this section fresh, not assuming the analysis below still reflects
   the codebase — confirm `monthly_coverage_svg()`'s 12-month constraint and the VRM 6-month
   retention window are still what they were before building against them again.

   `wizard/common.py:monthly_coverage_chart()` (Plotly) is confirmed **not** usable — its own
   docstring says so directly ("WeasyPrint can't render Plotly"; screen-only, wizard Step 6).
   Its docstring points at the actual PDF-compatible sibling, `proposals/charts.py:
   monthly_coverage_svg()` — inline SVG, same 520-unit width and palette as
   `victron/report_svg.py` *by explicit design* (its module docstring: "so the quote PDFs
   and the VRM weekly reports read as one family"), same paired-bar-with-amber-shortfall
   visual this step wants. Mechanically this is exactly the reuse the plan hoped for.

   **But it hard-requires exactly 12 months** (`if len(generation_kwh) != 12: return ""`) —
   a real, deliberate check, not an incidental limit, because the function's whole point for
   proposals is "does this cover a full year." The Overview report's own picked window tops
   out at `MAX_OVERVIEW_RANGE_DAYS = 183` (~6 months, locked in this same section) — it can
   never supply 12 months on its own. Feeding it a partial year either breaks the length
   check (returns `""`, chart silently vanishes) or requires querying a site's data **beyond
   the report's own picked period** to assemble a real Jan–Dec view — a materially different
   thing than every other Overview block, which all stay scoped to whatever `[start, end]`
   the operator picked.

   **This is a scope decision, not a technical one**, so not resolved unilaterally:
   - **(a) Reuse `monthly_coverage_svg()` for real, as a full-year view** — query the site's
     *entire* available history (via `get_available_dates()` / `get_energy_daily()` beyond
     the report window), bucket into calendar months, and only render the chart when ≥12
     distinct months of data exist. Closest to the plan's original "flagship chart" framing
     and to the wizard's proposal-side chart, but most real `vrm` sites won't have 12 months
     yet (VRM itself only retains ~6 months of 1-min-resolution data, per §7.6/§11's earlier
     findings) — the chart would render `""` (nothing) for nearly every site today, a real
     feature shipping mostly invisible at launch.
   - **(b) Port the visual design, not the function, scoped to the picked period.** A new,
     smaller function styled after `monthly_coverage_svg()` (same palette, same paired-bar
     shape, same amber-shortfall flag) but accepting however many calendar-month buckets the
     Overview window actually spans (2–7, not always 12) — visually similar to what
     `bar_chart_svg()`'s Overview mode (step 3) already draws, but framed as "coverage" with
     the shortfall-month flag added. Works today for every Overview report regardless of
     site age, at the cost of not being a true seasonal/annual view for a young site — and
     it's genuinely close to redundant with step 3's already-shipped bucketed bar chart,
     which is worth being honest about rather than building a near-duplicate block.
   - **(c) Skip this block for V1 of Phase B**, ship steps 6–9 (narrative, copy, UI,
     verification) without it, and revisit once real `vrm` sites actually accumulate a full
     year of history — at which point option (a) becomes the obviously right (and actually
     populated) choice.

   No option was wrong on the merits; each traded off differently between "matches the
   original flagship framing" and "actually shows something for the sites that exist today."
   Left as a genuine choice for the user rather than guessed at, since it changed what would
   get queried and what the report would promise, not just how a chart is drawn — (c) is the
   answer that came back.
6. **Done (2026-08-15).** No dependency on step 5, so done out of order while that one was
   still undecided. New
   `weekly_report.py:_bucket_trend_lines()` formats `overviewBuckets` + `overviewTrend`
   (both already built in steps 3-4) into one line per bucket — date range, days, solar,
   consumption, health, grid independence, battery cycles — feeding a genuinely different
   prompt frame in `generate_narrative()` for `isOverview`: "describe how the system trended
   across the segments... rather than only restating the period's totals," with the
   per-segment breakdown given explicitly so the model has real trend data to work from
   rather than being asked to infer a trend from one lump total. The non-overview prompt is
   untouched — same text as before this step, refactored only so both branches share the
   trailing per-period data lines (`site`, `pv`, `load`, outages, etc.) via a common
   `framing + shared_lines` structure instead of duplicating them.

   **A real bug caught by isolated testing, not by reasoning about the diff**: the initial
   edit left the shared data lines outside the closed parenthesis of the `if`/`else` branches
   — a plain `SyntaxError: unmatched ')'` that a diff read wouldn't obviously catch either,
   since each individual `if`/`else` block looked locally well-formed. Caught immediately by
   running `ast.parse()` on the file as the very first verification step, before any
   isolated-logic testing — fixed by having both branches build a `framing` string, then a
   single shared `prompt = (framing + ...)` continuation for the common data lines.

   **Verified**: `_bucket_trend_lines()`'s formatting (correct fields, correct
   `days`/date-range text, missing health score renders as `"n/a"` rather than a fabricated
   number); `generate_narrative()`'s existing fail-soft contract (`ANTHROPIC_API_KEY`
   missing → placeholder, unchanged) still holds for both branches; and a live Claude call
   for both branches on real `vista-atenas-lp-m3` data. The overview-mode narrative does
   exactly what this step asked — it names and compares the two segments rather than
   restating one lump total: *"the system's grid independence actually improved between
   segments — rising from 95.8% in the first 30 days to a perfect 100.0% in the final 10 —
   even as the battery health edged down slightly from 86 to 84."* The 7-day narrative came
   back unchanged in style from before this step ("a standout week..."), confirming zero
   regression on the Detallado path.
7. **Turned out to already be done (checked 2026-08-15), no new code.** `report_i18n.get(lang,
   num_days)` already does exactly what this bullet asked for — built during Phase A (§21),
   not this session: `num_days == 7` returns the original "Weekly" wording unchanged (so
   `monitoring`, which only ever passes 7, is untouched either way); any other length —
   which every Overview report is, by construction — returns `_PERIOD_OVERRIDES`
   ("Energy Report" / "Health Score" / "this period", etc.), already wired in both EN and
   ES. Confirmed live: `report_i18n.get('en', 40)['reportTitle']` returns `"Energy Report"`.
   grepped `weekly_report.py`/`report_svg.py`/the template for any remaining hardcoded
   "week"/"semana" outside comments and the always-correct 4-week-trend chart (which is
   deliberately exempt — see the code comment at `_PERIOD_OVERRIDES`'s definition, it's
   always a fixed 4×7-day view regardless of the report's own window) — none found. Every
   string this session's steps 3/4/6 added (`healthGridTrend`, `_bucket_trend_lines()`'s
   prompt text, etc.) was already written period-neutral from the start, so there was
   nothing left to generalize. §21's original "not decided" framing ("genericize everywhere
   including `monitoring`, or `vrm` only") is resolved by what already shipped: everywhere,
   since the override only ever triggers on a non-7-day count.
8. **Done (2026-08-15).** `pages/06_vrm_monitor.py: tab_report()`'s `vrm`-branch hard
   `st.error` at `num_days > MAX_CUSTOM_RANGE_DAYS` is gone — the outer bound check now
   targets `rdb.MAX_OVERVIEW_RANGE_DAYS` (183) instead, the only remaining hard stop. Every
   valid pick now shows a live `st.caption` mode indicator before the operator clicks
   Generar: "📅 Detallado — N días, día por día" at ≤31 days, "📊 Resumen (Overview) — N
   días, agrupado por mes..." past it — worded to match the locked no-weekly-tier rule
   (earlier draft text in this section said "semana/mes"; corrected to "por mes" only).
   Coverage warning unchanged.

   **Verified live** in the browser: default 7-day pick shows the Detallado caption; picking
   the site's full 2026-05-10→07-28 range (80 days) shows the Overview caption with no
   error, and clicking Generar actually renders — 4839.4 kWh solar, 97.1% independence,
   81/100 health, 80/80 days, over 3 monthly buckets — with no console errors beyond the
   same benign health-check-probe 404s seen in earlier steps (unrelated, self-correcting).
9. **Done (2026-08-15) for everything Phase B V1 actually ships** — step 5 is skipped, not
   deferred-and-pending, so there's no further block on calling this pass complete. Every
   step that landed (1-4, 6-8) got a consolidated final check on top of the per-step
   verification already recorded above:
   - **`monitoring` re-confirmed byte-for-byte unchanged** with all of steps 6-8's changes
     applied, not just steps 1-4's (53058 bytes, identical to §2 and §4's checks) — the
     narrative branch, the UI changes, and the copy-genericization check all touch code
     shared with `vrm`, so this needed re-running after they landed, not just once.
   - **The true 183-day max cap, against real (sparse) data** rather than the synthetic
     full-coverage data used in earlier per-step checks: `vista-atenas-lp-m3` only has 40
     real days, picked across a 183-day window — 7 buckets, 4 of them entirely empty (0
     days, `pv=0`), `missingDays=143`. Confirms the "don't silently show a partial period as
     a full one" rule holds at the real end of the range real customer data will actually
     produce, not an idealized one.
   - **Empty-bucket rendering, checked directly against the SVG output**: all three
     bucket-driven charts (`bar_chart_svg`, `soc_chart_svg`, `health_grid_trend_svg`)
     confirmed to contain no literal `"None"`/`"nan"` leaking into the rendered SVG text for
     those empty buckets — missing `min_soc`/`max_soc`/`healthScore` correctly stay `None`
     and get skipped by the drawing code, not coerced into a fabricated zero or a visible
     Python `None`.
   - **Both schemas re-confirmed live in the browser**, not just via script: `vrm` origin
     generates the Overview report end to end (already recorded in step 8); `monitoring`
     origin, switched to for the first time this session, correctly shows its unchanged
     fixed "Semana que termina el" picker (no Overview UI exposed there — by design, since
     `monitoring` can never set `is_overview`) and renders matching §11's original reference
     figures exactly (429.0 kWh solar, 100.0% independence, 84/100 health).

   **One item still open, gated by data age rather than by anything left to build**:
   cross-checking a bucketed period's sum against the same period's already-validated
   Detallado total needs a real site with enough history that an Overview render and a
   Detallado render actually overlap on real dates — not yet available for any real site
   (same constraint that ruled out step 5's option (a)). Worth doing whenever a site
   accumulates enough history for it, but nothing about Phase B V1 is waiting on it.

**Phase B V1 status: done.** Steps 1-4 and 6-9 shipped and verified; step 5 deliberately
skipped (decided with the user 2026-08-15, see step 5 above for the full reasoning and the
trigger for revisiting it).

## 23. Fixes from reviewing a real generated report (2026-08-16)

The user reviewed an actual Overview-mode PDF (`El Encino (Casona)`, 2026-05-10 → 07-29, 81
days) and found two real issues plus asked a question, all against real output rather than
against the plan.

### The daily bar/SOC chart text was wrong in Overview mode — a real bug, not a nitpick

`sectionDaily`/`subDaily`/`subSocChart` all still said "daily"/"diario" even when the chart
they label was drawing one bar per **month**, not per day. Root cause: `_PERIOD_OVERRIDES`
(Phase A, §21) already generalizes this wording once, but only for the case it was built
for — a Detallado custom range that's still day-by-day, just not exactly 7 days, where
"daily" stays completely accurate. Phase B's Overview mode (step 3) started drawing monthly
buckets under that same still-"daily" label and nothing caught it, because every isolated
test checked the *numbers* each chart produced, never re-read the *copy* sitting next to
them — exactly the kind of thing that only surfaces once someone looks at a real rendered
page rather than an assertion.

Fixed with a second override tier, `_OVERVIEW_OVERRIDES` in `report_i18n.py`, layered on top
of `_PERIOD_OVERRIDES` only when `is_overview=True`: `sectionDaily` → "Solar vs. consumption"
/ "Solar vs. consumo" (drops "daily" entirely), `subDaily` and `subSocChart` reworded around
"segment"/"tramo" instead of "day"/"día". `report_i18n.get()` gained an `is_overview`
parameter; `weekly_report.py`'s call site now passes `window["is_overview"]`. Verified:
Overview mode (81 days) no longer says "diario" anywhere in that block; a Detallado custom
range (checked at 20 days) still says "diaria"/"cada día" — confirming the fix is scoped to
the actual bucketed case and didn't regress the case Phase A already got right.

### How alarm episodes are actually counted (the user asked, not a bug)

Two layers, both already covered by earlier build notes (§8, §12) but worth restating
together since the report just shows one number with no explanation:

1. **Only two alarm categories are scored at all** — `low_battery` and `overload`
   (`victron/vrm_csv.py: ALARM_CATEGORIES`), deliberately mirroring exactly what Node-RED's
   live Cerbo path emits. The CSV export contains ten more alarm signals (DC ripple,
   temperature, the whole Battery Monitor set — `UNSCORED_ALARM_SIGNALS`), detected and
   surfaced as an ingestion warning but never counted here — scoring them would make a
   CSV-ingested site look systematically worse than an identically-behaving Cerbo site for
   no real difference in what happened, since `count_alarm_episodes()` runs one shared
   in-episode flag over whatever rows exist for the day.
2. **An episode is a WARNING→CLEARED transition, not a duration.** For each scored category,
   `victron/vrm_csv.py: alarm_events()` watches the raw 1-minute signal for edges (not-active
   → active = `WARNING`, active → not-active = `CLEARED`) and emits one row per transition. A
   Postgres function, `count_alarm_episodes(site_id, date)` (identical logic in
   `monitoring`/migration 005 and `vrm`/migration 012, differing only in which timezone
   buckets "date"), walks a day's events in time order and increments a counter each time the
   flag flips from clear to active — so a single alarm that stays active for six hours is
   **one** episode, and the same category re-triggering later the same day is a **second**
   one. This count becomes `daily_health.alarms_count`; "Total de Episodios de Alarma" in the
   report is just the sum of that column over the picked period.

Net effect on reading the number: 41 episodes means 41 distinct low-battery/overload
warning-to-clear cycles across the period, not 41 minutes or 41 separate alarm *types* — and
it's a floor, not a ceiling, since ten other real alarm signals aren't in that count at all.

### Chart removed after review

`health_grid_trend_svg()` (step 4's health/grid-independence/battery-cycling block) — the
user hadn't asked to see it and, seeing the real output, didn't want it. Removed
completely: the function, its template block and render call site, and the three i18n keys
that existed only for it (`healthGridTrend`, `subHealthGridTrend`, `cyclesAbbr`). The data it
was built on (`overviewTrend`, `bucket_health_days()`, `bucket_days()`'s grid/discharge sums)
stayed in place — step 6's narrative prompt still consumes `overviewTrend` via
`_bucket_trend_lines()`, so deleting those would have silently degraded the narrative too.
Verified: no leftover references anywhere in `victron/`/`pages/`/`database/`, syntax-checked,
and a real report regenerated for the same site/range that surfaced the original issues —
chart is gone, bar/SOC text no longer says "diario", narrative unaffected.

## 24. Report-sections preview in the Reporte tab (2026-08-16)

`tab_report()` (`pages/06_vrm_monitor.py`) now shows a card grid — one card per report
section, icon + title + one-line description — before the operator clicks Generar, so
they see what the report will actually contain (and how it reads) before spending a
generation.

**Reuses `report_i18n.get()`'s exact strings rather than a second, hand-written
description set.** Every card's title/description is `t["sectionX"]`/`t["subX"]` pulled
from the same dict `build_report_data()` feeds the PDF, called with the same
`(lang, num_days, is_overview)` the actual render will use. This was a deliberate choice
after §23's bug (a description drifting out of sync with what the report actually shows) —
duplicating the copy here would reintroduce exactly that risk the moment either one changes
without the other. Confirmed live: the 7-day pick shows "Weekly Health Score" / "Daily solar
vs. consumption" (unmodified base strings); switching to an 80-day Overview pick updates
the same cards to "Health Score" / "Solar vs. consumption" with the segment-worded
description from §23's fix, while "4-week solar trend" correctly stays unchanged in both —
it's always a fixed weekly view regardless of mode, and the preview reflects that faithfully
because it's reading the same dict, not inferring it.

Which cards appear also reacts to real state, not a fixed list: `system_type` (`has_batt`/
`has_grid`, matching `weekly_report.py`'s own gating) hides Battery Health/SOC for
`grid_zero` sites and Grid Quality for `off_grid` ones; the Narrativa/Clima "Incluir"
checkboxes show or hide those two cards. The KPI summary row and the AI-narrative card use
short original copy (no `sub*` key exists for either in the PDF itself — the KPI row is
just numbers, the narrative is a dynamic AI paragraph), everything else is a direct reuse.

Verified live for both schemas: `vrm` origin at 7 days and at 80 days (Overview), and
`monitoring` origin (always the fixed 7-day wording, confirmed unaffected). No console
errors beyond the same benign health-check-probe 404s seen throughout this document.

## 25. Company logo in the report footer (2026-08-16)

Small logo added to the bottom-right corner of the weekly report footer, both schemas —
one change, since `monitoring` and `vrm` render through the exact same
`weekly_report.py`/`weekly_report.html` pipeline.

Reused `proposals/assets/assets.py: get_logo_b64()` (already existed, already used by the
proposal PDFs) rather than adding a second base64-encoding path — one shared source for
the logo asset, so the two PDF families can't drift apart on which file or encoding they
embed. `weekly_report.py: render_html()` now passes `logo_b64=get_logo_b64()` into the
Jinja context; the template's single `.ftr` block (there's only one footer div in this
template, at the true end of the document — see §the template itself, no per-page footer
exists) gained a small `<img class="ftr-logo">` beside the existing "Page 1"/"Página 1"
text, 13px tall.

Verified by rendering both a `monitoring` (7-day) and a `vrm` (Overview, 80-day) report to
PNG via `pdftoppm` and inspecting the footer directly — logo appears small, clean, bottom
right, in both.

## 26. Apps Script retirement, scoped — scheduling + email + PDF archiving only (2026-08-16)

Scope, per the user: port the three of §12's four remaining Apps Script jobs that aren't
the Sheets backup writer. That writer (`doPost` → `sheet.appendRow()`) stays on Apps Script
untouched, and — found while reading the code, not assumed — `saveDriveBackup()`, which
saves a raw JSON dump of every daily payload to Drive, is called from the *same* `doPost`
handler right after the Sheets row write (`Victron_Events_App_Script_v1p7.js:121`), not from
`weeklyReport()`. It's part of the Sheets-backup job, not the "Drive archiving" being
retired here, so it stays too — worth being explicit about so it isn't accidentally cut
later under the "Drive archiving" heading.

**Scope is `monitoring` only, inherited from what already exists.** `runAllWeeklyReports()`
only ever iterates `monitoring.sites` — Apps Script's scheduler has never touched `vrm`.
`vrm` reports stay exactly what the plan already decided for V1 (§5): manual, on-demand,
from the Streamlit Reporte tab. Nothing here changes that.

### 1. PDF archiving → Supabase Storage (no open decision, direct port)

`weeklyReport()` (lines 994-1012) saves the rendered PDF to Drive under
`weekly-reports/{siteSlug}/`. Replace with `proposals/generator.py:upload_pdf()`'s already-
working pattern (`client.storage.from_("solar-tool").upload(...)`, already used for proposal
PDFs, same Supabase project) rather than standing up a second storage mechanism. New
function, `victron/archive.py: upload_report_pdf(pdf_bytes, site_id, end_str) -> str`,
path `vrm-monitor-reports/{site_id}/{end_str}.pdf` — mirrors the existing `proposals/
{proposal_id}/...` convention, in the same `solar-tool` bucket rather than a new one (no new
bucket to create/configure).

### 2. Email delivery — needs a provider decision, not resolved here

`MailApp` → a transactional provider, per the arch doc's own §6 recommendation (Postmark/
Resend/SES) — Gmail/Workspace send quotas and the total lack of delivery observability
(bounces, retries) are exactly the failure mode an *unattended* scheduled job can't afford,
unlike the interactive Streamlit path where a human is watching. This needs an account
signup + API key, so it's asked of the user separately (see below) rather than picked here.

Recipient resolution ports as-is: `get_report_email` is already a Postgres RPC
(`fetchReportEmail_`, `Victron_Events_App_Script_v1p7.js:1726`) — callable directly via
`get_client().schema("monitoring").rpc("get_report_email", {"p_site_id": site_id}).execute()`
(same `.schema().rpc()` pattern already used in `tools/run_migration_012.py`), falling back
to `proyectos@paulyco.com` (today's `CONFIG.reportEmail`) when a site has no linked client.

`buildEmailHtml()` (`Victron_Events_App_Script_v1p7.js:1588`, ~150 lines) ports to a new
`victron/templates/weekly_report_email.html` — table-layout, inline-styled, no `data:` URIs
(the original's own comment: "Gmail strips data: URIs," hence the text-based logo fallback
there — worth keeping that constraint even though the PDF footer now embeds the logo as a
`data:` URI directly, since email and PDF are different rendering environments with
different rules). The "surplus" feel-good line and the narrative-highlight extraction
(skip the first sentence, prefer sentences 2-3) port as straight logic, not net-new design.

### 3. Scheduling — needs a mechanism decision, not resolved here

`createWeeklyReportTrigger()` runs inside Google's infrastructure, so it's always on
regardless of any particular machine's state. This app currently has **no deployed server**
— it runs locally via `.venv/bin/python3.9 -m streamlit run app.py` (this doc's own §
recreations of `scripts/start_dimensionador.sh` earlier this session). A naive port to a
local `cron`/`launchd` job would be a real reliability regression from today: if the Mac is
asleep or off Monday morning, the report silently never sends, and nothing here has anyone
watching for that. Two options exist that don't have that dependency, asked of the user
below rather than picked unilaterally since it's an infrastructure choice, not a technical
one:
- A GitHub Actions scheduled workflow (`cron:` trigger) running a Python script against this
  same repo — no new hosting account, matches the project's existing GitHub-centric
  workflow, secrets go in the repo's Actions secrets.
- A Supabase Edge Function + `pg_cron`, calling a small webhook — stays inside the Supabase
  project already used for everything else here, but the function itself would be
  TypeScript/Deno, not Python, so none of `victron/weekly_report.py`'s logic runs there
  directly (it would need to be a thin trigger calling out to something else that runs the
  actual Python — likely the GitHub Actions workflow via its `repository_dispatch` API, or a
  small always-on Python endpoint that doesn't exist yet).

New script either way: `tools/run_weekly_reports.py`, porting `runAllWeeklyReports()`'s
fan-out (every `monitoring.sites` row where `active = true`, one site's failure logged and
skipped rather than blocking the rest — same try/except-continue shape).

### Recommended addition beyond pure Apps-Script parity: a report log

Not in the original Apps Script (which relies on `Logger.log()` — invisible once the
execution finishes) and not literally asked for, but flagged because §21's ingestion path
already draws this exact lesson: an unattended process needs somewhere to say what happened,
or a failure is invisible until a customer asks why they didn't get a report. Recommend
`monitoring.report_log` (new migration): `id, site_id, sent_at, pdf_bytes, storage_path,
recipient_email, email_status, error`. Cheap now (mirrors `vrm.ingestion_log`'s own
reasoning from migration 012), and it's the only thing that will answer "why didn't Tuesday's
run send" without grepping GitHub Actions logs by hand.

### Build order

1. Storage archiving (`victron/archive.py`) — self-contained, no new accounts, do first.
2. `report_log` migration — cheap, do alongside step 3 so testing has visibility from the
   start rather than bolted on after something already broke silently.
3. Email: port `buildEmailHtml()` → Jinja2 template, wire the chosen provider's send call,
   recipient resolution via `get_report_email`. Blocked on the provider decision below.
4. `tools/run_weekly_reports.py` — orchestrates 1-3 per active `monitoring` site, logs to
   `report_log`, same per-site failure isolation as `runAllWeeklyReports()`.
5. Wire the scheduling trigger (whichever mechanism is chosen) to call step 4's script.
   Blocked on the mechanism decision below.
6. Validate against a real Monday run: recipient, subject, attachment, archived copy, and a
   `report_log` row all match what Apps Script would have produced; confirm one site's
   failure doesn't block the others (deliberately break one site's data mid-test).
7. Cutover: disable `createWeeklyReportTrigger()`'s trigger only — `doPost` (Sheets write +
   `saveDriveBackup()`) stays running exactly as it does today, untouched by this work.

### Two decisions — locked with the user (2026-08-16)

Both were new-account/infrastructure choices, not technical determinations this plan
could resolve by reading code the way §22/§23's earlier open items were:
1. **Email provider: Resend** (not Postmark or SES).
2. **Scheduling mechanism: GitHub Actions** scheduled workflow (not a Supabase Edge
   Function + `pg_cron`).

Also agreed: the recommended `monitoring.report_log` table (§ above) — build it.

This section is now a locked scope, not an open one. Cross-referenced into the top-level
project docs the same day: `PHASES.md` (new Phase 12), `REQUIREMENTS.md` (v3.8, Section
4.5), `CONTEXT.md` (Victron Monitor integration section — also corrects that section's
stale tariff-savings-via-Apps-Script note, superseded since §15's real numbers shipped in
the Python report instead).
