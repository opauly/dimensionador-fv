# Pauly&Co — Solar Design Tool & Victron Monitor

This repository hosts two products built by **Pauly y Compañía**, sharing one Supabase project:

| Product | What it does | Where |
|---|---|---|
| **Solar Design Tool** | Wizard-driven solar proposal generator (Grid Zero, Off-Grid, Hybrid) with PDF output, proposal versioning, and project financial tracking | repo root — see below |
| **Victron Monitor** | Fleet monitoring for deployed Victron Energy systems via Node-RED + Google Apps Script, with weekly AI-narrated reports | [`victron-monitor/`](victron-monitor/README.md) |

They're separate products with independent roadmaps, isolated by Postgres schema (`public` vs `monitoring`) in the same Supabase project — see [CONTEXT.md](CONTEXT.md#victron-monitor-integration-added-2026-07-13) for why they're consolidated.

---

## Solar Design Tool

A wizard-driven proposal tool for Pauly&Co engineers. The engineer walks a structured input flow, the tool calculates all technical and financial parameters, and produces a branded PDF proposal in Spanish or English.

Three top-level areas:
- **Proposals** — create, draft, version, and manage client quotations
- **Projects** — won jobs with full financial tracking
- **Admin** — equipment catalog, tariffs, cost templates, settings

### Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Backend/DB | Supabase (PostgreSQL + Storage + Auth) |
| PDF | WeasyPrint + Jinja2 |
| AI | Anthropic Claude API |
| Irradiance | PVGIS REST API |
| Financial math | numpy-financial |
| Charts | Plotly |

### Setup

```bash
# 1. Clone and create a virtualenv (Python 3.9+ — see CONTEXT.md for a macOS-specific note on why 3.9)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ANTHROPIC_API_KEY, EXCHANGE_RATE_API_KEY

# 3. Set up the database (run in Supabase SQL Editor, in order)
#    database/schema.sql
#    database/migrations/*.sql

# 4. Seed reference data
python -m database.seed.seed_tariffs
python -m database.seed.seed_equipment   # if present

# 5. Run
streamlit run app.py
```

### Project docs

- [REQUIREMENTS.md](REQUIREMENTS.md) — full functional specification
- [PHASES.md](PHASES.md) — development phases, current status, roadmap
- [CONTEXT.md](CONTEXT.md) — living doc: environment quirks, current state, decisions made along the way

Read these three, in that order, before making architectural changes.

---

## Victron Monitor

Fleet monitoring for Victron Energy installations — Cerbo GX devices running Node-RED push telemetry to this project's `monitoring` schema and to Google Sheets, with a Claude-narrated weekly PDF report.

See [`victron-monitor/README.md`](victron-monitor/README.md) for architecture, setup, onboarding a new site, and troubleshooting.

**Status:** internally deployed across a handful of Pauly&Co-owned sites. Not yet ready to sell as a paid subscription to external customers — see Phase 9 in [PHASES.md](PHASES.md) for what's needed first (per-site Row-Level Security and per-device credential provisioning, replacing the current shared-key model).

---

## Repository structure

```
.
├── app.py, pages/, wizard/, proposals/, calculations/, ai/, database/, utils/, config.py
│   └── Solar Design Tool (Streamlit app)
├── database/migrations/
│   └── Schema migrations for both `public` (solar tool) and `monitoring` (Victron Monitor)
├── victron-monitor/
│   └── Victron Monitor (Node-RED flow, Apps Script, schema reference, docs)
├── tools/
│   └── One-off scripts (asset prep, tariff parsing, etc.)
├── REQUIREMENTS.md, PHASES.md, CONTEXT.md
│   └── Solar Design Tool planning docs
└── .env.example
```
