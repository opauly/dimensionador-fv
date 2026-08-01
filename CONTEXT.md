# Pauly&Co Solar Tool — Project Context

> **Living document.** Update at the end of every phase. A new Claude session should read
> REQUIREMENTS.md, PHASES.md, and this file — in that order — before writing any code.

---

## Current state

| Item | Value |
|---|---|
| **Phase completed** | Phase 5 full (Off-Grid + Hybrid wizard, PDF templates) + Phase 4 full + Phase 3 UX polish (Cotizaciones directed-flow, per-version PDF) + Phase 7 partial (Admin equipment catalog, ARESEP tariff xlsx parser, Clientes/Prospectos tab) |
| **Phase next** | Phase 6 — Projects Module |
| **Branch** | main |
| **Last commit** | see `git log` |
| **Working tree** | Clean |
| **GitHub remote** | `https://github.com/opauly/dimensionador-fv` (added 2026-07-09) |

---

## Environment

| Item | Value |
|---|---|
| **Python** | 3.9.22 via `.venv/` (Homebrew) — always use `.venv/bin/python` |
| **Activate** | `source .venv/bin/activate` |
| **Run app** | `streamlit run app.py` |
| **Run seed** | `python -m database.seed.seed_tariffs` |

**Why .venv and not conda/system Python:**  
macOS has two broken Python installs: conda base is 3.8.5 x86_64 (too old for supabase 2.x),
system Python 3.11 has an arm64/x86_64 cffi mismatch. The Homebrew Python 3.9 at
`/usr/local/Cellar/python@3.9/3.9.22_1` is clean. `.venv` was created from it.

**Python 3.9 compat note:**  
All files use `from __future__ import annotations` at the top so that `X | None` union
type hints (Python 3.10+ syntax) work at runtime on 3.9.

---

## Supabase

- **Project URL:** `https://qqorjwnlawhlmrmxxgdb.supabase.co`
- **Credentials:** in `.env` (gitignored) — copy from `.env.example` if `.env` is missing
- **Schema:** `database/schema.sql` — run in Supabase SQL Editor for fresh installs
- **Seeded:** 8 distributors + 2026 T-RE tariff tiers, 4 panels, 5 inverters, 2 batteries,
  2 charge controllers, 2 monitoring devices

---

## Victron Monitor integration (added 2026-07-13)

`victron-monitor/` at the repo root is a separate product (Victron fleet telemetry via
Node-RED + Google Apps Script) that was migrated in from a standalone repo
(`opauly/victron-monitor`) to share this project's Supabase instance and consolidate
infrastructure. Full details: [`victron-monitor/README.md`](victron-monitor/README.md).

- Lives in its own Postgres schema, **`monitoring`**, alongside this tool's `public` schema
  in the same Supabase project — not a separate project/database.
- Schema source of truth: [`database/migrations/004_add_monitoring_schema.sql`](database/migrations/004_add_monitoring_schema.sql).
  `victron-monitor/sql/schema.sql` is a portable reference copy kept manually in sync.
- No RLS on `monitoring` tables (same pattern as `public`) — access via schema-level
  `GRANT`s to `anon`/`authenticated`/`service_role`, since Supabase doesn't auto-grant
  non-`public` schemas the way it does `public`.
- `monitoring` must stay checked under Settings → API → Data API → Exposed schemas.
  PostgREST requests need a `Content-Profile`/`Accept-Profile: monitoring` header —
  it doesn't route by URL path.
- Node-RED (running on physical Cerbo GX field hardware) writes with the shared
  project's **anon** key, deliberately not `service_role`, to limit blast radius if the
  device or flow file is ever exposed.
- **The anon key is NOT hardcoded in the flow.** It's stored as a Node-RED Global
  Environment Variable (User Settings → Environment) with type `credential`, which
  Node-RED encrypts at rest and excludes from flow exports. The `Project Config`
  function node reads it via `env.get('SUPABASE_ANON_KEY')`. This was a deliberate fix
  after an earlier commit briefly had the literal key in `node-red/victron_monitor_v1p6.json`
  (caught before push by the auto-mode credential-leak classifier, never reached GitHub —
  fixed by amending before the first successful push). Do not reintroduce a literal key
  into any node's function source.
- Live/current versions: `node-red/victron_monitor_v1p8.json` and
  `apps-script/Victron_Events_App_Script_v1p7.js`.
- Old standalone repo `opauly/victron-monitor` is **archived** (2026-07-13) — this repo
  is now the single source of truth for Victron Monitor.
- **Known gap:** no RLS on `monitoring` — one shared `anon` key can read/write/delete
  all sites' data. Fine for the current internally-owned sites; must be fixed (per-site
  RLS + per-device JWT provisioning) before onboarding paying external customers.
  Planned in PHASES.md as a future phase.
- **Planned — weekly-report tariff savings (not built yet):** the weekly PDF + email
  will show an **estimated savings** figure. Agreed approach:
  - Port the CR bill formula (`calculations/tariff_calculator.py` → `estimate_bill_crc`)
    to JS **inside the Apps Script** — the formula shape is duplicated, but the *rates*
    stay single-sourced in Supabase and are what actually change.
  - Read tariffs **live from the shared Supabase `public` tables** (`distributors` →
    `tariff_types` → `tariff_tiers`, mirroring `database/tariffs_db.py::get_tariff_info`)
    via PostgREST + `UrlFetchApp`. `public` is PostgREST's default profile, so no
    `Content-Profile` header (unlike the `monitoring` writes).
  - Define each site's **electric company** via the Node-RED Project Config payload
    (`distributor` abbreviation + `tariff_code`), landing in the `DailySummary` sheet and
    read like `pv_kwp` — matching the existing "site config comes from Node-RED" pattern.
  - Savings model (kept deliberately simple): `(weekly load − weekly grid import) ×
    effective ₡/kWh`, where the effective rate = `estimate_bill_crc(monthly-equivalent
    kWh) / kWh`.
  - **Prerequisites before it can activate:** `SUPABASE_URL` + `SUPABASE_ANON_KEY` added
    to the Apps Script Script Properties (the anon key currently lives only in Node-RED);
    anon `SELECT` access to the public tariff tables; tariffs seeded for the relevant
    distributors. Until then a "coming soon" placeholder ships in both the PDF (below the
    4-week trend) and the email.
- **Weekly report migrated from Google Sheets to Supabase (2026-07-17).** Confirmed by
  running both versions for the same site/week and comparing output — the Sheets version
  had two real bugs, not just noise:
  1. `weeklyReport()`'s row filter only excluded `event === "TEST_DAILY_SUMMARY"`, not
     `dump_type`, so MANUAL/TEST rows written during testing got summed into the weekly
     totals — inflated PV/load numbers.
  2. Battery cycles used `dailyRows[0].battery_usable_kwh || 1` — when that per-row Sheets
     field was blank, it silently divided discharge kWh by 1 instead of the real ~41 kWh
     capacity, producing nonsense figures (e.g. "144.32 cyc" in one comparison run).
  The Supabase version doesn't have either bug: it filters `dump_type=eq.AUTO` server-side,
  and sources `battery_usable_kwh` from `monitoring.sites` (one reliable row) instead of a
  per-row Sheets column. Live Apps Script promoted to this version; old Sheets-reading code
  removed. Node-RED still writes to Sheets as a human-browsable backup — only the *report
  reader* changed.
  - **Trigger gotcha when promoting:** Apps Script time-driven triggers always call their
    function with zero arguments. `weeklyReport()` now requires `siteId`, so the old
    Monday trigger (pointing at bare `weeklyReport`) had to be deleted and reinstalled
    against the new `runAllWeeklyReports()` fan-out wrapper — otherwise the schedule
    would fail silently every week with no email sent.
  - **Duplicating an Apps Script project ≠ safe URL swap.** `doPost` and the Sheets-writing
    functions use `SpreadsheetApp.getActiveSpreadsheet()`, which only works if the script
    is container-bound to that specific Sheet. "File → Make a copy" from the script editor
    produces a *standalone*, unbound copy — repointing the live Web App URL at a duplicate
    project would silently break every Node-RED write, not just the report. Always edit
    code in place in the original (bound) project instead.
- **Client email routing (2026-07-17).** `monitoring.sites.client_id` (migration 007) links
  a site to a `public.clients` row. The weekly report's recipient is resolved via
  `monitoring.get_report_email(site_id)` — a narrow `SECURITY DEFINER` RPC that returns only
  the linked client's email, falling back to `CONFIG.reportEmail` (internal) if unlinked.
  Deliberately *not* a direct `GRANT SELECT` on `clients` to `anon` — that would let anyone
  holding the (field-hardware-resident) anon key enumerate the entire client list's
  names/emails/phones instead of just answering "what's the email for this one site_id."
- **Per-site health thresholds actually wired everywhere now (2026-07-17).** Found and fixed
  a gap: `weeklyReport()`'s battery-stress label was still reading the hardcoded Apps Script
  `CONFIG.defaultHealthThresholds` unconditionally, while the Postgres-computed
  `daily_health.health_score` already correctly used per-site thresholds — the two could
  disagree. Fixed to merge `siteRow.health_thresholds` over the default, matching the
  pattern `appendDailyHealth()` already used. `CONFIG.defaultHealthThresholds` is
  deliberately *not* deleted — it's the last-resort fallback if a Supabase fetch fails
  mid-session; removing it would make every threshold comparison silently evaluate `x >
  undefined` = false, reporting perfect health regardless of real conditions. Same
  reasoning applied to Node-RED's `Project Config`: `healthThresholds` and the system-specs
  block (`batteryUsableKWh`, `pvKwp`, `latitude`, `longitude`) were removed from the
  hardcoded local object entirely (they were already being overridden by Merge Site
  Config in the normal path) — `supabaseUrl` also moved to a second Global Environment
  Variable (`SUPABASE_URL`, type `string` — not a secret, so no `credential` type needed).
- **`system_type` column added to `monitoring.sites`** (migration 009) —
  `grid_zero` | `off_grid` | `hybrid`, same vocabulary as `public.proposals.system_type`.
  Defaults to `hybrid` (matches every current site). Threaded through into the weekly
  report's data object (`d.systemType`) with `TODO(system_type)` comments marking the
  exact KPI-card and info-block locations that would need conditional layout for
  off-grid/grid-zero sites — **not implemented yet**. The KPI/info-block layout is
  hand-tuned pixel-math SVG (fixed 4-column KPI row, fixed 2-column info blocks), so
  hiding a card means recomputing column widths, not just wrapping in `if()`. Deliberately
  deferred until there's a real off-grid or grid-zero site to verify the reflow against —
  building untested layout math blind was judged not worth the risk.
- **Battery-cycling threshold recalibrated (migration 010).** Old default
  (`batteryCyclesHigh: 1.5`/week) was based on nothing real — Hybrid/Off-Grid systems are
  *designed* to cycle the battery ~daily (~7/week) as normal self-consumption behavior, so
  the old default flagged every correctly-functioning system as "High stress" permanently.
  New default (10.0 high / 7.0 mid per week) only flags genuinely abnormal cycling
  (sustained >1.5–2x/day), based on Pylontech's LFP cycle-life rating (~6,000 cycles @ 80%
  DOD ≈ 15+ years at daily cycling — well past typical system lifetime) and the fact that
  depth-of-discharge (already tracked as "Lowest SOC of the Week") is a better stress
  signal than raw cycle count. Applies identically to Hybrid and Off-Grid — both cycle
  daily by design, no per-`system_type` value needed for this specific threshold. Where
  `system_type` *does* need to change behavior: a future no-battery Grid Zero site
  shouldn't be scored on battery cycling **at all** (not a different number — no
  applicable metric). Marked as a `TODO(system_type)` inline in
  `monitoring.compute_daily_health()` and tracked in PHASES.md's Phase 9 section, alongside
  the Apps Script report TODOs above — same deferral reasoning (no real grid_zero site to
  verify against yet).
- **[ARCHITECTURE.md](ARCHITECTURE.md) added (2026-07-17)** — root-level system diagram
  (Mermaid) covering full wiring across both products: Cerbo GX/Node-RED, Apps Script,
  Sheets, Gmail, Drive, Supabase (`public` + `monitoring`), and the Streamlit app, plus a
  Supabase schema ER diagram and the prospect→client lifecycle state diagram.

---

## Clients vs. Prospects (added 2026-07-17)

Business rule from the user: a "client" is someone who has actually bought a project.
Someone who's only been quoted and hasn't bought is a "prospect" — kept separate so the
client list doesn't fill up with people who never converted. Full spec in
[REQUIREMENTS.md §4.6](REQUIREMENTS.md). Implementation summary:

- **Migration 008** (`database/migrations/008_prospects.sql`): new `prospects` table
  (same shape as `clients` + `empresa` — also fixed a real bug where `clients.empresa`
  never existed as a column despite `clients_db.py` assuming it did, silently dropping the
  wizard's "Empresa" field on every save). `proposals.prospect_id` added alongside the
  existing `client_id`, `CHECK`-constrained mutually exclusive. `promote_prospect_to_client()`
  — atomic: copies the prospect into `clients`, repoints every proposal referencing them,
  deletes the prospect row.
- **Wizard change** (`pages/02_new_proposal.py`): client-step search still queries
  `clients` only (per explicit decision — a repeat customer is found by name; a genuinely
  new prospect creating a duplicate-looking prospect row on a second quote is an accepted
  tradeoff, prospects aren't meant to be a curated list). No search match → `create_prospect()`
  instead of `upsert_client()`.
- **Promotion trigger** (`pages/01_proposals.py`, the `next_st === "won"` handler — already
  the exact right hook point, confirmed the Projects module (`pages/03_projects.py`) is
  still an unbuilt 6-line stub so there was nothing else to wire around): marking a
  proposal won calls `promote_prospect()` if `prospect_id` is set. Automatic only — no
  manual promote button, by explicit choice, to keep exactly one trigger point for the
  state transition.
- **Admin → Clientes tab** (`pages/05_admin.py`): list/add/edit/delete clients, checkbox
  linker to `monitoring.sites` (via new `database/monitoring_sites_db.py`, using
  `get_client().schema('monitoring')` — confirmed supported by the installed `supabase-py`
  2.31.0, zero new grants needed since `service_role` already has full `monitoring` access).
  Read-only Prospectos sub-tab for visibility, no actions (matches automatic-only promotion).

---

## Git behavior on this machine

`git-lfs` is configured globally but not installed. This causes `git add` on multiple
files at once and `git show` to hang. **Workarounds:**

- Stage files one at a time or in small batches (5–10 files per `git add` call)
- Use `timeout 90 git commit` — commits take ~20–30s (macOS scanning new objects)
- `git log --oneline` is always fast; `git show --stat` hangs — avoid it

**GitHub remote:** Added 2026-07-09. `origin` points to `https://github.com/opauly/dimensionador-fv.git`.
Push with `git push` (tracking branch already configured for `main`).

---

## Key decisions (Phase 0)

| Decision | What was decided | Why |
|---|---|---|
| Python env | `.venv` with Homebrew Python 3.9 | Only clean Python on this machine |
| Seed idempotency | `tariff_types` uses query-first then insert/update | No unique constraint on (distributor_id, code) in live DB; schema.sql updated for future |
| Type hints | `from __future__ import annotations` in all files | Python 3.9 doesn't support `X \| None` at runtime |
| App entry | `app.py` = home dashboard, `pages/` = feature pages | Streamlit multi-page standard |

---

## Validation reference numbers

These are the ground-truth numbers to validate against. Every calculation phase must
reproduce them exactly.

### Grid Zero — María José Castro

| Metric | Value |
|---|---|
| Avg consumption | 1,475 kWh/month |
| Avg bill | ₡157,874/month |
| System generation | 1,262 kWh/month |
| New consumption | 521 kWh/month |
| New bill | ₡51,681/month |
| Monthly savings | ₡106,192 |
| Year 1 savings | $2,798 USD |
| 25-year savings | $127,873 USD |
| IRR | 22.92% |
| ROI | 5.48 years |
| Total cost | $18,110 USD |

### Off-Grid — Jorge Ramírez

| Metric | Value |
|---|---|
| Panels | 8 × JA Solar 620W |
| Inverter | 1 × Victron MultiPlus 5000VA |
| Batteries | 2 × Pylontech US5000C |
| Charge controller | 1 × Victron MPPT 250/100 |
| System size | 5.0 kW |
| Array area | 16 m² |
| Daily generation | 6.38 kWh/day |
| Battery at 10h | 9.60 kWh |
| Discharge | 66.46% |
| Total cost | $10,320 USD |
| Cost per Wp | $2.08/Wp |

---

## Scaffold status

All modules exist as stubs with `raise NotImplementedError("Phase N")`.
The phase tag tells you when each function gets implemented.

| Module | Phase | Notes |
|---|---|---|
| `proposals/generator.py` | ✅ done | `generate_pdf()` + `upload_pdf()` implemented; `build_from_wizard_blob()` accepts optional `version_date` (DD/MM/YYYY) for historical PDF dates |
| `proposals/templates/grid_zero_es.html` | ✅ done | Spanish — 1-page, pixel-accurate |
| `proposals/templates/grid_zero_en.html` | ✅ done | English — 1-page, full translation |
| `wizard/state.py` | ✅ done | Auto-save, load_draft, company/bank defaults |
| `wizard/common.py` | ✅ done | Steps 1–3: system type, client, site+PVGIS |
| `wizard/grid_zero.py` | ✅ done | Steps 4–8: utility, consumption, equipment, costs, review |
| `calculations/tariffs.py` | ✅ done | Block-tier bill calculator, IVA threshold, bomberos |
| `calculations/sizing_grid_zero.py` | ✅ done | System kW, monthly generation, savings table, averages |
| `calculations/pvgis.py` | ✅ done | PVGIS API call + Supabase cache + CR geocode lookup table |
| `calculations/mppt.py` | ✅ done | Explores all valid (series × parallel) combos; A/B/C scenarios; manual `check_design()` |
| `calculations/financials.py` | ✅ done | IRR + ROI implemented |
| `database/proposals_db.py` | ✅ done | Proposal + version CRUD; `mark_version_sent()` now also sets `proposals.status = "active"` |
| `database/equipment_db.py` | ✅ done | Full CRUD: `upsert_panel`, `delete_panel`, `upsert_inverter`, `delete_inverter` |
| `database/tariffs_db.py` | ✅ done | Read functions for Phase 2 |
| `database/clients_db.py` | ✅ done | New file: client search + upsert |
| `pages/01_proposals.py` | ✅ done | Proposals list + directed status flow + per-version PDF buttons (see Phase 3 UX polish below) |
| `pages/02_new_proposal.py` | ✅ done | Full 8-step wizard orchestrator |
| `calculations/bill_parser.py` | ✅ done | Bill PDF extraction + 12-month grid builder |
| `calculations/tariff_calculator.py` | ✅ done | CR tariff formula: fixed + tiered + bomberos + IVA |
| `calculations/tablero_parser.py` | ✅ done | Electrical panel schedule → loads list via Claude vision |
| `calculations/load_estimator.py` | ✅ done | Seasonal load estimation; `DEFAULT_LOADS` seeded; `estimate_loads_12_months_ai()` |
| `calculations/datasheet_parser.py` | ✅ done | AI panel + inverter spec extraction from PDF datasheets |
| `ai/proposal_writer.py` | 4 | Intro paragraph generation |
| `calculations/sizing_off_grid.py` | ✅ done | Battery bank, array, split-phase check — validated against Jorge Ramírez |
| `calculations/load_profile_off_grid.py` | ✅ done | 5-category load taxonomy, Open-Meteo climate integration — new in Phase 5, not in original scope |
| `wizard/off_grid.py` | ✅ done | Steps 4–8, verified live in browser incl. real PDF generation |
| `wizard/hybrid.py` | ✅ done | Thin wrapper over off_grid.py + grid-connection option + AC-coupling note |
| `proposals/templates/off_grid_{es,en}.html` | ✅ done | Built against real Jorge Ramírez reference PDF |
| `database/projects_db.py` | 6 | Project financial CRUD |
| `ai/tariff_updater.py` | 7 | CNFL PDF tariff refresh |

---

## Phase 1 — What was built

**Goal achieved:** pixel-accurate Grid Zero PDF from hardcoded data, both ES and EN, single page.

**Key files:**
- `proposals/templates/grid_zero_es.html` — Spanish Jinja2 template
- `proposals/templates/grid_zero_en.html` — English Jinja2 template
- `proposals/generator.py` — `generate_pdf(data, system_type, language) → bytes`
  - `MARIA_JOSE_DATA` dict = hardcoded test data (all reference numbers)
  - `_build_context()` formats all numbers and selects ES/EN strings
  - `upload_pdf()` implemented (Supabase Storage)
- `pages/02_new_proposal.py` — test buttons to generate ES/EN PDFs

**PDF structure (12 sections, top to bottom):**
1. Header — COTIZACIÓN + SOLAR (green underline) + logo
2. Client info table (6 rows when quote_number present: N° COTIZACIÓN first, then client fields)
3. Intro paragraph (Phase 4 will AI-generate; placeholder for now)
4. FACTURACIÓN MENSUAL PROMEDIO — "Cálculos esperados" label; 7-column table; Promedio row only
5. BENEFICIOS A CORTO / MEDIANO / LARGO PLAZO — 6-column table
6. DETALLES DE COSTOS — 4-column; "–" for non-qty items; bold Total row
7. DETALLES TÉCNICOS — 4-column mini table (56% width)
8. RESUMEN — 2-column mini table (30% width)
9. NOTAS ADICIONALES — 4 bullets + 2-column bank transfer table
10. DETALLES DE GARANTÍA — 3-column; "Paneles solares" rowspan=2
11. Más información — flex card: signature | name/title/license | phone/email/website
12. Footer — "Validez de la oferta: 15 días hábiles…" (centered, italic)

**CSS notes:** WeasyPrint 66 on macOS. Page margin 0.75cm top/bottom, 1.2cm sides.
Font Arial 7.5pt body, 7pt tables, 6.5pt bank table. Line-height 1.15.
Tighten all these if adding a new cost line item causes overflow.

**Validation passed:** ES and EN both render as 1 page. All María José Castro numbers match.

---

## Phase 2 — What was built

**Goal achieved:** Complete 8-step Grid Zero wizard with manual data entry. Real proposals possible.

**Key files (all implemented):**
- `wizard/state.py` — `autosave()`, `load_draft()`, `get_company_info()`, `get_bank_info()`
- `wizard/common.py` — Steps 1–3: system type + language, client with typeahead, site + PVGIS geocode
- `wizard/grid_zero.py` — Steps 4–8: utility (tariff picker), consumption table + chart, MPPT equipment selector, cost data_editor, review + PDF generation
- `calculations/pvgis.py` — PVGIS PVcalc API, Supabase app_settings cache, 40-city CR geocode lookup + Nominatim fallback
- `calculations/tariffs.py` — Block-rate bill calc, IVA threshold 280 kWh, bomberos 1.75%
- `calculations/sizing_grid_zero.py` — Monthly generation, avg billing diff, savings table
- `calculations/mppt.py` — 3-scenario MPPT validator centered on `0.85 × avg_kwh / avg_irradiance`
- `database/proposals_db.py` — Full CRUD: create, list, get, upsert_version, lock, versions, save_pdf_path
- `database/clients_db.py` — New: `search_clients()`, `upsert_client()`
- `pages/02_new_proposal.py` — Wizard orchestrator; auto-saves on each step; Phase 1 test buttons kept in expander

**MPPT validation:** JA Solar 620W + Fronius Primo 10.0-1 → Scenario B = 16 panels × 9.92 kW ✓

**Tariff formula note:** Seed rates are approximate (Phase 0 note: "verify before going live"). The formula is correct; numbers will match reference once actual ARESEP rates for the specific distributor are entered via Admin (Phase 7).

**Auto-save design:** Saves on each Next/Back navigation. True debounce not implemented (Streamlit limitation). Draft writes to `proposal_versions.data` JSONB. Draft is created in DB at Step 2 completion (once client name is known).

---

## Phase 3 — What was built

**Goal achieved:** Proposals list, version history, locking. The tool is a real workspace.

**Key files:**
- `pages/01_proposals.py` — Full proposals list with status filter, per-proposal expanders showing version history, action buttons per version (Continuar / PDF / Nueva versión / Marcar enviada), status dropdown that updates DB
- `database/proposals_db.py` — `lock_version(version_id, version_note=None)` updated to accept optional note
- `wizard/grid_zero.py` Step 8 — Lock section added at bottom: version note input + "Bloquear versión" button; post-lock shows "Nueva versión" / "Marcar enviada" / "Ir a cotizaciones" buttons; DB check on entry for already-locked versions
- `pages/02_new_proposal.py` — Dynamic title ("Editar cotización — [client name]" when resuming) + "← Cotizaciones" back button
- `app.py` — Dashboard counts for drafts + sent proposals now live from DB; Phase 3 marked complete

**Version lifecycle:**
- Unlocked version: wizard navigates here via "Continuar" from proposals list
- Locking: writes `locked=True` + `locked_at` + optional `version_note` to `proposal_versions`
- Nueva versión: `create_version(proposal_id, existing_data)` copies data into a new unlocked row, wizard resets to step 1

**Validation passed:**
- Created proposal with 2 versions, locked v1 with note, created v2 from v1 data, locked v2, marked v2 as sent
- Confirmed v1 total ($18,110) and note unchanged after v2 operations

**Bug fixed (post-Phase 3):**
- `wizard/grid_zero.py` step7_costs: `pd.NA != ""` raises ambiguous boolean when resuming a draft that saved `qty=None`. Fixed both `_row_total` and the updated_items loop to use `pd.isna()` first.

---

## Quote numbering (post-Phase 3)

**Nomenclature:** `PC-YYYY-NNN` (v1) / `PC-YYYY-NNN-vN` (v2+)
- `PC` = Pauly & Co, `YYYY` = year issued, `NNN` = 3-digit sequential per year
- v1 has no suffix (clean base for invoices); subsequent versions append `-v2`, `-v3`, etc.

**Key files:**
- `database/proposals_db.py` — `_next_quote_number(year)` assigns next int at creation; `format_quote_number(quote_number, created_at, version_number)` formats the display string
- `database/schema.sql` — `quote_number int` column on proposals
- `database/migrations/001_add_quote_number.sql` — ALTER + back-fill UPDATE (run once in Supabase SQL Editor)
- `tools/run_migration_001.py` — status checker; run with `python -m tools.run_migration_001`
- `proposals/templates/grid_zero_{es,en}.html` — quote number as first row of client info table (`N° COTIZACIÓN:` / `QUOTE NO.:`)
- `proposals/generator.py` — `quote_number` key passed into Jinja2 context
- `wizard/grid_zero.py` step8 — fetches `proposal.quote_number` from DB, formats with version suffix, passes to `generate_pdf()`
- `pages/01_proposals.py` — quote number shown in expander label and in each version row

**Migration status:** ✅ Applied. Existing proposals back-filled (PC-2026-001, PC-2026-002).

---

## Phase 4 — What was built (Step 5 Consumo AI enhancements)

**Goal achieved:** Step 5 is a full three-mode consumption input with AI assistance, seasonal estimation, and automatic Factura computation from actual DB tariff tiers.

### New files

**`calculations/bill_parser.py`**
- `parse_bill_pdf(pdf_bytes) → dict` — sends PDF as base64 document block to Claude Haiku; returns `{distributor, nise, history: [{month, year, kwh, bill_crc}]}`
- `build_12_month_grid(history, reference_year, location, tariff_info) → list[dict]` — only uses months with `kwh > 0` as known (zero = new service); calls `_estimate_missing_kwh()` for the rest; fills Factura via tariff_calculator
- `_estimate_missing_kwh(known, missing_months, location)` — Claude Haiku with Costa Rica dry/rainy season context; falls back to simple average on API error
- `MONTH_NAMES_ES` — module-level constant (not inside function) to avoid self-import errors

**`calculations/tariff_calculator.py`**
- `estimate_bill_crc(kwh, tariff_info) → float` — full CR formula: `fixed + tiered_energy + bomberos × (fixed + energy) + IVA (13% if kwh ≥ threshold)`
- `fill_bill_amounts(history, tariff_info)` — fills null/0 bill_crc from tariff; preserves real PDF values
- `tariff_info` dict shape: `{access_charge_crc, bomberos_pct, iva_threshold_kwh, tiers: [{from_kwh, to_kwh, rate_crc, is_fixed, sort_order}]}`

**`calculations/tablero_parser.py`**
- `parse_tablero(file_bytes, media_type) → list[dict]` — JPEG/PNG → image block; PDF → document block
- Prompt instructs Claude to skip "Prevista" circuits, skip 0 VA, assign h/día and días/mes by load type (fridge 24/30, A/C 8/20, microwave 0.5/30, etc.)
- Returns sanitized list: `[{Descripción, W, Und, h/día, días/mes}]`

### Updated files

**`calculations/load_estimator.py`** (previously a stub)
- `DEFAULT_LOADS` — 5 typical CR household loads (fridge, lighting, TV, A/C, washer)
- `kwh_from_loads(loads)` — sums `W × Und × h/día × días/mes / 1000`
- `estimate_loads_12_months_ai(loads, location)` — sends loads table to Claude Haiku with seasonal context; returns `[Jan, ..., Dec]`; falls back to `[nominal] × 12`
- `estimate_from_tablero(total_kva, demand_factor)` — 3-scenario estimator (unchanged structure)

**`wizard/grid_zero.py` Step 5** — fully restructured
- Three-mode radio: `Subir factura` / `Cargas instaladas` / `Manual`
- `_render_bill_section()` — file uploader (multi-file) → extract button → preview table → overwrite warning → "Aplicar" button → `build_12_month_grid()` → stores `w5_applied_source_meta` with date range label
- `_render_loads_section()` — tablero import expander (image/PDF) → `parse_tablero()` → editable loads table with versioned key (`w5_loads_{ver}`) → overwrite warning → "Aplicar a 12 meses →" → `estimate_loads_12_months_ai()` → Factura fill
- `step5_consumption()`:
  - Restores `w5_applied_months` and `w5_applied_source_meta` from saved draft on first load
  - Source badge (green pill) above table: `📊 Fuente: {label}` — updates when source changes or edits happen
  - Auto-recompute Factura on kWh change in **any** mode (not just manual): fetches `get_tariff_tiers(tariff_id)`, recomputes all 12 months, increments `w5_table_ver`, calls `st.rerun()`
  - Edits on top of bill/loads source update badge to `"{label} · editada"`
- Versioned data_editor key pattern: `key=f"w5_table_{table_ver}"` — incrementing forces fresh render with new data without losing unedited rows

**`wizard/grid_zero.py` Step 4** — now saves tariff rate fields to `wizard_utility`:
- `access_charge_crc`, `bomberos_pct`, `iva_threshold_kwh` passed from `selected_tariff` dict
- Avoids extra DB calls in Step 5; only `get_tariff_tiers(tariff_id)` fetched when needed

### Key bugs fixed

| Bug | Fix |
|---|---|
| Zero-kWh months (new service) counted as known data | `build_12_month_grid`: only index months with `kwh > 0` |
| Averaged months showed Factura = 0 | Pass `tariff_info` to `build_12_month_grid`; call `estimate_bill_crc` for all months |
| Infinite loop in manual auto-recompute | Change-detect with `old_kwh == new_kwh`; second rerun sees matching `df_init` and skips |
| Self-referential import in bill_parser | Move `MONTH_NAMES_ES` to module level before any function definitions |

### Session state keys (Step 5)

| Key | Purpose |
|---|---|
| `w5_applied_months` | `list[dict]` — 12 rows `{month, kwh, bill_crc}` currently in table |
| `w5_table_ver` | `int` — incremented to force data_editor reset with new data |
| `w5_applied_source_meta` | `{source: "bill"|"loads"|"manual", label: str}` — badge text |
| `w5_bill_history` | raw history list from `parse_bill_pdf()` |
| `w5_bill_meta` | `{distributor, nise}` from parsed bill |
| `w5_loads_data` | current loads table rows (set from tablero import or default) |
| `w5_loads_ver` | `int` — incremented when tablero import resets loads editor |

---

## Phase 4 — What was built (Step 6 Equipment + MPPT + Zero-Export Savings)

**Goal achieved:** Step 6 is a complete equipment selection and string design tool with realistic zero-export savings projections. Admin page has a full equipment catalog with AI datasheet ingestion.

### New files

**`calculations/datasheet_parser.py`**
- `parse_panel_datasheet(pdf_bytes) → list[dict]` — Claude Haiku document block; returns all power-class variants found in the PDF
- `parse_inverter_datasheet(pdf_bytes) → list[dict]` — same for inverters; returns all kW variants
- `_parse_list_response(response, label)` — JSON parse + list normalization; strips markdown fences
- Panel fields extracted: brand, model, wp, voc, vmp, isc, imp, temp_coeff_pmax, width_m, height_m (in meters), warranty_product_yr, warranty_power_yr
- Inverter fields extracted: brand, model, kw, type, vmax, vmin_mppt, vmax_mppt, imax_mppt (per tracker), mppt_channels, phase, output_v, warranty_yr

### Updated files

**`calculations/mppt.py`** — complete rewrite
- `_combo_metrics(ns, np_, panel, inverter) → dict` — shared helper; all metrics + violations list for any (series, parallel) pair
- `_make_description(scenario, combo, b_total, inverter) → str` — one-liner explaining why the scenario was chosen; covers primary reason, string architecture, voltage position within MPPT window
- `validate_string_design(panel, inverter, target_kw) → list[dict]` — explores ALL valid (ns, np_) combos; B = closest to target; A = largest with fewer panels; C = smallest with more panels; each result includes `description` field
- `check_design(panel, inverter, panels_per_string, n_strings) → dict` — validates a specific pair for manual mode; returns full metrics dict with `scenario="M"`

**`database/equipment_db.py`**
- Added `upsert_panel(data)`, `delete_panel(panel_id)`, `upsert_inverter(data)`, `delete_inverter(inverter_id)`

**`pages/05_admin.py`** — equipment catalog tab added
- `_panel_form(existing, prefill)` / `_inverter_form(existing, prefill)` — st.form with all fields; submits to upsert
- `_panels_section()` / `_inverters_section()` — datasheet upload expander → AI extract → variant selectbox (multi-model PDFs) → "Usar estos datos" → form pre-fill; card list with edit/delete (two-step confirm)
- `_equipment_catalog()` — tabs for panels + inverters
- Admin page now has 3 top-level tabs: Catálogo de equipos | Actualizar tarifas | Tarifas actuales

**`wizard/grid_zero.py`** Step 6 — major redesign

*Equipment spec cards:* one spec per line (Voc, Vmp, Isc, Imp, Área, Garantías each on own line)

*Zero-export savings model (`_scenario_projection`):*
- `daytime_kwh = avg_kwh × daytime_fraction` — consumption during solar hours
- `self_consumed = min(gen, daytime_kwh)` — solar actually used on-site
- `curtailed = max(0, gen − daytime_kwh)` — wasted solar (not exported)
- `grid_kwh = avg_kwh − self_consumed` — always > 0 (nights always draw from grid)
- `coverage = self_consumed / avg_kwh` — capped at daytime_fraction, never 100%
- `self_consumption_pct = self_consumed / gen × 100` — how much of generation is used

*AI daytime fraction (`_estimate_daytime_fraction_ai`):*
- Calls Claude Haiku with loads profile (`w5_loads_data`) and city
- Returns `(daytime_fraction, explanatory_note)`; falls back to 0.45
- Cached in `w6_coverage_ai` session key
- **Load-bearing for billing:** fraction determines `daytime_kwh` and thus `grid_kwh` and bill estimate
- AI call runs first when "Calcular MPPT" is clicked; `target_kw = daytime_kwh / avg_irradiance` computed from fresh fraction before MPPT scenarios are generated

*MPPT target for zero-export:* `target_kw = daytime_fraction × avg_kwh / avg_irradiance` — sizes to daytime consumption, not total, so scenarios span the saturation point and show meaningfully different bills

*Projection cards:* each of the 3 scenario columns has a `○ / ● Escenario X — N paneles (Y kW)` selector button directly above the card; clicking selects that scenario and clears manual mode

*Manual section layout:*
- Input spinners (series, parallel)
- Compact chips row (panels, kW, m², strings/MPPT, Voc, Vmp)
- Two-column body: validation bars (Voc/Vmp/Corriente) left; projection card right
- Selector button `○ / ● Usar configuración manual` above the card — mirrors auto scenario buttons
- Card border: purple when active, grey when not

*Unified selection UX:* clicking any auto scenario button sets `w6_selected_scenario` and clears `w6_use_manual`; clicking manual button sets `w6_use_manual = True`; no separate confirm/cancel button pair

*Saturation warning:* shown when all scenarios have `curtailed > 0` (all above saturation point); shows optimal kW

### Session state keys (Step 6)

| Key | Purpose |
|---|---|
| `w6_scenarios` | `list[dict]` — computed MPPT scenarios (A/B/C) |
| `w6_selected_scenario` | `"A"`, `"B"`, or `"C"` — active auto scenario |
| `w6_use_manual` | `bool` — manual config is active selection |
| `w6_equip_key` | `"{panel_id}_{inverter_id}"` — clears scenarios + selection on equipment change |
| `w6_coverage_ai` | `{fraction: float, note: str}` — cached AI daytime fraction estimate |

### Key decisions made

| Decision | What was decided |
|---|---|
| Zero-export model | `grid_kwh = avg_kwh − min(gen, daytime_kwh)`; no net metering; curtailed solar is wasted |
| MPPT target | Size to `daytime_fraction × avg_kwh`, not 85% of total consumption |
| AI fraction timing | AI call runs before MPPT scenario generation so target_kw uses the real fraction |
| Scenario cards | Selector button above each card (not a horizontal radio widget) for spatial alignment |
| Manual UX | Symmetric ○/● button above card; no separate "Usar esta configuración" flow |

---

## Cotizaciones UX polish (post-Phase 4, completed 2026-07-09)

**Goal achieved:** `pages/01_proposals.py` redesigned to be production-ready.

### Key changes

**Status flow — directed transitions:**
- Replaced free-form `st.selectbox` dropdown with `st.pills` using `STATUS_TRANSITIONS` dict
- Directed flow: `draft → active`, `active → won/lost/cancelled/draft`, `lost/cancelled → draft`. `won` is a terminal state.
- Pills appear in the t_col (title column) of the detail panel; visually distinct from the action buttons

**Per-version PDF:**
- `build_from_wizard_blob()` in `generator.py` accepts `version_date=locked_at[:10]` formatted as DD/MM/YYYY — so historical PDFs show the correct date
- Each version row has its own Generar / ⬇ PDF control (not just the current version)
- "Generar PDF" removed from detail panel header (redundant with per-version controls)

**Version row PDF controls:**
- `st.pills(["📄 Generar"])` — compact pill widget, visually different from primary action buttons
- `<a class="vrow-pill-btn">⬇ PDF</a>` — HTML anchor styled as an outlined pill matching `st.pills` appearance; direct download without Streamlit round-trip
- On hover: border and text go green (`#4BAE6A`)

**Detail panel header simplified:**
- Layout: `[title + flow pills] | divider | [Continuar] [Nueva versión]` (removed PDF column)
- Subtitle line "Creado · Total · vN" removed (redundant with version rows below)
- `margin-bottom: 8px` on title div adds breathing room before flow pills

**Theme:**
- `.streamlit/config.toml` added with `primaryColor = "#4BAE6A"` — primary buttons (✏️ Continuar, 📋 Nueva versión, ➕ Nueva) are green

### CSS constants in `pages/01_proposals.py`

- `div[data-testid="stPills"] button[aria-selected="true"]` → black (for status flow pills and filter pills)
- `a.vrow-pill-btn` → outlined pill shape (`border-radius: 20px`, transparent background, `#31333f` text, green border/text on hover)

---

## Phase 5 — What was built (Off-Grid + Hybrid wizard)

**Goal achieved:** Off-Grid and Hybrid system types are fully operational end-to-end — wizard Steps 1–8, PDF generation, both languages. Verified live in the browser (not just read), including a real PDF download. Went beyond the original Phase 5 scope in PHASES.md: Steps 4–5 were redesigned around a load-profile taxonomy (see below) that didn't exist when Phase 5 was originally scoped.

**Key files (all implemented):**
- `calculations/sizing_off_grid.py` — `size_battery_bank()`, `size_array()`, `check_split_phase()`. Battery bank formula validated exactly against the Jorge Ramírez reference (66.46% discharge, 2×Pylontech US5000C, 9.6 kWh installed).
- `calculations/load_profile_off_grid.py` — **new module, not in the original Phase 5 plan.** Implements the 5-category load taxonomy from `tools/off-grid-wizard-load-profile-approach.md` (Casa Principal quote write-up): customers give load name + quantity + nameplate watts only (no usage hours); an AI call (Claude Haiku, constrained to 5 enum values, checked against a hardcoded pre-classification table first) categorizes each load; a deterministic function per category computes kWh/day — never AI for the actual math. Categories: `fixed_cycling` (benchmark table), `behavior_driven` (aggregated once per property as kWh/day/bedroom × bedroom count, not per line), `climate_driven` (Open-Meteo climate API + cooling-degree-day model), `discretionary` (regional CR defaults or a customer-answered override), `ignition_only` (fixed negligible default). Every line carries a `confidence` tag (`benchmark` / `api_calculated` / `default_assumed` / `user_confirmed`) shown in the UI so generic estimates are visually flagged, not hidden.
  - Two real bugs found and fixed while validating against a representative house: the climate model initially used 24h mean temperature and returned 0 kWh/day of A/C load for Atenas (a genuinely hot town) because tropical nights pull the daily average below any reasonable cooling threshold — switched to daily max temperature. And pool-pump loads weren't matching the discretionary defaults table due to a word-order-sensitive substring match — switched to a keyword-list match.
- `calculations/mppt.py` — extended with `max_array_for_charge_controller()` and `check_charge_controller_design()`. Off-Grid validates strings against a *charge controller* (`vin_max`/`imax_in`, no MPPT voltage window), not an inverter's MPPT channels like Grid Zero — a different validator was needed, not a reuse of the existing one. Confirmed rule: keep Voc_total ≤ vin_max, then add parallel strings up to imax_in to maximize array power.
- `database/equipment_db.py` — `list_batteries()`/`list_charge_controllers()` were stubs; implemented to match the existing `list_panels()`/`list_inverters()` pattern.
- `wizard/off_grid.py` — Steps 4–8. Step 4: loads table (name/qty/kW only) + home profile (bedrooms, home class, autonomy days 1–7, voltage 120V/120-240V split-phase). Step 5: runs `build_load_profile()`, shows the confidence-tagged breakdown, allows manual override per line. Step 6: panel + charge controller + inverter (`type='hybrid'` filter) + battery + monitoring device selection; runs `size_array()` → string config (`_pick_string_config()`, a local helper reconciling the load-driven panel count against the controller's electrical limits) → `size_battery_bank()` → `check_split_phase()`. Step 7: cost line items including Monitoreo and Estructura de montaje (both required by the real reference PDF, not in the original line-item set) — filters out "Permiso de Interconexión" for true Off-Grid (no utility connection to interconnect; kept for Hybrid). Step 8: technical summary + PDF generation.
- `wizard/hybrid.py` — thin wrapper delegating to `wizard/off_grid.py`'s step functions, adding a grid-connection-at-main-panel checkbox (Step 4) and an AC-coupling note auto-appended to the proposal text (Step 8).
- `wizard/common.py` — Step 1's Off-Grid/Híbrido radio options were hard-disabled with an "available in Phase 5" message; removed, both now selectable.
- `pages/02_new_proposal.py` — Steps 4–8 routing now dispatches on `wizard_meta.system_type` (grid_zero → `wizard.grid_zero`, off_grid → `wizard.off_grid`, hybrid → `wizard.hybrid`). Progress-bar step labels also branch by system_type (Off-Grid's Steps 4–5 are "Cargas"/"Demanda", not Grid Zero's "Distribuidora"/"Consumo" — found this cosmetic bug live in the browser, not before).
- `proposals/generator.py` — `generate_pdf()` now maps `system_type` to a template file (`hybrid` shares the `off_grid` template — same technical shape, just a different `system_type_label`) and dispatches to a new `_build_context_off_grid()` context builder (no `billing_avg`/`benefits` keys — Off-Grid has no utility bill or grid-savings model to show; battery/discharge/daily-generation fields instead).
- `proposals/templates/off_grid_{es,en}.html` — built against the real Jorge Ramírez reference PDF (`Propuesta OFF GRID - Jorge Ramírez [Cabaña].pdf`), reusing Grid Zero's CSS classes verbatim for brand consistency. Structural differences from Grid Zero: no monthly billing table, no short/medium/long-term benefits table (neither applies without a utility bill); DETALLES TÉCNICOS shows 5 off-grid-specific columns (installed kW, roof area, daily generation, battery capacity @10h, max discharge) instead of panel/inverter counts; warranty table gains a Baterías row (10 years) the reference PDF had but Grid Zero's doesn't need. Kept Grid Zero's "Mantenimiento" warranty row and quote-number row, both of which the (older, pre-quote-numbering) reference PDF happened to lack.

**Bugs found and fixed only by actually running the wizard in a browser** (not by reading code): the interconnection-permit cost line appearing on true Off-Grid quotes; the progress-bar step labels; a `build_from_wizard_blob()` API-signature mismatch in Step 8's original PDF call (the wizard's own PDF path builds its context dict inline and calls `generate_pdf()` directly — `build_from_wizard_blob()` is a separate, Grid-Zero-specific path used elsewhere for regenerating PDFs from already-locked versions).

**Validation:** Full wizard walkthrough in the browser (Steps 1–8) with Jorge Ramírez's real equipment (JA Solar 620W, Victron MultiPlus-II, Victron SmartSolar MPPT 250/100, 2×Pylontech US5000C, Victron Cerbo GX) produced a real downloaded PDF matching the reference's technical numbers exactly (5.0 kW, 16 m², 6.38 kWh/day, 9.60 kWh, 66.46% discharge, $10,320, $2.08/Wp) once those historical figures were fed through the template. Note: a *freshly computed* quote using today's seeded JA Solar panel dimensions computes ~20.7 m² for 8 panels, not 16 m² — flagged as a real discrepancy between the original 2020 installation's actual panel and today's catalog SKU, not a bug in `size_array()` (which computes area from real datasheet dimensions, same pattern as `calculations/mppt.py`).

### Step 4 follow-up (same day, user feedback after first walkthrough)

Three real gaps found after Phase 5 was marked complete, all fixed and re-verified live:

- **`calculations/load_profile_off_grid.py`**: added `CATEGORY_LABELS_ES` (Spanish display labels) and `COMMON_LOADS_CATALOG_V1` (19 typical CR off-grid loads, pre-tagged with nameplate kW + category). `build_load_profile()` now accepts an optional `"category"` key per load — if the engineer already set one (via the catalog or a manual override), `classify_load_category()` (the AI call) is skipped entirely for that line.
- **`calculations/tablero_parser.py`**: added `parse_tablero_off_grid()` — a second tablero-photo extraction function that, unlike the original `parse_tablero()` built for Grid Zero, does **not** ask the AI for usage hours/duty cycle. Grid Zero's version embeds an hours-lookup table inside the prompt and has the AI invent h/día — exactly the naive pattern the load-profile taxonomy doc was written to replace, so it couldn't be reused as-is for Off-Grid without reintroducing that anti-pattern.
- **`wizard/off_grid.py` Step 4** — three additions: (1) a `help=` tooltip on "Clase de vivienda" spelling out what Básica/Estándar/Premium concretely mean (previously undefined, per direct user question), plus a tooltip on "Dormitorios" explaining it's the direct multiplier in the behavior-driven formula, not just a vague housing question; (2) a "Categoría" column on the loads table (`SelectboxColumn`, defaults to "(Automático)") plus an "Agregar cargas comunes" multiselect + button sourced from `COMMON_LOADS_CATALOG_V1`, so the engineer can add pre-filled common loads with a click instead of typing every row, and can override a load's category directly instead of only trusting the AI classification silently happening in Step 5; (3) an "Importar desde tablero eléctrico" expander (photo/PDF upload), mirroring Grid Zero's Step 5 pattern, calling the new `parse_tablero_off_grid()`.
- **Bug found and fixed during this same live test**: the "Agregar" button initially tried to reset the multiselect by writing directly to `st.session_state["w4og_catalog_pick"]` after that widget had already rendered in the same script run — Streamlit raises `StreamlitAPIException` for this. Fixed with a versioned-key pattern (`w4og_catalog_pick_{catalog_ver}`, mirroring the `w5_loads_{ver}` pattern `grid_zero.py` already uses for the same reset problem) instead of writing to the widget's own key.

### Second follow-up round (same day, user questioned "what's the point of rooms/home class if I'm listing loads individually?")

Two more real issues, not just polish:

- **Real undercounting bug in `build_load_profile()`**: `behavior_aggregate` (the dormitorios × home_class general-use estimate) was only computed `if behavior_load_count > 0` — i.e. only if at least one load in the list happened to get classified `behavior_driven`. Since individual behavior-driven loads' own wattage is *never* used (the category is priced purely from the bedroom formula, by design — see `estimate_behavior_aggregate()`), a load list that simply forgot to mention lighting/outlets (a common omission) silently **dropped general-use consumption from the total entirely**, not just from that one line. Fixed: the aggregate is now always computed and always included, regardless of whether any load was classified that way. Verified live: a loads table with only "Refrigerador" (0 behavior_driven lines) still produced "Cargas generales (0 circuitos, agregado) — 7.50 kWh/día" in the Step 5 output.
- **Consequence of the above, applied to the UI**: since individual behavior-driven loads never affect the number anyway, `_DEFAULT_LOADS` and `COMMON_LOADS_CATALOG_V1` no longer include "Iluminación general"/"Tomacorrientes"/etc. — offering them as loads to add implied itemizing them changes the estimate, which was never true. Step 4's caption now says so explicitly: "No es necesario listar iluminación, tomacorrientes, TV u otros usos generales."
- **`autonomy_days` now accepts fractional values** (`st.slider(min_value=0.5, max_value=7.0, step=0.5, ...)`, was integer-only 1–7) — occasional-use cabins reasonably need less than a full day of autonomy. Propagated the `int → float` type change through `wizard/off_grid.py`'s result dict and `calculations/sizing_off_grid.py:size_battery_bank()`'s type hint. Verified: 0.5-day autonomy correctly sizes to 1 battery instead of 2 for the same daily generation, at the same discharge %.

### Step 6 (Equipos) UI redesign (same day, user feedback: "organize this in a production-ready UI... don't put all specs in a single line")

`wizard/off_grid.py` Step 6 previously rendered plain selectboxes with no spec display, and the string-design validation result as one dense run-on sentence (`"✅ Configuración válida: 4 panel(es) en serie × 2 string(s) — Voc 200.8V / Vin máx 250V · 29.24A / Imax 35A"`). Redesigned:

- Added `_spec_card()` — a small helper rendering a `BRAND_GREEN_LIGHT` card with one spec per line, directly under each equipment selector (panel, charge controller, inverter, battery, monitoring). This isn't a new pattern — it's the same one `grid_zero.py` already uses (CONTEXT.md Phase 4: "Equipment spec cards: one spec per line, no multi-value concatenation") — Off-Grid's Step 6 just never had it applied.
- Replaced the single-sentence validation result with a `st.container(border=True)` card: a status line ("✅ Configuración válida"), then Strings / Voc total / Corriente total / Descarga del banco each on their own line in a 2-column grid, with a ✅/❌ indicator on each of the two limit checks individually (not just one overall checkmark).
- `is_valid` is now computed once and reused for both the display and the "Siguiente" button's `disabled` check (previously recomputed redundantly).

Verified live in the browser (full wizard walkthrough, Steps 1–6) — confirmed the cards and validation grid render as designed with real equipment data (Canadian Solar CS7N-620MS, Victron MultiPlus-II, Victron SmartSolar MPPT 250/100, Pylontech US5000C).

### Client-search null-handling bug (same day, separate user report)

`wizard/common.py` had a real bug independent of Phase 5: `dict.get(key, default)` only substitutes the default when a key is *missing*, not when it's present with value `None`. Since Supabase returns explicit `NULL` for empty `phone`/`email`/etc. columns (key present, value `None`), five call sites — the client-search dropdown label (rendered literally as "None None"), both client-loading callbacks (`_on_client_select`, `_on_prev_prop`), the previous-proposals label, and the Step 2 form's initial defaults — were all vulnerable to the same failure mode. The concrete crash: selecting a client with a null phone set `st.session_state["w2_phone"] = None`, and Streamlit's `text_input` then returns `None` instead of coercing to `""`, so the later `phone.strip()` raised `AttributeError`. Fixed all five with `.get(key) or default`, which falls back correctly in both the missing-key and present-but-None cases. Verified live: searching "rainforest" now shows a clean "The Rainforest Lab" (no more "None None"), and clicking Siguiente no longer crashes.

### Step 6 "Dimensionamiento calculado" / "Validación del diseño" card redesign (same day, follow-up to the spec-card redesign above)

The previous redesign fixed the equipment selector spec cards but left the sizing results as four plain `st.metric` cards and the design checks as a 2-column grid of text — the user asked for a clearer split: equipment quantities on top, sizing insights below, and the cross-checks reorganized as their own card row.

- Added two new small card helpers in `wizard/off_grid.py` (next to `_spec_card()`): `_metric_card()` — a neutral bordered card (label / big value / optional sublabel) for quantities and insights — and `_check_card()` — a color-coded card (green/red/gray left border + ✅/❌/ℹ️ icon, driven by a `status` arg) for the cross-check row.
- "Dimensionamiento calculado" is now two labeled rows of `_metric_card()`s: **Cantidad de equipos** (Paneles solares, Inversores, Controlador de carga, Baterías) and **Resultado del dimensionamiento** (Potencia instalada, Área, Generación diaria, Capacidad del banco). Inverter quantity is now shown explicitly (1, or 2 when `split_phase["requires_split_phase"]` is true) with its sublabel showing either the output voltage (`"120V"`) or `"Split-phase 120/240V (master/slave)"`. Panel quantity's sublabel shows the string arrangement (`"4 en serie × 2 en paralelo"`), computed from the existing `string_config`.
- "Validación del diseño" now leads with a full-width status banner (✅ Configuración válida / ❌ Configuración inválida), then four `_check_card()`s in a row — Configuración de strings, Voc total, Corriente total, Descarga del banco — each independently color-coded rather than one shared checkmark.
- Verified live: full wizard walkthrough (Steps 1–6, Off-Grid, Atenas/Alajuela site, default Refrigerador load) confirmed both rows render correctly with real sizing output (8 panels / 4S×2P, 1 inverter @ 120V, 3 batteries, 3.1 kW / 13.5 m² / 9.63 kWh/día / 14.4 kWh installed) and the validation cards all showed green/info status as expected for a valid design. Test proposal and prospect deleted from Supabase after verification.

### Sample-PDF test panel moved from wizard to Cotizaciones (same day, user request)

The "🧪 Prueba Fase 1 — PDF con datos de muestra" expander lived at the bottom of every wizard step in `pages/02_new_proposal.py` (rendered unconditionally after the step dispatch, so it showed on all 8 steps regardless of `system_type`) and only ever generated a Grid Zero sample (hardcoded `generate_pdf(MARIA_JOSE_DATA, "grid_zero", ...)`). User asked for it to be removed from the wizard entirely and moved to a discreet spot at the bottom of the Cotizaciones list, with the ability to test all three system types.

- Removed the expander block from `pages/02_new_proposal.py` entirely.
- Added `_render_test_pdf_panel()` at the bottom of `pages/01_proposals.py`, called unconditionally after the proposals list/empty-state — required restructuring the early `return` inside the empty-state branch into an `if/else` so the panel still renders when the list is empty or filtered to zero results.
- The panel is a collapsed `st.expander("🧪 Generar PDF de prueba")` with a `st.radio` for system type (Grid Zero / Off-Grid / Híbrido) and Español/English generate+download buttons, mirroring the old panel's button pattern.
- Added two new sample data dicts to `proposals/generator.py` alongside the existing `MARIA_JOSE_DATA`: `JORGE_RAMIREZ_DATA` (Off-Grid, matching the CONTEXT.md validation reference numbers — 8×620W panels, Victron MultiPlus-II, 2×Pylontech US5000C, Victron MPPT 250/100, 5.0 kW / 16 m² / 6.38 kWh/day / $10,320 total) and `HYBRID_DATA` (same shape, spread from `JORGE_RAMIREZ_DATA` with just `client`/`system_type_label`/`intro_lines` overridden — Hybrid reuses the off_grid template, so no separate technical fields were needed). This was the first time the off_grid PDF path (`_build_context_off_grid` → `off_grid_es.html`/`off_grid_en.html`) had sample data to exercise outside the full wizard.
- Verified live: all three system types × both languages (6 combinations) generate PDFs successfully from the Cotizaciones page without errors, and the old expander no longer appears anywhere in the wizard (checked Step 1).

### Step 4 "Uso general" redesign: subsections, visible tier examples, property-agnostic copy (same day, user question "what is the point of dormitorios/clase de vivienda")

Follow-up to the earlier Step 4 taxonomy work. The user asked why dormitorios/clase de vivienda existed at all if loads are listed individually (answered: they drive the `behavior_driven` aggregate, never the individual loads — see [[project_solar_tool]] context), then asked for three concrete UI changes:

- **Reorganized into subsections under one "Cargas eléctricas" heading**: `wizard/off_grid.py`'s `step4_loads()` now renders Días de autonomía / Voltaje as system-level params first, then `### Cargas eléctricas` with two subsections — `##### Uso general` (Habitaciones/espacios + Nivel de uso general) and `##### Cargas individuales` (import/catalog/table, unchanged). Previously all of this was flat with Dormitorios/Clase/Autonomía in one 3-column row.
- **Visible tier explanations with tangible examples**: the old `_HOME_CLASS_HELP` was a hover-only tooltip with hardcoded kWh numbers. Replaced with `_USAGE_LEVEL_DESCRIPTIONS` (a one-line description per tier) plus a bullet list rendered directly under the selector — each tier shows its rate and a concrete example (`"Ej.: 3 espacios ≈ 7.5 kWh/día"`), computed live from `BEHAVIOR_KWH_PER_BEDROOM_DAY_V1` (imported from `calculations/load_profile_off_grid.py`) rather than hardcoded, so the copy can't drift out of sync with the actual benchmark table if it's ever revised.
- **Removed the "homes only" framing**: off-grid/hybrid systems can be sized for small businesses, not just residences. Renamed "Dormitorios" → "Habitaciones / espacios" and "Clase de vivienda" → "Nivel de uso general" (labels + help text now explicitly mention both use cases: dormitorios for a home, oficinas/espacios for a business). Also updated `estimate_behavior_aggregate()`'s `source_detail` string in `calculations/load_profile_off_grid.py` (shown in the Step 5 demand table's "Detalle" column) from `"kWh/día/dormitorio × N dormitorios"` to `"kWh/día/espacio × N espacios"`, and synced the duplicate step title in `wizard/hybrid.py`. Internal variable/session-state names (`num_bedrooms`, `home_class`, `w4og_bedrooms`) were deliberately left unchanged — purely internal, not user-facing, and renaming would touch stored proposal JSON for no user-visible benefit.

Verified live: fresh Off-Grid wizard walkthrough (Atenas/Alajuela) confirmed the two subsections render under "Cargas eléctricas" with the tier bullet list showing correct computed examples (Básica 1.5×3=4.5, Estándar 2.5×3=7.5, Premium 4.0×3=12.0 kWh/día), and Step 5's demand table Detalle column now reads "2.5 kWh/día/espacio × 3 espacios" instead of the old dormitorio-specific wording. Test proposal/prospect deleted from Supabase after verification.

### Step 5 "Consumo por categoría" chart (same day, user suggestion)

User asked whether Step 5 would benefit from a chart. Discussed scope first: a full solar-generation + battery-SoC + load-curve visualization isn't feasible here because the model deliberately works in daily kWh aggregates, not hourly (per the load-profile taxonomy doc), and array/battery sizing doesn't happen until Step 6 — so that combo chart belongs on Step 6 or the Step 8 review, not Step 5. A category breakdown chart, by contrast, just visualizes numbers already in the Step 5 table, so we built that.

- Added a horizontal Plotly bar chart to `step5_demand()` in `wizard/off_grid.py`, right after the "Consumo diario total estimado" metric: one bar per load category (grouped from the *edited* dataframe, so it reflects any manual kWh/día overrides, not just the AI's original estimate), sorted ascending, labeled via the existing `CATEGORY_LABELS_ES` map.
- Added `_CATEGORY_CHART_COLORS` (module-level, next to `_CONFIDENCE_BADGES`) — one distinct color per category, reusing colors already established elsewhere in the codebase for visual consistency (`BRAND_GREEN` for fixed_cycling, `BRAND_NAVY` for behavior_driven, `#1d4ed8`/`#b45309`/`#6b7280` for climate_driven/discretionary/ignition_only, matching the confidence-badge and Grid Zero irradiance-chart colors). Required adding `BRAND_GREEN` to the `config` import (previously only `BRAND_GREEN_LIGHT`/`BRAND_NAVY` were imported).
- **Bug found and fixed during verification**: the longest bar's outside text label was getting clipped (showed "7.50" instead of "7.50 kWh/día") because the default x-axis range left no headroom past the max bar value for `textposition="outside"` to render into. Fixed by explicitly setting `xaxis.range=[0, cat_totals.max() * 1.25]` instead of relying on Plotly's auto-range, and tightening the right margin back down since it was no longer needed.

Verified live: Off-Grid wizard walkthrough confirmed the chart renders under "Consumo por categoría" with correct per-category totals, brand-consistent colors, and (after the fix) fully visible labels on every bar. Test proposal/prospect deleted from Supabase after verification.

### Step 5 "Cant." display bug + Step 6 multi-charge-controller support (same day, user report from screenshots)

User flagged two things from Step 5/6 screenshots: (1) the "Cargas generales" row showed "Cant.: 0" next to "16.00 kWh/día", which reads as a bug (0 units producing a nonzero total); (2) a specific equipment combo (JA Solar 620W + Victron SmartSolar MPPT 250/100, ~27 kWh/day load) showed "Paneles solares: 0" and "❌ No existe una configuración de strings válida", while simultaneously showing a nonzero "Potencia instalada: 8.68 kW" — contradictory. User asked why, and suggested the system should support more than one charge controller when needed. Also asked whether Step 6 recalculates live as equipment selections change — confirmed yes: Streamlit reruns the whole script on every widget change and Step 6 has no AI calls or "Calculate" gate (unlike Step 5), so `array`/`string_config`/`battery_bank` are recomputed fresh from current widget state on every rerun automatically.

- **Fix 1 (Step 5, `wizard/off_grid.py` `step5_demand()`)**: the "Cant." column for the behavior_driven aggregate row was showing `agg["load_count"]` — how many *individually listed* loads happened to get tagged behavior_driven (often 0, since lighting/outlets are rarely itemized) — not the actual multiplier behind the kWh figure. Changed it to show `current.get("num_bedrooms")` (the espacios count that's actually multiplied by the per-space rate, matching the Detalle column's own explanation), and simplified the row label from `"Cargas generales (N circuitos, agregado)"` to `"Cargas generales (uso general agregado)"` since the circuit count was the source of the confusion.

- **Fix 2 (Step 6, `wizard/off_grid.py`)**: root cause of "no valid config" was real, not a bug — a single Victron SmartSolar MPPT 250/100 (35A Imax_in) genuinely cannot carry a ~14-panel/8.68kW array's combined string current at any series/parallel split (even the minimum-current split at max series still exceeds 35A). Implemented multi-charge-controller support, mirroring the existing inverter split-phase quantity pattern:
  - `_pick_string_config()` now returns a 3-tuple `(panels_per_string, n_strings, cc_qty)` instead of 2 — for each series count (descending from Vin_max/Voc), computes the minimum `cc_qty` (1..`_MAX_CHARGE_CONTROLLERS`, capped at 4) whose *combined* Imax_in covers the array's total string current, rather than requiring everything fit on one controller.
  - The "Controlador de carga" quantity card now shows the real `cc_qty` (was hardcoded `"1"`); the "Corriente total" cross-check now validates against `imax_in × cc_qty` instead of a single controller's limit, with the limit label showing the breakdown (e.g. "140 A (4×35A)"); an info caption explains when/why multiple controllers are needed.
  - "Potencia instalada" / "Área" / "Generación diaria" metric cards now derive from `actual_panel_count` (what's actually buildable per the chosen string config) instead of `size_array()`'s raw load-driven target — fixes the "0 panels but 8.68 kW installed" contradiction for good, including the residual case where even 4 controllers can't cover the load (now shows 0 across the board consistently, with an updated error message naming the controller cap).
  - `charge_controller_qty` is now persisted in the Step 6 result and consumed by Step 7's cost line items (was hardcoded `qty: 1`), so multi-controller designs cost correctly.
  - **Deliberately did not touch** `battery_bank` sizing's `daily_kwh` input — it still reads `array["daily_generation_kwh"]` (the original target-based value, not the new actual/display one) to preserve the exact validated Jorge Ramírez reference pipeline documented earlier in this file.

Verified two ways: (1) a standalone script pulling real catalog data (JA Solar 620W + Victron SmartSolar 250/100) confirmed `_pick_string_config` now returns `(5, 3, 2)` for a 13-panel target where it previously returned `None` for every series/parallel combination. (2) Full live wizard walkthrough (15 espacios × Premium tier, default Refrigerador load only, 61.2 kWh/day total) reproduced a genuine 4-controller scenario end-to-end: Step 5 showed "Cant.: 15" correctly, Step 6 showed "Controlador de carga: 4" with a green "✅ Configuración válida" banner, all three cross-check cards green (strings 4×8, Voc 200.8V/250V, corriente 116.96A/140A), and the explanatory caption; Step 7's cost table showed "Controlador de carga … Qty 4". Test proposal/prospect deleted from Supabase after verification.

### PDF cost summary: added Subtotal/IVA rows (same day, user request)

Both wizards' Step 7 cost editor already computes and displays a three-line summary (Subtotal sin IVA / IVA / Total — `wizard/off_grid.py` and `wizard/grid_zero.py` `step7_costs()`, storing `subtotal_usd`/`iva_usd`/`total_usd` in `wizard_costs`), but the generated PDF's "DETALLES DE COSTOS" table only ever rendered a single "Total" row — the IVA breakdown was computed but never made it into the PDF. User asked for the PDF to match the wizard's three-line summary.

- **`proposals/generator.py`**: both `_build_context()` (Grid Zero) and `_build_context_off_grid()` (Off-Grid/Hybrid) now format and expose `subtotal_usd`/`iva_usd` in the template context (falling back to `total_usd`/`0` if absent, for old saved proposals predating this field). `build_from_wizard_blob()` (used when re-downloading a PDF for an already-saved proposal from the Cotizaciones page) now also extracts `subtotal_usd`/`iva_usd` from the saved blob's `costs`, with the same fallback. Added matching fields to the three sample/test-PDF datasets (`MARIA_JOSE_DATA`, `JORGE_RAMIREZ_DATA`; `HYBRID_DATA` inherits via spread) — pinned to `subtotal_usd = total_usd, iva_usd = 0.0` rather than inventing a tax split, since `total_usd` in both is a validated reference figure documented earlier in this file (María José $18,110 / Jorge Ramírez $10,320) that must stay unchanged.
- **All 4 PDF templates** (`grid_zero_es/en.html`, `off_grid_es/en.html`): added two rows to the cost table between the line items and the existing bold "Total" row — "Subtotal (sin IVA)" / "IVA" in Spanish, "Subtotal (excl. VAT)" / "VAT" in English (first use of "VAT" as IVA's English translation in this codebase) — styled with a new muted `.cost-subtotal` CSS class (light gray text, no bold/border, distinct from the existing bold `.cost-total` row).
- **`wizard/off_grid.py` and `wizard/grid_zero.py` `step8_review()`**: both `pdf_data` dicts (the "Generar PDF" button's live-wizard path, separate from the Cotizaciones re-download path above) now include `subtotal_usd`/`iva_usd` sourced from `costs.get(...)`, previously only `total_usd` was passed through.

Verified by generating all 6 sample PDFs (3 system types × 2 languages) via a script and extracting text with `pdfplumber` (installed temporarily for this check, then uninstalled — not a project dependency): every PDF correctly shows "Subtotal (sin IVA)/(excl. VAT) $X", "IVA"/"VAT" $0.00" (matching the sample data's pinned split), and an unchanged "Total" line exactly matching the validated reference figures ($18,110.00 / $10,320.00). Did not re-verify with a live nonzero-IVA wizard walkthrough — traced the full data path instead (`step7_costs()` → `wizard_costs` session state → `step8_review()`'s `pdf_data` → `_build_context(_off_grid)` → template) and confirmed it's a direct dict pass-through with no transformation risk.

### Step 6: energy-coverage and design-margin charts + safe min SoC card (same day, user follow-up to the multi-controller fix)

Off a screenshot of the redesigned Step 6, user asked for two charts to visually confirm "the proposed design will cover the building's energy needs — solar needs to cover days and charge batteries" — plus a card for safe minimum SoC. All three land in `wizard/off_grid.py` `step6_equipment()`, only rendered when a valid `string_config` exists (nothing to chart for an unbuildable design):

- **"Generación vs. consumo"** — a 2-bar horizontal Plotly chart (Generación diaria vs. Consumo diario) right after the "Resultado del dimensionamiento" metric cards, using `display_daily_generation` (the actual-panel-count-based figure, not the raw target) vs. `consumption["daily_kwh"]`. A caption below states whether generation covers consumption and ties in the battery/autonomy angle in words (kWh stored, ~N days of autonomy) rather than adding a third bar — kept the chart to 2 bars for legibility.
- **"SoC mínimo seguro" card** — added as a 5th `_check_card()` in the "Validación del diseño" row (now `st.columns(5)` instead of 4). Shows `100 - battery.dod_pct` (the battery spec's floor, e.g. 20% for an 80%-DoD-rated Pylontech) as the headline value, with `"Diseño llega a {100 - battery_bank['discharge_pct']}%"` as the sublabel — i.e., the battery-spec-derived safe floor vs. where this specific design's daily/autonomy cycle actually bottoms out. Status is `"ok"` only if the design's ending SoC is at or above the safe floor (true by construction today, since `size_battery_bank()` already sizes the bank so cycle depth stays at or under the battery's rated DoD — but the card makes that invisible safety margin visible rather than assuming the reader trusts the math).
- **"Margen de diseño"** — a 3-bar horizontal chart (Voc del arreglo / Corriente del arreglo / Profundidad de descarga), each as a % of its own limit (Voc/Vin_max, Imp_total/(Imax_in×cc_qty), discharge_pct/dod_pct — the third one intentionally normalized against the battery's DoD ceiling, not against 100%, to stay consistent with the other two "how close to the limit" bars), placed right after the validation check-card row. Color-coded by threshold (green <80%, amber 80–95%, red >95%) with a 100%-limit reference line and a one-line legend caption — answers "how much margin does this design have" at a glance instead of reading four separate value/limit pairs.

Verified live: reproduced a real 2-controller/2-inverter scenario (Off-Grid, 10 espacios × Estándar, split-phase 120/240V) and confirmed all three render correctly — generation (30.82 kWh/día) vs. consumption (26.20 kWh/día) with a green ✅ caption; SoC card showing 20% floor / "Diseño llega a 30%"; margin chart showing all three bars correctly bucketed into amber (80.3%, 84%, 88% — each >80 and ≤95 per the threshold code, confirmed against the actual computed percentages, not just the rounded display labels). Test proposal/prospect deleted from Supabase after verification.

### Chart brainstorm round 2 — 5 prototypes built to compare (same day, user request: "not just plain column charts")

User asked to brainstorm further chart ideas beyond the Step 5/6 bar charts already built, using AI and the app's own data where it adds value. Proposed 7 ideas (seasonal coverage, cumulative payback curve, energy-flow Sankey, design sensitivity sweeps, AI-illustrative hourly load shape, temp-corrected Voc margin, battery cycle-life gauge); user picked the top 5 to build and see live before deciding what to keep. All five are additive/optional — nothing existing was removed, easy to prune later per chart.

**Off-Grid/Hybrid (`wizard/off_grid.py`), all in Step 6 unless noted:**

1. **Cobertura estacional** — line+area chart of monthly generation (from the same 12-month PVGIS data already fetched, `pvgis_monthly`, scaled by `display_array_kw` and calendar days/month) against a flat dashed "Consumo diario" reference line, with the weakest month marked (red X) if it dips below consumption. Real engineering gap this closes: the design is validated elsewhere against an *average* month; this is the first place the wizard shows whether the *worst* month (rainy season) still clears the load. Placed right after "Generación vs. consumo".

2. **Flujo de energía (Sankey)** — `Generación bruta → {Pérdidas del sistema, Energía útil} → {load categories, Margen/recarga batería}`. Category shares come from Step 5's `profile` (lines + behavior_aggregate), rescaled proportionally to the (possibly manually-edited) `daily_kwh` total so the diagram can't drift out of sync with the edited table. No fabricated numbers — every value is either the 20%-loss assumption already used in `size_array()` or a real per-category kWh/día. Plotly auto-layout puts both true sinks ("Pérdidas" and the category leaves) in the same rightmost column, which is correct Sankey behavior, not a bug.

3. **Sensibilidad de diseño** — two small bar-sweep charts, both pure re-invocations of the existing sizing functions (no AI, no new state): (a) battery count vs. autonomy days swept over [0.5, 1, 1.5, 2, 3] via `size_battery_bank()`; (b) target panel count vs. Nivel de uso general (Básica/Estándar/Premium) via `estimate_behavior_aggregate()` + `size_array()`, holding the non-behavior_driven load total fixed. Current selection highlighted green among gray bars. Purely informational — doesn't change the active equipment selection.

4. **Perfil horario ilustrativo (IA)** — Step 5, not Step 6. New `estimate_hourly_shape_illustrative()` in `calculations/load_profile_off_grid.py`: Claude Haiku call (same `_MODEL` as load classification) generating 24 relative-intensity weights per category, given the categories present and load names — genuinely generative (not deterministic math), explicitly scoped to *when* load happens, never *how much* (the category's own kWh/día from the deterministic estimators is untouched, only redistributed across 24 hours for the chart). `_DEFAULT_HOURLY_SHAPES` hardcoded fallback (5 categories × 24 values, hand-authored typical CR residential shapes) covers every category if the AI call fails, times out, or returns malformed/out-of-range data — the feature never blocks the page. Gated behind a button (`🎨 Generar perfil horario ilustrativo`) with the result cached in `st.session_state`, since Step 5 reruns on every widget interaction and this shouldn't fire an API call each time. Rendered as a stacked-area chart (`go.Scatter(stackgroup=...)`), one trace per category. Caption is explicit that this is illustrative-only and never feeds the kWh/día sizing math, consistent with the taxonomy doc's core AI-never-computes-energy-math principle.

**Grid Zero (`wizard/grid_zero.py`), Step 8:**

5. **Flujo de caja acumulado (25 años)** — cumulative cash-flow line chart, right after the existing technical/cost/billing summary panel. Same cashflow formula as `calculations/financials.py`'s `calculate_irr`/`calculate_25yr_savings` (`-total_usd` at year 0, `savings_year1_usd × 1.05^y` for years 1–25), just kept year-by-year instead of collapsed into single IRR/ROI/25yr numbers — makes payback something a client can see cross zero, not just read as "5.48 years." Breakeven year found by scanning the cumulative series for the first non-negative value; marked with a vertical dashed line + annotation. Point markers colored red/green by sign. Required adding `BRAND_NAVY` to this file's `config` import (only `BRAND_GREEN`/`BRAND_GREEN_LIGHT` were imported before).

**Bug found and fixed during verification**: both new Step 6 sensitivity bar charts (item 3) had the same outside-label-clipping issue fixed earlier this session for the Step 5 category chart — no y-axis headroom above the tallest bar. Fixed identically: explicit `yaxis.range=[0, max(values) * 1.2]` instead of Plotly's auto-range.

**Verification**: Off-Grid items (1–4) verified live end-to-end — reproduced a 2-controller scenario with 3 load categories (fridge/A/C/EV charger), confirmed the seasonal chart, Sankey, both sensitivity charts (post-fix, via direct inspection of the rendered Plotly `yaxis.range` — 0–9.6 for an 8-battery max, 0–8.4 for a 7-panel max), and the AI hourly-shape chart (real API call, real Haiku-generated stacked area with plausible morning/evening peaks) all rendering correctly with real data. Grid Zero item (5) verified differently: the "Continuar" button for the one complete Grid Zero proposal available (`PC-2026-003-v2`) turned out to be disabled (sent proposals are read-only, discovered via `element.disabled` inspection — expected app behavior, not a bug), and building a fresh Grid Zero proposal from scratch (12 months of billing entry + tariff selection) was out of proportion for a prototype-stage check — instead verified by constructing the exact chart code standalone with the validated María José Castro reference figures (`savings_year1_usd=2798.81`, `total_usd=18110.00`): breakeven year computed as 6 (consistent with the documented ROI of 5.48 years), and the cumulative 25-year sum matched `calculate_25yr_savings()` fed the same inputs exactly. Figure object builds and serializes without error. Not a substitute for seeing it rendered in the actual page, flagged here explicitly.

Test proposals/prospects deleted from Supabase after verification; dev server stopped.

### Chart brainstorm round 2 — user critique of all 5 prototypes (same day, screenshots)

User reviewed all 5 new charts live and gave 7 pieces of feedback in one pass. All in `wizard/off_grid.py` unless noted:

1. **Descriptions under every chart title** — every `##### <chart title>` in Step 5/6 (and Step 8 in `wizard/grid_zero.py`) now has a one-line `st.caption()` immediately below it stating what the chart shows, before the plot itself — distinct from the existing *after*-chart captions that interpret this specific result (kept both; they serve different purposes).
2. **"Generación vs. consumo" should show battery charging** — added a third bar, "Recarga de batería" = `max(0, display_daily_generation - daily_kwh)` (the same surplus concept already used in the Sankey's margin flow, computed independently here to keep the two chart blocks self-contained). Caption updated to name the excedente explicitly.
3. **Sankey label font illegible** — root cause: no explicit `textfont` on the `go.Sankey` trace, so labels didn't have reliable contrast against the colored node/link bands. Fixed with `textfont=dict(color=BRAND_NAVY, size=13, family="Arial, sans-serif")` at the trace level, plus a thin white node border (`node.line`) and slightly more `pad` for breathing room.
4. **"Cobertura estacional" — does it include battery buffering?** No — it's raw monthly array generation (PVGIS-driven) vs. flat consumption, no battery smoothing modeled. Added a caption saying so explicitly: a whole month below the line is a structural deficit the battery can't fix (it can only shift *when* energy is used within days it has stored, not manufacture more of it).
5. **"Margen de diseño" — margin against what?** Fair gap: none of the 3 bars involve the inverter, only the charge controller (Voc, corriente) and battery (profundidad de descarga) — the chart's own title didn't say so. Added a caption naming exactly which two components are being checked and calling out that the inverter is validated separately, and appended `(vs. controlador)` / `(vs. batería)` directly onto each bar's y-axis label so it's legible without reading the caption.
6. **"Paneles vs. nivel de uso general" sensitivity chart — useless, remove.** Deleted outright (function, both columns collapsed back to one full-width chart). Kept "Baterías vs. días de autonomía," the one that wasn't flagged.
7. **Split-phase warning misplaced** — was rendered at the very bottom of the whole "Dimensionamiento calculado" section (after every chart), disconnected from the inverter choice that triggers it. Moved `check_split_phase()`'s call from mid-function up to immediately after the inverter's `_spec_card()` in the equipment-selection column, and the `st.warning()` now renders right there. The later duplicate call/render was removed; `split_phase` (computed once, earlier) is still reused downstream for `inverter_qty` etc. — no behavior change, only *when* the warning is computed and *where* it's shown.

Verified live end-to-end: rebuilt a split-phase Off-Grid scenario (Atenas, A/C load, 120/240V) and visually confirmed all 7 — description captions present on every chart, 3-bar generation/consumption/battery-recharge chart, legible dark-navy Sankey labels, the seasonal-coverage caveat caption, the margin chart's clarified bar labels + caption, only one (full-width) sensitivity chart, and the split-phase warning appearing directly under the inverter spec card on Step 6 instead of at the page bottom. Test proposal/prospect deleted from Supabase after verification.

### Off-Grid Step 6/8 restyled to match Grid Zero's card format (same day, user request off 3 screenshots of Grid Zero's Opción 2 panel, Step 8 summary card, and cash-flow chart)

User asked for Off-Grid's equipment/validation cards and Step 8 summary to visually match Grid Zero's, and asked what the cash-flow chart assumes. Before touching code, dispatched an Explore agent to document Grid Zero's exact patterns (`wizard/grid_zero.py`): Step 6 has no radio button between "Opción 1" (auto A/B/C scenario candidates via `validate_string_design()`) and "Opción 2 — Configuración manual" (free-form sliders + live `check_design()` recompute) — both always visible, sharing `st.session_state["w6_use_manual"]`. That manual-override slider architecture doesn't exist in Off-Grid (which sizes deterministically via `_pick_string_config()`) and reproducing it was out of scope for a styling request — so this round ports only the **visual** chip-row/param-row/summary-card patterns, not the dual auto/manual scenario picker. Flagging this scope choice explicitly here and to the user.

**`wizard/off_grid.py` Step 6 (`step6_equipment()`):**
- Replaced `_check_card()` with `_CHIP_STYLE`/`_chip_row()`/`_param_row()`, copied verbatim from Grid Zero's Opción 2 CSS (light-gray pill chips `background:#f1f5f9;border:1px solid #cbd5e1`; param rows as a 3-column `44%/28%/28%` label/value/limit grid, green `#166534`/red `#991b1b` themed with ✓/✗ icon).
- "Cantidad de equipos" + "Resultado del dimensionamiento" (8 metric cards) collapsed into one `_chip_row()` (🔢 paneles, 🔀 arreglo, ⚡ kW, 📐 área, 🔌 inversores, 🎛️ controladores, 🔋 baterías) + a 2-card row (Generación diaria, Capacidad del banco only — the rest moved into the chip row).
- "Validación del diseño" (5 `_check_card`s) collapsed into 4 `_param_row()` calls (Voc total, Corriente total, Profundidad de descarga, SoC mínimo seguro). Dropped "Configuración de strings" as its own row since the 🔀 chip already shows it.

**`wizard/off_grid.py` Step 8 (`step8_review()`):** replaced the `st.columns()+st.metric()` summary with an HTML sectioned card using the same `_kv()` helper pattern as Grid Zero's — "Técnico" (Sistema, Paneles+brand/model, Inversores+brand/model, Área, Controlador(es)+brand/model, Baterías+brand/model), "Generación y autonomía" (Generación diaria, Banco de baterías, Descarga — off-grid's equivalent of Grid Zero's billing section, since there's no utility bill to compare against), "Costos del proyecto" ($/Wp, Subtotal, IVA, Total-accented). No "Proyección financiera" section — off-grid has no savings baseline to project.

Verified live: resumed a saved Off-Grid draft ("GZ Style Test," 8 panels/1 inverter/1 controller/3 baterías), confirmed the chip row and all 4 param rows render on Step 6 exactly like Grid Zero's Opción 2 (same pill/grid CSS, green "✅ Configuración válida" banner), filled Step 7 costs ($9,400 total), and confirmed Step 8's three-section HTML card renders correctly with real data (4.96 kW / 8 paneles / 15.41 kWh/día / $9,400 total). Test proposal ("PC-2026-009," prospect "GZ Style Test") and its version deleted from Supabase after verification; dev server stopped.

**Cash-flow chart assumptions (user's question, answered in chat, not a code change):** `wizard/grid_zero.py` Step 8's "Flujo de caja acumulado" reuses the exact same inputs as the `calculate_irr`/`calculate_roi`/`calculate_25yr_savings` metrics shown just above it in the same card (`savings_year1_usd`, `total_usd`), but plots them year-by-year instead of collapsing to single numbers. `savings_year1_usd` itself comes from a genuine month-by-month tariff simulation (`monthly_savings_table()` in `calculations/sizing_grid_zero.py`, using real PVGIS monthly generation and real per-month tariff-tier billing via `calculate_bill()`), not a flat guess. Key assumptions baked into the 25-year projection: (1) savings escalate 5%/year (`escalation=0.05`, assumed utility-tariff inflation) — generation itself does **not** escalate; (2) **no panel degradation modeled anywhere in the codebase** (confirmed via repo-wide grep for "degrad" — zero hits), so year-25 generation is assumed identical to year-1; (3) no consumption growth over 25 years — today's load profile is assumed to hold; (4) no NPV discounting — all cumulative figures are nominal dollar sums; (5) exchange rate is fetched once at Step 8 render time and held constant for the full 25-year projection (falls back to 520.0 if the live API call fails). One inconsistency worth knowing about: the "Payback" metric above the chart is `calculate_roi()` — a naive `total_cost / savings_year1` with no escalation — while the chart's own breakeven marker uses the escalating series, so the two numbers won't quite agree (escalating savings breakeven a bit earlier than the flat payback figure suggests). Not a bug, just two different ways of answering "when does this pay for itself" sitting next to each other without a label explaining the difference — worth a caption if this becomes a client-facing concern.

### Off-Grid Step 6: A/B/C auto-scenario picker + manual mode (live-updating) + section reorder (same day, user request: "what if we generate 3 scenarios plus a manual scenario in off grid... charts should update live", plus a reorder + a Sankey-margin question)

User asked to replicate Grid Zero's full Opción 1 (3 auto scenarios)/Opción 2 (manual config) architecture in Off-Grid — the exact thing explicitly scoped OUT of the prior round (which ported only the visual chip/param-row styling). This round builds the real thing, with every downstream chart re-deriving from whichever configuration is active.

**`calculations/mppt.py` — new charge-controller scenario generator**, mirroring `validate_string_design()`/`check_design()`'s split for grid-tied inverters:
- `check_charge_controller_design_multi(panel, cc, panels_per_string, n_strings, max_cc=4)` — like the old `check_charge_controller_design()`, but accounts for paralleling multiple controllers: `charge_controller_qty` is the minimum controller count (≤max_cc) whose combined Imax_in covers the array's current, and `within_limits`/`violations` are checked against that *scaled* current limit (`imax_in × cc_qty`), not a single controller's rating — this is the same correction wizard/off_grid.py's UI layer was already applying ad hoc via separate `voc_ok`/`imp_ok` variables; now it's centralized in the calc function itself. Returns `None` if even `max_cc` controllers can't carry the design. Does **not** set a `scenario` key — it's a shared building block, and the caller (manual-mode UI, or the scenario generator below) attaches whatever label makes sense.
- `validate_charge_controller_design(panel, cc, target_panel_count, max_cc=4)` — generates up to 3 scenarios (A/B/C). Series count is fixed at the value that maximizes Voc within `vin_max` (minimizes current/cabling, the same choice the sizing already made); scenarios then vary **strings in parallel** around the load-driven target from `size_array()`: B = closest match, A = one string fewer (cheaper, less coverage), C = one string more (pricier, more margin) — off-grid arrays scale by paralleling strings (and controllers), not by changing series, unlike Grid Zero's MPPT-window-constrained series variation. Old `check_charge_controller_design()` (now fully unused) was deleted.
- **Bug caught during testing, fixed before verification**: initial implementation built scenario dicts as `{"scenario": "A", **a}` where `a` already contained a hardcoded `"scenario": "M"` key from `check_charge_controller_design_multi()` — since dict-literal unpacking applies keys left-to-right, the later `**a` silently overwrote the intended "A"/"B"/"C" label with "M" for every scenario. Caught via a standalone script test (`validate_charge_controller_design(real_panel, real_cc, 8, 4)` should reproduce the Jorge Ramírez reference exactly at target=8) before ever touching the browser — output showed all three scenarios labeled "M". Fixed by removing the internal "scenario" key from `check_charge_controller_design_multi()`'s return entirely (see above); confirmed fixed by rerunning the same script (labels now correctly A/B/C, and target=8 reproduces 8 panels/4.96 kW exactly).

**`wizard/off_grid.py` Step 6 (`step6_equipment()`), full rewrite of the sizing section:**
- Deleted `_pick_string_config()` (the old single-deterministic-scenario picker); added `_og_scenario_projection()` — off-grid's equivalent of Grid Zero's `_scenario_projection()`, computing per-scenario daily generation, resulting battery bank (count/kWh) at the current autonomy setting, and whether it covers daily consumption.
- **"🔁 Opción 1 — Configuración automática"**: scenario table (Escenario/Paneles-string/Strings/Controladores/Total paneles/Sistema kW/Área/Voc/Corriente/Estado/Notas) + 3 cards with selector buttons, visually identical to Grid Zero's pattern (green border+bg when selected, ○/● bullet in the button label, ⚠️ fallback text for out-of-limits scenarios instead of a button).
- **"⚙️ Opción 2 — Configuración manual"**: `st.number_input` sliders for panels-per-string/strings-in-parallel, live chip row + `_param_row()` validation (reusing the chip/param helpers ported last round), a selector button, and a live projection card — all recomputed every rerun via `check_charge_controller_design_multi()` (cheap pure math, no AI/API call needed here unlike Grid Zero's daytime-fraction estimate, so no button-gating was needed — scenarios and the manual check both just recompute on every render).
- **Single source of truth**: after both sections render, `chosen` resolves to either the selected auto scenario or the manual config (only if it's currently within limits — if the user drags the manual sliders into an invalid zone after selecting manual, `chosen` becomes `None` rather than silently keeping stale valid numbers or falling back to an auto scenario the user didn't pick). Every downstream variable (`panels_per_string`, `n_strings`, `cc_qty`, `display_array_kw`, `display_daily_generation`, `is_valid`) is derived from `chosen`, and **the battery bank is now sized off `display_daily_generation`** (this scenario's actual generation) instead of `size_array()`'s flat nominal target — a deliberate behavior change so that switching scenarios (or dragging manual sliders) visibly changes the battery count. Confirmed this doesn't break the Jorge Ramírez reference numbers (target panel count there has no series/parallel rounding mismatch, so nominal and actual generation coincide). The "Sensibilidad de diseño" battery-vs-autonomy sweep was updated to use the same live `display_daily_generation` for the same reason (previously used the stale nominal figure, which would have made the sweep's "current" bar silently drift out of sync with the real battery count once scenarios could differ from the nominal target).
- Session-state reset (`w6og_use_manual`, `w6og_selected_scenario`) on panel/controller change, mirroring Grid Zero's `w6_equip_key` pattern exactly.
- `equipment["array_scenario"]` (the winning label: A/B/C/M) and `equipment["array_scenarios"]` (the full A/B/C list) are now carried into the wizard result dict for audit-trail parity with Grid Zero, though nothing downstream (PDF, Step 8) reads them yet.

**Section reorder (2nd part of the same request)**: "Validación del diseño" and "Margen de diseño" moved from after "Flujo de energía" to immediately after "Generación vs. consumo" — both are framed as part of the sizing/validation phase, while "Cobertura estacional," "Flujo de energía," and "Sensibilidad de diseño" are supporting/exploratory analysis. New order: Generación vs. consumo → Validación del diseño → Margen de diseño → Cobertura estacional → Flujo de energía → Sensibilidad de diseño. Both moved sections now read from `chosen` instead of the old `cc_check`/`string_config` variables they were written against.

**Verified live end-to-end**: built a fresh Off-Grid proposal ("Scenario Test," Atenas/Alajuela, default Refrigerador + Uso general Estándar×3 load → 8.70 kWh/día) through Step 6. Confirmed: (1) Opción 1 shows 3 correctly-labeled scenarios (A=4 paneles/2.48kW, B=8 paneles/4.96kW, C=12 paneles/7.44kW/2 controladores) with the Jorge-Ramírez-reference numbers exactly reproduced at B; (2) clicking "Escenario C" live-updates the chip row, both metric cards, and every chart below to C's numbers (23.11 kWh/día, 33.6 kWh banco, 7 baterías) — confirmed via the "Configuración activa: Escenario C" caption; (3) switching to "Usar configuración manual" and dragging strings-en-paralelo to 3 (matching C's total) live-updates everything identically, confirmed via "Configuración activa: manual"; (4) reorder confirmed — Validación/Margen render directly under Generación vs. consumo, before Cobertura estacional; (5) advanced to Step 7 and confirmed the line-item table reflects the manual selection (12 paneles, 2 controladores, 7 baterías), proving the "Siguiente" result dict carries the live-chosen config through correctly, not stale defaults. Test proposal ("Scenario Test") and prospect deleted from Supabase after verification; dev server stopped.

**Flujo de energía margin calculation (user's question, answered in chat, not a code change):** the Sankey's "Margen / recarga batería" flow is `max(0, display_daily_generation − daily_kwh)` — the exact same single-day surplus already shown as the "Recarga de batería" bar in the "Generación vs. consumo" chart directly above it, not an independently-computed figure. It is a same-day energy-balance snapshot, not a battery simulation: it does not model round-trip charge/discharge efficiency (real LiFePO4 banks lose a few percent converting AC/DC surplus into stored charge — the diagram assumes 100%), and it does not check whether the battery bank still has headroom that day (if the bank is already full from a prior sunny day, this "margin" would actually be curtailed, not stored — Step 6 doesn't track state-of-charge across multiple days, only the single archetypal day's balance). The Sankey's other flows are similarly simple: "Pérdidas del sistema" is not an independently measured loss — it's exactly `gross_kwh − display_daily_generation`, i.e. the complement of the flat 20% system-loss derating (`system_losses_pct=0.20`) already applied everywhere else in Step 6/`size_array()`, not a per-component breakdown of wiring/temperature/soiling/inverter losses. The per-category kWh values are Step 5's category estimates (reference tables, behavior aggregates, or AI-classified individual loads), rescaled proportionally so they sum exactly to `daily_kwh` (handles the case where a user manually edited Step 5's total after the category breakdown was computed) — not independently re-derived from anything in Step 6.

### Off-Grid Step 6 equipment-selection block alignment (same day, screenshot showing misaligned rows)

User pointed out (via screenshot) that Off-Grid's "Selección de equipos" cards didn't line up the way Grid Zero's do — e.g. "Controlador de carga" and "Batería" labels started at different heights. Root cause: the whole section used one `st.columns(2)` split with 3 items stacked in the left column (Panel → Controlador → Monitoreo) and 2 in the right (Inversor+warning → Batería) — Streamlit lays out each column independently top-to-bottom, so a taller card (or the split-phase warning box) on one side pushed everything below it out of alignment with its counterpart on the other side, since the columns had no way to know about each other's heights.

Fixed in `wizard/off_grid.py`'s `step6_equipment()` by splitting into 3 independent `st.columns(2)` calls, one per paired row — Row 1 (Panel | Inversor+warning), Row 2 (Controlador | Batería), Row 3 (Monitoreo, alone). Each row now starts level regardless of how tall the previous row's cards were, since Streamlit renders a fresh column pair per row rather than one long-lived pair holding everything. This mirrors Grid Zero's own layout, which never had this problem only because it has exactly one equipment item per column (nothing to misalign against).

Verified live: resumed an existing Off-Grid draft (PC-2026-006, Oscar Pauly) to Step 6 and confirmed all three rows — Panel/Inversor, Controlador/Batería, Monitoreo — now start at consistent heights. Dev server stopped after verification (no new test data created, since this used an existing draft with no input changes).

### Off-Grid Step 6: inverter + battery quantities added to Opción 1 table/cards and Opción 2's card (same day, screenshots showing the table/cards without inverter or battery-capacity columns)

User asked to show inverter quantity, inverter total power (W), battery quantity, and battery capacity (kWh) in the Opción 1 scenario table and in the scenario/manual cards — currently the table only covered the array (paneles/strings/controladores/Voc/corriente) and the cards only showed battery, not inverter.

`wizard/off_grid.py`'s `step6_equipment()`: hoisted `inverter_qty` (previously computed only after `chosen` was resolved, well below Opción 1/2) up next to `dod_pct`/`autonomy_days`, right after equipment selection — it doesn't depend on which array scenario is active (only the inverter's output voltage vs. the required voltage decides split-phase), so it's available before Opción 1 renders. Added `inverter_power_w = inverter_qty × inverter['kw'] × 1000`. Removed the old duplicate `inverter_qty` line further down.

Introduced `scenario_projections` — a dict computed once (`{scenario_label: _og_scenario_projection(...)}`) and reused by both the scenario table and the scenario cards, instead of the cards recomputing their own projection separately from the table (which didn't have projection data at all before this change, since battery count/capacity genuinely vary by scenario and weren't in the table). The scenario table gained 4 columns: "Inversores", "Potencia inversor (W)" (both constant across rows — same inverter regardless of array scenario, shown per-row so each row reads as a complete system spec), "Baterías", "Capacidad batería (kWh)" (both scenario-specific, pulled from `scenario_projections`). Both Opción 1's 3 cards and Opción 2's "Proyección" card gained a "🔌 Inversores: N (X,XXX W)" line, placed between "Generación" and "Baterías".

Verified live: resumed the same Off-Grid draft (PC-2026-006) to Step 6 and confirmed the table shows Inversores=1/Potencia=5000 W (constant) and Baterías=3/5/7 with capacity 14.4/24.0/33.6 kWh varying correctly by scenario (A/B/C), and all three auto-scenario cards plus the manual "Proyección" card show the new "🔌 Inversores: 1 (5,000 W)" line. Dev server stopped after verification (existing draft, no new test data).

### Off-Grid Opción 1 redesign: min-SoC + recharge-reliability scenarios, replacing string-count nudges (same day, user feedback: scenarios should be tied to battery capacity and inverter power, not just strings)

User pushed back on the A/B/C design from earlier this session: scenarios varying string count ±1 around a load-driven target, with battery bank as a downstream side-effect, wasn't the right mental model. Requested instead: scenario 1 = minimum acceptable (SoC down to ~20%, recharges to 100% most days), scenario 2 = ~40% min SoC, recharges almost all days, scenario 3 = ~50% min SoC, always recharges, plus headroom for future load growth — with MPPT/charge-controller sizing as a pure consequence of whatever array results, never a scenario driver itself. Confirmed two design parameters via AskUserQuestion before implementing: (1) "most/almost all/always" → 9/11/12 out of the 12 real PVGIS months must fully recharge; (2) the existing "días de autonomía" (Step 4) multi-day backup floor stays in effect as a hard safety minimum layered under the new min-SoC targets, never silently overridden.

**New calc-layer functions** (old `calculations/mppt.py` A/B/C generator — `validate_charge_controller_design()`/`_cc_make_description()` — deleted outright, fully superseded):

- `calculations/mppt.py: find_array_for_reliability(panel, cc, monthly_kwh_kwp, daily_kwh_consumption, required_months_ok, max_cc, growth_extra_strings=0)` — series fixed at the max-Voc value (unchanged convention), then searches increasing parallel-string counts until the array's generation clears daily consumption in at least `required_months_ok` of the 12 real PVGIS months (reusing the exact same per-month math "Cobertura estacional" already renders — `kwh_kwp × system_kw × 0.8 / days_in_month`). `growth_extra_strings` adds headroom on top for scenario 3.
- `calculations/sizing_off_grid.py: size_battery_for_min_soc(daily_kwh_consumption, min_soc_pct, autonomy_days, battery_dod_pct, battery_voltage_v, battery_capacity_kwh)` — a genuinely different question from the existing `size_battery_bank()`: sizes for a target *daily cycle depth* (how far a normal day's load drains the bank before next recharge), driven by **consumption**, not generation — physically correct, since it's the load that draws the battery down between charges, not the array's output. Takes `max()` against the pre-existing multi-day autonomy-floor formula (also switched to consumption-driven here, since surviving a cloudy stretch is bounded by what the load draws, not by how much a possibly oversized array happens to generate — this was a latent conceptual mismatch in the old generation-driven formula that only stayed invisible while arrays were sized close to consumption). `size_battery_bank()` itself is untouched — still used unchanged by Manual mode and the Sensibilidad sweep, keeping their existing (already-validated) behavior.
- `calculations/sizing_off_grid.py: generate_reliability_scenarios(panel, cc, battery, daily_kwh_consumption, monthly_kwh_kwp, autonomy_days, max_cc)` — orchestrates the two above into the 3 fixed scenario definitions (`_RELIABILITY_SCENARIO_DEFS`: (1, 20%, 9 months, +0 strings), (2, 40%, 11 months, +0), (3, 50%, 12 months, +1)), returning one merged dict per scenario (array combo + `battery` sub-dict + scenario metadata). Omits any scenario whose array search fails.

**Bug caught during standalone testing, fixed before the browser**: initial `find_array_for_reliability()` scenario dicts came out with duplicate/incorrect labels — same class of dict-unpacking-order bug as the earlier A/B/C round (a leftover "scenario" key from a lower-level helper silently overwriting the intended one). Caught by a standalone script reproducing the Jorge-Ramírez-adjacent inputs before touching the UI; fixed by never setting a "scenario" key inside the shared building-block functions, only at the point where each scenario's true label is known.

**`wizard/off_grid.py` rewiring**: removed the `size_array()` call and `target_panel_count` entirely (no longer meaningful — scenarios search outward from 1 string, not around a target). `w6og_equip_key` now includes the battery id (battery choice now directly drives scenario sizing, not just a display detail). Opción 1's table gained "SoC objetivo", "Meses c/recarga" (X/12) columns; cards show SoC target + actual, months-cleared, and a "🌱 string extra para crecimiento futuro" note on scenario 3. Manual mode (Opción 2) intentionally untouched — it has no min-SoC concept of its own, still free-form sliders checked against absolute electrical limits, with battery derived from its own array's generation exactly as before. `chosen`-resolution now branches: auto scenarios (1/2/3) reuse their own precomputed `battery` dict directly; manual mode keeps calling `size_battery_bank()` off `display_daily_generation` as always.

**Bug caught during live verification, fixed immediately**: the "Siguiente" result dict still referenced the deleted `array` variable (`{**array, ...}`) — a leftover from before `size_array()` was removed, surfaced as a `NameError` only when actually clicking through to Step 7 (not caught by `ast.parse()` or by viewing Step 6 alone). Fixed by building that dict from explicit keys (`array_kw`, `panel_count`, `area_m2`, `daily_generation_kwh`) instead of spreading a variable that no longer exists. Underscores why the verification checklist includes actually advancing past the step being changed, not just rendering it.

**On the old Jorge Ramírez validation reference**: `size_array()` and `size_battery_bank()` themselves are completely unchanged by this round (still used as-is by Manual mode), so their own docstring-documented validation still holds. What changed is that Opción 1 no longer calls them at all for the auto scenarios — it's an intentionally different, more sophisticated algorithm superseding the "scenario B ≈ old deterministic result" equivalence from the previous A/B/C round. Reproducing the old reference numbers is no longer the right bar for the new scenario picker; verified instead via standalone scripts confirming the new functions' own internal logic (see below) plus live browser verification.

**Verified**: standalone script against real DB equipment (Canadian Solar 620W / Victron SmartSolar 250/100 / Pylontech US5000C) confirmed: at low consumption (8.70 kWh/day) all three scenarios' arrays land on the same 2-string/8-panel array (already clears 12/12 months at the cheapest viable string count — correct, not a bug, since the reliability bar is a minimum not a target) while batteries differentiate (3/4/4 units, ~40/55/55% actual min SoC — the 55/55 tie between scenarios 2 and 3 being a real artifact of the 4.8 kWh battery's coarse granularity, transparently shown via "SoC mín. real" rather than hidden); at higher consumption (20 kWh/day) all three axes differentiate (strings 3/4/5, batteries 6/7/9). Live in the browser (existing Off-Grid draft PC-2026-006): confirmed the new table/card layout renders correctly, selecting Escenario 3 live-updates the chip row, both metric cards, Validación, Margen, Cobertura estacional (visibly showing 12/12-month coverage), Flujo de energía, and Sensibilidad — all sourced from `chosen["battery"]` directly rather than being recomputed from generation — and advanced all the way to Step 7, confirming the line-item table reflects the selected scenario's panels/batteries/controllers correctly post-fix. Dev server stopped after verification (existing draft, no new test data — though this round did save new equipment selections into PC-2026-006 via the normal "Siguiente" flow, which is expected/fine for an already-established personal test draft).

### Off-Grid Scenario 3: inverter-power headroom check + answering 3 follow-up questions (same day: voltage-choice sanity check, inverter headroom for scenario 3, and whether "12/12 for all scenarios" is a bug)

User asked three things off a table screenshot showing "Meses c/recarga" = 12/12 for all three scenarios: (1) is 120V/120-240V split-phase selection still available (yes, untouched — confirmed by grep, `wizard/off_grid.py` Step 4 lines ~76-81, orthogonal to all scenario-picker work this session); (2) Scenario 3 should also check inverter power, not just panels/battery — if scenarios 1/2 are already close to the inverter's limit, scenario 3 should plan for more inverters, e.g. 2× more; (3) is 12/12-for-all-scenarios in the screenshot a bug.

**Answered #3 directly (no code change)**: not a bug. The reliability search finds the *smallest* array meeting or exceeding each scenario's threshold (9/11/12 months) — if the site's consumption is low enough that the cheapest 2-string array already clears all 12 months, every scenario's search lands on the same array (there's no mechanism, nor should there be one, to deliberately undersize scenario 1 just to make it look different from 2/3). Confirmed via the exact numbers already validated earlier this session: at 8.70 kWh/day consumption, 2 strings already hits 12/12, so all three show 12/12 — differentiation still happens on SoC objetivo/battery/growth, just not on months-covered in this particular case. At higher consumption (verified earlier: 20 kWh/day) all three scenarios do show different months/strings/batteries.

**Implemented #2** — a real, previously-nonexistent gap: the wizard had never checked connected load against inverter capacity anywhere; inverter qty was purely a function of split-phase voltage requirements, constant across all scenarios.

- **`calculations/sizing_off_grid.py`**: `generate_reliability_scenarios()` gained 3 new required params — `base_inverter_qty`, `inverter_kw`, `total_connected_load_kw` — plus a module constant `_INVERTER_HEADROOM_TRIGGER_PCT = 0.80`. Computes `load_ratio = connected_load_w / (base_inverter_qty × inverter_kw × 1000)` once; if `load_ratio >= 80%`, scenarios 1/2 get flagged `inverter_headroom_tight=True` (informational — they never gain inverters, since they represent *current* need) while scenario 3 gets `inverter_qty = base_inverter_qty × 2` and `inverter_growth_added=True` — literally "2× more inverters," matching the user's own example. Each scenario dict now carries its own `inverter_qty`/`inverter_power_w`/`inverter_load_ratio_pct` instead of a single constant applied to all three.
- **`total_connected_load_kw`** is computed in `wizard/off_grid.py` as the sum of Step 4's individually-rated loads (`quantity × connected_power_kw` from `consumption["profile"]["lines"]`) — deliberately excluding the "Uso general" behavior-driven aggregate, which has no defined peak-watts figure (only kWh/día), so this is an honest lower bound, not a complete simultaneous-load figure. Documented as such in the function's docstring and the caption on-screen.
- **Wizard wiring**: table gained per-scenario "Inversores"/"Potencia inversor (W)"/"Carga conectada / inversor" columns (previously constant columns); cards show a "🔌➕ Inversores duplicados" note when scenario 3 actually doubles, or a "⚠️ Carga conectada usa el X%..." note on scenarios 1/2 when tight but not growing. Opción 1's header caption updated to explain the check.
- **A real propagation bug found and fixed while wiring this in**: `inverter_qty` had never been persisted into the wizard's result dict at all — Step 7 (`step7_costs()`) and Step 8 (`step8_review()`) each independently *recomputed* `2 if split_phase.get("requires_split_phase") else 1` from scratch, completely blind to whatever Step 6 had actually resolved. This was harmless before (recomputing the same fixed formula independently three times still gave the same answer), but would have silently broken the moment scenario 3 doubled inverters — Step 6 would show 4 inverters while Step 7's cost table and Step 8's PDF data would still show 2, an invisible-until-invoiced inconsistency. Fixed by adding `"inverter_qty": final_inverter_qty` to the Step 6 result dict (`final_inverter_qty` resolved from `chosen["inverter_qty"]` for auto scenarios, or the base split-phase-driven value for manual mode/no-selection) and changing both `step7_costs()` and `step8_review()` (including the PDF `technical.inverter_count` field) to `equipment.get("inverter_qty") or (2 if split_phase.get("requires_split_phase") else 1)` — preferring the stored value, falling back to the old formula only for proposals saved before this change existed. `wizard/hybrid.py` inherits the fix automatically (it delegates straight through to `wizard.off_grid`'s step functions).

**Verified**: standalone script confirmed the headroom math directly against `generate_reliability_scenarios()` — at 75% utilization (2×5kW inverters, 7.5kW load) nothing triggers; at 82% (8.2kW load) scenarios 1/2 show `inverter_headroom_tight=True` unchanged at 1×qty, scenario 3 shows `inverter_qty=4`/`inverter_growth_added=True`. Live in the browser, two passes: (1) a "comfortable" ~10%-utilization case (default 0.5kW Refrigerador only) confirmed the new caption/columns/cards render with no false-positive warnings — all three scenarios show "Inversores: 1 (5,000 W)," nothing flagged; (2) a deliberately overloaded case ("Headroom Trigger Test" — Refrigerador 0.5kW + Aire acondicionado 1.5kW + Cargador de auto eléctrico 7.0kW = 9.0kW connected load against the single 5kW inverter, 180% utilization) actually triggered the feature live: Scenarios 1 and 2 both showed "⚠️ Carga conectada usa el 180% de la capacidad del inversor — poco margen para agregar cargas más adelante" while staying at 1×5,000W; Scenario 3 showed **2 (10,000 W)** inverters with both the growth-string note and "🔌➕ Inversores duplicados — carga actual usa el 180% de un solo juego, sin margen para crecer," and its array grew to 16 panels/4 strings vs. 12/3 for scenarios 1–2 (the extra growth string). Confirms the full chain end to end: connected-load sum → 80% threshold → differential treatment (warn-only for 1/2, double for 3) → correct array/table/card rendering.

Getting load #2's UI interaction to register was itself a small debugging story: Streamlit's "Agregar cargas comunes" multiselect (a BaseWeb Select rendered in a floating popup) would not accept clicks or keyboard selection via the browser tool's normal `computer` click/type actions — the popup would open and then silently close on click with no option selected, repeatedly, including via ref-based clicks. Root cause turned out to be a coordinate-space mismatch specific to this session's browser tool (click coordinates were being read off screenshots but interpreted as viewport-space, overshooting the actual option's on-screen position by roughly 2×). Fixed by finding the target `<li>` element directly via `document.querySelectorAll` and dispatching a real `mousedown`/`mouseup`/`click` sequence at its own `getBoundingClientRect()` center via `javascript_tool` — bypassing coordinate translation entirely. Worth remembering for any future BaseWeb/Streamlit multiselect interaction in this app if plain clicks stop registering. Test proposal and prospect deleted from Supabase after verification; dev server stopped.

### Off-Grid load taxonomy: 6th category "appliance" + "Uso general" recalibrated (2026-07-28, user direction over two rounds)

User supplied five loads to add to the picklist with usage patterns (microondas 1500 W ×3 usos/noche, cafetera 750 W, pantalla TV 45 W siempre prendida, plantilla eléctrica 1000 W, iluminación 100 W ext / 20 W int solo turno noche) and asked whether lighting was already covered by "Uso general".

**Round 1 — the discovery.** All five were already mapped `behavior_driven` in `_PRECLASSIFIED_V1`, and `build_load_profile()` **skipped** behavior_driven loads entirely (`continue` — never reached `lines`). The catalog excluded them on purpose with a comment saying so. So adding them as-is would have been a silent no-op: 0 kWh **and** 0 W. The 0 W half was a genuine gap — Step 6's inverter-headroom check sums `connected_power_kw` across profile lines, so a site with a 1500 W microwave + 1000 W hotplate + 750 W coffee maker reported **0 W** of connected load. Their daily kWh is small but their simultaneous peak is exactly what sizes an inverter. Implemented (user-approved): behavior_driven loads now emit a line with `estimated_kwh_day=0.0` + real `connected_power_kw`, badged `⚡ Solo potencia (W)` (new `CONFIDENCE_POWER_ONLY`, deliberately not `default_assumed` so it doesn't trip the "revísalas" banner). Verified: energy stayed 8.70 kWh/día, connected load went 0.5 → 3.915 kW.

**Round 2 — the better model (supersedes round 1 for appliances).** User then proposed pulling appliances out of "Uso general" entirely and giving them their own kW *and* kWh, leaving the aggregate for "iluminación/tomacorrientes only — considerando que en tomacorrientes pueden haber computadores, routers, relojes". Implemented:

- **New 6th category `appliance`** ("Electrodomésticos (microondas, TV, lavado)") sized from a new `APPLIANCE_USE_KWH_DAY_V1` benchmark table (microondas 0.40, plantilla 0.75, cafetera 0.30, TV 0.45, lavadora 0.50, secadora 1.50, licuadora 0.05 kWh/día), derived from the user's stated patterns. Same shape as `estimate_fixed_cycling()` — a kWh/día benchmark, **not** nameplate×hours, so the taxonomy's "never ask the customer for horas de uso" rule still holds. `estimate_appliance_use()` matches longest-key-first so "plantilla eléctrica" beats bare "plantilla" and "pantalla tv" beats "tv".
- **`behavior_driven` narrowed** to lighting + always-on receptacle background load. `computadora`/`router`/`módem`/`reloj`/`cargadores` deliberately STAY here per the user's framing (continuously-connected plug load = "tomacorrientes"), while task appliances (microondas, lavadora, secadora, licuadora, cafetera, TV, plantilla) moved to `appliance`.
- **`BEHAVIOR_KWH_PER_BEDROOM_DAY_V1` recalibrated v1→v2: 1.5/2.5/4.0 → 0.5/0.8/1.3** kWh/día/espacio (user-chosen). **This was mandatory, not cosmetic** — the old tiers were *defined* as including appliances (tier text literally read "TV, computadora, lavadora, cocina eléctrica ocasional"), so itemizing appliances without dropping the tiers would be a straight double-count. The two tables are now coupled; there's a ⚠️ comment on each pointing at the other.
- **Iluminación keeps the round-1 watts-only mechanism** — it's the one remaining behavior_driven catalog entry, energy in the aggregate but real watts to the inverter check. That's why round 1's work is still load-bearing.
- Propagated the new category through: `CATEGORIES`, `CATEGORY_LABELS_ES`, `_CLASSIFY_PROMPT`, `_DEFAULT_HOURLY_SHAPES` (own cooking/laundry curve), `_HOURLY_SHAPE_PROMPT`, `_CATEGORY_CHART_COLORS` (#7c3aed), plus Step 4's "Uso general" caption, "Cargas individuales" caption and `_USAGE_LEVEL_DESCRIPTIONS` (which still described the old scope).

**Bug caught while wiring it.** The AI classifier's fallback was `behavior_driven`. Post-split that means "0 kWh line", so any load the classifier couldn't handle would have silently contributed nothing to sizing — a worse failure than before, when the fat aggregate absorbed it. Changed to `_CLASSIFY_FALLBACK = "appliance"`, which yields `_APPLIANCE_USE_DEFAULT_KWH_DAY_V1` (0.30) flagged `CONFIDENCE_DEFAULT` and therefore surfaces in the wizard's "revísalas antes de continuar" banner — visible and reviewable instead of a silent zero.

**⚠️ CALIBRATION IMPACT — flagged to the user, not yet resolved.** For an equivalent fully-itemized home (refrigerador + 6 appliances, 3 espacios Estándar) the new model estimates **6.05 kWh/día vs 8.70 under the old one — about 30% lower**, which shrinks every off-grid array and battery bank proportionally. Two readings: either the old 2.5/espacio catch-all was over-generous, or the new 0.8 is too lean. There's no metered CR data in the project to settle it, and under-sizing an off-grid system is a much worse failure than over-sizing (no grid to fall back on). The lever is `BEHAVIOR_KWH_PER_BEDROOM_DAY_V1` — restoring ~8.7 kWh/día for that same home would need roughly **1.68** kWh/día/espacio Estándar instead of 0.8. Revisit before quoting real jobs.

**Verified**: classification split checked for all 14 relevant load names; profile math confirmed (appliances carry own kWh + W, iluminación 0 kWh + W, total 5.50 with agregado 2.40 = 0.8×3); live browser pass through Steps 4→5→6 on a fresh Off-Grid proposal confirmed the new "Electrodomésticos" rows with "Tabla de electrodomésticos v1" detail, the "⚡ Solo potencia (W)" lighting row, the new purple category in the Consumo-por-categoría chart, no spurious warning banner, and Step 6 scenarios/charts rendering correctly off the new totals. Test proposal and prospect deleted from Supabase; dev server stopped.

### Off-Grid Step 6: panel count + string arrangement added to the scenario cards (same day, user request off screenshots)

The Opción 1 scenario cards and Opción 2's "Proyección" card listed inversores, baterías and controladores but not the array itself — panel count only appeared in the selector button above each card ("Escenario 1 — 3 paneles"), and the string arrangement only in the table further up. Added a line to both card types, placed first among the equipment lines since the array is what the scenario actually varies:

`🔢 Paneles: <b>N</b> (X en serie × Y en paralelo)`

Verified live on an existing Off-Grid draft (PC-2026-006, split-phase 2×inverter case): all three auto-scenario cards show it (8 paneles = 4×2 for escenarios 1–2, 12 = 4×3 for escenario 3) and the manual Proyección card shows it too, matching its own chip row.

### Step 8: equipment-name crop fixed + AI-generated intro paragraph wired up (2026-07-28, user request)

**1. Cropped equipment names.** Both wizards' `_kv()` summary-card helper styled subtitles `white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:160px`, so equipment model numbers truncated ("Victron Energy MultiPlus-II 48/3…", "Victron Energy SmartSolar MPP…"). A clipped model number is worse than a two-line one — the reader can't tell which unit was quoted. Switched to `white-space:normal; overflow-wrap:anywhere; line-height:1.35; max-width:190px` in **both** `wizard/off_grid.py` and `wizard/grid_zero.py` (same helper, same bug); the flex row just grows taller.

**2. AI intro paragraph.** `ai/proposal_writer.py` had been a `raise NotImplementedError("Phase 4")` stub since Phase 0, and Grid Zero's Step 8 caption still read "En Fase 4 lo generará Claude". Implemented `generate_intro(system_params, language)`:
- One prompt serves both wizards via `_FACT_LABELS_ES`, an allow-list of recognized keys rendered as a labelled facts block. Absent keys are skipped, so Grid Zero passes savings/ROI while Off-Grid passes battery/autonomy. **Keys not on the list are never shown to the model**, so internal fields can't leak into a client-facing PDF.
- Prompt forbids inventing any figure not supplied (no prices, plazos, garantías, percentages) and forbids guaranteed-results language — these are design estimates.
- `_SYSTEM_TYPE_HINTS` gives the model the grid_zero / off_grid / hybrid distinction so it doesn't describe an off-grid system as grid-connected.
- Never raises: any API failure falls back to a deterministic paragraph built from the same figures, so PDF generation can't be blocked by a network hiccup. A reply under 40 chars is also treated as failure rather than written into a PDF.
- Wired into both wizards as a "✨ Generar con IA" button above the textarea, with a caption stating plainly what the IA may and may not use.

**Two bugs caught during verification, both fixed:**
- **English requests came back in Spanish.** The prompt is Spanish and ended "Responde … en inglés" — the surrounding language dominated and the model answered in Spanish anyway. Fixed by replacing `_LANG_NAMES` with `_LANG_INSTRUCTION`, where the English variant states the requirement *in English* ("IMPORTANT — LANGUAGE: Write your answer in ENGLISH, not Spanish…"). Re-tested: EN now returns English, ES unaffected.
- **Generated text never appeared in the textarea.** `st.text_area(..., key="w8og_intro")` keeps its value in session_state under its own key, and that wins over the `value=` argument on rerun — so writing only `wizard_proposal_text` left the box visibly empty even though generation had succeeded. Fixed by assigning the widget key too before `st.rerun()`. That in turn tripped Streamlit's "created with a default value but also had its value set via the Session State API" warning, so the textarea now seeds its key once via `setdefault()` and drops `value=` entirely — the idiomatic pattern. Same fix applied to Grid Zero's `w8_intro`.

**Verified**: standalone calls against the real API for off-grid ES/EN and grid-zero ES — output used only the supplied figures, correct system-type framing, no invented numbers. Live in the browser on an existing Off-Grid draft: equipment names now wrap in full, "✨ Generar con IA" produces an accurate paragraph (8 paneles Canadian Solar CS7N-620MS, 4.96 kW, 2 inversores MultiPlus-II 48/5000/70-50, banco de 4 baterías 19.2 kWh, 1 día autonomía, 15.58 kWh/día generación vs 8.7 kWh/día consumo), and no Streamlit warning. Test cost/intro edits reverted on the shared draft; dev server stopped.

### PDF: filename convention, header rule position, monthly-coverage chart (2026-07-28, user request off a real generated quote)

**1. Download filename convention.** Was `cotizacion_{cliente}_{ES|EN}.pdf` — no quote number, so a folder of downloads didn't sort and revisions overwrote each other. New convention, implemented as `pdf_filename()` in `wizard/state.py` (one shared implementation, both wizards import it):

`PC-2026-009_Henry_Garita_ES.pdf` — **quote number first** so a folder sorts numerically/chronologically on its own, then client, then language. The version suffix rides along inside the quote number when present (`PC-2026-009-v2_...`), so revisions never collide. Falls back to `Cliente_ES.pdf` when a draft has no quote number yet rather than emitting a leading underscore. `_safe_filename_part()` collapses unsafe characters to single underscores but **keeps accents** — "Peña" reading as "Pena" in a client-facing filename looks like a typo. Supabase Storage paths (`upload_pdf()`) deliberately left alone: they're keyed by proposal_id/version and changing them would orphan existing stored PDFs.

**2. Green rule moved between the two title lines.** Was `border-bottom` on `.title-solar` (under "ENERGÍA SOLAR"); now on `.title-cotizacion`, which also became `display:inline-block` so the rule is exactly as wide as the word "COTIZACIÓN" rather than spanning the whole flex column, with `.title-solar` back to a plain block beneath it. Applied to all four templates (both system types × ES/EN).

**3. Monthly-coverage chart** in the empty space above "Más información", per user pick from three options. New `proposals/charts.py` → `monthly_coverage_svg()`: 12 green bars of estimated monthly generation against a navy consumption line, month labels, ½/max gridlines, legend, ES/EN.
- **Hand-built inline SVG, not matplotlib/plotly** — WeasyPrint renders inline SVG directly, so no new dependency, no temp image files, no external fetch (templates are otherwise pure HTML/CSS + base64 assets). Only rect/line/polyline/circle/text are used; WeasyPrint's SVG support doesn't cover filters, gradients or CSS-in-SVG.
- Built in `generate_pdf()` rather than in each wizard, so both system types and both languages share one implementation; returns `""` on unusable data (missing / wrong length / all zeros) and the template `{% if %}`s the whole section away.
- Units are **kWh per month**, not per day — that's what a client recognizes from a bill. Grid Zero feeds its 12 real billed months + PVGIS-driven `sizing["monthly_generation"]`; Off-Grid feeds PVGIS × array kW × 0.80 derating vs. daily consumption × real days-in-month.

**Two bugs caught during verification:**
- **SVG would have rendered as escaped text.** The Jinja `Environment` uses `autoescape=True`, so `{{ coverage_chart_svg }}` emits literal markup. Fixed with `| safe` in all four templates.
- **Grid Zero charts came out entirely amber.** The chart colours a bar amber when generation falls below consumption — correct for Off-Grid, where there's no grid to fall back on and a shortfall is a real finding. But **Grid Zero is deliberately sized to cover daytime consumption only**, with the grid supplying the rest, so generation sits below the line *every month by design*. First render of the María José reference painted all 12 months amber plus a "Mes bajo cobertura" warning legend — reading as "your system fails year-round" on a perfectly correct quote. Fixed with a `flag_shortfall` parameter, passed as `system_type != "grid_zero"` from `generate_pdf()`.

**Verified**: rendered real PDFs for both system types. Header rule sits between COTIZACIÓN and ENERGÍA SOLAR; Grid Zero chart renders all-green under the consumption line with no warning legend; Off-Grid with a deliberately weak month renders 3 amber bars + the warning key; guards return "" for empty/short/all-zero input; EN template produces English month abbreviations. `pdf_filename()` unit-checked across normal, versioned, no-quote-number and punctuation-heavy client names.

### PDF coverage chart: VRM restyle + the fixed-footer page-overlap bug (2026-07-29, user follow-up)

User reported the freshly-added coverage chart **overflowed the page** and asked for something "more subtle, like the same design we are using for vrm custom pdf reports."

**1. Chart rewritten to VRM proportions.** `proposals/charts.py` now mirrors `victron/report_svg.py`'s `bar_chart_svg()` so the quote PDFs and the VRM weekly reports read as one family: same 520-unit content width, same 78-unit bar height, same paired-bar layout, same muted grey labels (`#aaa` / `#bbb`), same palette (`GREEN #1FAE6E`, `MINT #C8DDD5`, `AMBER #D4860F`, gridlines `#E8EDEA`). Total SVG height dropped **236 → 114**. Consumption changed from a navy overlay line to a mint paired bar — easier to read at this size and consistent with VRM. Only `_nice_ceiling()` deliberately diverges from VRM's ceil-to-next-10: monthly kWh runs into the hundreds/thousands, where rounding 1,475 to 1,480 gives an axis label nobody reads.

**2. The real overflow cause was a pre-existing template bug, not the chart's size.** `.footer-wrap` is `position: fixed`, so WeasyPrint paints it on **every** page, while the space for it was being reserved with `body { padding-bottom }` — which only adds trailing space after the last element and reserves nothing on the pages before it. Any content tall enough to reach the bottom of a page therefore rendered *underneath* the footer. The chart was simply the first block big enough to expose it. Bumping the padding (60pt → 78pt) did not help, confirming the diagnosis. Fixed in all four templates by reserving the band in the page box itself:
```css
@page { size: A4; margin: 0.75cm 1.2cm 2.7cm 1.2cm; }
.footer-wrap { position: fixed; bottom: -1.95cm; left: 0; right: 0; }
body { padding: 0; }
```
The negative `bottom` pulls the fixed footer down into the reserved margin band. This benefits every long proposal, not just ones with a chart.

**3. Caption orphaning.** With the above fixed, Off-Grid still split the block: chart on page 1, the two-line `.coverage-note` alone on page 2, wasting a whole sheet on a caption. Fixed by shortening the note to one line ("Estimaciones de diseño según la irradiancia solar real del sitio; la producción real varía según clima, sombreado y uso.") and wrapping title + chart + note in a `.coverage-block { page-break-inside: avoid }` container so they move as a unit.

**Verified**: re-rendered both system types (Jorge Ramírez off-grid with a deliberately weak November, María José grid-zero). Off-Grid now fits on **one page** — chart, one-line note and footer cleanly separated, the weak month correctly amber with the "Mes bajo cobertura" key. Grid Zero's page 1 is fuller (~47pt free vs. the block's ~140pt), so the whole block moves to page 2 **intact** — the intended trade-off, and still correctly all-green with no shortfall flag.

**Follow-up same day**: user asked to shrink the chart and caption further and center them on the page (a screenshot showed the chart still reading a bit large next to the rest of the document, which is otherwise all left-aligned tables). Rather than touch `charts.py`'s SVG geometry — deliberately pinned to VRM's proportions — capped it with CSS on the container: `.coverage-chart { max-width: 320pt; margin: 3pt auto 1pt auto }`, and centered the caption under it at a smaller size (`.coverage-note { max-width: 320pt; margin: 0 auto 6pt auto; font-size: 6pt; text-align: center }`, was 7.5pt left-aligned). The "COBERTURA MENSUAL ESTIMADA" section title stays left-aligned, matching every other section header on the page — only the chart+caption are centered. Verified on fresh renders of both system types.

### Real battery SoC simulation for Off-Grid/Hybrid scenarios (2026-07-29, design pass requested by user)

User's framing: "the secret behind this solar tool we are building is to be as precise as possible for the real world in which the system will live... so I won't have any surprises or mad customers." This drove a full design pass (planned, then implemented) replacing two static, single-shot calculations with a real day-by-day battery energy-balance simulation.

**What was static before:** `size_battery_for_min_soc()`'s `min_soc_actual_pct` was one ratio (`100 - daily_kwh_consumption/total_kwh_installed×100`) — a single average day's cycle depth, blind to multi-day cloudy streaks. `find_array_for_reliability()` checked *monthly-average* PVGIS generation against consumption in ≥N of 12 months — a "9/12 months OK" result said nothing about whether the 3 weak months contained one two-week streak or twelve isolated bad days. Neither had round-trip battery efficiency anywhere in the codebase.

**1. Real daily generation data.** New `calculations/pvgis.py: fetch_daily_series(lat, lon)` calls PVGIS's `seriescalc` endpoint (hourly PV output for one real historical year — not the monthly averages `fetch_irradiance()` already provides) and aggregates to 365 daily kWh/kWp values. Deliberately *not* PVGIS's spliced "TMY" construction (which blends different real months from different years and would erase real cross-month cloudy streaks) — one real year preserves genuine day-to-day and multi-day sequences. The valid historical-year range varies by location/radiation database (confirmed via direct API testing: Costa Rica sits on PVGIS-NSRDB, valid 2005–2015, not the 2005-2020 range a naive guess would assume) — `fetch_irradiance()` now also captures `year_min`/`year_max` from PVGIS's own response metadata so `fetch_daily_series()` requests a real in-range year instead of guessing; a 400-response fallback parses PVGIS's own error message for the true bounds and retries once, so a stale monthly-cache row from before this field existed can't wedge a site. Cached separately from the monthly series (`pvgis_daily_{lat}_{lon}` key) since it's a different endpoint/payload shape. `wizard/common.py: step3_site()` fetches it alongside the monthly series, but only for Off-Grid/Hybrid (`system_type` read from `wizard_meta`) — Grid Zero has grid backup and no battery-reliability concept, so it skips the extra ~800KB PVGIS call entirely.

**2. `calculations/sizing_off_grid.py: simulate_battery_soc()`** — new day-by-day energy-balance loop: each day, generation (already array-kW-scaled and derated) charges the battery up to its cap, consumption discharges it, and a hard DoD floor prevents going lower (real systems load-shed instead — counted as an `unmet_load_day`). Round-trip efficiency (`_BATTERY_ROUND_TRIP_EFFICIENCY = 0.92`, a documented LiFePO4-typical assumption — no per-battery spec field exists yet) is applied to the full day's generation before it enters the battery, a deliberately conservative simplification since in reality some generation goes straight to direct-use loads with no round-trip loss at all. Returns `min_soc_actual_pct` (worst SoC reached all year — replaces the old static ratio), `days_full_pct` (replaces "months OK"), `unmet_load_days` (real blackout-risk days — this is what scenario search gates on), and `longest_low_soc_streak_days` (informational — extended shallow cycling that stresses the battery without ever actually blacking out).

**3. Deliberately did not promote the Step 5 illustrative hourly load shape.** `calculations/load_profile_off_grid.py`'s per-category hourly curves are explicitly AI-generated and documented as "never used for sizing." Using them here would quietly turn an uncalibrated visualization aid into a load-bearing input — the wrong direction for "no surprised customers." The simulation instead runs at **daily** resolution: real generation variability, flat daily consumption. Documented as the pass's known ceiling (can't distinguish a load lining up with the solar peak from the same load right after sunset) pending real hourly data from installed VRM sites.

**4. Wired into the search, not bolted on after.** `find_array_for_reliability()` (`calculations/mppt.py`) now takes a fixed battery `capacity_kwh` (computed once per scenario *before* the array search, since battery capacity only depends on consumption + the min-SoC preference, not array size) and, per candidate string count, runs the simulation and checks `unmet_load_days` against a per-scenario tolerance — replacing the monthly-average check. `_RELIABILITY_SCENARIO_DEFS`'s old `required_months_ok` (9/11/12) became `max_unmet_load_days` (15/5/0) — a **deliberate reinterpretation, not a unit conversion**, documented in-code: a "bad month" under the old check meant the month's average fell a little short while the battery still cycled normally; an "unmet load day" under the new one means the battery actually hit its floor — a real field outage. `generate_reliability_scenarios()` keeps its existing return shape (every key `wizard/off_grid.py`'s table/cards/downstream charts already read) — `min_soc_actual_pct`/`driven_by` now come from the simulation, plus the three new keys folded into the `battery` sub-dict.

**Bug caught during verification:** "Validación del diseño"'s "SoC mínimo seguro" row independently recomputed `100 - battery_bank["discharge_pct"]` — the *old* static ratio, never touched by the simulation — so it silently diverged from the scenario card's now-simulated `min_soc_actual_pct` (e.g. card showed 57%, Validación showed 62%, same scenario). Fixed to read `min_soc_actual_pct` directly, renamed to "SoC mínimo real (año simulado)" to distinguish it from the still-static "Profundidad de descarga (día típico)" row above it, and gated the pass/fail on `unmet_load_days == 0` too — without that, a scenario with real blackout days would clamp to exactly the floor value and read as a false "OK".

**Verified**: standalone script against real DB equipment (Canadian Solar 620W / Victron SmartSolar 250/100 / Pylontech US5000C) — full 3-scenario generation with a real 365-day Atenas series ran in **18ms**; a synthetic 10-day-zero-generation stress test correctly produced 9 unmet-load days and a 14-day low-SoC streak. Live in the browser: built a fresh Off-Grid draft through Step 6 — scenario 1 correctly showed 1 unmet-load day (amber warning) while 2/3 showed zero; Validación/card numbers matched after the fix; switching scenarios live-updated every downstream chart (Cobertura estacional, Flujo de energía, Sensibilidad) with no visible lag. Also opened a **pre-existing** Off-Grid draft (Henry Garita, created before this change, no cached daily series) and confirmed the on-demand fallback fetch in `wizard/off_grid.py` transparently backfilled it and rendered correctly, including the inverter-headroom warning path. Test proposal/prospect ("SoC Sim Test") deleted from Supabase after verification; dev server stopped. Left the two `pvgis_daily_*` cache rows created during testing (Atenas and Henry Garita's site) in place — they're shared infrastructure cache, not proposal data, and removing them would just force a redundant PVGIS refetch for real future work at those sites.

**Not done this pass (flagged for later):** `Cobertura estacional`'s monthly chart still reads the coarse monthly-average PVGIS series — intentionally left alone since that section's own caption already discloses it ignores battery buffering; and the manual-mode (Opción 2) battery bank still uses the old static `size_battery_bank()`, not the simulation, since manual mode has no fixed scenario reliability target to search against — `battery_bank.get("min_soc_actual_pct")` gracefully falls back to the static computation there, unchanged from before.

### Stacked battery-recharge PDF chart, then solar curtailment/utilization metric for both system types (2026-07-30, user follow-up requests)

**1. PDF chart: real stacked "Recarga de batería" segment.** Following the SoC-simulation round above, the user asked to actually show battery recharge being considered in the PDF's monthly coverage chart. `simulate_battery_soc()` (`calculations/sizing_off_grid.py`) already tracked `daily_charge_in_kwh`; exposed it and aggregated to 12 real monthly totals. `proposals/charts.py: monthly_coverage_svg()` gained an optional `recharge_kwh` param — when given, the right-hand bar stacks mint (consumo) + navy (recarga) instead of a plain mint bar; Grid Zero (no battery) passes `None` and keeps the original plain bar, fully backward compatible. Verified via a real render against Henry Garita's actual persisted equipment — the stack matched the simulation exactly, and the visual gap between the green generation bar and the mint+navy stack turned out to be a real, previously-invisible finding: the array was drastically oversized for a 4.8 kWh battery (71% of a year's generation curtailed), which led directly to the next request.

**2. Solar curtailment/utilization metric, both system types.** User: "each scenario should include it accordingly and the summary chart right before generating the pdf... also add to DETALLES TÉCNICOS."

- **Off-Grid/Hybrid** (`calculations/sizing_off_grid.py: simulate_battery_soc()`): added `utilization_pct`, `total_generation_kwh`, `curtailed_kwh` to the return dict — curtailed = generation the battery had no room left to store (`max(0, gen_kwh*eff - charge_in)`), summed across the simulated year. Folded into `generate_reliability_scenarios()`'s `battery` sub-dict for the 3 auto scenarios; `_og_scenario_projection()` (manual mode, `wizard/off_grid.py`) gained an optional `daily_kwh_kwp` param to run the same simulation against the manual array + its own sized battery bank, so manual mode gets the identical real number, not an approximation. Surfaced in the Step 6 scenario table (new "Aprovechamiento solar" column), every scenario card (auto and manual), and a new Step 8 section — "☀️ Aprovechamiento de generación solar" — with a stacked horizontal bar (Aprovechado vs. Curtailed, kWh/año) and a "sistema sobredimensionado" warning below 50%, positioned right before the "Generar PDF" button. The Step 8 computation (`_og_monthly_coverage_and_sim()`, new module-level helper) was refactored out of the "Generar PDF" click handler — it used to run only after clicking; now it runs unconditionally near the top of `step8_review()` so the summary section has real numbers before the button is ever pressed, and the click handler just reuses the same result instead of recomputing.

- **Grid Zero**: no new calculation needed — `_scenario_projection()` (`wizard/grid_zero.py`) already computed `self_consumption_pct` and `curtailed` from the AI-estimated daytime-consumption fraction (`_estimate_daytime_fraction_ai()`), already shown per-scenario as "⚡ Autoconsumo: X%" on the cards. It just wasn't (a) in the scenario table, (b) persisted past Step 6, or (c) shown at Step 8/in the PDF. Added to the `scenario_data` table, persisted into `wizard_equipment["projection"]` (plus `daytime_fraction_note`, since the AI note itself lived in a transient `w6_coverage_ai` session key that `_autosave()` never serializes — same class of bug as the Atrás fix below, fixed the same way: persist it explicitly rather than relying on a key that silently doesn't survive a resumed session) at Step 6's "Siguiente", and surfaced at Step 8 with the same stacked-bar-chart treatment as Off-Grid, sourced from the persisted `projection` instead of recomputing.

- **PDF**: both `_build_context_off_grid()` and `_build_context()` (`proposals/generator.py`) gained a new `technical` field (`utilization_pct` / `self_consumption_pct`), formatted with a `"—"` fallback when the underlying simulation/AI estimate was never available (old draft, fetch failure) rather than crashing on `None`. All 4 templates gained a new "Aprovechamiento solar" / "Solar utilization" column in DETALLES TÉCNICOS — next to "Descarga máxima de batería" for Off-Grid/Hybrid, next to "Inversores" for Grid Zero — with `.tech-table` widths bumped (Off-Grid 68%→80%, Grid Zero 56%→68%) to fit the extra column at the existing 6.5pt font size.

**Bug found and fixed along the way (unrelated to the metric, surfaced while testing on a real draft): Step 4/5's "← Atrás" silently dropped unsaved edits.** User: "individual loads are not being saved in cache when selecting Atrás." Root cause, confirmed directly from Henry Garita's persisted Supabase row: `loads`/`loads_display` contained only `[Refrigerador]`, while the persisted `daily_kwh` (1.95) mathematically only reconciled with a completely different load set (3 appliances, no Refrigerador) — proof the two had desynced. Mechanism: every step's "← Atrás" button only changed `wizard_step` and called `_autosave()`, which persists whatever is *already* sitting in `wizard_consumption`/`wizard_equipment` — it never re-saved the current step's live-edited widget state first (unlike "Siguiente", which always does). Any edit made after the last "Siguiente" click and before "Atrás" — or before the browser session simply ended — only ever lived in an ephemeral per-step session key (`w4og_loads_data` for Step 4's table) that a resumed session doesn't have, so it silently evaporated. Fixed in `wizard/off_grid.py`: Step 4's "← Atrás" now saves the table via a shared `_build_consumption_result()` helper (factored out of the "Siguiente" handler so both use identical logic, not two copies that can drift), and Step 5's "← Atrás" now saves the calculated `profile`/`daily_kwh` the same way. Grid Zero's equivalent "Atrás" buttons have the same shape and weren't touched this round — flagged, not fixed, since the user only reported the Off-Grid case.

**Verified live end-to-end, both system types, real drafts (not synthetic data):**
- Off-Grid (Henry Garita, PC-2026-009): reproduced the bug's exact symptom in the browser (Step 4 showed only Refrigerador after navigating back), used it as a live test of the fix — added the 3 missing appliances back via the catalog picker, clicked "← Atrás" (not "Siguiente"), confirmed directly in Supabase that all 4 loads persisted correctly this time. This also happened to repair the real draft's data (daily_kwh now correctly reconciles: 3.15 kWh/día from all 4 loads, was 1.95 from a mismatched set). Continued forward through Steps 5→8: "Aprovechamiento solar" showed 45% on both the Step 6 table and every scenario card, matching exactly at Step 8's summary chart (45% · 1,392 kWh aprovechado / 55% · 1,674 kWh curtailed) and the oversized-system warning; clicked "Generar PDF" for real — succeeded, 101,426 bytes, no errors.
- Grid Zero (Oscar Pauly, PC-2026-004): "Autoconsumo" cards unchanged (30/30/25%); Step 8's new section correctly showed 30% · 104 kWh aprovechado / 70% · 242 kWh curtailed, the AI daytime-fraction note reproduced correctly (proving the `daytime_fraction_note` persistence fix works), and the oversized-system warning appeared. Clicked "Generar PDF" for real — succeeded, 105,385 bytes, no errors.
- Also confirmed via standalone script (real DB equipment, real Atenas PVGIS series) that `utilization_pct` decreases as array size grows relative to a fixed battery (32% → 32% → 20% across scenarios 1/2/3) — the metric moves in the correct direction under a controlled change.
- No new test proposals were created this round (verification used the user's own existing drafts), so no Supabase cleanup was needed — Henry Garita's draft was left in a *better* state (correct load data) than found. Dev server stopped after verification.

### Same PDF stacked chart, live, in Step 6 "Equipos" (2026-07-30, same-day follow-up)

User: "I want this same generation/consumption stacked bar in the '6. Equipos' above 'Cobertura estacional', for both off grid/hybrid and grid zero wizards according to each type in the proposal PDFs."

Implemented by calling `proposals/charts.py: monthly_coverage_svg()` directly from the wizard and embedding the returned SVG via `st.markdown(svg, unsafe_allow_html=True)` — genuinely the same chart (same function, same call), not a re-implementation that could drift from the PDF over time.

- **Off-Grid/Hybrid** (`wizard/off_grid.py`, `step6_equipment()`): new "Cobertura mensual estimada" section inserted right above the existing "Cobertura estacional" line chart. Reuses `_og_monthly_coverage_and_sim()` (the same helper Step 8 already used) but called with this step's *live* `display_array_kw`/`battery`/`battery_bank` instead of the final persisted equipment — so it re-renders immediately as the user switches between Escenario 1/2/3 or drags the manual sliders, same as every other chart on this step. Docstring updated to note the helper is now shared by three call sites (PDF, Step 8 summary, Step 6 live preview) rather than two.
- **Grid Zero** (`wizard/grid_zero.py`, `step6_equipment()`): no equivalent section existed here before, so added the same chart in the analogous spot (after the Opción 1/2 scenario/manual cards, before "Monitoreo"). Resolves the currently-selected scenario or manual config into a `system_kw`, computes monthly generation from PVGIS × that kW and real billed `months_data` for consumption (same inputs `step8_review()` already uses for the PDF), and calls the same SVG function with `recharge_kwh=None` and `flag_shortfall=False` — Grid Zero has no battery and generation sitting below consumption is the deliberate zero-export design, not a fault, so both must stay off exactly as they are for the PDF version.

**Verified live** on the same two real drafts as the prior round: Off-Grid (Henry Garita) — chart renders correctly above "Cobertura estacional," matches the PDF's proportions and colors exactly. Grid Zero (Oscar Pauly) — chart renders in the new section; consumption reads as ~0 kWh for 11 of 12 months, traced directly to Supabase and confirmed this is the test draft's own real (sparse/placeholder) `months_data` — only January has a real billed figure — not a rendering bug; the chart faithfully reflects what's actually stored. Dev server stopped after verification; no new test data created.

### Chart polish: y-axis units, interactive wizard chart, remove Sensibilidad de diseño (2026-07-30, same-day follow-up)

Three small requests after seeing the new Step 6 chart live:

**1. Y-axis units on the PDF/shared chart.** `proposals/charts.py: monthly_coverage_svg()`'s gridline labels went from bare numbers ("0", "200", "400") to "0 kWh", "200 kWh", "400 kWh". `BAR_LPAD` bumped 46→58 to fit the longer labels without clipping — re-rendered a real PDF to confirm no overflow/collision with the bars.

**2. Step 6's chart made interactive (Plotly), PDF kept as the static SVG.** New `wizard/common.py: monthly_coverage_chart()` — a Plotly twin of the SVG chart, importing the *same* color constants (`GREEN`/`MINT`/`AMBER`/`NAVY`) from `proposals/charts.py` so the two never drift apart even though they're two separate implementations now. Uses Plotly's `offsetgroup` mechanism (bars sharing a group stack; different groups sit side by side) to reproduce the same grouped-then-stacked layout — Generación gets offsetgroup 0, Consumo+Recarga share offsetgroup 1 with Recarga's `base` set to Consumo's values. Both wizards' Step 6 now call this instead of embedding the raw SVG string; the PDF path (`proposals/charts.py`, `proposals/generator.py`) is untouched — WeasyPrint can't render Plotly, so the static SVG stays there. Verified live: hovering a bar shows "Enero / Generación: 221 kWh"-style tooltips, native Plotly toolbar appears, both wizards render without error.

**3. Removed "Sensibilidad de diseño"** (Off-Grid Step 6 only — Grid Zero never had it) — the autonomy-days-vs-battery-count sweep chart, along with its now-unused local variables. "Flujo de energía" now flows directly into the Atrás/Siguiente buttons.

**Also answered**: "is it expected that scenario 1 (1 battery) and scenario 2 (2 batteries) show similar-sized 'Recarga de batería' bars?" — verified with real data (Henry Garita's actual PVGIS series, same 3.1 kW array across both scenarios): yes, expected. Recharge amount in steady state ≈ what the battery discharged the previous day ≈ daily consumption, independent of battery capacity, as long as there's enough generation headroom to top it back up. Confirmed numerically: 1,143 kWh/year (1 battery, 7 unmet-load days) vs. 1,147 kWh/year (2 batteries, 0 unmet-load days) — nearly identical recharge totals despite double the capacity. Battery size changes `min_soc_actual_pct`/`unmet_load_days`, not the recharge bar height, unless the *array* size also differs between the scenarios being compared.

### Reorder: "Validación del diseño" moved above "Dimensionamiento calculado" (2026-07-30, same-day follow-up)

User: "move 'Validación del diseño' section above 'Dimensionamiento calculado' in all system types wizards." Only `wizard/off_grid.py` (Off-Grid/Hybrid) has either section — Grid Zero's Step 6 has no equivalent titled sections (its Voc/current checks render inline per scenario card instead), so this was a single-file change.

Moved the whole block (pass/fail banner + Voc/current/discharge/SoC param rows) to right before "Dimensionamiento calculado", now gated on `if chosen:` instead of the `if display_daily_generation > 0:` guard it inherited from its old position inside "Generación vs. consumo" — none of its own logic actually needs generation to be non-zero, only a resolved `chosen` scenario/manual config. "Margen de diseño" was deliberately left in its original spot (right after "Generación vs. consumo") since the user only asked to move Validación, not Margen. One cross-block variable to watch: `imp_limit` (used by both sections) is now set inside the earlier `if chosen:` block and read again later inside `if display_daily_generation > 0:` — safe because `display_daily_generation` is set to exactly `0` in the same `if chosen is None:` branch that skips the block defining `imp_limit`, so the two guards can never disagree, but flagging the coupling here in case either guard's condition changes independently in the future.

**Verified live** (Henry Garita draft): "Validación del diseño" (✅ Configuración válida banner + 4 param rows) now renders directly above "Dimensionamiento calculado" bit; scrolled further down and confirmed "Margen de diseño" still renders correctly with real values (97%/44%/41%) — no `NameError` from the `imp_limit` cross-block reference. Dev server stopped after verification; no new test data.

### Proposals-list detail panel: cleanup + brand-color buttons (2026-07-30, same-day follow-up)

User flagged the proposals-list detail panel (the expander with "Continuar" / "Nueva versión" and the VERSIONES list, `pages/01_proposals.py`) as visually disorganized/messy, asked for buttons with no emoji, and asked for "the blue brand hex code" for the "Continuar"/"Nueva versión" buttons.

**Checked first, before assuming an answer**: `config.py` only defines `BRAND_GREEN` (#4BAE6A) and `BRAND_NAVY` (#1E2D54) — no blue brand constant exists anywhere in the codebase. The one blue-ish hex in the repo, `#1d4ed8`, is an informal Tailwind "blue-700" shade used ad hoc for a couple of wizard UI notes and the pre-existing "Enviada" status badge — never a defined brand color. Used `BRAND_NAVY` (#1E2D54) for the two buttons, since it already is the project's defined dark-blue-reading brand color.

Changes in `pages/01_proposals.py`:
- **Emoji removed** from `st.button` labels: "➕ Nueva" → "Nueva cotización", "✏️ Continuar" → "Continuar", "📋 Nueva versión" → "Nueva versión", "📄 Generar" (pill) → "Generar PDF", "⬇ PDF" (download pill) → "PDF".
- **Continuar/Nueva versión styled with brand navy** instead of default Streamlit grey secondary buttons: each wrapped in `st.container(key="det_continuar_wrap"/"det_newv_wrap")` (Streamlit 1.48 stamps a `st-key-<key>` class on the wrapper div) and targeted with new CSS in `_CSS` — Continuar is a solid navy fill (primary action, active when the version is unlocked), Nueva versión is a navy outline (secondary action, active when locked), both with explicit `:disabled` states so the inactive one reads as clearly greyed-out rather than just a lighter navy.
- **Version-row lock/sent indicators replaced**: `"🔒 Bloqueada"`/`"✏️ Borrador"` + `" · 📤 Enviada"` string concatenation replaced with proper badge pills (new shared `_pill()` helper, factored out of the existing `_badge()`) — "Bloqueada" (grey), "Borrador" (amber), "Enviada" (blue, reusing the existing active-status badge colors) — visually consistent with the proposal-level status badge already used elsewhere on the same panel, instead of icon+text clutter.

**Verified live**: opened a draft/unlocked version (Henry Garita, PC-2026-009) — Continuar renders solid navy and clickable, Nueva versión renders greyed-out/disabled, version row shows an amber "Borrador" pill. Opened a locked/sent version (PC-2026-003-v2) — Continuar renders greyed-out/disabled, Nueva versión renders navy-outline and clickable, version rows show grey "Bloqueada" + blue "Enviada" pills correctly, "Propuesta inicial" note still renders beneath. Dev server stopped after verification; no new test data created, no Supabase writes.

**Follow-up bug found from a screenshot**: a blank rounded-border box was rendering directly above the panel title, and an unwanted vertical divider sat between Continuar and Nueva versión. Root cause of the blank box: the panel's border had been built by opening a raw `<div style="border:...">` in one `st.markdown()` call and closing it with a separate `</div>` markdown call much later — but each `st.markdown()` call renders as its own isolated DOM fragment in current Streamlit (1.48), so the browser's parser auto-closes that empty opening tag immediately rather than letting it wrap the later sibling elements, leaving a stray empty bordered box and an orphaned unmatched `</div>`. This open/close-across-separate-calls pattern never actually worked as a real wrapper — fixed by replacing it with a genuine `st.container(key="det_panel_wrap")` and giving that container's `st-key-det_panel_wrap` class the border/padding/radius via CSS instead (same class-injection mechanism already used for the navy buttons above). The divider was a separate `_sep` column (`border-left:1px solid #cbd5e1`) between the title column and the two action-button columns — removed outright, columns collapsed from `[3, 0.03, 1.5, 1.5]` to `[3, 1.5, 1.5]`.

**Verified live**: reopened Henry Garita's draft — no blank box above the title, no divider between the buttons, panel border now correctly wraps the full title/buttons/versions content in one continuous box. No console errors. Dev server stopped after verification.

### Step 6 "Equipos" layout audit + Aprovechamiento solar relocation (2026-07-31)

User asked whether "☀️ Aprovechamiento de generación solar" (added the prior round, in Step 8 right before "Generar PDF") made more sense living in "Equipos" (Step 6) instead, where the user can still act on a bad number by picking a different scenario/battery/array. Agreed, then asked to move it: the **full chart** into Step 6 above "Cobertura estacional" (Off-Grid) / above the monitoring section (Grid Zero, which has no seasonal chart), and **only the resulting percentage** into Step 8's summary panel.

- **Off-Grid/Hybrid** (`wizard/off_grid.py`, `step8_review()`): removed the stacked Aprovechado/Curtailed chart + oversized-system warning entirely; added a `"Aprovechamiento solar"` KV (`{_og_sim['utilization_pct']:.0f}%`) to the existing "Generación y autonomía" row.
- **Off-Grid/Hybrid** (`step6_equipment()`): added the same chart+warning block (moved, not duplicated — deleted from Step 8, re-created here reading `_step6_sim` from the step's own live `_og_monthly_coverage_and_sim()` call) directly after "Cobertura mensual estimada" and before "Cobertura estacional".
- **Grid Zero** (`wizard/grid_zero.py`, `step8_review()`): same pattern — removed the chart, added `"Aprovechamiento solar"` to the "Técnico" KV row (Grid Zero has no "Generación y autonomía" section, so it went in the closest analogous section — the one with Sistema/Paneles/Inversores/Área). `projection = equipment.get("projection", {})` moved up to the top of the function so the KV has data before the summary panel is built.
- **Grid Zero** (`step6_equipment()`): added the chart+warning after "Cobertura mensual estimada", before the monitoring/nav section — using a fresh `_scenario_projection()` call off `_resolved_kw` (the step's already-computed currently-selected scenario/manual kW), not a duplicate computation path.

**Separately, a layout audit**: user asked three pointed questions — is Step 6's block order/categorization logical, are horizontal dividers (`st.divider()`) used correctly between sections, and is spacing consistent across the whole step. Answer, from actually reading both `step6_equipment()` functions top to bottom: the equipment-picking phase (Selección de equipos → Opción 1 → Opción 2) was cleanly divider-separated, but everything after it — 6+ chart-heavy sections in Off-Grid, 2 in Grid Zero — ran together with zero dividers until one final divider right before the Atrás/Siguiente buttons. Also, "Margen de diseño" (an electrical-limits check) sat inside the energy-flow chart run, interrupting it, when it belongs conceptually next to "Validación del diseño" (the other electrical-limits check, directly above it).

User approved both fixes:
- **Off-Grid** (`wizard/off_grid.py`): moved the entire "Margen de diseño" block (heading, caption, `_margin_pct_color()`, the horizontal bar chart) out of its old spot inside "Generación vs. consumo" and into the "Validación del diseño" `if chosen:` block, right after its `_param_row()` calls — both electrical-limits checks now read together. Needed its own `import plotly.graph_objects as go` since the original import lived further down in "Generación vs. consumo", which now runs *after* it. Added `st.divider()` in 6 places: after Validación+Margen (before "Dimensionamiento calculado"), after the chips/metric-cards block (before "Generación vs. consumo"), and between each of Generación vs. consumo → Cobertura mensual estimada → Aprovechamiento de generación solar → Cobertura estacional → Flujo de energía.
- **Grid Zero** (`wizard/grid_zero.py`): added `st.divider()` between "Opción 2 — Configuración manual" and "Cobertura mensual estimada", and between "Cobertura mensual estimada" and "Aprovechamiento de generación solar" (the latter nested inside the same `if _resolved_kw and pvgis_monthly...` guard as the chart above it, so it only appears when that chart actually rendered — no redundant divider when it didn't).

**Verified live** on both real drafts (Henry Garita off-grid, Oscar Pauly grid-zero): confirmed the new section order and every new divider renders exactly where intended, confirmed Step 8's KV percentages (45% off-grid, 26% grid-zero) match Step 6's chart percentages exactly, no console errors.

**Side effects caught and fixed during this verification pass**: navigating through both drafts' wizard steps re-triggered `_autosave()`, which bumped their persisted `meta.step_reached` forward — confirmed after the session both are back to `6` (their real state) and both proposals' `status` is back to `draft` (one was accidentally flipped to `active` via a misclick on the "→ Enviada" status pill mid-verification, caught immediately and reverted through the UI). No lasting changes to real proposal data from this session's testing.

### Grid Zero Step 6 feature parity: monitoring moved up, Validación/Margen/Dimensionamiento/Generación-vs-consumo added (2026-07-31, same-day follow-up)

User asked three things after comparing Grid Zero's Step 6 against Off-Grid's, screenshot in hand: (1) why does only Grid Zero have a "Calcular configuración MPPT" button, (2) why is Grid Zero missing Off-Grid's Validación del diseño / Margen de diseño / Dimensionamiento calculado / Generación vs. consumo / Cobertura estacional sections, (3) move "Sistema de monitoreo (opcional)" into the equipment-selection block.

**Answered #1 by reading both scenario generators**: Grid Zero's button exists because scenario generation depends on an AI call (`_estimate_daytime_fraction_ai()`, `wizard/grid_zero.py:748`) estimating what fraction of consumption falls in daylight hours — needed to size a zero-export system without oversizing into curtailment. Real LLM latency, so it's user-triggered rather than run on every rerun. Off-Grid's `generate_reliability_scenarios()` is a pure deterministic day-by-day battery simulation off cached PVGIS data — no AI call, safe to recompute automatically.

**Answered #2 by checking each section against what Grid Zero already has**, rather than assuming they were all missing: Voc/Vmp/Corriente checks already existed inline (table "Estado" column, `_mppt_param_row()` bars in the manual card) but never as a consolidated pass/fail section; "Margen de diseño" had no equivalent at all; "Dimensionamiento calculado" info existed per-scenario in cards but never consolidated for the chosen config; "Generación vs. consumo" had no standalone chart. "Cobertura estacional" was judged **not** missing — Grid Zero's existing "Cobertura mensual estimada" already covers that ground better (real 12-month billed kWh vs. Off-Grid's flat single-day average), so it was deliberately not duplicated.

Implemented in `wizard/grid_zero.py`'s `step6_equipment()`, inserted right after Opción 1/Opción 2 (same position as Off-Grid), all scoped to **inverter-only limits** — no charge controller, no battery in Grid Zero:
- **Chosen config resolved once**, either branch (`m` from `check_design()` when manual, or the matching scenario dict from `validate_string_design()` otherwise) — both share the exact same key set (`calculations/mppt.py`: `_combo_metrics()`), so everything downstream reads one `chosen` dict with no manual/auto branching.
- **Validación del diseño**: ✅/❌ banner + Voc/Vmp/Corriente param rows via Grid Zero's own pre-existing `_mppt_param_row()` (already visually identical to Off-Grid's `_param_row()` — literally where it was ported from, per that function's own comment).
- **Margen de diseño**: horizontal %-of-limit bar chart, but only 2 items (Voc, Corriente) — deliberately not 3. Vmp has a two-sided window (min *and* max), which doesn't reduce to a single "how close to a ceiling" percentage the way Off-Grid's DoD/Voc/Corriente all do; it's already a clean pass/fail in the Validación row above, so it wasn't force-fit into the margin chart.
- **Dimensionamiento calculado**: chip row (paneles, arreglo, kW, área) + 2 metric cards — "Generación mensual" and "Cobertura", **not** ported as "Generación diaria"/"Capacidad del banco" from Off-Grid, since Grid Zero's whole domain (`avg_kwh`, `_scenario_projection()`) is monthly, not daily, and there's no battery to have a "capacity" metric for.
- **Generación vs. consumo**: 2-bar chart (Generación mensual, Consumo mensual) via `_scenario_projection()` on the chosen config — no third "Recarga de batería" bar (no battery); the unused surplus is already covered by "Aprovechamiento de generación solar" further down.

**#3**: moved the "Sistema de monitoreo (opcional)" selectbox out of the bottom (right before the nav-button divider) into the equipment-selection block, in its own row right under Panel/Inversor — matching the row-per-pair layout `wizard/off_grid.py` already uses for its own monitoring selector (`row3_col1`). Added a spec-card display for the selected device (Grid Zero didn't show one before), matching Grid Zero's own inline-HTML card style for panel/inverter rather than importing Off-Grid's private `_spec_card()` helper.

**Verified live** (Oscar Pauly's Grid Zero draft, PC-2026-004): all 4 new headings render in the correct order between Opción 2 and Cobertura mensual estimada; Validación banner shows ✅ with correct Voc/Vmp/Corriente values; Margen de diseño shows exactly 2 bars (25%, 54%); Dimensionamiento calculado's "346 kWh/mes" matches the Aprovechamiento section's own generation total (90+256=346) exactly; toggled from auto (Escenario B) to manual mode live and confirmed "Configuración activa: manual" updates correctly with no crash, proving the shared `chosen` resolution works both ways. Monitoreo selector confirmed to appear exactly once, now up top. No console errors (aside from the same pre-existing background WebSocket-poll noise seen in earlier rounds, unrelated to this change). Confirmed via direct Supabase query afterward that the draft's persisted `step_reached` (6) and `mppt_scenario` (B) were untouched — the manual-mode toggle used for testing only changes `st.session_state`, never triggers `_autosave()`. Dev server stopped after verification.

### Step 6 heading system: Section/Subsection tiers, "Estadísticas" grouping, emoji removed (2026-07-31, same-day follow-up)

User flagged a concrete bug from a screenshot — "Validación del diseño" and "Margen de diseño" ran together with zero visible gap — and asked for a real fix: a proper section/subsection typographic system applied uniformly across both wizards, not a one-off patch. Asked to plan first before touching code.

**Root cause of the bug**: `_mppt_param_row()`'s rows end with `margin-bottom: 3px` (deliberately tight, so the pass/fail rows read as one block), and the "Margen de diseño" heading right after it had no defined top margin — just whatever Streamlit's theme gives an h5 by default, which wasn't enough. Nothing enforced *any* spacing between two headings placed back to back by design (no divider between grouped items) — it was accidental, not a rule, so it silently broke.

**Plan presented and approved**: a strict two-tier system — **Section** (`####`, always preceded by `st.divider()`, 1.15rem/700-weight/navy) for a major self-contained topic, and **Subsection** (`#####`, never preceded by a divider, 0.95rem/600-weight/slate) for a chart/detail that elaborates on the section directly above it, with its spacing coming entirely from a defined `margin-top` — never from a divider. This makes "grouped without a divider" read as intentional instead of missing.

Implemented as one shared function, `wizard/common.py: inject_step6_heading_css()` — a single `<style>` block targeting `[data-testid="stMarkdownContainer"] h4/h5`, called once at the top of both `step6_equipment()` functions. Scoped safely to only the currently-mounted step without any CSS-selector scoping trick, because Streamlit reruns the whole script per step change — Step 6's `<style>` tag simply isn't in the DOM when another step renders.

Heading-level changes, both wizards:
- **Off-Grid** (`wizard/off_grid.py`): "Validación del diseño" promoted `#####`→`####` (Margen de diseño stays `#####` as its subsection, no divider between them — this is the exact pair from the bug report, now spaced correctly by CSS). Removed the two dividers bracketing "Generación vs. consumo", tucking it as a subsection of "Dimensionamiento calculado" instead of its own section (it's just a chart of the same numbers). Emoji stripped from "Opción 1"/"Opción 2"/"Aprovechamiento de generación solar" headings (🔁/⚙️/☀️).
- **Grid Zero** (`wizard/grid_zero.py`): same "Validación del diseño" promotion; "Dimensionamiento calculado" promoted `#####`→`####` (was inconsistently h5 here vs. h4 in Off-Grid — a leftover from last round, now fixed); "Generación vs. consumo" divider-before removed, tucked as its subsection; **new** "Selección de equipos" `####` heading added above the Panel/Inversor pickers (Off-Grid already had one, Grid Zero didn't — added for parity); same emoji strip on Opción 1/Opción 2/Aprovechamiento.

**New "Estadísticas" section** (both wizards), per explicit user request: instead of 4 (Off-Grid) / 2 (Grid Zero) independent divider-bounded sections for the parallel chart-driven analyses, they're now subsections of one `#### Estadísticas` heading — no dividers between them, just subsection-level CSS spacing:
- Off-Grid: Estadísticas → Cobertura mensual estimada, Aprovechamiento de generación solar, Cobertura estacional, Flujo de energía.
- Grid Zero: Estadísticas → Cobertura mensual estimada, Aprovechamiento de generación solar.

**Verified live** on both real drafts: confirmed via DOM query that both wizards produce the identical heading sequence (`H4: Selección de equipos | H4: Opción 1... | H4: Opción 2... | H4: Validación del diseño | H5: Margen de diseño | H4: Dimensionamiento calculado | H5: Generación vs. consumo | H4: Estadísticas | H5: Cobertura mensual estimada | H5: Aprovechamiento de generación solar` [+ H5: Cobertura estacional | H5: Flujo de energía for Off-Grid only]); screenshotted the exact Validación/Margen pair from the bug report and confirmed clear, consistent spacing now separates them; confirmed the two headings render pixel-identical (font/size/color/spacing) across both wizards. No console errors. Confirmed via Supabase afterward that neither real draft's `step_reached` or `status` changed from this verification pass. Dev server stopped after verification.

### PDF: "Cobertura mensual estimada" moved above "Notas adicionales" (2026-07-31, same-day follow-up)

User asked to move the COBERTURA MENSUAL ESTIMADA block (in the PDF, not the wizard) to sit directly above NOTAS ADICIONALES, for both Off-Grid and Grid Zero. It previously sat at the very end of the document, right before the pinned footer, after DETALLES DE GARANTÍA.

Moved in all 4 templates (`proposals/templates/off_grid_es.html`, `off_grid_en.html`, `grid_zero_es.html`, `grid_zero_en.html`) — Hybrid needed no separate change since `proposals/generator.py` already routes it through the off_grid templates (`template_key = "grid_zero" if system_type == "grid_zero" else "off_grid"`). New order: RESUMEN/SUMMARY → **COBERTURA MENSUAL ESTIMADA/ESTIMATED MONTHLY COVERAGE** → NOTAS ADICIONALES/ADDITIONAL NOTES → DETALLES DE GARANTÍA/WARRANTY DETAILS.

**Verified**: generated real PDFs (with `monthly_coverage` data populated, since the block is conditionally rendered only when `coverage_chart_svg` is non-empty — the stock sample fixtures don't carry that field, so a first pass with them silently confirmed nothing since the block never rendered) and confirmed via `pdftotext -layout` that the section order in the actual rendered PDF output matches for both Off-Grid and Grid Zero.

### AI intro paragraph: no courtesy-opener filler, more concise (2026-07-31, same-day follow-up)

User pointed at a real generated PDF (`PC-2026-009_Henry_Garita_ES.pdf`) whose AI-written intro opened with "Con mucho gusto le presentamos esta propuesta..." — flagged as unprofessional filler — and asked for a direct, professional opener like "La presente propuesta consiste en un sistema fotovoltaico...", plus less verbosity overall (the flagged paragraph ran ~120 words across 4 sentences with some repeated figures).

Updated `ai/proposal_writer.py`'s shared `_PROMPT` (`REGLAS ESTRICTAS` section, used for both ES and EN since only `output_instruction` differs per language):
- Explicit ban on courtesy openers, naming the actual offending phrase plus common variants ("Con mucho gusto le presentamos", "Nos complace presentar", "Es un placer", "It is our pleasure to present").
- Explicit required opening pattern: `"La presente propuesta consiste en un sistema [tipo] de [potencia]..."` (or equivalent).
- Tightened from "2 a 4 oraciones" to "2 a 3 oraciones, máximo ~70 palabras en total", with an added instruction not to repeat the same figure twice or over-explain.
- Softened "tono profesional y cálido" to "tono profesional y directo" — "cálido" (warm) was likely nudging the model toward exactly the courtesy-opener style being removed.

`_fallback()` (the deterministic non-AI path used when the API call fails) was left untouched — it already opens directly with "Esta propuesta presenta..." and has no courtesy filler, so it didn't need the same fix.

**Verified** by calling `generate_intro()` directly with Henry Garita's real design figures (2.48 kW, 4 paneles JA Solar JAM66D45-620LB, Victron MultiPlus-II, 4.8 kWh, 1.95/6.69 kWh/día): 3 runs in a row all opened with "La presente propuesta consiste en un sistema fotovoltaico aislado (off-grid) de 2.48 kW...", landed at 68–72 words (down from ~120), no courtesy filler, no invented figures. Also spot-checked English (62 words, direct opener, no filler) and a Grid Zero case with savings/ROI figures (77 words, correct facts) — both wizards' fact sets flow through the same prompt correctly.

### PDF fix: moving the coverage chart had overflowed a real proposal to 2 pages (2026-07-31, same-day follow-up)

User attached two real downloaded PDFs and reported the earlier "move COBERTURA MENSUAL ESTIMADA above NOTAS ADICIONALES" change had broken a proposal that used to fit on one page — Oscar Pauly's Grid Zero EN PDF now split WARRANTY DETAILS mid-table across a page 2 that was otherwise nearly empty.

**Root cause, found by direct experimentation** (not guessed): `.coverage-block` had `page-break-inside: avoid` on the *whole* heading+chart+caption group. As the last section before the pinned footer, this was harmless — if it didn't fit, it simply became a clean, lone page 2. Once moved earlier in the document (between RESUMEN/SUMMARY and NOTAS ADICIONALES/ADDITIONAL NOTES), the same "move the whole block if it doesn't fit" rule now had *later* sections behind it. When the block didn't fit in the space remaining on page 1, WeasyPrint pushed the entire group down, wasting the leftover page-1 space — and everything after it (Notes, Warranty) then had less room, so `.warranty-table` (which has no split protection) broke mid-table instead of the coverage chart alone moving cleanly.

Confirmed via a scratch A/B render (same real proposal data, old template order vs. new): with the coverage chart *not* populated (the common case for older drafts, which never triggered this bug), both orders render identically at 1 page — the bug only appears once a proposal has real, non-empty `monthly_coverage` data, which is newer functionality that many existing drafts (including the stale PDF the user's first attachment turned out to be — its content still showed the pre-Session intro text and the old chart position, i.e. it was a leftover download from before today, not evidence of the current bug) never exercised until now.

**Fix, applied to all 4 templates** (`off_grid_es.html`, `off_grid_en.html`, `grid_zero_es.html`, `grid_zero_en.html`):
- `page-break-inside`/`break-inside: avoid` moved from the wrapper `.coverage-block` to just `.coverage-chart` (the SVG itself) — the heading and caption can now flow independently, so only the chart image is guaranteed not to be visually cut, and nothing forces a wasteful whole-block jump.
- `.coverage-note` bottom margin trimmed 6pt→3pt, `.section-row` top margin (used by *every* section heading document-wide) trimmed 6pt→4pt — small, uniform reclaims of vertical space.

**Verified**: rebuilt Henry Garita's real off-grid draft with a genuine simulated 12-month coverage chart (generation + consumption + recharge, from the same `simulate_battery_soc()` the wizard itself uses) — renders at **1 page**, matching the pre-bug expectation. Oscar Pauly's Grid Zero case is a much heavier document (7 cost line items, a full billing table, a full benefits table, a full 12-month chart, and the notes/bank/warranty sections) — even with the fix it lands at 2 pages, but the overflow shrank from "the whole Warranty table plus a near-empty page" down to just its last 2 rows spilling over, a much smaller and cleaner break.

**Follow-up same round**: user screenshotted the still-overflowing Oscar Pauly PDF and asked to shrink the font on the NOTAS ADICIONALES/ADDITIONAL NOTES bullet list and the DETALLES DE GARANTÍA/WARRANTY DETAILS table specifically, across all 4 templates. Changed `.notes-list` and `.warranty-table` font-size 6.5pt→6pt in all 4 files; also trimmed `.warranty-table td` padding 1.5pt→0.75pt (in two steps, checking page count after each) since font-size alone barely moves row height without a matching padding trim — the vertical padding is what actually governs row height in a table this dense. Re-tested Oscar Pauly's exact heavy case after each increment: 6.5pt font/1.5pt padding → 2 rows spilled; 6pt font/1pt padding → 1 row spilled; 6pt font/0.75pt padding → **1 page, zero spill**, full 6-row warranty table renders intact above the footer. Full regression pass (both languages × all three system types, using the existing built-in sample fixtures) confirmed no other proposal regressed to 2 pages from this trim.

**Second follow-up same round**: at 6pt/0.75pt the warranty table was tight enough against the fixed-position footer that its "More information"/"Más información" heading line visually overlapped the table's last row in a fresh screenshot. User asked to lower the font further and remove "More information"/"Más información" entirely (all 4 templates).
- Removed `.footer-heading` (the CSS rule and the `<div class="footer-heading">...</div>` markup) from all 4 templates. Since `.footer-wrap` is `position: fixed; bottom: -1.95cm` with the heading and the navy `.footer-card` stacked inside it in normal flow, removing the heading line shrinks the wrapper's own height — and because its *bottom* edge is what's pinned, the whole wrapper (now just the card) shifts further down/away from the page content, directly fixing the overlap as a side effect of deleting the line.
- Dropped `.notes-list`/`.warranty-table` font-size 6pt→5.5pt and `.warranty-table td` padding 0.75pt→0.5pt.

**Verified**: rendered Oscar Pauly's exact heavy case again — still 1 page, and a rasterized screenshot (via `pdftoppm`) confirms clean visual separation between the warranty table and the footer card, with no "More information" text anywhere. Grepped all 4 templates for `footer-heading`/`Más información`/`More information` — zero matches. Full 5-case regression (both languages × all three system types) still all 1 page.

**Third follow-up same round**: with the overflow now fixed, Henry Garita's off-grid PDF (a lighter document) had visibly leftover whitespace at the bottom — user asked to redistribute some of that reclaimed space as breathing room *between* sections (DETALLES DE COSTOS → DETALLES TÉCNICOS → RESUMEN → COBERTURA MENSUAL → NOTAS ADICIONALES → DETALLES DE GARANTÍA), "with logic" rather than arbitrarily.

The single lever that controls the gap before every section heading document-wide is `.section-row`'s `margin-top` (emergency-trimmed to 4pt earlier this round, down from an original 6pt) — increasing it uniformly is the "logical," centralized way to add rhythm across the whole page rather than hand-tuning six separate gaps. The binding constraint is Oscar Pauly's Grid Zero draft, the heaviest real case found this round, which sits at exactly 1 page with ~0 slack — so each candidate value was tested against *both* Henry Garita (plenty of slack) and Oscar Pauly (none) before keeping it:
- `margin-top: 6pt` (full revert to original) → Oscar Pauly back to 2 pages. Rejected.
- `margin-top: 5pt` → both stay 1 page. Kept.
- Also bumped every table wrapper's `margin-bottom: 3pt → 4pt` (`.gt`, `.cost-table`, `.tech-wrap`, `.summary-table`, `.bank-table`, `.warranty-table`) for a touch more air below each table before the next heading — re-tested, still 1 page for both.

Deliberately left `.notes-list`/`.warranty-table` font-size and cell padding untouched — those were the specific, separate fix for the overflow bug earlier this round, not part of "spacing between blocks," and the user's screenshot didn't flag them as a problem.

**Verified**: measured actual whitespace via `pdftotext -bbox` before finalizing — Oscar Pauly's heaviest case now has the tail of its warranty table ending ~17pt above where the footer begins (a real but modest safety margin, not zero), while Henry Garita's lighter case still has ~70pt of natural breathing room at the bottom (expected and fine — not every proposal needs to fill the page). Re-rendered Henry Garita's PDF to a PNG and visually confirmed clearer, more even gaps between all six sections. Full 5-case regression (both languages × all three system types) plus both real drafts (Henry Garita, Oscar Pauly) still render at 1 page.

**Fourth follow-up same round**: user reconsidered the uniform "5pt everywhere" rhythm and asked for something more deliberate — DETALLES/NOTAS and the footer grouped tight at the bottom, with one clear gap right after the chart separating "proposal/design" content (Costos, Técnicos, Resumen, Cobertura) from "general info" (Notas, Garantía).

Reverted the third follow-up's two uniform bumps back to their emergency-trimmed values in all 4 templates — `.section-row margin-top` 5pt→4pt, and the six table `margin-bottom` rules 4pt→3pt. (Caught and fixed a mistake mid-revert: the blanket `sed 's/margin-bottom: 4pt/margin-bottom: 3pt/'` also clobbered `.header`/`.client-table`/`.intro`, which were *already* 4pt before any of this round's changes and were never part of the bump — restored those three back to 4pt by name.) Then added exactly one deliberate gap: `.coverage-note`'s bottom margin (previously 3pt, untouched by the uniform bumps since it's set via shorthand `margin:` not `margin-bottom:`) went to 10pt — this is the last element of the "design" zone, right before NOTAS ADICIONALES/ADDITIONAL NOTES begins, so it's the one place a bigger gap reads as intentional rather than random. Tried 14pt first — overflowed Oscar Pauly's case by one row — backed off to 10pt, the largest value that still holds both test cases at 1 page (~19pt of clearance remains above Oscar Pauly's footer).

**Verified**: rendered both real drafts to PNG via `pdftoppm` and visually confirmed the intended structure — Henry Garita's Costos/Técnicos/Resumen/Cobertura sit close together, a clear single gap follows the chart, then Notas Adicionales/Detalles de Garantía sit close together above the footer; same shape holds for Oscar Pauly's much heavier draft with tight-but-real clearance. Full 5-case regression (both languages × all three system types) plus both real drafts still render at 1 page.

**Fifth follow-up same round, off-grid only**: even with the deliberate post-chart gap, Henry Garita's proposal (a light document) still left NOTAS ADICIONALES/DETALLES DE GARANTÍA floating mid-page with a large dead gap below them before the footer — a fixed-size gap can't adapt to how much content sits above it. User asked specifically for **off-grid** (this round's screenshot was Henry Garita's off-grid draft — not grid-zero) to push Notas/Garantía down to sit on top of the footer.

Implemented a CSS flexbox "pinned to bottom" layout in `off_grid_es.html`/`off_grid_en.html` only:
- `<body>` content (everything except the fixed footer) wrapped in a new `.page-wrap` — `display:flex; flex-direction:column; min-height:744pt` (the exact one-page content box: A4 841.89pt − top margin 21.26pt − bottom margin 76.54pt).
- NOTAS ADICIONALES through the end of DETALLES DE GARANTÍA wrapped in a new `.bottom-group` with `margin-top: auto` — in a flex column, an auto top-margin consumes all left-over space above the element, so it lands flush against the page's content-box bottom (i.e., right above where the fixed footer sits) regardless of how much or little content is above it. Degrades safely if a proposal is heavy enough to need a 2nd page — `min-height` just stops being the binding constraint once content exceeds it, flex falls back to plain top-down flow with no clipping or overlap (verified with an intentionally-3x-inflated cost table forcing a 2-page overflow — page 2 renders correctly, just with unused trailing space, no corruption).
- **Found and fixed a real WeasyPrint flexbox quirk along the way**: wrapping `.tech-table` (DETALLES TÉCNICOS/TECHNICAL DETAILS) in its old `<div class="tech-wrap">` container added a spurious ~17pt of extra height once that div became a flex item — isolated by comparing section-to-section gaps via `pdftotext -bbox` against a non-flex baseline (every other gap matched within ~3pt, only the tech-wrap-preceded one was inflated). Fixed by flattening — moved `.tech-wrap`'s `margin-bottom: 3pt` directly onto `.tech-table` and deleted the wrapper div from the markup entirely; the anomaly disappeared.
- **Deliberately did not touch `grid_zero_es.html`/`grid_zero_en.html`** — the user's ask was scoped to off-grid, and testing the same flex change against Oscar Pauly's heaviest Grid Zero case (still using its own un-flattened wrapper divs) regressed it to 2 pages, splitting the warranty table again. Grid Zero would need the same wrapper-div audit before this technique could safely apply there — left for a future round if requested.

**Verified**: re-tested off-grid's own heaviest known content (`JORGE_RAMIREZ_DATA` + a full synthetic 12-month chart, and `HYBRID_DATA` — Hybrid renders through the same off_grid templates) — both still 1 page. Henry Garita's real draft re-rendered from the actual template files (not a scratch copy) and visually confirmed: Notas Adicionales/Detalles de Garantía now sit directly above the footer, with the reclaimed whitespace gone from the middle of the page. Full 3-case off-grid/hybrid regression still 1 page.
