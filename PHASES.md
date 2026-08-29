# Pauly&Co Solar Tool — Development Phases

**Builder:** Oscar Pauly (solo)  
**Stack:** Streamlit · Supabase · WeasyPrint/Jinja2 · Anthropic SDK · numpy-financial  
**Reference:** Requirements v3.5  
**Goal:** Real proposals in production as fast as possible  
**Last updated:** 2026-08-16

| Phase | Status |
|---|---|
| 0 — Foundation | ✅ Complete |
| 1 — PDF Engine | ✅ Complete |
| 2 — Grid Zero Wizard | ✅ Complete |
| 3 — Proposal Management | ✅ Complete + UX polish (directed flow, per-version PDF) |
| 4 — AI Features | ✅ Complete (bill parser, tablero, datasheet, load estimator, daytime fraction) |
| 5 — Off-Grid + Hybrid | ✅ Complete — includes a taxonomy-driven load profile estimator beyond the original spec (see below) |
| 6 — Projects Module | ⬜ Not started |
| 7 — Admin + Polish | 🔶 Partial (equipment catalog ✅, ARESEP xlsx parser ✅, tariff manager UI ✅, Clientes/Prospectos ✅; cost templates, settings pending) |
| 8 — QA + Handoff | ⬜ Not started |
| 9 — Victron Monitor Multi-Tenant Hardening | ⬜ Not started (separate product, no dependency on 0–8) |
| 10 — Site Register & Preventive Maintenance Scheduler | ⬜ Not started (spans both products, no dependency on 0–9) |
| 11 — Design Calibration from Fleet Data | ⬜ Not started (gated by data availability, not sequence) |
| 12 — Victron Monitor: Retire Apps Script Scheduling/Email/Archiving | ⬜ Not started (separate product, no dependency on 0–11) |
| 13 — VRM Monitor Customer Portal (Streamlit) | 🔶 Superseded by Phase 14 — Step 1 built & validated (migration 021, login, role resolution) |
| 14 — VRM Monitor unified Next.js site (marketing + portal + admin) + Python pipeline API | 🔶 Steps 1–7 built & validated (design system, auth, tenancy, vrm_api, upload/reports, admin+invites); Step 8 (deploy/cutover) pending — see PLAN_PHASE14.md |
| 15 — VRM Monitor: direct VRM API ingestion (customer-connected Victron accounts + Oscar's own admin fleet access) | ✅ Steps 0–6 built & independently verified (see PLAN_PHASE15.md); Step 7 (scheduled sync) deferred at Oscar's request |
| 16 — VRM Monitor: public signup + customer self-service billing on ONVO Pay | ✅ Complete — Steps 0–7 built & verified (see PLAN_PHASE16.md) |
| 17 — VRM Monitor: scheduled reports, report cost limits, tiered white-label branding, visible trial | ✅ Complete — Steps 0–9 built & live-verified (see PLAN_PHASE17.md); CSV-sourced sites are structurally excluded from scheduling (§0.7) |

---

## Guiding principles

- **Vertical slices, not horizontal layers.** Each phase produces something you can actually use, not just a piece that needs five other pieces to function.
- **PDF fidelity from phase 1.** The proposal is the product clients see. It needs to look right before anything else.
- **One system type first.** Grid Zero is your most common type and has the richest financial output. Build it end-to-end before touching Off-Grid or Hybrid.
- **Manual before AI.** Get calculations right with manual input. AI features layer on top once the math is validated.

---

## Phase 0 — Foundation (3–5 days)

**Goal:** Project skeleton running locally. Nothing visible yet, but everything connected.

### Tasks

**Supabase setup**
- Create Supabase project
- Run schema SQL: `panels`, `inverters`, `batteries`, `charge_controllers`, `monitoring_devices`, `distributors`, `tariff_types`, `tariff_tiers`, `proposals`, `proposal_versions`, `clients`
- Create Storage buckets: `proposals/`, `equipment/`, `assets/`
- Copy `.env` template, add keys

**Python project scaffold**
- `requirements.txt`: streamlit, supabase-py, anthropic, weasyprint, jinja2, numpy-financial, plotly, pillow, python-dotenv, requests
- Folder structure per v3 requirements
- `config.py`: brand colors, constants, defaults
- `utils/supabase_client.py`: singleton client
- `utils/currency.py`: exchangerate-api.com fetch + cache
- `utils/formatting.py`: CRC/USD formatters

**Asset preparation**
- Invert `firma_white.png` → `firma_dark.png` using Pillow (one-time script)
- Embed logo and signature as base64 strings in `proposals/assets/assets.py`
- Confirm brand hex values from logo: green `#4BAE6A`, navy `#1E2D54`

**Seed data**
- `seed_tariffs.py`: 8 distributors, T-RE residential tiers for each (2026 values)
- `seed_equipment.py`: 3–5 panels, 3–5 inverters you actually use (JA Solar 620W, Fronius Primo, Victron Multiplus, etc.)

**Validation**
- `streamlit run app.py` shows sidebar with navigation
- Supabase connection confirmed (ping test)
- Seed data visible in Supabase table editor

---

## Phase 1 — PDF Engine (4–6 days)

**Goal:** Generate a pixel-perfect Grid Zero PDF from hardcoded data. No wizard yet. This is the most important phase — nail the output before building the input.

### Why first

The PDF template is the hardest thing to get right visually, and it's the thing clients actually see. Building it first means every subsequent phase produces real output you can evaluate immediately.

### Tasks

**Jinja2 HTML templates**
- `grid_zero_es.html` — Spanish
- `grid_zero_en.html` — English
- CSS that matches the Pauly&Co proposal exactly:
  - Header block (COTIZACIÓN / SOLAR, client fields, logo top-right)
  - Table styles: green `#4BAE6A` headers, white text, alternating row tints
  - Section headings: green underline or bold
  - "Facturación mensual promedio" table (average row only)
  - "Beneficios a corto/mediano/largo plazo" table
  - "Detalles de costos" table (with panel asterisk footnote)
  - "Detalles técnicos" table
  - "Resumen" block
  - "Bienes y servicios incluidos" bullet list
  - "Notas" bullet list
  - Payment details two-column table
  - "Detalles de garantía" table
  - "Más información" footer card (signature left, contact center, logo right)
  - Footer: "Validez de la oferta: 15 días hábiles..."

**WeasyPrint generator**
- `proposals/generator.py`: takes a Python dict → renders Jinja2 → WeasyPrint → returns PDF bytes
- Test with María José Castro hardcoded data (from the reference PDF)
- Compare output side-by-side with reference until pixel-accurate

**Supabase Storage upload**
- Save generated PDF to `proposals/{proposal_id}/v{n}_{client}_{date}.pdf`
- Return public or signed URL for download

**Validation**
- Generate both Spanish and English versions from same data dict
- Visual diff against reference PDFs — fonts, spacing, table widths, colors
- Download works in Streamlit with `st.download_button`

---

## Phase 2 — Grid Zero Wizard, Manual Input (6–8 days)

**Goal:** Complete end-to-end flow for Grid Zero with manual data entry. Real proposals possible.

### Tasks

**Wizard shell**
- `wizard/state.py`: session state helpers, auto-save to Supabase (debounced)
- Step progress indicator in UI (Step N of 8, breadcrumb)
- Back/Next navigation
- Draft indicator: `● Guardado` / `Guardando…`

**Step 1 — System type + language**
- Grid Zero selected → branch locked
- Language toggle ES/EN

**Step 2 — Client**
- Name, phone, email
- Typeahead search against `clients` table (simple contains match)
- Auto-fill if existing client found; create new on save

**Step 3 — Site + PVGIS**
- City + province text fields → geocode to lat/lon (simple lookup table for Costa Rican provinces, or Nominatim API)
- "Obtener irradiancia" button → PVGIS API call → shows monthly kWh/kWp table
- Manual override fields

**Step 4 — Utility account**
- Distributor dropdown (8 options)
- NISE field (or N/A)
- Tariff type dropdown (populated from DB per distributor)
- Shows current tariff ₡/kWh from DB

**Step 5 — Consumption (manual entry)**
- 12-row table: month, kWh, bill amount ₡
- System auto-calculates: avg kWh/month, avg bill ₡, consumption chart (Plotly bar)
- Interconnection permit cost field (default $1,000)

**Step 6 — Equipment**
- Panel selector (dropdown from DB) → shows specs card
- Inverter selector → shows specs card
- MPPT validator runs automatically → shows 3 scenarios (A/B/C)
- Engineer selects scenario → panel count locked
- Monitoring selector (optional)

**Step 7 — Costs**
- Line items table pre-filled from selected equipment
- Editable: qty, unit cost, description
- Add/remove rows for installation items
- IVA toggle (0% or 13%)
- Subtotal / IVA / Total auto-computed
- $/Wp shown live
- Exchange rate shown (CRC equivalent)

**Step 8 — Review**
- Summary cards: system kW, panels, area m², $/Wp
- Billing comparison table preview (average row)
- Benefits preview: savings Y1, savings 25yr, IRR, ROI
- Intro paragraph textarea (placeholder text; AI not yet)
- "Generar PDF / Generate PDF" button
- PDF download immediately

**Calculations**
- `calculations/pvgis.py`: PVGIS API call, cache response in Supabase
- `calculations/tariffs.py`: tiered bill calculator (blocks, IVA threshold 280 kWh, bomberos 1.75%)
- `calculations/sizing_grid_zero.py`: system kW, panel count, daily generation, monthly savings table
- `calculations/mppt.py`: 3-scenario string validator
- `calculations/financials.py`: IRR (numpy_financial), ROI, 25yr projection at 5% escalation

**Validation**
- Run the María José Castro numbers through the wizard
- Compare: avg kWh 1,475, avg bill ₡157,874, generation 1,262 kWh, new consumption 521, new bill ₡51,681, savings ₡106,192
- Compare: savings Y1 $2,798, savings 25yr $127,873, IRR 22.92%, ROI 5.48
- Generated PDF matches reference visually and numerically

---

## Phase 3 — Proposal Management (3–4 days)

**Goal:** Proposals list, version history, locking. The tool becomes a real workspace rather than a one-shot generator.

### Tasks

**Proposals list page**
- Table: client name, system type, status badge, current version, total USD, last modified
- Filter by status: All / Draft / Active / Won / Lost
- Click row → open proposal

**Version history panel**
- Per proposal: list of versions (v1, v2, v3…)
- Each version: date, total, note, locked/draft badge, sent badge
- Actions per version: View PDF, Download PDF, New version from this, Mark as sent

**Version locking**
- "Bloquear versión / Lock version" button on review step
- Locks `proposal_versions.locked = true`, sets `locked_at`
- "Nueva versión / New version" creates a copy of the locked version's data as a new unlocked version
- Engineer adds version note before locking (optional field)

**Proposal status**
- Status dropdown: Borrador / Enviada / En negociación / Ganada / Perdida
- "Ganada" triggers prompt: "¿Mover a Proyectos? / Promote to Project?"

**Validation**
- Create 3 versions of María José Castro proposal with different totals
- Lock v1, create v2, modify panel count, lock v2, verify v1 PDF unchanged
- Mark v2 as sent

---

## Phase 4 — AI Features (4–5 days)

**Goal:** All AI-powered shortcuts operational. The wizard becomes dramatically faster.

### Tasks

**Bill PDF extraction**
- `ai/bill_parser.py`: upload bill PDF → Claude extracts month, kWh, ₡ amount
- UI: upload button on Step 5, review/edit table before confirming
- Handles CNFL, ICE, JASEC bill formats (tested on real bills)

**Equipment datasheet ingestion**
- `ai/datasheet_parser.py`: upload PDF → Claude extracts specs → pre-fills equipment form
- Separate prompts per equipment type (panel / inverter / battery)
- "Revisar y guardar / Review and save" step before writing to DB

**Intro paragraph generation**
- `ai/proposal_writer.py`: call Claude with system params → returns 2–4 sentence paragraph
- Editable textarea on review step (Step 8)
- "Regenerar / Regenerate" button
- Both ES and EN on same call (returned as `{"es": "...", "en": "..."}`)

**PVGIS geocoding improvement**
- `ai/geocoder.py`: if lat/lon not found from lookup table, ask Claude to estimate coordinates for a Costa Rican location description

**Validation**
- Upload a real CNFL or ICE bill PDF → verify extracted kWh matches actual bill
- Upload JA Solar 620W datasheet → verify Voc, Vmp, Isc, Imp extracted correctly
- Generate intro paragraph for Grid Zero in both languages, verify quality
- Full wizard run with AI extraction (no manual entry for bills or equipment)

---

## Phase 5 — Off-Grid + Hybrid (5–7 days)

**Goal:** All three system types fully operational.

### Tasks

**Off-Grid wizard branch**
- Steps 4–8 for Off-Grid (demand, loads, backup, equipment with batteries + charge controllers, costs)
- Critical loads table (add rows: description, watts, qty, hours/day)
- Autonomy days slider (1–7)
- Voltage output selector (120V / 240V split-phase)
- Split-phase warning + autotransformer recommendation if needed

**Hybrid wizard branch**
- Extends Off-Grid
- Grid connection at main panel option
- AC coupling note in proposal text

**Load estimation (tablero)**
- `ai/tablero_parser.py`: upload tablero PDF/image → Claude extracts circuits, total kVA, demand factor
- 3-scenario buttons: Conservative (40% / 6h) / Optimal (55% / 8h) / Maximum (75% / 10h)
- Shows: estimated kWh/day, estimated monthly kWh, estimated monthly bill ₡
- Proposal flagged: "Basado en estimación de cargas"

**Off-Grid / Hybrid PDF templates**
- `off_grid_es.html` + `off_grid_en.html`
- Technical table: kW, area, daily kWh, battery kWh @10h, discharge %
- Battery + charge controller warranty rows
- Summary always shows IVA row (even at $0.00)

**Calculations**
- `calculations/sizing_off_grid.py`: battery bank sizing, array sizing, discharge %, split-phase check
- Extends MPPT validator for inverter-parallel configurations

**Validation**
- Run Jorge Ramírez Off-Grid numbers: 8 panels × 620W, 1 Victron Multiplus 5000VA, 2 Pylontech US5000C, 1 Victron MPPT 250/100
- Compare: 5.0 kW, 16 m², 6.38 kWh/day, 9.60 kWh battery @10h, 66.46% discharge, $10,320 total, $2.08/Wp
- PDF matches Jorge Ramírez reference visually and numerically

### Beyond the original spec

Real usage after the phase "completed" surfaced gaps the original spec didn't anticipate — closed as part of the same phase rather than deferred, since they change how the wizard actually sizes systems, not just how it looks:

- **Load profile: taxonomy-driven estimation, not nameplate × assumed hours.** The original spec's "3-scenario buttons (Conservative/Optimal/Maximum)" approach was directly observed to overstate real consumption by 2–2.5x on a real quote. Replaced with a 5-category taxonomy (fixed/cycling, behavior-driven, climate-driven, discretionary, ignition-only) routing each load to a deterministic estimation method suited to what actually drives its energy use, with AI used only for bounded classification/extraction, never the energy math itself. Full design rationale: `tools/off-grid-wizard-load-profile-approach.md`. Implemented in `calculations/load_profile_off_grid.py`. See REQUIREMENTS.md changelog v3.6→v3.7.
- **Real day-by-day battery simulation replaces flat discharge-%.** `simulate_battery_soc()` runs the site's actual PVGIS daily series against the battery bank across a full reference year (tracking real SoC, unmet-load days, longest low-SoC streak) instead of a single average-day discharge percentage — drives the Step 6 reliability-scenario picker.
- **New solar-utilization/curtailment metric (both Off-Grid and Grid Zero).** What fraction of a year/month's generation is actually used vs. curtailed — a real, previously-invisible finding (e.g. an oversized array reads identical to a well-matched one on every other number). Surfaced in the wizard (Step 6 + Step 8) and the PDF (`DETALLES TÉCNICOS` gained an "Aprovechamiento solar" column). See REQUIREMENTS.md changelog v3.6→v3.7.
- **Proposal PDF layout, both system types:** the monthly coverage chart moved from the end of the document to a first-class section right after the cost/technical summary (previously an appendix-like afterthought after Warranty Details); Off-Grid/Hybrid additionally keeps Notes/Warranty pinned tight against the footer via a CSS flexbox layout regardless of how much content precedes them. Full mechanics and the WeasyPrint-specific gotchas encountered: CONTEXT.md, 2026-07-31 entries.

---

## Phase 6 — Projects Module (5–6 days)

**Goal:** Financial tracking for active projects. The tool covers the full job lifecycle.

### Tasks

**Promote to Project flow**
- From a won proposal version: "Mover a Proyecto" button
- Creates `projects` row linked to `proposal_id` + `version_id`
- Pre-fills `contract_usd` from version total
- Pre-fills expense budget from proposal cost breakdown (each line item → `project_expenses.budgeted_usd`)

**Presupuesto screen**
- INGRESOS: contract amount, IVA rate, extras, grand total
- PAGOS: payment schedule (up to 5 payments), paid/pending toggle, date, bank account
- GASTOS: expense categories with cost, IVA, total, paid status, budget vs actual, remainder
- UTILIDAD: gross profit, IVA net, net profit — live as entries are made

**Expense ledgers** (tabbed interface per project)
- Banco / Equipo / Materiales / Viáticos / Extras: rubro, valor, fecha, pagado, comentarios
- Labor (Mano de obra): worker name, quoted amount, advances (adelantos) with running saldo
- All tabs show running TOTAL at bottom

**Facturación screen**
- Line items: artículo, categoría, IVA rate, monto
- Auto-totals by category: Equipos (0%), Materiales (13%), Servicios (13%)
- TOTAL GENERAL with IVA breakdown

**Client payments / ONVO**
- Payment schedule with ONVO commission calc (2.4% default, editable)
- Per payment: gross, commission, IVA on commission, net to deposit
- Paid toggle + date
- Running: received vs pending

**Projects list**
- Cards: client name, status, contract amount, received %, expenses vs budget, profit
- Click → project detail (tabs: Presupuesto / Banco / Equipo / Materiales / MOD / Viáticos / Extras / Facturación / Pagos)

**Validation**
- Create Jorge Ramírez project from his Off-Grid proposal
- Enter: Pago 1 $7,224 paid, zero expenses
- Verify: utilidad bruta $10,320, IVA $0, utilidad neta $10,320
- Enter: Equipo FV $3,679.30 (from Facturación sheet)
- Verify: remanente updates correctly

---

## Phase 7 — Admin + Polish (3–4 days)

**Goal:** The tool is fully self-maintained without touching code.

### Tasks

**Equipment catalog UI**
- List with search + filter by type
- Add/edit/delete forms
- Upload datasheet → AI fill → review → save
- Price field with last-updated indicator

**Tariff manager**
- Per distributor: tariff types, tier table (editable)
- Last updated timestamp + staleness warning (>90 days)
- "Refresh CNFL" button → fetches PDF → AI extracts → shows diff → confirm update

**Cost templates**
- Default line items per system type (Grid Zero / Off-Grid / Hybrid)
- Edit names, descriptions, default amounts
- Changes apply to new proposals only

**Settings**
- Company info (name, license, phone, email, website)
- Contact person (name, title)
- Bank details (local + international)
- Logo upload + signature upload
- Default IVA rate
- Default tariff escalation rate (5%)
- Anthropic API key
- Proposal validity period (15 days default)
- ONVO commission rate (2.4% default)
- Exchange rate display + manual refresh

**Home dashboard**
- Open drafts (proposals, draft status)
- Awaiting response (proposals, sent status)
- Active projects (mini: contract, received %, profit %)
- Quick button: "Nueva cotización"

**Validation**
- Add a new panel from datasheet via UI (no code)
- Update CNFL tariff manually
- Change company phone number in settings → appears in next generated PDF

---

## Phase 8 — Quality, Edge Cases, and Handoff (2–3 days)

**Goal:** The tool is stable enough to trust with real client proposals.

### Tasks

**Edge case handling**
- PVGIS timeout → graceful fallback to manual irradiance entry
- Exchange rate API unavailable → use cached value, show warning
- Anthropic API error → show error message, allow manual entry
- WeasyPrint font/image issues → fallback handling
- Very high kWh consumption (commercial) → system doesn't cap unreasonably
- Very low consumption → minimum system size warning

**Input validation**
- Required fields marked clearly
- Numeric fields reject non-numbers
- Date fields validated
- Duplicate client detection

**Performance**
- PVGIS response cached per lat/lon in Supabase (avoids repeat API calls for same location)
- Exchange rate cached with 1-hour TTL
- PDF generation < 5 seconds target

**Testing against all three reference proposals**
- Grid Zero: María José Castro — all numbers and PDF match
- Off-Grid: Jorge Ramírez — all numbers and PDF match
- Run one brand-new real proposal end-to-end from scratch

**Documentation**
- `README.md`: setup instructions (clone, .env, seed, run)
- Brief notes on adding new equipment, updating tariffs
- Note on future web deployment (Supabase already production-ready; only Streamlit host changes)

---

## Phase 9 — Victron Monitor Multi-Tenant Hardening (3–5 days, separate product)

**Goal:** Victron Monitor is safe to sell as a paid subscription to external customers, not just run internally across your own sites.

This phase belongs to `victron-monitor/`, not the solar proposal tool — it has no dependency on Phases 0–8 and can be done whenever the subscription business is ready to onboard its first external (non-Pauly&Co-owned) site. See [`victron-monitor/README.md`](victron-monitor/README.md), [`ARCHITECTURE.md`](ARCHITECTURE.md), and [`CONTEXT.md`](CONTEXT.md#victron-monitor-integration-added-2026-07-13) for current architecture.

**Already done, ahead of this phase (not part of its remaining scope):** per-site DB-driven
config (specs, thresholds, Apps Script URL — migration 006), automatic `daily_health`
compute in Postgres (migration 005), the client/prospect data model with email routing for
reports (migrations 007–008), a `system_type` column for future report personalization
(migration 009), and a recalibrated default battery-cycling threshold shared by Hybrid and
Off-Grid (migration 010). What's described below — RLS + per-device JWT — is the one piece
of multi-tenant hardening that's still outstanding.

**Separately tracked TODO, not part of this phase either:** once real Grid Zero (no-battery,
Fronius) sites exist, two places need `system_type`-conditional logic that's deliberately
*not* built yet (no real site to verify the change against):
- `monitoring.compute_daily_health()` (migration 010) — skip the battery-cycling penalty
  entirely for `system_type = 'grid_zero'` rather than comparing against any threshold,
  since there's no battery to stress. Marked inline in the function.
- `weeklyReport()`'s `buildReportHtml()` (Apps Script) — the Battery Health info block and
  the donut's battery segment/legend are meaningless without a battery; the Grid
  independence KPI and Grid info block are meaningless for Off-Grid. Both require
  recomputing the hand-tuned SVG column layout (fixed 4-column KPI row, fixed 2-column
  info blocks), not just an `if()` wrap. Marked with `TODO(system_type)` comments at the
  three exact locations.

### Why this phase exists

As of v3.4, every site in `monitoring.sites` is reachable by **one shared Supabase `anon` key** with schema-wide `GRANT ALL` and no RLS. A single compromised or physically-stolen Cerbo GX device currently exposes every other customer's telemetry, not just its own, and there's no way to revoke one customer's access without rotating the key for the entire fleet. That's an acceptable trust model for a handful of internally-owned sites; it's disqualifying once someone else's business data is on the other end of that key.

### Tasks

**Row-Level Security**
- Enable RLS on all `monitoring` tables (`sites`, `energy_daily`, `daily_health`, `alarm_events`, `grid_events`, `ac_input_events`, `mppt_snapshots`, `flow_logs`)
- Policy pattern: `site_id = (auth.jwt() ->> 'site_id')` for both read and write, scoped per table
- Decide whether `fleet_summary` (the cross-site view) needs a separate internal-only role that bypasses per-site RLS for Pauly&Co's own dashboard use

**Per-device JWT provisioning**
- Small provisioning script (could live in `victron-monitor/tools/` or as an Admin-area action in this Streamlit app) that, given a `site_id`, mints a signed Supabase-compatible JWT with a `site_id` claim, using the project's `service_role` key server-side — the device never sees `service_role`
- Decide token lifetime / rotation policy (long-lived vs. periodic refresh) — Cerbo devices are not always online, so refresh flows need to tolerate extended offline periods
- Store the minted JWT the same way `SUPABASE_ANON_KEY` is stored today: Node-RED Global Environment Variable, type `credential`, referenced via `env.get()` — never hardcoded in the flow

**Onboarding flow update**
- Update `victron-monitor/docs/onboarding.md`: Step 1 becomes "insert site row + mint device JWT" instead of just "insert site row"
- New site's `Project Config` node references the per-device credential var, not the shared one

**Key rotation / revocation**
- Document how to revoke a single site's access (e.g., a `revoked` flag checked by an RLS policy, or short-lived JWTs with a refresh endpoint that checks a revocation list) without affecting other customers
- Runbook for "customer cancels subscription" and "device reported stolen"

**Validation**
- Two test sites, two different device JWTs — confirm site A's JWT cannot read or write site B's rows (via curl, same technique used to debug the schema-exposure issue in this repo's history)
- Revoke one site's JWT — confirm that site's writes start failing while the other site is unaffected
- Confirm `fleet_summary` (or its replacement) still works for internal fleet-wide visibility without exposing cross-site access to device credentials

---

## Phase 10 — Site Register & Preventive Maintenance Scheduler (4–6 days, spans both products)

**Goal:** Every installed system — Victron-monitored or not — has one durable record, and the tool tells you who's overdue for a maintenance visit. Replaces the manual `Registro de mantenimientos FV.xlsx` Google Sheet (analyzed 2026-07-18: 23 real installations across 12 clients, a rolling 365-days-from-last-visit due date computed per row, and a hand-built month-by-month "who's due when" dashboard on Google Sheets-only array formulas).

### Why this phase exists

The register currently lives in a spreadsheet with no connection to this tool's own data — a customer's `clients` row, their won `projects`, and their Victron `monitoring.sites` row (if any) are three separate identities today with no shared "this is one physical site" concept, and there's no computed overdue/due-soon status anywhere in the app.

### Where this sits relative to other phases

- UI hangs off the **Projects** nav item (decided over a top-level "Sitios" area or an Admin sub-tab), but the register itself is **not** scoped to a single `projects` row — most of the 23 real sites predate this tool and have no proposal/project history. `site_properties` / `monitoring.sites` are the anchor entities; a `projects` link is optional, not required.
- Off the critical path, same as Phase 9 — no dependency on Phase 6 (Projects financial ledgers) being finished first, though it will likely land in the same nav tab once Phase 6 exists.
- Touches the `monitoring` schema (Victron Monitor's territory) as well as `public` schema (solar tool's territory) — cross-product, like the weekly-report tariff-savings feature below.

### Key modeling decision: site identity stays in `monitoring.sites`, only secrets and visit history move out

`monitoring.sites` carries a blanket `GRANT ALL ... TO anon` with no RLS (documented gap, see Phase 9) because the anon key lives on physical field hardware (Cerbo GX devices). Only genuinely sensitive data needs to be walled off from that — panel/inverter/battery counts and dashboard URLs aren't secrets, so (refined 2026-07-18, after the initial split proved more cautious than necessary) they live directly on `monitoring.sites`:

- **`monitoring.sites`** stays the single source of truth for site *identity* — one row per meter/device, Victron-monitored or not (confirmed via live query 2026-07-18: today it holds exactly 3 rows, `vista-atenas-lp-m1/m2/m3`, Lori Pickett's 3 Victron installations at one property, all still unlinked to any `client_id`). Gains: `property_id`, `panel_count`, `inverter_count`, `battery_count`, `monitoring_urls` (text[]). `latitude`/`longitude` already exist as columns — the 22 non-Victron sites just need them populated (see geocoding below).
- **Only `credentials` and visit history stay off `monitoring.sites`**, in `public` schema (service_role only, same trust boundary as `clients`/`proposals`) — those are the two that either are secrets (plaintext WiFi/portal passwords) or are inherently one-to-many (a visit log can't be a column).
- A property can span multiple `monitoring.sites` rows (one visit, one charge, covers every meter at that location — e.g. Lori Pickett's M1/M2/M3), but the same client's sites in different locations are separate properties with separate visit schedules (e.g. Karen Montealegre's 3 distinct properties in Santa Ana each get their own maintenance cycle).

### Geocoding — reuse, don't rebuild

`calculations/pvgis.py:geocode_cr(city, province)` (built in Phase 2 for the wizard's Site step) already does exactly this: a Costa Rica city lookup table, falling back to Nominatim. Ran it against all 22 xlsx locations (2026-07-18) — only Naranjo and Liberia hit the lookup table directly; the rest fall through to a live Nominatim call at import time (canton-centroid accuracy, not exact-address — acceptable for a maintenance register, not for anything needing precision).

**Found a real bug to fix first:** `geocode_cr()`'s fallback strips the province and matches on city name alone when the exact `"city, province"` key misses. The lookup table's only `"san isidro"` entry is Pérez Zeledón's (San José) — but María Lía Artavia's site is "San Isidro, **Heredia**", ~150km away. There are at least 3 "San Isidro"s in Costa Rica. Fix before the import runs: add a province-qualified key to `_CR_LOOKUP`, or force this one row through Nominatim directly instead of the ambiguous fallback.

### Tasks

**Schema (`database/migrations/011_site_maintenance_register.sql`)**
```sql
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS property_id      uuid;  -- REFERENCES public.site_properties(id), added once that table exists
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS panel_count      int;
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS inverter_count   int;
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS battery_count    int;
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS monitoring_urls  text[];
-- latitude/longitude already exist (migration 004) — no ALTER needed, just backfill values

CREATE TABLE public.site_properties (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id                   uuid REFERENCES public.clients(id),
  name                        text NOT NULL,
  location                    text,
  maintenance_interval_days   int NOT NULL DEFAULT 365,
  created_at                  timestamptz DEFAULT now()
);

CREATE TABLE public.site_credentials (
  site_id      text PRIMARY KEY REFERENCES monitoring.sites(site_id),
  credentials  text,   -- service_role only; never GRANTed to anon
  notes        text
);

CREATE TABLE public.maintenance_visits (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  property_id   uuid REFERENCES public.site_properties(id) ON DELETE CASCADE,
  visit_date    date NOT NULL,
  amount_usd    numeric(10,2),
  technician    text,
  notes         text,
  created_at    timestamptz DEFAULT now()
);
```

- `public.get_property_maintenance_status(property_id)` — Postgres function mirroring `monitoring.compute_daily_health()`'s pattern: reads `MAX(visit_date)` for the property (falls back to the earliest `commissioned_at` among its linked `monitoring.sites` rows if never visited), adds `maintenance_interval_days`, returns `{next_due_date, status}` where status is `overdue` / `due_soon` (within 30 days) / `up_to_date` — replaces the xlsx's `IF(P="","",P+365)` plus its red conditional-format rule.

**One-time migration script (`tools/import_maintenance_register.py`)**
- Fix the `geocode_cr()` San Isidro collision first (see above)
- Reads `Registro de mantenimientos FV.xlsx` (`Proyectos FV` sheet) via openpyxl
- Matches each `Cliente` to an existing `public.clients` row — all 12 are already paying customers, so log (don't silently create) any that fail to match
- Groups rows into `site_properties` by (client, location)
- **Skips Lori Pickett's 3 rows entirely** (`vista-atenas-lp-m1/m2/m3` already exist) — only backfills their `property_id`, `client_id` (currently null), and geocoded coordinates if missing
- Inserts a `monitoring.sites` row for each of the other 22 xlsx rows: mints a slug `site_id` from the `Proyecto` name (e.g. `karen-montealegre-guarda`), fills `panel_count`/`inverter_count`/`battery_count` directly from the xlsx counts, geocodes `location` via `geocode_cr()` into `latitude`/`longitude`, sets `system_type = 'hybrid'` if `battery_count > 0` else `'grid_zero'` (confirmed 2026-07-18: 15 of the 22 have no battery), leaves Victron-only columns (`health_thresholds`, `app_script_url`, etc.) at their defaults since these aren't monitored
- Converts every populated yearly `Fecha`/`Monto` cell (2021–2026 columns in the xlsx) into one `maintenance_visits` row
- Flags the `Credenciales` cell contents for manual review in a dry-run/print-only pass before writing anything to `public.site_credentials` — no blind import of plaintext WiFi/portal passwords

**UI**
- New tab reachable from the Projects nav — not nested inside a single project's detail page, since it needs to list every property regardless of whether a `projects` record exists
- Overdue list (red) + upcoming-by-month view, replacing the `Cronograma` sheet's manual calendar
- Property detail: linked `monitoring.sites` rows (with panel/inverter/battery counts, monitoring URLs shown inline), visit history, "log a visit" form
- Credentials field rendered only within the Streamlit session (already single-user/service_role — no new exposure beyond what the app already holds), fetched from `public.site_credentials` separately from the rest of the site row

**Validation**
- Run the import script in dry-run mode; confirm the 22 new `monitoring.sites` rows + property groupings match the xlsx 1:1 (client, location, panel/inverter/battery counts, system_type)
- Confirm geocoded coordinates are sane per row (spot-check against Google Maps for the province), and specifically confirm Hacienda Zurquí lands in Heredia, not Pérez Zeledón
- Confirm Lori Pickett's existing 3 rows keep their original `id`/`created_at` after import, and end up with the correct `client_id`
- Confirm `get_property_maintenance_status()` reproduces the xlsx's current overdue flags for every property (cross-check against the `Cronograma` sheet's red-highlighted rows)
- Log a new visit for a test property, confirm status flips from overdue → up_to_date and `next_due_date` recalculates

---

## Phase 11 — Design Calibration from Fleet Data (4–6 days, spans both products)

**Goal:** the sizing constants behind Off-Grid/Hybrid proposals stop being judgement calls and become measurements, refreshed as monitored sites accumulate history. Every new export makes the next proposal better.

The first pass was done by hand in Aug 2026 across 9 sites and is written up in [`docs/design-calibration-2026-08.md`](docs/design-calibration-2026-08.md) — that document is the specification for this phase. It already contains the method, the derived constants, the back-test, and (most valuable) the list of traps that produce plausible wrong answers.

### Why this phase exists

`calculations/sizing_off_grid.py`'s tier tables (`_HYBRID_DESIGN_TIERS`, `_OFF_GRID_DESIGN_TIERS`) originally encoded engineering judgement. The 2026-08 calibration found the judgement was off in ways nobody could have spotted without field data: batteries oversized ~2–3×, PV sized past what a non-exporting site can absorb, and `backup_autonomy_hours` modelling an outage profile that does not occur. Those fixes are now in the code with the evidence in comments — but they came from a one-off analysis that will go stale, and re-doing it by hand each time does not scale.

### Where this sits relative to other phases

- Off the critical path, like Phases 9 and 10. Trigger by data availability, not sequence.
- Depends on `victron/vrm_csv.py` (exists) and the `monitoring.sites` design columns (exist: `pv_kwp`, `battery_nominal_kwh`, `battery_dod_pct`, added by migrations 017–019).
- Related to Phase 10 but distinct: Phase 10 answers *"who needs a visit"*; this answers *"what should we quote next time"*. They share `monitoring.sites` as the anchor entity and would sit in the same nav tab.
- **Blocked in practice by data, not code**: VRM retains 1-minute data only ~6 months, so the low-irradiance months (Sep–Nov) can't be exported at full resolution until a December run. See the doc's §1 for the workarounds.

### Scope

**Ingestion**
- Batch-parse a folder of VRM exports through the existing `parse_export()`, joining to `monitoring.sites` on the filename slug (the `<site-slug> <type>.csv` convention already works).
- Persist per-day rows to `vrm.energy_daily` / `monitoring.energy_daily` so calibration reads the database rather than a folder of CSVs.
- Support a coarser (hourly) archive alongside the 1-min recent window — the only way to reach Sep–Nov.

**Exclusion rules — enforced, not optional** (doc §8)
- drop partial days; drop all-signal-null days (gateway offline ≠ zero generation)
- drop idle sites (<0.2 cycles/day) from battery calibration
- drop faulty arrays (peak <600 W/kWp) from PV calibration

**Metrics** — per site: peak W/kWp, PR vs PVGIS (mean and p98), cycles/day, min-SoC distribution, night-load fraction, cycling window ÷ night load, PV coverage, rolling multi-day minimum yield, delivered vs design coverage.

**Triage** — classify each site as `well-matched` / `over-built` / `under-built` / `array-fault` / `monitoring-gap` using the discriminators in doc §2, especially **peak W/kWp vs mean PR** (capability vs delivery — conflating them misclassified three healthy arrays on the first pass).

**Calibration output**
- Proposed constants, each with the observed range and the site count behind it.
- **Never auto-applied.** Produces a diff against the shipped tiers for an engineer to accept or reject — a fleet of 9 with one broken array cannot be trusted to rewrite the quoting engine unattended.
- Version each accepted set so a quote can record which calibration produced it.

**Back-test gate** — before a constant set can be accepted: re-run it against installed systems and confirm T2 lands near what is actually on the roof at sites that work, tier monotonicity holds at every site, and no working site is flagged as needing more equipment than it has.

### UI

New tab under Projects (alongside Phase 10's register): fleet scorecard, per-site triage with its evidence, and the proposed-constants diff with accept/reject. Read-only until an engineer accepts.

### Validation

- Reproduce the Aug 2026 numbers from the same 9 exports (doc §3/§4 are the fixture).
- Confirm triage flags villalobos as `array-fault`, karen as `monitoring-gap`, guarda as `over-built`, casona as `well-matched` — the four cases that broke naive versions of each rule.
- Confirm the back-test gate rejects a deliberately bad constant set.

---

## Superseded — Victron weekly-report tariff savings (resolved a different way)

**This did not happen as described below, and does not need to.** Real savings shipped
directly in the Python VRM report instead (`victron/savings.py`, 2026-07-29) — a CR
blended-tariff average or a per-site configured flat rate, never a fabricated number. Once
Phase 12 below retires Apps Script's own report generation, every weekly report renders
through that one Python path regardless of schema, so a JS port inside Apps Script would
now be throwaway work. Kept here, unexecuted, only so the abandoned approach isn't
re-proposed without the context of why it wasn't the one taken — see
[`CONTEXT.md`](CONTEXT.md#victron-monitor-integration-added-2026-07-13) for the full note.

- ~~Port `estimate_bill_crc` (`calculations/tariff_calculator.py`) to JS inside the Apps Script; read tariffs live from the shared Supabase `public` tables via PostgREST.~~
- ~~Define each site's electric company (`distributor` + `tariff_code`) via the Node-RED Project Config payload.~~
- ~~Savings ≈ `(weekly load − weekly grid import) × effective ₡/kWh`.~~

---

## Phase 12 — Victron Monitor: Retire Apps Script Scheduling, Email, and PDF Archiving (separate product, scoped 2026-08-16)

**Goal:** the weekly report's automation shell — not its rendering, already fully on
Python — moves off Apps Script/Gmail/Drive onto infrastructure that doesn't depend on
Google Workspace send quotas or a single script's execution limits, matching the arch
doc's own recommendation once real customer volume is a possibility.

This phase belongs to `victron-monitor/`, off the critical path like Phases 9–11. Full
scope, exact line numbers in the Apps Script this was grounded in, and the build order
are in [`victron-monitor/docs/vrm-report-v1-implementation-plan.md` §26](victron-monitor/docs/vrm-report-v1-implementation-plan.md) — not
duplicated in full here.

### What's in scope, and what explicitly isn't

Report *rendering* is already fully replaced by `victron/weekly_report.py` (both
`monitoring` and `vrm`). What's left on Apps Script, and what this phase retires:
1. **Scheduling** — `createWeeklyReportTrigger()`'s Monday time-driven trigger +
   `runAllWeeklyReports()`'s fan-out over active `monitoring.sites`.
2. **Email delivery** — `MailApp.sendEmail()` + `buildEmailHtml()`.
3. **PDF archiving** — the Drive upload inside `weeklyReport()`.

**Explicitly not in scope, stays on Apps Script untouched:** the Sheets backup writer
(`doPost` → `sheet.appendRow()`) and `saveDriveBackup()` — found while scoping this to run
from the *same* `doPost` handler right after the Sheets write, not from `weeklyReport()`,
so it's part of the Sheets-backup job rather than the PDF-archiving one being retired.
`vrm` reports are untouched either way — Apps Script's scheduler has never generated
those; they stay manual, from the Streamlit Reporte tab, exactly as decided for V1.

### Decisions locked with the user (2026-08-16)

- **Email: Resend**, over Postmark or SES.
- **Scheduling: a GitHub Actions scheduled workflow** (`cron:` trigger), over a Supabase
  Edge Function + `pg_cron` — this app has no deployed server today (it only runs when
  someone starts Streamlit locally), so a `cron`/`launchd` job tied to a personal Mac was
  ruled out as a real reliability regression from what Apps Script already provides
  today (always-on, independent of any one machine).
- **A new `monitoring.report_log` table** (`site_id, sent_at, storage_path,
  recipient_email, email_status, error`) — not literally asked for, but agreed because an
  unattended scheduled job needs somewhere to say what happened; Apps Script's
  `Logger.log()` disappears once execution ends, and that's exactly the kind of silent
  failure this repo has hit before (see the Sheets-vs-Supabase weekly-report bugs, and
  `vrm.ingestion_log`'s own reasoning in migration 012).

### Tasks (see plan doc §26 for full detail)

1. `victron/archive.py` — PDF archiving via Supabase Storage, reusing
   `proposals/generator.py:upload_pdf()`'s existing pattern (same `solar-tool` bucket,
   new `vrm-monitor-reports/{site_id}/{end_str}.pdf` path convention).
2. Migration: `monitoring.report_log`.
3. Email: port `buildEmailHtml()` (Apps Script, ~150 lines, table-layout/inline-styled,
   no `data:` URIs — Gmail strips them) to a Jinja2 template; wire Resend's send call;
   recipient resolution via the existing `get_report_email` RPC (already ported-ready,
   no change needed — same `.schema("monitoring").rpc(...)` pattern already used
   elsewhere in this repo).
4. `tools/run_weekly_reports.py` — orchestrates archive → email → log, one pass per
   active `monitoring` site, same per-site failure isolation
   `runAllWeeklyReports()` already has (one site's failure logged and skipped, not
   blocking the rest).
5. GitHub Actions workflow (`.github/workflows/`), Monday cron, calling step 4's script.

### Validation

- A real Monday run: recipient, subject, PDF attachment, and archived copy all match
  what Apps Script would have produced; a `report_log` row exists for every site.
- Deliberately break one site's data mid-run — confirm the others still send.
- Cutover: disable only `createWeeklyReportTrigger()`'s trigger. `doPost` (Sheets write +
  `saveDriveBackup()`) keeps running exactly as it does today.

---

## Phase 13 — VRM Monitor Customer Portal: Auth, User Dashboard, Admin Dashboard (5–8 days, separate product surface, scoped 2026-08-16)

> **Superseded by Phase 14** ([`PLAN_PHASE14.md`](PLAN_PHASE14.md)) — the goal stands, the Streamlit implementation does not. Step 1 (migration 021 + login + role resolution) was built and validated live and is **not** to be redone. Kept in full because its product decisions carried forward.

**Goal:** VRM Monitor stops being a tool Oscar operates on customers' behalf and becomes a
product customers log into. A customer follows a **Log in** link from the landing page,
signs in with a password they set from an invitation email, and gets their own
tenant-scoped dashboard — Reports, Upload CSV, My Sites, Profile. Oscar gets an admin
dashboard in the same app: create customers, send the invite, and see every customer,
site, and upload across the product.

Full build plan, resolved decisions, and per-step validation gates:
[`PLAN_PHASE13.md`](PLAN_PHASE13.md). Not duplicated in full here.

### Why this phase exists

Everything about VRM Monitor is sellable today except the part where a customer can
actually use it. The report pipeline is done and validated (V1, plan doc §1–§25), the
`vrm` schema is multi-tenant by design (migration 012), and the landing page is publicly
pitching subscriptions with an account-type toggle and per-site pricing. But
`pages/06_vrm_monitor.py` is an internal Spanish admin tool where Oscar picks a customer
from a dropdown and uploads their CSV for them — there is no login, no customer-facing
surface, and no way to onboard someone without Oscar doing the work by hand. This phase
closes exactly that gap and nothing else.

### Where this sits relative to other phases

- **A new, separate Streamlit application**, not new pages on the existing one. `app.py`
  and everything under `pages/` — including `pages/06_vrm_monitor.py` — are **not modified
  by this phase**. Entry point `victron-monitor/portal/app.py`, all Python in a new
  root-level `vrm_portal/` package (the same "Python at the repo root, product assets under
  `victron-monitor/`" split that `victron/` already follows).
- Off the critical path like Phases 9–12. Triggered by business need (the first external
  customer who should self-serve), not by sequence.
- **Reuses the pipeline, doesn't rebuild it** — `victron/vrm_csv.py`, `victron/ingest.py`,
  `victron/weekly_report.py`, `victron/report_svg.py`, `victron/report_i18n.py`,
  `victron/savings.py`, `database/vrm_report_db.py`, `database/supabase_client.py` are all
  imported as-is. Arch doc §7's "port, don't rebuild."
- **Leaves `vrm_portal/mailer.py` (Resend) behind for Phase 12**, which needs the same
  integration for weekly report emails. Written generic on purpose. If Phase 13 lands
  first, Phase 12 inherits it; if not, Phase 13 writes it.

### Decisions locked (see PLAN_PHASE13.md §1 for the full reasoning)

- **One login per customer**, on `vrm.customers` — the tenant root already in migration 012.
  Auth linkage is a set of columns on that row (`auth_user_id`, `auth_email`, `invited_at`,
  `activated_at`, `account_type`, `site_limit`, `ui_language`), not a companion table.
  `auth_user_id` is a **soft pointer with no FK** to `auth.users`, matching
  `vrm.sites.public_client_id`'s existing precedent: the schema must stay dumpable into its
  own project, and an `ON DELETE CASCADE` from `auth.users` would mean deleting a login
  deletes a customer's telemetry.
- **Access control: service_role + enforced application-layer scoping.** No per-user JWTs,
  no RLS policies yet — `vrm.*` stays RLS-enabled-with-no-policies. `service_role` bypasses
  RLS by definition, so policies would protect nothing the app does; they would only matter
  alongside a new access path (user JWTs) that would have to thread a per-session client
  through modules shared with the untouchable internal app. Migration 012 already wrote this
  intention down; this phase honours it and records the revisit trigger (any non-Streamlit
  client talking to Supabase on a customer's behalf).
- **Real enforcement lives in one choke point**, `vrm_portal/db.py`: every tenant function
  takes `customer_id` as its required first argument, site operations go through
  `assert_owns_site()`, and customer views may not import `get_client()`,
  `database/vrm_report_db.py`, or `victron/ingest.py` directly.
- **Admin identity via `app_metadata.vrm_role == 'admin'`** — tamper-proof (unlike
  `user_metadata`), returned directly by `sign_in_with_password`, no extra table.
- **Invitations: `auth.admin.generate_link(type='invite')` + our own Resend email**, not
  `invite_user_by_email()`. Supabase's default invite link delivers its tokens in the URL
  **fragment**, which is never sent to the server and which Streamlit cannot read; the
  `token_hash` query-param variant + `verify_otp()` is the server-side flow that works, and
  building the link ourselves keeps the email template in git instead of in undiffable
  dashboard state. Re-sends and forgot-password use `type='recovery'` through the same
  activation screen.
- **No public self-serve signup.** Oscar creates accounts; the landing page's
  "Request early access" `mailto:` stays a `mailto:`. The only landing-page change is a
  **Log in** link in the nav.

### Tasks

1. **Migration + shell + login** — `ALTER TABLE vrm.customers` (auth columns + two partial
   unique indexes), `.env.example` additions (`SUPABASE_ANON_KEY`, `PORTAL_BASE_URL`,
   `RESEND_API_KEY`, `PORTAL_FROM_EMAIL`), the entry point with its `sys.path` bootstrap and
   `st.navigation` role branch, `vrm_portal/auth.py`, the login view, `strings.py`.
2. **`vrm_portal/db.py`** — the tenant-scoped choke point, plus `admin_db.py` for the
   cross-customer counterpart. Ships with a scoping test proving customer A cannot touch
   customer B's site.
3. **Customer dashboard: My Sites + Profile** — scoped port of `tab_sites()`, plus profile
   editing, plan/limit display, and change-password.
4. **Customer dashboard: Upload CSV + Reports** — ports of `tab_upload()` and `tab_report()`
   with the customer picker and schema picker removed, `ingest.upsert_customer()` never
   called from a customer session, and the upload history from `vrm.ingestion_log` finally
   surfaced in a UI.
5. **Admin dashboard + invite flow** — Clientes (create/invite/resend/edit/deactivate),
   Sitios (cross-customer), Cargar CSV (on behalf of), Reporte (both schemas), Actividad
   (ingestion log), plus `mailer.py`, `invites.py`, and the branded invite email template.
6. **Landing-page link, deployment, docs** — Log in link in the nav (re-run `build.py`,
   never hand-edit `landing_page.html`), Dockerfile/host config with WeasyPrint's system
   libs, host env vars, `victron-monitor/portal/README.md`, and updates to
   `victron-monitor/README.md`, `ARCHITECTURE.md`, and `CONTEXT.md`.

### Explicit non-goals

Public signup, billing/payments/usage metering (plan is a label plus a site cap), multiple
users per customer, RLS policies / per-user JWTs, persistent login across a hard browser
refresh, VRM API token ingestion, scheduled customer report emails (that's Phase 12),
per-customer report branding / white-labelling, admin impersonation, and retiring
`pages/06_vrm_monitor.py` (it stays live and untouched).

### Validation

- Oscar creates a customer from the admin dashboard → the invite email arrives → the link
  opens the activation screen → the customer sets a password → lands on their dashboard →
  uploads their own CSV → downloads their own report. No Oscar involvement after the invite.
- Customer A cannot see or modify customer B's sites, including by tampering with a
  submitted `site_id` — `NotAuthorized`, nothing written.
- A report generated from the portal is numerically identical to the same range generated
  from `pages/06_vrm_monitor.py`.
- Re-uploading the same CSV does not grow row counts or double alarm episodes.
- `git diff --stat` shows **no changes** to `app.py` or anything under `pages/`, and
  `streamlit run app.py` still works with an unchanged sidebar.

### Open questions for Oscar (block Task 6 only, not 1–5)

Hosting target (recommendation: Render/Railway + Dockerfile + `monitor.paulyco.com`, because
Streamlit Community Cloud sleeps and has no custom domain), portal UI default language
(assumed English with a per-customer `ui_language` override; admin views stay Spanish),
exact Admin v1 scope, whether the landing page's `mailto:` truly stays as-is, and the
site-limit numbers to seed per plan.

---

## Phase 14 — VRM Monitor unified Next.js site: marketing + customer portal + admin, on a Python pipeline API (12–18 days, supersedes Phase 13, scoped 2026-08-16)

**Goal:** VRM Monitor becomes one product on one domain: the marketing page, the customer
dashboard, and Oscar's admin dashboard are all pages of a single Next.js application sharing
one design system, one navigation, and one login — instead of two disconnected surfaces (a
static marketing Artifact and a separate Streamlit app). The Python report pipeline is not
rewritten; it is wrapped in a small internal HTTP API that only the Next.js server calls.

Full build plan, resolved decisions, and per-step validation gates:
[`PLAN_PHASE14.md`](PLAN_PHASE14.md). Not duplicated in full here.

### Why this phase exists

Phase 13 shipped a working Streamlit login and role resolution, but Oscar reviewed the
approach and rejected the *shape*, not the goal: a second Streamlit app ships fast but reads
as a different, disconnected product from the landing page that sells it. This phase rebuilds
the customer-facing surface as one coherent website instead.

### Where this sits relative to other phases

- **Supersedes Phase 13.** `database/migrations/021_vrm_portal_auth.sql` (already run against
  the dev DB) and the product decisions in `PLAN_PHASE13.md` §0.3/§1 mostly carry forward
  unchanged — see `PLAN_PHASE14.md` §7 for the exact decision-by-decision map. What's replaced
  is Streamlit-specific: the app shell, the two-client rule, and — because a browser-facing
  frontend reopens Phase 13's own written revisit trigger — the access-control model.
- `app.py` and everything under `pages/` (including `pages/06_vrm_monitor.py`) are **not
  modified by this phase either**. It stays live and untouched, and remains the only path for
  CSV backfills larger than the new portal's upload cap.
- Off the critical path like Phases 9–13. Triggered by the same business need Phase 13 was.
- Introduces this repo's first JS/TypeScript toolchain (Next.js), alongside the existing
  Python pipeline — `victron/*.py` and `database/vrm_report_db.py` are imported unchanged by
  a new Python API service (`vrm_api/`), not reimplemented.

### Decisions locked (see PLAN_PHASE14.md §1 for the full reasoning)

- **All Supabase access is server-side; no Supabase credential of any kind reaches the
  browser.** No `NEXT_PUBLIC_SUPABASE_*` variable ever exists, every server module is guarded
  by `import 'server-only'`, and `anon`/`authenticated` keep zero grants on `vrm` (unchanged
  since migration 012) — a stronger position than adding RLS policies, which would require
  *opening* a browser-reachable grant in order to then constrain it.
- **Repo layout:** `victron-monitor/web/` (the Next.js app) + root-level `vrm_api/` (a FastAPI
  service importing `victron/*`/`database/*` unchanged), matching this repo's existing
  "Python at the root, product assets under `victron-monitor/`" convention.
- **Hosting:** Vercel for the Next.js app, Render (Docker) for `vrm_api` — WeasyPrint's system
  libraries rule out a buildpack-only host for the pipeline.
- **Design system ports as CSS Modules over shared tokens**, not a Tailwind rewrite, so the
  hand-tuned landing-page CSS can be diffed against the original rather than silently
  regressing inside a mechanical-looking rewrite.
- **Brand blue is being reconsidered**, not silently inherited: Oscar sampled the real
  MultiPlus-II hardware and gave two candidates (`#3481B8` / `#0588B6`) to replace the RAL
  5012 spec value (`#0089B6`) used when the landing page was first designed. Decided on a
  `/styleguide` swatch page, not by hex code alone.
- **One login per customer, admin-provisioned accounts, `generate_link()` + Resend for
  invites** — all carried forward from Phase 13 unchanged.

### Explicit non-goals

Public signup, billing/payments/usage metering beyond `site_limit`, multiple users per
customer, RLS policies / per-user JWTs / any browser-side Supabase client, a real job queue
(Celery/Redis), introducing a test framework as a side effect of this phase, VRM API token
ingestion, scheduled customer report emails (Phase 12's job — this phase only leaves
`victron/mailer.py` behind for it), per-customer report branding, admin impersonation, and
retiring `pages/06_vrm_monitor.py` (stays live, stays the only path for large backfills).

### Validation

- From the deployed marketing page: Log in → sign in → upload a CSV → generate a report →
  download it, end to end on the real hosts (Vercel + Render).
- Three leak checks pass against a production build: no `NEXT_PUBLIC_SUPABASE_*` anywhere in
  the source, no secret key string in the compiled client bundle, and a direct PostgREST call
  against `vrm.sites` with a real user access token returns nothing.
- Customer A cannot see or touch customer B's anything, including via a tampered request
  straight at `vrm_api` with a stolen bearer token.
- A report generated from the new site is numerically identical to the same range generated
  from `pages/06_vrm_monitor.py`, verified inside the Python 3.11 container as well as locally.
- `git diff --stat` shows **no changes** to `app.py` or anything under `pages/`, and
  `streamlit run app.py` still works with an unchanged sidebar.

### Open questions for Oscar (see PLAN_PHASE14.md §0.4 — block specific steps, not the start)

Domain name, Supabase Free vs. Pro (sets the customer-facing CSV upload ceiling), the final
brand-blue pick from the `/styleguide` page, whether the marketing site stays English-only,
Anthropic/Resend spend tolerance now that a public login page exists, and whether to migrate
to Supabase's new `sb_publishable_…`/`sb_secret_…` key format now or at a later cleanup.

---

## Phase 15 — VRM Monitor: direct VRM API ingestion (10–14 days, scoped 2026-08-18; Step 0 done 2026-08-18)

**Goal:** two new, parallel ways data can arrive besides a manual CSV upload — (1) a customer
connects their own Victron VRM account once, with a personal access token they generate in their
own VRM portal, maps their real VRM installations to their VRM Monitor sites, and their data is
pulled from Victron instead of being exported and uploaded by hand; (2) Oscar's own VRM personal
access token already sees his whole fleet (confirmed at Step 0: 13 installations on one account),
and he can link/sync any of it onto any customer's site himself, admin-side — the API-era
equivalent of uploading a CSV on their behalf, added to the plan after Step 0 at Oscar's request.
Neither replaces CSV upload, which stays available for every site regardless of how it's linked,
and a customer who never connects a token must not be able to tell this phase happened.

Full build plan, resolved decisions, the verified Victron API findings, and per-step validation
gates: [`PLAN_PHASE15.md`](PLAN_PHASE15.md). Not duplicated in full here.

### Why this phase exists

`vrm.sites.source` has had a `'vrm_api'` value since migration 012 and nothing has ever written
it. Every customer's data still arrives because a human exported a CSV from the VRM portal and
uploaded it — which caps the product at "as fresh as the last time someone remembered." Migration
012 also pre-built the token columns (`vrm_token_secret_id` and friends) on the explicit
understanding that a plaintext token column was never acceptable. This phase finally uses them.

### Where this sits relative to other phases

- **Depends on Phase 14** (`victron-monitor/web/` + `vrm_api/` + the tenancy choke points). Its
  security model is inherited wholesale, not re-decided.
- Off the critical path like Phases 9–14. Triggered by a customer who should not have to export a
  CSV every week, and by Oscar wanting fleet visibility without exporting one either.
- **Step 0 is done.** Oscar provided a VRM personal access token from his own account; the
  discovery spike ran against 13 real installations and every open question in PLAN_PHASE15.md
  §0.2 is now answered. That same token is being kept permanently as the admin fleet credential
  (§3.3 below), not revoked.
- Touches `victron/vrm_csv.py` for the first time since it was written — but only to *extract* its
  format-independent core into `victron/vrm_daily.py`, behind a byte-identical-output gate.

### Decisions locked (see PLAN_PHASE15.md §1–§6 for the full reasoning)

- **Naming, deliberately:** Victron's remote service is reached through `victron/vrm_remote.py`
  and mapped by `victron/vrm_series.py`. Neither is called "api" — this repo's own FastAPI service
  is already `vrm_api/`, and the ambiguity would otherwise bite every future stack trace.
- **Token storage: Supabase Vault**, reached *only* through three `SECURITY DEFINER` wrappers in
  the `vrm` schema (`vault` is not exposed to the Data API and must never be). The vault secret id
  never leaves Postgres. Envelope encryption is the documented fallback, taken only if Step 1's
  empirical gate fails.
- **Verified against Victron's current docs, correcting the old exploratory doc:** the auth header
  is `X-Authorization: Token <token>` (not `Authorization: Bearer`); a personal access token can
  read **every installation the account can see**, with no per-installation scoping available;
  rate limit is a ~200-request rolling window; and Victron's own terms say the API is not intended
  for commercial use — a business risk flagged for Oscar.
- **The customer maps installations explicitly.** Never auto-mapped, not even when there is exactly
  one installation and one site.
- **Coexistence:** `source` means "the path this site's data currently arrives by," not an
  exclusive mode. Every sync writes a `vrm.ingestion_log` row (`source='vrm_api'`) so "why did this
  report look wrong" stays answerable, and a sync that overwrites CSV-sourced days says so.
- **Trigger:** on-demand "Sync now" in v1 (confirmed by Oscar — Step 7's scheduling is deferred); a
  GitHub Actions `cron:` hitting one authenticated `run-due` endpoint remains the design if it's
  ever built, the same scheduling mechanism Phase 12 locked.
- **Admin fleet access (added after Step 0, PLAN_PHASE15.md §3.3):** Oscar's own token is a
  platform secret (`VRM_ADMIN_TOKEN`, stored like `PIPELINE_API_KEY`/`RESEND_API_KEY`), not a
  Vault-per-customer one — there's exactly one of it. New `vrm_api` endpoints let admin browse his
  fleet and link/sync any installation onto any site; both the Next.js `/admin` panel and
  `pages/06_vrm_monitor.py`'s "Cargar" tab get this capability (Step 4b).

### Explicit non-goals

Replacing the CSV path, OAuth (Victron has none), writing anything back to Victron, real-time
dashboards, multiple VRM accounts per customer, **Oscar pasting a *customer's* token** from
`/admin` (distinct from Oscar using his *own* token as the admin fleet credential, which is now
in scope — see above), widening the scored alarm taxonomy, RLS policies, a real job queue, a test
framework, and backfilling beyond VRM's own retention.

### Validation

- The reference CSV export produces a **byte-identical** `parse_export()` result before and after
  the `vrm_daily.py` extraction.
- The same window pulled through both paths for one real site produces an agreement table within
  written per-column tolerances; anything that can't meet its tolerance ships as `NULL` with a
  warning rather than as a number nobody trusts.
- A token never appears in a log line, a `vrm.jobs` row, a client bundle, a URL, or a cookie.
- Customer A's token cannot reach customer B's data, including via a tampered request aimed
  straight at `vrm_api`.
- Re-syncing does not grow row counts, double alarm episodes, or leave two `daily_health` rows for
  one date on a mixed-source site.
- `git diff --stat` shows no changes to `app.py` or anything under `pages/`.

### Open questions — all resolved 2026-08-18 (see PLAN_PHASE15.md §0.5–§0.6)

All eight are answered: the Step 0 token was provided and Step 0 is complete; Victron's
non-commercial API terms are an accepted risk Oscar will address directly with Victron via the
Software Integrator Program; on-demand "Sync now" is enough for v1 (Step 7 deferred); initial
backfill is 31 days at 15-minute interval; admin does not paste a *customer's* token (Oscar's own
admin-fleet token, added after Step 0, is a separate and already-scoped exception, see above); and
`source` stays non-exclusive. Nothing blocks Step 1.

---

## Phase 16 — VRM Monitor: public signup + customer self-service billing on ONVO Pay (complete, 2026-08-19 → 2026-08-21)

**Goal:** a stranger can sign up from the landing page, verify their email, enter a card, and be a
working customer minutes later — and an existing customer manages their own subscription (upgrade,
downgrade, cancel), the card on file, and their billing address from `/app/billing`. And
`vrm.customers.plan`/`site_limit` stop being values a human types into `/admin/customers` and become a
derived consequence of a real, paid, verified ONVO subscription.

Full build plan, the verified-vs-unverified ONVO API findings, and per-step validation gates:
[`PLAN_PHASE16.md`](PLAN_PHASE16.md). Not duplicated in full here.

### Why this phase exists

Every plan change before this phase was Oscar editing a row, and every customer arrived because Oscar
invited them. That doesn't scale past the people he can remember, and it meant the product had no
revenue mechanism and no acquisition mechanism of its own — `plan` and `site_limit` were assertions,
not consequences of anyone having paid.

### What shipped

- **Public self-serve signup** (`/signup` → `/signup/verify` → `/activate`, reusing the existing
  invite/activation machinery rather than paralleling it). A submission stages a
  `vrm.signup_requests` row and sends one email; no `vrm.customers` row, Supabase auth user, or ONVO
  object of any kind exists until a single-use, hashed, 24-hour token is redeemed.
- **Customer self-service billing** at `/app/billing` (also the first-run checkout surface for a
  freshly-verified signup): subscribe, upgrade/downgrade (cancel-and-restart — no in-place price
  change exists on ONVO's side, confirmed at Step 0), cancel (graceful by default), resume, replace
  the card, edit the billing address, view renewal history. Card entry exists in exactly one place in
  the codebase — the ONVO web SDK's own card form; no card data ever reaches this product's servers.
- **Read-through reconciliation, not event-sourced** (§0.5): ONVO is the source of truth, this
  product's database is a cache, and a webhook (`/api/webhooks/onvo` → `vrm_api`'s
  `POST /v1/billing/webhook-event`) is a cache-invalidation hint only — never a payload that gets
  applied to a mirror row. Four reconcile triggers (post-mutation, webhook, on-read staleness, and the
  new daily `cron:` sweep) keep entitlement correct within one page load or 24 hours, even if every
  webhook is lost.
- **Admin visibility**: a billing column and per-customer actions on `/admin/customers` (view,
  refresh/reconcile, cancel — never card entry by Oscar), a pending-signups filter, a **Promote to
  active** support escape hatch, and a recent-signups panel.
- **Scheduling + retention** (Step 7): `.github/workflows/billing-reconcile.yml` — this repo's first
  GitHub Actions workflow (Phase 12 locked `cron:` as the mechanism but never built one) — runs daily,
  calling `POST /v1/billing/reconcile-due` (the scheduled sweep) and the new
  `POST /v1/billing/prune-signups` (retention for `vrm.signup_requests` and `vrm.rate_limits`, §3.7/
  §3.8) against `vrm_api`, authenticated with repo secrets.
- Migration 025: `vrm.plans`, `vrm.billing_customers`, `vrm.subscriptions`, `vrm.subscription_invoices`,
  `vrm.billing_events`, `vrm.signup_requests`, `vrm.rate_limits`, plus `site_limit_source`/
  `provisioning_state`/`origin` columns on `vrm.customers` — all additive, every existing customer's
  behavior unchanged.

### Decisions locked (see PLAN_PHASE16.md §0.5, §3, §4, §5.5, §6)

- **ONVO is the source of truth; our database is a cache; webhooks are cache-invalidation hints and
  nothing more.** ONVO documents no `subscription.created`/`.updated`/`.canceled` event, warns events
  can arrive out of order, and states no retry policy — so state is never written from an event
  payload; it is always re-read from ONVO with our own secret key. This also makes a forged webhook
  structurally unable to change anything.
- **Public signup verifies the email before anything exists.** A submission writes only a
  `vrm.signup_requests` staging row and sends one email; the `vrm.customers` row is created only when
  a single-use, hashed, 24-hour token is redeemed; the ONVO customer and subscription are created only
  when the visitor enters a card; and the account is promoted to a real tenant only when a *reconcile*
  observes an entitled subscription. An abandoned signup leaves nothing usable and no ONVO object.
- **No ONVO object id is ever accepted from a request body.** Every id is looked up from a mirror row
  already scoped to a tenancy-checked customer — the direct analogue of Phase 15's installation-id
  binding, and here it is what stands between us and charging the wrong person's card.
- **No card data ever touches our servers.** ONVO's web SDK renders the card form; our servers hold
  opaque ids only.
- **A downgrade never deactivates or deletes a site.** An over-limit customer keeps everything and is
  simply blocked from adding more.
- **Deliberately deferred, recorded as a conscious risk acceptance, not an oversight:** Costa Rican
  tax/factura electrónica (Q7) — prices are not confirmed to include or exclude the 13% IVA, and no
  electronic invoice is issued. Surfaces after the first live (non-test-mode) charge, not before —
  worth Oscar's own eyes before flipping `ONVO_MODE` to `live`.

### Explicit non-goals

One-off payments/Checkout Sessions (so the $9.99 single report is not purchasable at signup), the
Solar Design Tool's unrelated `onvo_commission_pct` columns, social/OAuth login, multi-user accounts,
self-serve account deletion, disposable-email blocklists, factura electrónica/Hacienda filing,
refunds/coupons/marketplace/SINPE, dunning and abandoned-signup emails, invoice PDFs, metered billing,
automatic site deactivation, and any change to `victron/`, `pages/`, or `app.py` — confirmed at the end
of this phase: `git diff --stat -- pages/ victron/` is empty.

### Validation

Every step validated live against a real test-mode ONVO account and a running `vrm_api`/Next.js dev
server — see PLAN_PHASE16.md's per-step validation gates for the full list. Step 7 specifically:
`POST /v1/billing/reconcile-due` and the new `POST /v1/billing/prune-signups` both called live with the
exact headers/URL shape the GitHub Actions workflow uses; the prune endpoint verified against
deliberately-backdated throwaway rows in both `vrm.signup_requests` and `vrm.rate_limits` (old rows
deleted, fresh rows untouched, test rows cleaned up afterward); the workflow YAML validated with
`actionlint` (zero issues) and greped to confirm every secret is referenced only via `${{ secrets.NAME
}}`, never a literal value.

---

## Phase 17 — VRM Monitor: scheduled reports, report cost limits, tiered branding, visible trial (complete, 2026-08-21 → 2026-08-25)

**Goal:** the four things VRM Monitor sold on the Pricing page but did not have. A customer puts a site
on a daily/weekly/monthly schedule and the report arrives on its own — rendered, archived, emailed,
logged, with one site's failure never touching another's. Report generation stopped being an unbounded
cost, via two independent per-tier caps that live in a table Oscar can `UPDATE`. A Growth/Fleet
customer's report finally carries their own branding and a Starter customer's provably does not. And the
7-day trial is now visible on the Pricing cards and the signup form.

Full build plan, the confirmed-context tables, and per-step validation gates:
[`PLAN_PHASE17.md`](PLAN_PHASE17.md). Not duplicated in full here.

### Why this phase existed

Three of the four features were already on the Pricing page with **no automated report generation for
`vrm` customers at all** — reports existed only as an on-demand click — and `vrm.customers.branding` had
been an empty jsonb column since migration 012 that nothing read and no UI wrote. Meanwhile every report
cost a real Anthropic call with nothing bounding how many a customer could trigger. Phase 16 gave the
product a revenue mechanism; this phase made the thing being paid for actually run by itself.

### Where this sits relative to other phases

- Depended on Phases 14/15/16 (the web app, `vrm_api`, the tenancy model, `vrm.plans`,
  `vrm.rate_limits`, `apply_entitlements()`'s `billing_status`).
- **Closed Phase 15's deferred Step 7**: `POST /v1/vrm-sync/run-due` existed and had never been called —
  `.github/workflows/scheduled-reports.yml` now calls it every hour, ahead of the report step.
- **Is not Phase 12.** Phase 12 (the `monitoring` schema, Oscar's own bureau clients) remains unbuilt.
  This phase reused Phase 12's mechanism decision (GitHub Actions `cron:`) and left
  `victron/templates/report_email.html`/`cap_reached_email.html` plus `victron/mailer.py`'s attachment
  support behind for it.
- Touched `victron/` for the first time since Phase 15 — three files (`mailer.py`, two new templates),
  additively, behind a byte-identical-PDF gate for the unbranded/`monitoring` case.

### Decisions locked (see PLAN_PHASE17.md §0.5–§0.7, §2, §3, §4, §5)

- **The scheduler is a stateless due-check over durable state, not a queue.** "Due" is computed from the
  calendar and a ledger (`vrm.report_runs`), never from a timer, so a missed run, a late run, or two
  overlapping runs all produce the same result as one on-time run. Idempotency is a partial unique index
  in Postgres, not a lock in a process — proven live with 5 simultaneous claim attempts on the same
  period producing exactly 1 winner.
- **Every per-tier number is a database row** (`vrm.plan_limits`), not a constant. The fallback row is
  the most restrictive, deliberately the opposite of `lib/plans.ts:planSiteLimit()`'s fail-open
  behaviour.
- **Two independent report caps**: a short-window rate limit on manual regeneration (fails open — an
  abuse control) and a per-billing-period cap on scheduled runs (a UI-side projection at schedule-set
  time; a real backstop at run time).
- **Branding is resolved in exactly one server-side function** (`vrm_api/branding.py:resolve_branding()`)
  and the renderer never sees the raw jsonb. The chart palette is semantic and is never recolored — proven
  by rendering a low health score under a bright-amber brand colour and confirming the health badge stayed
  the fixed semantic red, not the brand colour, in both the PDF and the report email.
- **The entitlement gate is a denylist, not an allowlist** — `billing_status='none'` (every legacy,
  hand-created customer) keeps receiving reports, confirmed live rather than assumed.
- **Schedules are per-site**, and **CSV-sourced sites are structurally excluded from scheduling** at
  three independent layers (a database CHECK constraint, the write path, and the UI) — proven live by
  directly attempting the forbidden write and watching Postgres itself reject it.
- **Third-party report recipients are allowed, capped at 5 per site** (Q5, resolved 2026-08-25), with a
  stateless, HMAC-signed, cross-runtime unsubscribe link — no login required to opt out.

### Explicit non-goals

A real job queue, sub-hourly or cron-expression schedules, custom date ranges on a schedule, scheduled
reports for CSV-sourced sites at all, a report *template* system (branding is name/logo/colour/contact
only), recoloring the chart palette, fetching a customer-supplied URL at render time, multi-user accounts
or per-user notification preferences, a full unsubscribe preference centre beyond the one footer link,
any billing change, metered billing, backfilling the report ledger from `vrm.jobs`, RLS policies, a test
framework, and any change to `pages/`, `app.py`, the `monitoring` schema, Node-RED, or Apps Script.

### Validation

Every step validated live, not just typechecked — real Supabase writes against disposable fixtures
created and torn down by the tests themselves, confirmed zero leftovers each time. The headline ones: a
full end-to-end scheduled run producing a real Anthropic-narrated PDF, uploaded to real Storage, and a
real branded email landing in a real inbox with that PDF attached (confirmed by Oscar, screenshot and PDF
both); a `billing_status='none'` legacy customer's site generating normally; a CSV-sourced site rejected
by the database itself when a live schedule is attempted on it; 5 simultaneous scheduler claims on one
period producing exactly 1 winner; a customer hitting their scheduled-report cap across two sites in one
tick, and again on a second tick, triggering exactly one notification email for the whole billing period,
not two; and the `scheduled-reports.yml` workflow's own bash+`jq` loop run for real against the live API,
correctly stopping once `remaining` reached 0. Not verified this session: a real 48-hour unattended cron
run and a real GitHub-hosted `workflow_dispatch` trigger — both require the workflow to be pushed and
live on GitHub, which this session did not do without being asked.

### Decisions Oscar made 2026-08-21 → 2026-08-25 (see PLAN_PHASE17.md §0.6–§0.7)

Per-site schedules (Q1); Oscar's own limit-numbers table (Q2); report email in this phase, not a
fast-follow (Q4); logo to real storage, customer-editable fields confirmed as color + header text only
(Q6, Q8); CSV-sourced sites never eligible for scheduling at all, enforced at three independent layers,
which also settled Q9 (the deferred Phase 15 VRM sync) as load-bearing rather than optional (§0.7); and,
2026-08-25, **third-party report recipients allowed, capped at 5 per site**, with an unsubscribe footer
link (Q5) — the fuller option, not the "customer's own address only" fallback.

## Phase 18 — VRM Monitor: personalized report modules for Growth/Fleet (in progress, started 2026-08-26)

**Goal:** let Growth/Fleet installer accounts choose which content modules appear in a given site's
report, instead of every site getting the same fixed set — the content-personalization sibling of Phase
17's tiered white-label branding (appearance only). Phase 1 (module toggling on the existing 12 modules)
shipped 2026-08-28; Phase 2 (new module types) is in progress.

Full build plan, the module inventory (verified against a live VRM API diagnostics probe, not assumed),
and per-step validation gates: [`PLAN_PHASE18.md`](PLAN_PHASE18.md). Not duplicated in full here.

### Why this phase exists

The marketing page has always sold "computed once and shown consistently everywhere" as a feature to
everyone — this phase is a deliberate carve-out from that promise for paying tiers who manage many
client sites and want more control over the deliverable, not a walk-back of the promise for
Starter/owner accounts.

### Where this sits relative to other phases

- Depends on Phase 17 (`resolve_branding()`'s exact tier-gating shape; the `report_schedule`/
  `default_report_schedule` per-site/per-customer column pattern, reused verbatim for module selection).
- Built on its own branch (`feature/personalized-reports`) rather than directly on `main`, given the
  size of the risk — a mistake here degrades every existing customer's report, not just Growth/Fleet's —
  merged back once Phase 1 was fully verified.
- A live, read-only VRM API diagnostics probe against all 13 real installations (2026-08-26) corrected
  several assumptions in this codebase's own existing comments (per-tracker PV yield is real, not
  API-blocked as `vrm_series.py`'s docstring claimed; a real grid meter, generator run-hours, and a tank
  sensor all exist on real sites today) — grounding Phase 2's module inventory in verified fact.
- Closed a real, unrelated bug found along the way: the battery-health block's "Avg temperature" row
  had displayed `max_temp`, not an average, since the block was written — shipped to `main` immediately
  as its own fix (commit `7d06f3c`), independent of this phase.
- Also surfaced (2026-08-28/29) that `PIPELINE_API_URL`'s GitHub Actions secret was wrong, silently
  breaking both `scheduled-reports.yml` and `billing-reconcile.yml` for two days — fixed the same day,
  unrelated to this phase's own code but found while chasing down why a live test didn't show expected
  behavior.

### Decisions locked (see PLAN_PHASE18.md's Decisions section, §1–§5)

- **The 12 modules split 3 fixed + 9 selectable.** KPI header, AI narrative, and the daily bar chart are
  the report's identity and are never optional; the other 9 are independently selectable.
- **Selection lives per-site, with a per-customer default** — identical shape to
  `report_schedule`/`default_report_schedule` (migration 026): `NULL` means "every module on," today's
  exact behavior, unchanged; a customer's default only ever applies to a *new* site, never retroactively.
- **Entitlement is enforced once, server-side**, in `resolve_report_modules()` — reuses the exact same
  `white_label` plan_limits flag and tier/account-type population branding already gates on, rather than
  a second, identically-seeded column. Admin can set a selection for any customer regardless of plan
  (same "admin write path is separate and untiered" precedent branding uses), but render-time
  entitlement is re-checked independently of who triggered generation — proven live: a real admin-set
  selection on a non-entitled test customer correctly rendered every module anyway, and the same
  selection, simulated against an entitled customer, correctly applied.
- **What looked like the hard part (a full layout-reflow engine) turned out narrow.** `row2`/`row3`
  already used generic pairing functions, so 8 of the 9 modules got full independent toggling without a
  rewrite; the one real gap (a full-width 3-way energy-mix donut for a battery system missing only
  `battery_health`) was a single new function, not a redesign.
- **A real gap was found and fixed after Phase 1 "shipped"**: the one function every real report path
  goes through (`_do_report()`) never actually called `resolve_report_modules()` — a saved selection had
  zero effect on any real report until this was wired in, caught by Oscar's own live test on a real site,
  not by any of this phase's earlier verification.

### Explicit non-goals (Phase 1)

New module *types* (deferred to Phase 2 — see `PLAN_PHASE18.md` §7 for the full, verified candidate
list, with **Critical alerts** — DC ripple, cell imbalance, temperature faults — as the explicit top
priority), a real full-width 3-way donut becoming a general-purpose N-way layout primitive, module
selection for CSV-sourced sites being treated any differently than VRM-API sites (deliberately no such
distinction — module selection isn't gated by live-data freshness the way scheduling is), and an
operator-notes module (the column exists; nothing writes to it yet).

### Validation

Every step verified against real data, not just typechecked: a byte-for-byte identical regression check
(a real site's report, before and after, matching exactly) confirming zero effect on any customer who
never opts in; six real rendered PDF combinations covering every edge case (empty selection, a
single-block fallback, the documented energy-mix/battery-health gap); the entitlement gate exercised
with 7 real cases against the live `plan_limits` table; and, after Oscar's own live test surfaced the
wiring gap, the exact real site and saved selection re-verified end to end, correctly hiding the
deselected modules once entitlement was actually met.

---

## Timeline summary

| Phase | Description | Estimated days | Cumulative |
|---|---|---|---|
| 0 | Foundation | 3–5 | Week 1 |
| 1 | PDF engine | 4–6 | Week 2 |
| 2 | Grid Zero wizard | 6–8 | Weeks 3–4 |
| 3 | Proposal management | 3–4 | Week 4–5 |
| 4 | AI features | 4–5 | Week 5–6 |
| 5 | Off-Grid + Hybrid | 5–7 | Week 7–8 |
| 6 | Projects module | 5–6 | Week 9–10 |
| 7 | Admin + polish | 3–4 | Week 11 |
| 8 | QA + handoff | 2–3 | Week 11–12 |
| 9 | Victron Monitor multi-tenant hardening | 3–5 | Whenever needed — independent of 0–8 |
| 10 | Site register & maintenance scheduler | 4–6 | Whenever needed — independent of 0–9 |
| 11 | Design calibration from fleet data | 4–6 | Whenever needed — gated by data, not sequence |
| 12 | Retire Apps Script scheduling/email/archiving | 2–4 | Whenever needed — independent of 0–11 |
| 13 | VRM Monitor customer portal (Streamlit, superseded) | 5–8 | Step 1 built & validated; superseded by Phase 14 |
| 14 | VRM Monitor unified Next.js site + Python pipeline API | 12–18 | Whenever needed — triggered by the first self-serve customer |
| 15 | VRM Monitor: direct VRM API ingestion (customer-connected accounts + Oscar's admin fleet access) | 10–14 | Whenever needed — triggered by a customer who shouldn't have to export a CSV weekly, or by Oscar wanting fleet visibility without one |
| 16 | VRM Monitor: public signup + customer self-service billing on ONVO Pay | 13–18 | Complete (2026-08-19 → 2026-08-21) — the first phase that gives the product its own revenue and acquisition mechanism |
| 17 | VRM Monitor: scheduled reports, report cost limits, tiered branding, visible trial | 9–13 | Complete (2026-08-21 → 2026-08-25) — the phase where the product's marketing copy and its behaviour were made to agree |

**First real proposal possible:** End of Phase 2 (week 3–4), Grid Zero only, manual input  
**Full MVP ready:** End of Phase 8 (~12 weeks at part-time pace)  
**Victron Monitor sellable to external customers:** End of Phase 9, triggered by business need (first external customer), not by calendar time  
**Site register replaces the maintenance spreadsheet:** End of Phase 10, triggered by whenever you want off the manual xlsx, not by calendar time  
**Fleet-calibrated design constants become self-refreshing:** End of Phase 11, gated by monitored sites accumulating enough history, not by calendar time  
**Apps Script fully retired from the weekly-report pipeline:** End of Phase 12, triggered by wanting off Gmail send quotas / Google's execution limits, not by calendar time  
**VRM Monitor becomes self-serve (customers log in and run it themselves):** End of Phase 14 (Phase 13's Streamlit approach was superseded before completion), triggered by the first customer who should not need Oscar to upload their CSV for them

These are part-time estimates assuming 2–3 focused hours per day alongside client work. If you have a full week free, Phase 0+1 can be done in 3 days.

---

## Critical path

The sequence that cannot be reordered:

```
Phase 0 (Supabase + scaffold)
    ↓
Phase 1 (PDF engine) ← most important to get right early
    ↓
Phase 2 (Grid Zero wizard + calculations) ← first real usable output
    ↓
Phase 3 (versioning) ← makes it a real tool, not a prototype
    ↓
Phase 4 (AI) ← can be done in parallel with Phase 5 if needed
    ↓
Phase 5 (Off-Grid + Hybrid) ← can start before Phase 4 is complete
    ↓
Phase 6 (Projects) ← depends on proposals being stable
    ↓
Phase 7 + 8 (admin + QA) ← always last
```

Phases 4 and 5 have no hard dependency on each other. If you have a real Off-Grid proposal urgent before the AI features are done, do Phase 5 first.

**Phase 9 is off this critical path entirely.** It belongs to Victron Monitor, a separate product sharing this repo and Supabase project — not a step in the solar tool's proposal/projects/admin roadmap. Trigger it by business need (onboarding the first external Victron Monitor customer), not by sequence.

**Phase 10 is also off this critical path.** It spans both products (extends `monitoring.sites`, adds new `public` schema tables) and its UI hangs off the Projects nav item without depending on Phase 6 being built. Trigger it whenever you're ready to retire the manual maintenance spreadsheet.

**Phase 11 (Design Calibration) is off the critical path too**, and is gated by *data* rather than by other phases — VRM's ~6-month retention of 1-minute data means the low-irradiance months only become exportable in a December run. The first calibration was already done by hand (see [`docs/design-calibration-2026-08.md`](docs/design-calibration-2026-08.md)) and its results are live in the tier tables, so this phase is about making that repeatable, not about unblocking proposals.

**Phase 12 (Retire Apps Script scheduling/email/archiving) is off this critical path too.** Report *rendering* is already fully on Python for both `monitoring` and `vrm` — this phase only replaces the automation shell (trigger, `MailApp`, Drive) still running on Apps Script. Trigger it whenever Gmail's send quotas or Apps Script's execution limits become a real constraint, not by sequence.

**Phase 13 (VRM Monitor customer portal, Streamlit) is superseded by Phase 14** — its Step 1 (migration 021, login, role resolution) was built and validated live, but the app shell it was building is replaced. See `PLAN_PHASE13.md`'s supersession banner and `PLAN_PHASE14.md` §7 for the full decision map.

**Phase 14 (VRM Monitor unified Next.js site) is off this critical path as well**, and — like Phase 13 before it — builds a *second application* rather than extending the existing one; `app.py` and `pages/` stay untouched. It depends on the VRM report pipeline (done) and on nothing else; Phases 9 and 12 are complementary but not prerequisites. Phase 14 and Phase 12 overlap in exactly one place — the Resend integration — and whichever lands first should write `victron/mailer.py` generically so the other inherits it. Trigger Phase 14 by the first customer who should be able to upload their own CSV without Oscar doing it for them.

**Phase 15 (direct VRM API ingestion) is off this critical path too**, and is the first phase that *depends* on another off-path phase: it builds on Phase 14's web app, `vrm_api`, and tenancy model rather than standing alone. It is also the first time this product stores a credential belonging to a third party on a customer's behalf, which is why its plan spends more of its length on storage and tenancy than on features. Trigger it by the first customer for whom weekly CSV exports are the thing standing between them and renewing.

**Phase 16 (public signup + ONVO billing) is off this critical path too, and is now complete.** Like Phase 15 it depends on Phase 14's web app, `vrm_api`, and tenancy model. Unlike every previous phase, its failure modes are financial rather than informational, and it opened this system's first door that starts outside it (a stranger with no session, at `/signup`) — which is why its plan spent most of its length on reconciliation, tenancy, and the trust boundary rather than on features. It is the first phase that makes VRM Monitor self-sustaining: a stranger can now sign up, verify, pay, and become a working customer with no action from Oscar, and an existing customer manages their own subscription end to end.

**Phase 17 (scheduled reports, report cost limits, tiered branding, visible trial) is off this critical path too, and is now complete.** It depends on 14/15/16. It is the phase where the product's marketing copy and the product's behaviour were made to agree: three of its four features were already on the Pricing page and none of the three existed. It is also the first phase whose primary deliverable runs when nobody is watching (`.github/workflows/scheduled-reports.yml`, hourly), which is why its plan spent more of its length on failure visibility, idempotency, and timezone arithmetic than on features. Triggered by the first customer who should not have to click Generate every Monday morning.

---

## Starting prompt for Claude Code (Phase 0)

When you open Claude Code, paste this to kick off:

```
I'm building a solar proposal tool for Pauly&Co, a Costa Rican solar company.
Read REQUIREMENTS.md for full context.

Start Phase 0:
1. Create the full folder structure from the requirements
2. Generate requirements.txt with all dependencies
3. Create config.py with brand colors and constants
4. Create utils/supabase_client.py
5. Write the complete Supabase schema SQL as database/schema.sql
6. Create seed/seed_tariffs.py with 2026 ARESEP T-RE residential tariffs for all 8 distributors
7. Create a one-time script tools/invert_signature.py that inverts firma_white.png to firma_dark.png using Pillow
8. Create app.py with Streamlit sidebar navigation (Proposals, Projects, Admin sections)

Use python-dotenv for .env loading. Supabase client should be a singleton.
```
