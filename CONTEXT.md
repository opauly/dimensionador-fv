# Pauly&Co Solar Tool — Project Context

> **Living document.** Update at the end of every phase. A new Claude session should read
> REQUIREMENTS.md, PHASES.md, and this file — in that order — before writing any code.

---

## Current state

| Item | Value |
|---|---|
| **Phase completed** | Phase 4 full + Phase 3 UX polish (Cotizaciones directed-flow, per-version PDF) + Phase 7 partial (Admin equipment catalog, ARESEP tariff xlsx parser) |
| **Phase next** | Phase 5 — Off-Grid wizard |
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
| `calculations/sizing_off_grid.py` | 5 | Off-Grid sizing |
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

## Phase 5 starting instructions

**Goal:** Off-Grid wizard (Steps 4–8 for off-grid system type).

**Key files to implement:**
- `calculations/sizing_off_grid.py` — battery sizing, days of autonomy, charge controller selection
- `wizard/off_grid.py` — Steps 4–8 mirroring grid_zero.py structure
- Step 5 in off_grid.py reuses `_render_bill_section`, `_render_loads_section` from grid_zero.py (or refactor to shared module)

**Validation target:** Jorge Ramírez off-grid system (see validation reference numbers above).
