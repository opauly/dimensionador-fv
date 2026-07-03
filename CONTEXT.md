# Pauly&Co Solar Tool — Project Context

> **Living document.** Update at the end of every phase. A new Claude session should read
> REQUIREMENTS.md, PHASES.md, and this file — in that order — before writing any code.

---

## Current state

| Item | Value |
|---|---|
| **Phase completed** | Phase 3 — Proposal Management |
| **Phase next** | Phase 4 — AI Features |
| **Branch** | main |
| **Last commit** | see `git log` |
| **Working tree** | Clean — all Phase 3 + quote numbering committed |

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
| `proposals/generator.py` | ✅ done | `generate_pdf()` + `upload_pdf()` implemented |
| `proposals/templates/grid_zero_es.html` | ✅ done | Spanish — 1-page, pixel-accurate |
| `proposals/templates/grid_zero_en.html` | ✅ done | English — 1-page, full translation |
| `wizard/state.py` | ✅ done | Auto-save, load_draft, company/bank defaults |
| `wizard/common.py` | ✅ done | Steps 1–3: system type, client, site+PVGIS |
| `wizard/grid_zero.py` | ✅ done | Steps 4–8: utility, consumption, equipment, costs, review |
| `calculations/tariffs.py` | ✅ done | Block-tier bill calculator, IVA threshold, bomberos |
| `calculations/sizing_grid_zero.py` | ✅ done | System kW, monthly generation, savings table, averages |
| `calculations/pvgis.py` | ✅ done | PVGIS API call + Supabase cache + CR geocode lookup table |
| `calculations/mppt.py` | ✅ done | 3-scenario validator centered on target kW |
| `calculations/financials.py` | ✅ done | IRR + ROI implemented |
| `database/proposals_db.py` | ✅ done | Proposal + version CRUD |
| `database/equipment_db.py` | ✅ done | Read functions for Phase 2 |
| `database/tariffs_db.py` | ✅ done | Read functions for Phase 2 |
| `database/clients_db.py` | ✅ done | New file: client search + upsert |
| `pages/02_new_proposal.py` | ✅ done | Full 8-step wizard orchestrator |
| `ai/bill_parser.py` | 4 | Bill PDF extraction |
| `ai/datasheet_parser.py` | 4 | Equipment spec extraction |
| `ai/proposal_writer.py` | 4 | Intro paragraph generation |
| `calculations/sizing_off_grid.py` | 5 | Off-Grid sizing |
| `calculations/load_estimator.py` | 5 | Tablero load estimation |
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

## Phase 4 starting instructions

**Goal:** All AI-powered shortcuts operational.

**Key files to implement:**
- `ai/bill_parser.py` — Upload bill PDF → Claude extracts month, kWh, ₡ amount
- `ai/datasheet_parser.py` — Upload PDF → Claude extracts specs → pre-fills equipment form
- `ai/proposal_writer.py` — Call Claude → returns 2–4 sentence intro paragraph (ES + EN)
- `wizard/grid_zero.py` Step 5 — Add bill PDF upload + AI extraction UI
- `wizard/grid_zero.py` Step 8 — Wire up AI intro paragraph generation + "Regenerar" button
- `pages/05_admin.py` — Equipment catalog with datasheet upload + AI fill

**Validation:** Upload a real CNFL or ICE bill PDF → verify extracted kWh matches actual bill; generate intro paragraph in both languages.
