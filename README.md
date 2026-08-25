# Pauly&Co — Solar Design Tool & Victron Monitor

This repository hosts two products built by **Pauly y Compañía**, sharing one Supabase project:

| Product | What it does | Where |
|---|---|---|
| **Solar Design Tool** | Wizard-driven solar proposal generator (Grid Zero, Off-Grid, Hybrid) with PDF output, proposal versioning, and project financial tracking | repo root — see below |
| **Victron Monitor** | Fleet monitoring for deployed Victron Energy systems via Node-RED + Google Apps Script, with weekly AI-narrated reports | [`victron-monitor/`](victron-monitor/README.md) |

They're separate products with independent roadmaps, isolated by Postgres schema (`public` vs `monitoring`) in the same Supabase project — see [CONTEXT.md](CONTEXT.md#victron-monitor-integration-added-2026-07-13) for why they're consolidated, and **[ARCHITECTURE.md](ARCHITECTURE.md)** for how everything is wired together, including the full Supabase schema map.

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

See [`victron-monitor/README.md`](victron-monitor/README.md) for the original Node-RED/Apps-Script fleet architecture, onboarding a new site, and troubleshooting.

**Status:** internally deployed across a handful of Pauly&Co-owned sites. Not yet ready to sell as a paid subscription to external customers — see Phase 9 in [PHASES.md](PHASES.md) for what's needed first (per-site Row-Level Security and per-device credential provisioning, replacing the current shared-key model).

### VRM Monitor — the SaaS product (web + API)

Starting with `PLAN_PHASE14.md`, Victron Monitor grew a second, customer-facing surface: a Next.js app (marketing site + customer portal + admin dashboard — this is today's actual **landing page**, replacing the static one under `victron-monitor/landing-page/`) backed by a FastAPI service that wraps the existing report pipeline. They're two separate local processes:

```bash
# Terminal 1 — vrm_api (FastAPI, port 8000). From the REPO ROOT — it
# imports victron.* and database.* as top-level packages.
python3 -m venv .venv && source .venv/bin/activate   # first time only
.venv/bin/python -m pip install -r requirements-api.txt
.venv/bin/python -m uvicorn vrm_api.main:app --reload
```

Use `.venv/bin/python -m ...` rather than the bare `pip`/`uvicorn` commands, even right after activating — on a machine with Anaconda installed, its `(base)` environment can shadow the venv on `PATH`, so `uvicorn` silently runs Anaconda's Python (missing this project's dependencies) instead. See [`vrm_api/README.md`](vrm_api/README.md#run-locally) if that happens.

```bash
# Terminal 2 — the web app (Next.js, port 3000 — the landing page,
# /app customer portal, and /admin dashboard all live here).
cd victron-monitor/web
source "$HOME/.nvm/nvm.sh" && nvm use   # pins Node 20.20.0 via .nvmrc — Next.js 16 needs ≥20.9
npm install                             # first time, or after a dependency change
npm run dev
```

Then open `http://localhost:3000` for the landing page/app, and `http://localhost:8000/health` to confirm the API is up.

Both need real environment variables before anything works — `vrm_api` reads the repo-root `.env` (see [`vrm_api/README.md`](vrm_api/README.md#env-vars)); the web app reads its own `victron-monitor/web/.env.local` (see [`victron-monitor/web/README.md`](victron-monitor/web/README.md#environment-variables)). At minimum, the web app needs `PIPELINE_API_URL=http://localhost:8000` and a `PIPELINE_API_KEY` matching the value in the root `.env`, so it can actually reach the API.

**One-click alternative:** once `.venv` and `node_modules` exist (the one-time setup above), double-click **[`start_vrm_monitor.command`](start_vrm_monitor.command)** in Finder — or run `./start_vrm_monitor.command` from Terminal — to launch both in their own Terminal windows and open the landing page automatically once it's up. Safe to run again while both are already running; it detects each port already listening and skips starting a duplicate instead of erroring.

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
