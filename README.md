# Pauly&Co — Solar Design Tool

Wizard-driven solar proposal generator (Grid Zero, Off-Grid, Hybrid) for Pauly y Compañía, with PDF output, proposal versioning, and project financial tracking.

**Victron Monitor / VRM Monitor moved to its own repo, 2026-09-16:** [`github.com/opauly/vrm-monitor`](https://github.com/opauly/vrm-monitor) now hosts the fleet-monitoring pipeline (Node-RED + Apps Script ingestion, the report pipeline, `vrm_api`, and the Next.js web app) as an independent product with its own history, deploy targets (Render + Vercel), and roadmap. This repo keeps `database/supabase_client.py`, `config.py`, and the shared Supabase project (same instance, isolated by schema — `public` here, `monitoring`/`vrm` there) — see [CONTEXT.md](CONTEXT.md#victron-monitor-integration-added-2026-07-13) for the original reasoning behind schema isolation, still accurate even though the code has now physically split too, and **[ARCHITECTURE.md](ARCHITECTURE.md)** for how the two repos still connect through that one Supabase project.

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

## Repository structure

```
.
├── app.py, pages/, wizard/, proposals/, calculations/, ai/, database/, utils/, config.py
│   └── Solar Design Tool (Streamlit app)
├── webapp/
│   └── Flask/Jinja2 rewrite of the same app (main_jinja branch)
├── database/migrations/
│   └── Schema migrations for both `public` (solar tool) and `monitoring`
│       (Pauly & Co's own Victron fleet — the pipeline that reads it now
│       lives in github.com/opauly/vrm-monitor, but the schema itself,
│       and this repo's own admin-side registration code
│       (database/site_registration_db.py, database/monitoring_sites_db.py),
│       stay here)
├── tools/
│   └── One-off scripts (asset prep, tariff parsing, etc.) — a handful still
│       import from vrm-monitor's victron/vrm_api packages (pre-split
│       one-off migration/validation scripts); harmless until run, not
│       yet updated to point at the new repo
├── REQUIREMENTS.md, PHASES.md, CONTEXT.md
│   └── Solar Design Tool planning docs
└── .env.example
```
