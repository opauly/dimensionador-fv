# Pauly&Co Solar Tool — Project Context

> **Living document.** Update at the end of every phase. A new Claude session should read
> REQUIREMENTS.md, PHASES.md, and this file — in that order — before writing any code.

---

## Current state

| Item | Value |
|---|---|
| **Phase completed** | Phase 2 — Grid Zero Wizard |
| **Phase next** | Phase 3 — Proposal Management |
| **Branch** | main |
| **Last commit** | see `git log` |
| **Working tree** | Phase 2 code committed |

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
2. Client info table (5 rows, grey label column)
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

## Phase 3 starting instructions

**Goal:** Proposals list, version history, locking. The tool becomes a real workspace.

**Do this before writing any code:**
1. Read PHASES.md Phase 3 section in full
2. Read REQUIREMENTS.md sections 3 (versioning) and 8 (versioning UI)

**Key files to implement:**
- `pages/01_proposals.py` — Proposals list table, filter by status, click to open, version history panel
- `database/proposals_db.py` — `lock_version()` and `mark_version_sent()` are already stubbed (Phase 3)
- `wizard/grid_zero.py` Step 8 — Add "Bloquear versión" button after PDF download
- `pages/02_new_proposal.py` — Add "Nueva versión" flow (loads existing version data, opens wizard at step 1)

**Validation:** Create 3 versions of a proposal, lock v1, create v2, lock v2, verify v1 PDF path unchanged, mark v2 as sent.
