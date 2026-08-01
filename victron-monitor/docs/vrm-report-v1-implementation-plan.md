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
