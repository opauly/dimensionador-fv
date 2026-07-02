# Pauly&Co Solar Tool — Project Context

> **Living document.** Update at the end of every phase. A new Claude session should read
> REQUIREMENTS.md, PHASES.md, and this file — in that order — before writing any code.

---

## Current state

| Item | Value |
|---|---|
| **Phase completed** | Phase 0 — Foundation |
| **Phase next** | Phase 1 — PDF Engine |
| **Branch** | main |
| **Last commit** | `9354f1c` Phase 0 fixes: Python 3.9 compat + seed idempotency |
| **Working tree** | Clean |

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
| `proposals/generator.py` | 1 | PDF generation — next up |
| `proposals/templates/` | 1 | Jinja2 HTML templates — next up |
| `wizard/` | 2 | All wizard steps |
| `calculations/tariffs.py` | 2 | Tiered bill calculator |
| `calculations/sizing_grid_zero.py` | 2 | Grid Zero sizing |
| `calculations/pvgis.py` | 2 | PVGIS API |
| `calculations/mppt.py` | 2 | String design validator |
| `calculations/financials.py` | ✅ done | IRR + ROI implemented |
| `database/proposals_db.py` | 2 | Proposal CRUD |
| `ai/bill_parser.py` | 4 | Bill PDF extraction |
| `ai/datasheet_parser.py` | 4 | Equipment spec extraction |
| `ai/proposal_writer.py` | 4 | Intro paragraph generation |
| `calculations/sizing_off_grid.py` | 5 | Off-Grid sizing |
| `calculations/load_estimator.py` | 5 | Tablero load estimation |
| `database/projects_db.py` | 6 | Project financial CRUD |
| `ai/tariff_updater.py` | 7 | CNFL PDF tariff refresh |

---

## Phase 1 starting instructions

**Goal:** Generate a pixel-perfect Grid Zero PDF from hardcoded data. No wizard yet.

**Do this before writing any code:**
1. Read PHASES.md Phase 1 section in full
2. Read REQUIREMENTS.md sections 1, 6, 12, and 13
3. Ask Oscar for the reference PDF (María José Castro quotation) to match visually

**Files to create/implement:**
- `proposals/templates/grid_zero_es.html`
- `proposals/templates/grid_zero_en.html`
- `proposals/generator.py` — `generate_pdf()` and `upload_pdf()`
- Add a test button to `pages/02_new_proposal.py` that generates a PDF from hardcoded data

**Brand:**
- Green: `#4BAE6A` (table headers, section underlines)
- Navy: `#1E2D54` (sidebar, headings)
- Logo: `proposals/assets/logo_pauly_color.png` (not yet present — ask Oscar)
- Signature: run `tools/invert_signature.py` after Oscar places `firma_white.png`

**Validation:** generate both ES and EN from the María José Castro data dict.
Compare side-by-side with the reference PDF until pixel-accurate.
