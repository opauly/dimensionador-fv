# Pauly&Co Solar Tool — Development Phases

**Builder:** Oscar Pauly (solo)  
**Stack:** Streamlit · Supabase · WeasyPrint/Jinja2 · Anthropic SDK · numpy-financial  
**Reference:** Requirements v3.4  
**Goal:** Real proposals in production as fast as possible  
**Last updated:** 2026-07-13

| Phase | Status |
|---|---|
| 0 — Foundation | ✅ Complete |
| 1 — PDF Engine | ✅ Complete |
| 2 — Grid Zero Wizard | ✅ Complete |
| 3 — Proposal Management | ✅ Complete + UX polish (directed flow, per-version PDF) |
| 4 — AI Features | ✅ Complete (bill parser, tablero, datasheet, load estimator, daytime fraction) |
| 5 — Off-Grid + Hybrid | ⬜ Not started |
| 6 — Projects Module | ⬜ Not started |
| 7 — Admin + Polish | 🔶 Partial (equipment catalog ✅, ARESEP xlsx parser ✅, tariff manager UI ✅; cost templates, settings pending) |
| 8 — QA + Handoff | ⬜ Not started |
| 9 — Victron Monitor Multi-Tenant Hardening | ⬜ Not started (separate product, no dependency on 0–8) |

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

This phase belongs to `victron-monitor/`, not the solar proposal tool — it has no dependency on Phases 0–8 and can be done whenever the subscription business is ready to onboard its first external (non-Pauly&Co-owned) site. See [`victron-monitor/README.md`](victron-monitor/README.md) and [`CONTEXT.md`](CONTEXT.md#victron-monitor-integration-added-2026-07-13) for current architecture.

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

## Future — Victron weekly-report tariff savings (separate product, not scheduled)

**Goal:** the Victron weekly PDF + email show an **estimated savings** figure for the customer, instead of the current "coming soon" placeholder.

Belongs to `victron-monitor/`, not the solar tool's roadmap. Cross-product: the report reuses this repo's tariff data/formula. Full plan and prerequisites in [`CONTEXT.md`](CONTEXT.md#victron-monitor-integration-added-2026-07-13).

- Port `estimate_bill_crc` (`calculations/tariff_calculator.py`) to JS inside the Apps Script; read tariffs live from the shared Supabase `public` tables via PostgREST.
- Define each site's electric company (`distributor` + `tariff_code`) via the Node-RED Project Config payload.
- Savings ≈ `(weekly load − weekly grid import) × effective ₡/kWh`.
- **Blocked on:** Supabase creds in Apps Script Script Properties, anon `SELECT` on the public tariff tables, and tariffs seeded for the relevant distributors.

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

**First real proposal possible:** End of Phase 2 (week 3–4), Grid Zero only, manual input  
**Full MVP ready:** End of Phase 8 (~12 weeks at part-time pace)  
**Victron Monitor sellable to external customers:** End of Phase 9, triggered by business need (first external customer), not by calendar time

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
