# Pauly&Co Solar Design Tool — Final Requirements v3.0

**Version:** 3.0  
**Date:** 2026-07-02  
**Scope:** Grid Zero, Off-Grid, Hybrid (On-Grid placeholder)  
**Deployment:** macOS local first (Streamlit), later web (Supabase backend)

---

## Change log v2 → v3

- Auto-save / draft persistence throughout the wizard
- Proposal versioning system (v1, v2, v3… per proposal)
- Projects module with financial tracking (from Finanzas template)
- Supabase as the recommended backend (replaces SQLite/PostgreSQL distinction)
- Five additional features added (Section 14)

---

## 1. Overview

A wizard-driven solar proposal tool for Pauly&Co engineers. The engineer walks a structured input flow, the tool calculates all technical and financial parameters, and produces a branded PDF proposal in Spanish or English matching the existing Pauly&Co quotation format exactly.

The tool has three top-level areas:

- **Proposals** — create, draft, version, and manage client quotations
- **Projects** — active jobs that have been won, with financial tracking
- **Admin** — equipment catalog, tariffs, cost templates, settings

---

## 2. Auto-Save and Draft Persistence

### 2.1 Behavior

Every wizard step saves to the database automatically on field change (debounced, 2-second delay) or on "Next" / "Back" navigation. No explicit "Save" button needed. The engineer can close the browser or app at any point and return to exactly where they left off.

A draft indicator appears in the top-right of the wizard: `● Guardado / Saved` (green dot, updates to `Guardando…` during the write).

### 2.2 Draft state machine

```
New → Draft (auto-saved) → Complete (all required fields filled) → Proposal generated
                                                                  ↓
                                                          Version history
```

Incomplete wizards appear in the Proposals list with a `Borrador / Draft` badge and show which step they were last on (e.g., "Paso 3 de 8 — Equipos").

### 2.3 What gets saved

Every wizard field is serialized as a JSON document stored in a single `proposal_data` JSONB column in Supabase. This makes schema changes trivial — adding a new field doesn't require a migration. The JSON structure mirrors the wizard steps:

```json
{
  "meta": { "system_type": "grid_zero", "language": "es", "step_reached": 5 },
  "client": { "name": "María José Castro", "phone": "...", "email": "..." },
  "site": { "city": "Atenas", "province": "Alajuela", "lat": 9.98, "lon": -84.38, "pvgis_data": {...} },
  "utility": { "distributor": "ICE", "nise": "N/A", "tariff_type": "T-RE" },
  "consumption": { "source": "billing", "months": [...], "avg_kwh": 1475 },
  "equipment": { "panel_id": "uuid", "inverter_id": "uuid", "mppt_scenario": "B" },
  "costs": { "line_items": [...], "iva_rate": 0, "subtotal_usd": 18110 },
  "proposal_text": "Esta propuesta…"
}
```

---

## 3. Proposal Versioning

### 3.1 Concept

Every time a PDF is generated and confirmed by the engineer, a **version snapshot** is locked. Subsequent edits create a new version. The client may request a price change or equipment swap — the engineer adjusts and generates a new version without losing the previous one.

```
Proposal: María José Castro — Grid Zero
  ├── v1  01/07/2026  $18,110   PDF ↓   [Active]
  ├── v2  03/07/2026  $16,500   PDF ↓   (panel count reduced)
  └── v3  05/07/2026  $17,200   PDF ↓   [Sent to client]
```

### 3.2 Version rules

- Versions are **immutable once locked**. Locking happens when the engineer clicks "Confirmar versión / Lock version" on the review step.
- A new version inherits all data from the previous version as a starting point.
- The engineer can add a **version note** (e.g., "Cliente pidió reducción de precio — quité 2 paneles").
- Any version can be re-exported as PDF at any time.
- One version can be marked `[Enviado / Sent]` — the one most recently shared with the client.
- Any version can be promoted to a **Project** (see Section 5). Only one version per proposal can be promoted.

### 3.3 Data model (Supabase)

```sql
proposals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at    timestamptz DEFAULT now(),
  updated_at    timestamptz DEFAULT now(),
  client_name   text,                    -- denormalized for quick listing
  system_type   text,                    -- grid_zero | off_grid | hybrid
  status        text DEFAULT 'draft',    -- draft | active | won | lost | cancelled
  current_version_number int DEFAULT 1
)

proposal_versions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id   uuid REFERENCES proposals(id) ON DELETE CASCADE,
  version_number int NOT NULL,
  created_at    timestamptz DEFAULT now(),
  locked_at     timestamptz,             -- null = current working version
  locked        boolean DEFAULT false,
  version_note  text,
  sent_to_client boolean DEFAULT false,
  total_usd     numeric(10,2),           -- denormalized for quick display
  data          jsonb NOT NULL,          -- full wizard state
  pdf_path      text                     -- Supabase Storage path to generated PDF
)
```

### 3.4 UI — Proposals list

Each row in the proposals table shows:
- Client name + system type
- Status badge (Draft / Active / Won / Lost)
- Current version number and total
- Date last modified
- Quick actions: Open, New version, View PDF, Promote to project

---

## 4. Supabase as the Backend

### 4.1 Why Supabase is a strong fit

Yes — Supabase is an excellent choice for this project for the following reasons:

**It solves the local → web migration cleanly.** Right now you're building a single-user local Mac app in Streamlit. Supabase gives you a hosted PostgreSQL database + file storage + auth from day one. When you move to web, the backend is already production-ready — you just change the Streamlit deployment target. No SQLite-to-Postgres migration needed.

**JSONB for wizard state.** PostgreSQL's native JSONB type handles the flexible, evolving wizard data without schema migrations every time a field is added. You can index specific JSON keys for performance when needed.

**Storage for PDFs and assets.** Supabase Storage handles PDF outputs, uploaded datasheets, bill PDFs, electrical plan images, logo, and signature — all in one place with access control.

**Auth when you need it.** Currently single-user, so auth can be bypassed (or use a single hardcoded service role key). When you add more engineers, Supabase Auth is one config change away — including magic-link login and Row-Level Security per user.

**Real-time (future).** If you ever want a dashboard showing live project status across engineers, Supabase real-time subscriptions are built in.

**Cost.** Free tier covers: 500MB database, 1GB storage, 50,000 monthly active users. More than enough for a 1–5 person engineering team.

### 4.2 Connection pattern (Streamlit)

```python
# utils/supabase_client.py
from supabase import create_client, Client
import os

def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]  # service role for server-side
    return create_client(url, key)
```

`.env` file for local development:
```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
ANTHROPIC_API_KEY=sk-ant-...
```

### 4.3 Complete database schema

```sql
-- Equipment catalog
panels (
  id uuid PK, brand text, model text, wp int,
  voc numeric, vmp numeric, isc numeric, imp numeric,
  temp_coeff_pmax numeric, width_m numeric, height_m numeric,
  area_m2 numeric GENERATED ALWAYS AS (width_m * height_m) STORED,
  weight_kg numeric, warranty_product_yr int DEFAULT 10,
  warranty_power_yr int DEFAULT 25, cost_usd numeric,
  datasheet_path text, notes text,
  created_at timestamptz DEFAULT now()
)

inverters (
  id uuid PK, brand text, model text, kw numeric,
  type text, -- string_inverter | microinverter | hybrid
  vmax numeric, vmin_mppt numeric, vmax_mppt numeric, imax_mppt numeric,
  mppt_channels int, phase text, output_v numeric,
  warranty_yr int DEFAULT 5, cost_usd numeric,
  datasheet_path text, notes text,
  created_at timestamptz DEFAULT now()
)

batteries (
  id uuid PK, brand text, model text, chemistry text,
  capacity_kwh numeric, capacity_ah numeric, voltage_v numeric,
  dod_pct int, cycles int, warranty_yr int DEFAULT 10,
  cost_usd numeric, notes text,
  created_at timestamptz DEFAULT now()
)

charge_controllers (
  id uuid PK, brand text, model text, type text,
  vin_max numeric, vout numeric, imax_in numeric, imax_out numeric,
  cost_usd numeric, notes text,
  created_at timestamptz DEFAULT now()
)

monitoring_devices (
  id uuid PK, brand text, model text,
  compatible_with text, cost_usd numeric,
  created_at timestamptz DEFAULT now()
)

-- Tariffs
distributors (
  id uuid PK, name text UNIQUE, abbreviation text, coverage_area text
)

tariff_types (
  id uuid PK, distributor_id uuid REFERENCES distributors(id),
  code text, -- T-RE, T-CO, T-REH, etc.
  name text, sector text, -- residential | commercial | industrial
  access_charge_crc numeric, -- fixed monthly infrastructure charge
  bomberos_pct numeric DEFAULT 0.0175,
  iva_threshold_kwh int DEFAULT 280, -- IVA exempt below this
  last_updated timestamptz DEFAULT now()
)

tariff_tiers (
  id uuid PK, tariff_type_id uuid REFERENCES tariff_types(id),
  from_kwh int, to_kwh int, -- null = unlimited
  rate_crc numeric, -- CRC per kWh (or fixed charge if from_kwh = 0 and is_fixed)
  is_fixed boolean DEFAULT false,
  sort_order int
)

-- Proposals and versions (see Section 3.3)
proposals ( ... )
proposal_versions ( ... )

-- Projects (see Section 5)
projects ( ... )
project_expenses ( ... )
project_payments ( ... )
project_invoices ( ... )

-- Settings
app_settings (
  key text PRIMARY KEY,
  value jsonb,
  updated_at timestamptz DEFAULT now()
)
-- e.g. key='company_info', key='exchange_rate_cache', key='default_iva_rate'
```

### 4.4 Supabase Storage buckets

```
solar-tool/
├── proposals/
│   └── {proposal_id}/
│       ├── v1_2026-07-01_Maria_Castro.pdf
│       ├── v2_2026-07-03_Maria_Castro.pdf
│       └── uploads/
│           ├── bill_jan_2026.pdf
│           └── tablero_tempisque.jpg
├── equipment/
│   └── datasheets/
│       ├── JA_Solar_620W.pdf
│       └── Fronius_Primo_10.pdf
└── assets/
    ├── logo_pauly_color.png
    └── firma_oscar_dark.png
```

---

## 5. Projects Module

### 5.1 Concept

When a client accepts a proposal, the engineer promotes it to a **Project**. The project is the live job: the proposal version is locked as the contract baseline, and a financial tracking workspace opens.

The financial workspace is modeled directly on the `Finanzas - Jorge Ramírez (FV).xlsx` template, implemented as a set of database-backed interactive screens inside the Streamlit app.

### 5.2 Sheets to implement (from the Excel)

The template has 9 sheets. These are the ones to implement:

| Sheet | Implement | Notes |
|---|---|---|
| **Presupuesto** | ✅ Yes — core | Budget dashboard. Ingresos, pagos recibidos, gastos por rubro, utilidad bruta/neta |
| **Banco** | ✅ Yes | Bank transaction log: rubro, valor, fecha, pagado, comentarios |
| **Equipo** | ✅ Yes | Equipment purchase log: same structure as Banco |
| **Materiales** | ✅ Yes | Materials purchase log |
| **Mano de obra** | ✅ Yes | Labor payments with advance tracking (adelantos) per worker |
| **Viáticos** | ✅ Yes | Travel/expense log |
| **Extras** | ✅ Yes | Miscellaneous expenses |
| **Pagos Lori / Client payments** | ✅ Yes | Client-side payment tracking: invoice amounts, CC commission (ONVO), paid/pending |
| **Facturación** | ✅ Yes | Invoice line items by category (Equipos/Materiales/Servicios) with IVA per line |

### 5.3 Presupuesto screen — data model

Mirrors the Excel's Presupuesto sheet exactly:

**INGRESOS (Revenue)**
```
Contract amount (USD) — pulled from proposal version total
IVA rate on contract — 0% or 13%
Contract total with IVA
Extras (additional work orders) — add rows
Grand total income
```

**PAGOS (Client payments received)**
```
Pago 1: amount, paid (yes/no), date, bank account confirmed
Pago 2: ...
Pago 3: ...
Pago 4: ...
Pago 5: ...
Total received vs. total contracted
```

**GASTOS (Expenses by category)**
```
Rubro | Costo | IVA | Costo total | Pagado | Presupuestado | Remanente
Banco (bank charges)
Materiales
Equipo FV
Mano de obra
Viáticos
Extras
[+ add row]
Total
```

Budget (Presupuestado) column is pre-filled from the proposal cost breakdown when the project is created.

**UTILIDAD (Profit)**
```
Utilidad bruta = Total ingresos - Total gastos (before IVA)
IVA a pagar = sum of IVA collected on services - IVA paid on expenses
Utilidad neta = Utilidad bruta - IVA neto
```

### 5.4 Expense detail tabs

Each expense category (Banco, Equipo, Materiales, Mano de obra, Viáticos, Extras) is a ledger with the same structure:

```
Rubro | Valor (USD) | Fecha | Pagado (Sí/No) | Comentarios
[+ Add entry]
TOTAL: auto-sum
```

Labor (Mano de obra) adds:
- Worker name / contractor
- Advance tracking: Cotización inicial, Adelanto #1, Adelanto #2, Adelanto #3
- Saldo pendiente = Cotización - sum(adelantos)

### 5.5 Facturación (Electronic invoicing log)

One row per item on the electronic invoice (factura electrónica). Matches the Facturación sheet:

```
Artículo | Categoría (Equipos/Materiales/Servicios) | Tasa IVA | Monto | Subtotal | IVA | Total
```

Summarized by category at the bottom:
```
Equipos:    subtotal, IVA 0%, total
Materiales: subtotal, IVA 13%, total
Servicios:  subtotal, IVA 13%, total
TOTAL GENERAL
```

### 5.6 Client payments / ONVO tab

Tracks client payments including credit card processing fees (ONVO gateway):

```
Project | Total contract
Payment 1 (70%): gross amount, CC commission (2.4%), net to deposit, paid date, pending
Payment 2 (30%): same
---
ONVO commission breakdown:
  Total paid by client
  Commission 2.4%
  IVA on commission
  Por depositar (net received)
```

### 5.7 Projects database schema

```sql
projects (
  id              uuid PK DEFAULT gen_random_uuid(),
  proposal_id     uuid REFERENCES proposals(id),
  version_id      uuid REFERENCES proposal_versions(id), -- the winning version
  created_at      timestamptz DEFAULT now(),
  client_name     text, -- denormalized
  system_type     text,
  status          text DEFAULT 'active', -- active | completed | paused | cancelled
  contract_usd    numeric(10,2),
  contract_iva_rate numeric(4,3),
  notes           text
)

project_payments (
  id          uuid PK DEFAULT gen_random_uuid(),
  project_id  uuid REFERENCES projects(id) ON DELETE CASCADE,
  payment_number int, -- 1, 2, 3...
  amount_usd  numeric(10,2),
  paid        boolean DEFAULT false,
  paid_date   date,
  bank_account text, -- BAC, etc.
  onvo_commission_pct numeric(5,4) DEFAULT 0.024,
  onvo_iva_pct numeric(5,4),
  net_deposited numeric(10,2),
  notes       text
)

project_expenses (
  id          uuid PK DEFAULT gen_random_uuid(),
  project_id  uuid REFERENCES projects(id) ON DELETE CASCADE,
  category    text, -- banco | equipo | materiales | mano_de_obra | viaticos | extras
  description text,
  amount_usd  numeric(10,2),
  iva_rate    numeric(4,3) DEFAULT 0,
  total_with_iva numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED,
  paid        boolean DEFAULT false,
  expense_date date,
  budgeted_usd numeric(10,2), -- from proposal cost breakdown
  receipt_path text, -- Supabase Storage path to receipt scan
  notes       text
)

project_labor (
  id              uuid PK DEFAULT gen_random_uuid(),
  project_id      uuid REFERENCES projects(id) ON DELETE CASCADE,
  worker_name     text,
  role            text,
  quoted_amount   numeric(10,2),
  advances        jsonb, -- [{number: 1, amount: 460, date: "2026-01-15"}, ...]
  total_advanced  numeric(10,2),
  balance_pending numeric(10,2) GENERATED ALWAYS AS (quoted_amount - total_advanced) STORED
)

project_invoice_items (
  id          uuid PK DEFAULT gen_random_uuid(),
  project_id  uuid REFERENCES projects(id) ON DELETE CASCADE,
  description text,
  category    text, -- equipos | materiales | servicios
  iva_rate    numeric(4,3),
  amount_usd  numeric(10,2),
  iva_amount  numeric(10,2) GENERATED ALWAYS AS (amount_usd * iva_rate) STORED,
  total_usd   numeric(10,2) GENERATED ALWAYS AS (amount_usd * (1 + iva_rate)) STORED
)
```

### 5.8 Project dashboard (summary view)

Top-level summary card for each active project:

```
[Project name — system type]   [Status badge]
Contract:  $10,320             Received: $7,224 (70%)
Expenses:  $0 / $10,320        Pending: $3,096
Profit:    $10,320 → $0 spent  
```

---

## 6. Application Architecture — Updated

```
solar_tool/
├── app.py                         # Streamlit entry, sidebar nav, session state
├── .env                           # SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY
├── config.py                      # Constants, brand colors, defaults
│
├── database/
│   ├── supabase_client.py         # Supabase client singleton
│   ├── proposals_db.py            # CRUD: proposals, proposal_versions
│   ├── projects_db.py             # CRUD: projects, expenses, payments, invoices
│   ├── equipment_db.py            # CRUD: panels, inverters, batteries, etc.
│   ├── tariffs_db.py              # CRUD: distributors, tariff_types, tariff_tiers
│   └── seed/
│       ├── seed_equipment.py      # Sample panels, inverters, batteries
│       └── seed_tariffs.py        # 2026 ARESEP tariffs, 8 distributors
│
├── wizard/
│   ├── state.py                   # Auto-save logic, session state helpers
│   ├── common.py                  # Steps 1–3 (system type, client, site)
│   ├── grid_zero.py               # Steps 4–8 Grid Zero
│   ├── off_grid.py                # Steps 4–8 Off-Grid
│   └── hybrid.py                  # Steps 4–8 Hybrid
│
├── calculations/
│   ├── pvgis.py                   # PVGIS API + caching in Supabase
│   ├── tariffs.py                 # Tiered bill calculator (IVA, bomberos, blocks)
│   ├── sizing_grid_zero.py
│   ├── sizing_off_grid.py
│   ├── mppt.py                    # String design validator
│   ├── load_estimator.py          # 3-scenario load-based kWh estimation
│   └── financials.py              # IRR (numpy_financial), ROI, 25yr projections
│
├── ai/
│   ├── client.py                  # Anthropic SDK wrapper
│   ├── datasheet_parser.py        # Equipment spec extraction
│   ├── bill_parser.py             # Monthly kWh + CRC from bill PDFs
│   ├── tablero_parser.py          # Load schedule extraction
│   ├── tariff_updater.py          # Tariff table from distributor PDFs
│   └── proposal_writer.py         # Intro paragraph (ES/EN)
│
├── proposals/
│   ├── templates/                 # Jinja2 HTML templates (4 files)
│   ├── assets/                    # logo + firma (embedded base64 at build)
│   └── generator.py               # WeasyPrint → PDF → Supabase Storage
│
├── pages/
│   ├── 01_proposals.py            # Proposals list + version history
│   ├── 02_new_proposal.py         # Wizard entry
│   ├── 03_projects.py             # Projects list + financial dashboard
│   ├── 04_project_detail.py       # Presupuesto + all ledger tabs
│   └── 05_admin.py                # Equipment, tariffs, settings
│
└── utils/
    ├── currency.py                # Fetch + cache CRC/USD exchange rate
    └── formatting.py              # CRC/USD formatters, rounding
```

---

## 7. Auto-Save Implementation

```python
# wizard/state.py

import streamlit as st
from database.proposals_db import upsert_version

def autosave(proposal_id: str, version_id: str):
    """Called after every field change. Writes current session state to Supabase."""
    data = {
        "meta": st.session_state.get("wizard_meta", {}),
        "client": st.session_state.get("wizard_client", {}),
        "site": st.session_state.get("wizard_site", {}),
        "utility": st.session_state.get("wizard_utility", {}),
        "consumption": st.session_state.get("wizard_consumption", {}),
        "equipment": st.session_state.get("wizard_equipment", {}),
        "costs": st.session_state.get("wizard_costs", {}),
        "proposal_text": st.session_state.get("wizard_proposal_text", ""),
    }
    upsert_version(version_id, data)
    # Show save indicator in UI
    st.session_state["last_saved"] = datetime.now()

def load_draft(version_id: str):
    """Restores wizard session state from Supabase on app load."""
    row = get_version(version_id)
    if row:
        for key, value in row["data"].items():
            st.session_state[f"wizard_{key}"] = value
```

Streamlit's `on_change` callback on every input widget triggers `autosave()`. No user action needed.

---

## 8. Proposal Versioning — UI Flow

```
Proposals list
  → Open proposal "María José Castro"
    → Shows: v1 (locked, $18,110), v2 (locked, $16,500), v3 (current, in progress)
    → Click "v3 — En progreso"
      → Opens wizard at last saved step
      → Engineer makes changes
      → Review step: sees "Bloquear versión / Lock version" button
      → Locks v3 → PDF generated → stored in Supabase Storage
      → Option: "Marcar como enviada / Mark as sent to client"
      → Option: "Mover a Proyecto / Promote to Project" → opens Project creation form
```

---

## 9. Tariff Database — ARESEP Strategy (Confirmed)

The ARESEP website uses a JavaScript-rendered widget — static scraping is not viable. Confirmed approach:

**Seed data:** 2026 tariffs hardcoded at install for all 8 distributors. Approximate values from official ARESEP publications effective 2026-01-01.

**CNFL auto-refresh:** The CNFL publishes a PDF at cnfl.go.cr. "Refresh CNFL tariffs" button fetches the PDF → sends to Claude → extracts tariff table as JSON → updates DB. Covers the most common distributor in the GAM area.

**Manual override:** Any tariff can be edited per distributor in the Tariff Manager. Each row shows `last_updated` timestamp. Warning shown if any distributor tariffs are >90 days old.

**Bill-based fallback:** If the client's actual bill PDF is available, the actual amount paid / kWh consumed is a more accurate basis than recalculated tariffs. The bill parser extracts this directly.

---

## 10. Financial Model (Confirmed)

### IRR / TIR
Pure 25-year cashflow IRR via `numpy_financial.irr()`:
```python
cashflow = [-total_project_crc] + [savings_year_1 * (1.05 ** y) for y in range(25)]
irr_pct = npf.irr(cashflow) * 100  # → e.g. 22.92%
```

### ROI
Simple payback:
```python
roi_years = total_project_crc / savings_year_1  # → e.g. 5.48
```

### Savings projection
5% annual tariff escalation (configurable in Settings):
```python
savings_25yr = sum(savings_year_1 * (1.05 ** y) for y in range(25))
```

### Currency
- Equipment/project costs: USD
- Bills and savings: CRC
- Exchange rate: exchangerate-api.com, cached 1 hour in Supabase `app_settings`
- Toggle on proposals: display savings in CRC or USD

---

## 11. Additional Recommended Features

### 11.1 Client contact book

Currently the wizard asks for client data per proposal. As proposals multiply, the same client will appear again. A lightweight contact database avoids re-typing and links all proposals and projects to the same client:

```sql
clients (
  id uuid PK,
  name text,
  phone text,
  email text,
  notes text,
  created_at timestamptz
)
```

On the client step, typeahead autocomplete searches existing clients. If found, one click fills all fields. New clients auto-saved.

### 11.2 Equipment cost history and price alerts

Equipment prices (especially panels, batteries, and inverters) change frequently. The DB stores `cost_usd` per item, but the engineer may not remember to update it. Add:
- `equipment_price_history` table: tracks each cost update with date
- Visual sparkline on equipment cards showing price trend (3–6 data points)
- Optional: flag when an equipment item hasn't had its price updated in >60 days

### 11.3 Proposal email delivery

After generating a PDF, a one-click "Enviar al cliente / Send to client" button:
- Composes a pre-written email with the PDF attached (template in Spanish or English)
- Sends via SendGrid or Resend (both free tiers)
- Logs the send event on the version (`sent_at`, `sent_to_email`)
- Marks version as `[Enviado / Sent]` automatically

This replaces the current manual download → attach → email workflow.

### 11.4 Dashboard / home screen

Instead of jumping straight to a list, the home screen shows:
- **Open drafts** (proposals not yet sent)
- **Awaiting response** (proposals sent to client, no decision)
- **Active projects** with a mini progress bar (% of contract received, % of budget spent)
- **This month:** proposals sent, projects won, revenue received
- Quick-access button: "Nueva cotización / New proposal"

### 11.5 Proposal status pipeline

A simple Kanban-style or list-view pipeline to track where each proposal sits:

```
Borrador → Enviada → En negociación → Ganada → Perdida
 (draft)   (sent)    (negotiating)    (won→Project)  (lost)
```

Engineer drags or clicks to move proposals through stages. The `won` transition triggers the "Promote to Project" flow.

### 11.6 PDF cover letter / presentation mode (future)

Beyond the one-page quotation, some clients want a multi-page proposal document with:
- Cover page (client name, system type, date, Pauly&Co branding)
- Technology overview page (what is solar, how does it work — pre-written, translated)
- System diagram page (simplified schematic)
- Technical summary
- Financial summary
- Quotation page (existing)

This reuses all existing data and templates; it's a second PDF output mode. Not MVP, but architected for it.

### 11.7 Maintenance service tracking (future)

Each active project has a maintenance contract (annual visit, extra cost). A simple log per project:
- Visit scheduled date
- Visit completed date
- Engineer who visited
- Notes
- Invoice generated (yes/no)

This keeps the Projects module useful years after installation.

---

## 12. Resolved Design Decisions Summary

| # | Question | Decision |
|---|---|---|
| 1 | Auto-save | Supabase JSONB per wizard step, debounced 2s. No manual save button needed. |
| 2 | Proposal versioning | Immutable locked snapshots per version. Unlimited versions per proposal. Version note field. |
| 3 | Projects module | Financial tracking matching the Finanzas Excel. 8 screens: Presupuesto, Banco, Equipo, Materiales, Mano de obra, Viáticos, Extras, Facturación, Client payments (ONVO). |
| 4 | Backend | Supabase (PostgreSQL + Storage + Auth). Eliminates local/web migration friction. JSONB for wizard state. |
| 5 | ARESEP | Seed data + AI-assisted CNFL PDF refresh + manual override per distributor. |
| 6 | Hybrid excess solar | AC coupling — description note only, no cost line. |
| 7 | Intro paragraph | AI-generated, editable textarea, Regenerate button. |
| 8 | Monthly billing table in PDF | Average row only. |
| 9 | Financial projections | 5% escalation, `numpy_financial.irr()`, simple payback ROI. |
| 10 | Assets | Logo_color_v3.png (top-right). firma_white.png inverted to dark via Pillow. Both base64-embedded in Jinja2 templates. |
| 11 | Load estimation | Tablero upload → AI extract → 3 scenarios (conservative 40%/6h, optimal 55%/8h, maximum 75%/10h). Proposal notes estimate-based. |

---

## 13. Tech Stack (Final)

| Layer | Technology | Notes |
|---|---|---|
| UI | Streamlit | Multi-page app (`pages/` directory) |
| Backend / DB | Supabase (PostgreSQL) | JSONB for wizard state, relational for ledgers |
| File storage | Supabase Storage | PDFs, datasheets, bill scans |
| PDF generation | WeasyPrint + Jinja2 | 4 HTML templates (2 types × 2 languages) |
| AI | Anthropic Python SDK | `claude-sonnet-4-6` for all AI features |
| Irradiance | PVGIS REST API v5.2 | Free, no key |
| Exchange rates | exchangerate-api.com | Free tier, cached in Supabase |
| Financial math | numpy-financial | `npf.irr()` |
| Charts | Plotly | Savings projection, project expense charts |
| Image processing | Pillow | Invert firma_white.png at startup |
| Email (future) | Resend or SendGrid | Free tier for proposal delivery |

---

## 14. MVP Scope vs. Later

### MVP (build first)

- Complete wizard for Grid Zero, Off-Grid, Hybrid
- Auto-save and draft persistence
- Proposal versioning (lock, PDF, version notes)
- PDF generation matching existing Pauly&Co format (ES + EN)
- Equipment catalog with AI datasheet ingestion
- MPPT string validator (3 scenarios)
- Billing history entry (manual + PDF AI extraction)
- Load estimation from tablero (3 scenarios)
- PVGIS irradiance auto-fetch
- Seeded ARESEP 2026 tariffs with manual override
- Projects module: Presupuesto + all expense ledgers + Facturación + ONVO payments
- Supabase backend

### Later (post-MVP)

- CNFL AI-assisted tariff PDF refresh
- Client contact book with autocomplete
- Proposal email delivery (Resend)
- Home dashboard with pipeline
- Proposal status Kanban
- Equipment price history
- Maintenance service tracking
- Multi-user auth (Supabase Auth + RLS)
- Multi-page proposal document (cover + tech overview)
- On-Grid (net metering) system type
