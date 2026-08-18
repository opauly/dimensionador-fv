# Phase 14 — VRM Monitor as one unified Next.js product: marketing site + customer portal + admin, on a Python pipeline API

**Status:** ready for the coder agent, with 6 open questions for Oscar flagged in §0.4
**Author:** architect agent, 2026-08-16
**Supersedes:** [`PLAN_PHASE13.md`](PLAN_PHASE13.md) — which is *not* deleted. Its §0–§1
reasoning is still the record of why one login per customer, `app_metadata` admin identity,
the `vrm.customers` auth columns, the `PLANS` vocabulary, and the invite mechanics are shaped
the way they are. §1.1 (access control) and §1.6/§1.7/§1.10 (Streamlit mechanics) are the
parts this plan overrides, and each override says why below (§7). **Step 0 applies the
supersession markers to `PLAN_PHASE13.md` and `PHASES.md` — do it first.**
**Already built and live from Phase 13:** migration `021_vrm_portal_auth.sql` (run against the
dev DB), and a working Streamlit login + role resolution proven end-to-end with a real test
customer. See §0.2 — **do not redo the migration.**
**Spec sources:** `PLAN_PHASE13.md`, `victron-monitor/docs/vrm-report-saas-architecture.md`
§5–§7, `victron-monitor/landing-page/landing_template.html` (the design system being ported),
`database/migrations/012_vrm_schema.sql` + `021_vrm_portal_auth.sql`, `pages/06_vrm_monitor.py`
(the internal tool whose behaviour the portal reproduces).
**Plan doc convention:** same shape as `PLAN_PHASE6.md` / `PLAN_PHASE13.md` — confirmed
context, resolved decisions, then vertical build steps each with its own validation gate.

---

## Goal

VRM Monitor becomes **one product on one domain**: the marketing page, the customer dashboard,
and Oscar's admin dashboard are all pages of a single Next.js application that shares one
design system, one navigation, and one login. The Victron-blue "instrument panel" look that
the landing page already sells with is the app's real design system, not a separate artifact.
The Python report pipeline is **not rewritten** — it is wrapped in a small internal HTTP API
that only the Next.js server calls.

"Done" means: a visitor lands on `https://<domain>/`, reads the same marketing page they read
today (now server-rendered from this repo), clicks **Log in**, signs in with a password set
from an invitation email, uploads their own VRM CSV, and downloads their own report — and the
dashboard they land on looks like it belongs to the page they arrived from. Oscar gets the
admin surface in the same app. Customer A cannot see or touch customer B's anything.
**No Supabase service_role credential ever reaches a browser.**

**The existing Streamlit app (`app.py` + everything under `pages/`, including
`pages/06_vrm_monitor.py`) is not modified by this phase.** Not one line. The pipeline modules
it shares (`victron/*.py`, `database/vrm_report_db.py`, `database/supabase_client.py`) are
imported by the new API as-is; changes to them, if genuinely unavoidable, are additive only.

---

## 0. Confirmed context (do not re-derive)

### 0.1 Facts established by reading the code and the live state

| Fact | Where |
|---|---|
| `vrm.customers` is the tenant root; `vrm.sites.customer_id → vrm.customers(id) ON DELETE CASCADE`; `site_id` is globally unique, namespaced `<customer-slug>-<site-slug>` | migration 012, `victron/ingest.py:make_site_id()` |
| `vrm.*` is **RLS-enabled with zero policies**; `anon` and `authenticated` have `REVOKE ALL ON SCHEMA vrm`; only `service_role` is granted anything | migration 012 L629–645 |
| `database/supabase_client.py:get_client()` is a module-level singleton holding the service_role key | that file |
| The reusable pipeline and its real entry points: `vrm_csv.parse_export(source, site_id, filename, pv_kwp, battery_usable_kwh) -> dict`; `ingest.upsert_customer/upsert_site/ingest_parsed`; `ingest.slugify` / `make_site_id`; `weekly_report.build_report_data(site_id, start, end, schema, with_narrative, with_weather)` and `render_pdf(d) -> bytes`; `vrm_report_db.list_sites/get_site/get_available_dates/fetch_report_window`, `rdb.VRM`, `rdb.MONITORING`, `MAX_CUSTOM_RANGE_DAYS=31`, `MAX_OVERVIEW_RANGE_DAYS=183` | `victron/`, `database/vrm_report_db.py` |
| `parse_export()`'s return value is **small** — per-*day* rows, alarm events, outages, warnings, counts — even for a 140 MB input. It is safe to persist as JSONB between a preview step and a commit step. | `victron/vrm_csv.py:parse_export` / `to_energy_daily_rows` |
| `vrm.sites.battery_usable_kwh` is a GENERATED column (migration 019) — writing it errors | migration 019 |
| Report generation calls Anthropic (narrative) and Open-Meteo (weather), then WeasyPrint. It is seconds-to-a-minute of work, not milliseconds. | `victron/weekly_report.py` |
| Repo Python is **3.9.22** in `.venv`, every module starts `from __future__ import annotations` | `CONTEXT.md` §Environment |
| There is **no JS toolchain, no Dockerfile, no CI workflow and no test suite anywhere in this repo today** | `Glob` over the root |
| Landing page today: single hand-written HTML template + `build.py` that base64-inlines 4 `.woff2` faces and 2 PNGs (a Claude-Artifact CSP requirement), published as an Artifact. Nav has no Log in link; early access is a JS-composed `mailto:` | `victron-monitor/landing-page/` |
| Design tokens in use: `--ink #0B2231`, `--ink-2 #0E2A3C`, `--panel #12324A`, `--panel-2 #163A55`, `--line #234A63`, `--victron #0089B6`, `--victron-glow #4FC8EC`, `--signal #F2A93B`, `--paper #E9F2F6`, `--paper-dim #AFC7D4`, `--mute #6F93A6`, `--good #3FBF8F`. Type: Big Shoulders (headings, uppercase), IBM Plex Sans (body), IBM Plex Mono (eyebrows, numerals, buttons, labels) | `landing_template.html` L37–112 |
| Next.js current stable is **16.3** (released 2026-08-03) | nextjs.org/blog/next-16-3 |
| Supabase's own recommended Next.js pattern is `@supabase/ssr` with `createServerClient` + cookie storage + middleware refresh, and `getUser()` (not `getSession()`) for server-side checks | supabase.com/docs/guides/auth/server-side/nextjs |
| Supabase's **new API keys** (`sb_publishable_…` / `sb_secret_…`) replace `anon`/`service_role`; legacy keys deprecated end of 2026. **A secret key returns HTTP 401 if used from a browser, and is rejected in an `Authorization: Bearer` header** | supabase.com/docs/guides/getting-started/migrating-to-new-api-keys |
| **Vercel functions cap request bodies at 4.5 MB**, enforced at the infrastructure level — not configurable | vercel.com/docs/functions/limitations |
| **Supabase Storage caps uploads at 50 MB on the Free plan**; Pro and up can raise the global limit | supabase.com/docs/guides/storage/uploads/file-limits |

### 0.2 What Phase 13 actually built, and its fate

| Artifact | State | Fate under this plan |
|---|---|---|
| `database/migrations/021_vrm_portal_auth.sql` | **Run against the live dev DB.** Adds `auth_user_id`, `auth_email`, `invited_at`, `activated_at`, `account_type`, `site_limit`, `ui_language` to `vrm.customers` + two partial unique indexes | **Kept verbatim. Confirmed correct for this direction** — every column is framework-agnostic and describes the *tenant*, not the UI. Nothing in it assumes Streamlit. **Do not re-run, re-number, or rewrite it.** Its header's REVISIT TRIGGER has now fired, which §1.2 answers; migration 022 records that answer rather than editing an already-applied file's meaning. |
| `vrm_portal/` (`auth.py`, `strings.py`, `views/login.py`, `__init__.py`) and `victron-monitor/portal/app.py` | Working, validated live (a real test customer signs in and resolves to the correct `customer_id`) | **Obsolete implementation, still-correct logic.** Ported to TypeScript in Step 3, deleted in Step 8. See §6.1 for the recommended timing and why. |
| `victron-monitor/landing-page/` + the published Artifact | Live marketing page | **Design source of truth for the port; stays published and untouched until the Next.js site is live on a domain.** See §6.2. |

**Still correct, carried forward unchanged from `PLAN_PHASE13.md`:** one login per customer;
admin-provisioned accounts, no public self-serve signup; the `vrm.customers` auth-column
design and its no-FK reasoning (§1.3 there); `PLANS` vocabulary and site limits (§1.4 there);
admin identity via `app_metadata.vrm_role` (§1.5 there); the role-resolution order and the
clean-rejection rule (§1.5 there); English-default customer UI with a per-customer
`ui_language` override, Spanish admin (§0.3 Q2 there); admin v1 scope (§0.3 Q3 there);
`generate_link()` + Resend for invites (§1.8 there, re-examined in §1.9 below); and the
"what the customer surface must never do" list (§1.11 there, restated in §1.12 below).

### 0.3 What changed, and why this plan exists

Oscar reviewed the Phase 13 approach and rejected the *shape*, not the goal: a second
Streamlit app ships faster but reads as a different, disconnected product from the landing
page that sells it. The decision is one unified custom website — Next.js frontend, the
landing page rebuilt as real source-controlled pages, the Python pipeline reused through an
API. Everything in Phase 13 that was about *what the product does* survives; everything that
was about *Streamlit's constraints* (§1.1's access-control reasoning, §1.6's `sys.path`
bootstrap, §1.7's `st.navigation`, §1.10's no-session-persistence) is replaced.

### 0.4 Open questions for Oscar — these block specific steps, not the start

1. **Domain.** `monitor.paulyco.com`? A standalone name? The whole product is one Vercel
   deploy on one apex/subdomain, with the Python API on `api.<same-domain>`. Needed at Step 8
   only. Working assumption until answered: `monitor.paulyco.com` + `api.monitor.paulyco.com`.
2. **Supabase plan.** Free or Pro? This decides the CSV ceiling: Free caps Storage uploads at
   50 MB (a 7-day VRM export is ~12 MB, so customer uploads fit; Oscar's own ~140 MB
   80-day backfills do not). Needed at Step 6. Working assumption: Free, with 50 MB enforced
   in the UI and big backfills staying on the internal Streamlit tool (§1.5).
3. **Brand blue.** `#3481B8` vs `#0588B6` from the MultiPlus-II photo — §1.8 has the measured
   contrast numbers and a recommendation, but this is Oscar's call on a swatch page (Step 1's
   validation produces one). Blocks nothing; the token is one line.
4. **Does the marketing site stay English-only?** It is today. Assumption: yes, English-only
   for v1; only the *customer dashboard* is bilingual.
5. **Anthropic/Resend spend on a public surface.** Report generation costs an Anthropic call
   per report. Assumption: acceptable at first-customers scale, no per-customer quota in v1
   beyond `site_limit`. Flagged because a public login page makes it someone else's finger on
   the button for the first time.
6. **Do the two Supabase key sets get migrated now?** Recommendation in §1.2: create the new
   `sb_publishable_…`/`sb_secret_…` pair and use them for the *new* web app and API; leave the
   legacy `service_role` key serving the existing Streamlit app until a later cleanup (legacy
   keys work until end of 2026).

Steps 0–7 are unblocked today. Step 8 needs Q1.

---

## 1. Resolved decisions (these are not open questions)

### 1.1 Repo layout: monorepo, mirroring the split this repo already uses

```
victron-monitor/web/          # NEW — the Next.js app (marketing + portal + admin).
                              #   Its own package.json / tsconfig / node_modules.
vrm_api/                      # NEW — root Python package: the FastAPI pipeline service.
Dockerfile.api                # NEW — repo root; builds vrm_api with WeasyPrint's system libs.
victron/  database/  utils/  config.py     # UNCHANGED, imported by vrm_api.
victron-monitor/landing-page/ # Frozen; design source of truth; removed at cutover (§6.2).
vrm_portal/  victron-monitor/portal/       # Legacy Streamlit portal; deleted at Step 8 (§6.1).
```

**Why a monorepo subfolder and not a second repo:**
- The design system, the copy, and the pipeline being wrapped all live here. A split repo
  means the Next.js app's tokens are a *copy* of `landing_template.html`'s tokens with no
  mechanism keeping them honest, and every pipeline change becomes a two-repo coordination.
- `PHASES.md`, `CONTEXT.md`, `ARCHITECTURE.md` and the plan docs are this project's actual
  memory. Splitting the product across two repos splits that memory.
- Vercel supports a **Root Directory** setting (`victron-monitor/web`) natively, so a
  monorepo costs nothing at deploy time.

**Why `victron-monitor/web/` and not the repo root:** this repo's convention, set by the V1
plan and followed by Phase 13, is *Python packages at the root, product assets under
`victron-monitor/`*. A `node_modules/` and a `package.json` at the repo root would also sit
directly beside `app.py` and `.streamlit/`, which is exactly the kind of tooling collision
Phase 13 §1.6 went out of its way to avoid.

**Why `vrm_api/` at the root:** it is a Python package that imports `victron.*` and
`database.*`. At the root, `uvicorn vrm_api.main:app` run from the repo root just works —
none of Phase 13's `sys.path` bootstrap is needed, because that hazard was Streamlit-specific
(Streamlit puts the *entry script's* folder on `sys.path[0]`; uvicorn uses the CWD).

### 1.2 Access control: **all Supabase access is server-side; no Supabase credential of any kind reaches the browser; `vrm.*` stays unreachable to `anon`/`authenticated`**

This reopens `PLAN_PHASE13.md` §1.1, as its own revisit trigger demanded. The trigger has
fired — there is now a JS frontend. Here is the answer, and why it is not "add RLS policies."

**Decision, in four rules:**

1. **Every read and write of `vrm.*` happens in Next.js server code or in the Python API.**
   Server Components, Route Handlers, and Server Actions only. The Supabase *secret* key
   (`sb_secret_…`, replacing `service_role`) exists in exactly two runtimes: the Next.js
   server and the `vrm_api` container.
2. **There is no browser Supabase client at all — not even an anon-key one.** Concretely:
   **no `NEXT_PUBLIC_SUPABASE_*` environment variable is ever defined.** This is not a
   convention, it is a structural guarantee: without a `NEXT_PUBLIC_` var there is no legal
   way for client-side code to construct a Supabase client, and the coder cannot "just quickly"
   add one without a visible env-var change. Every server-only module additionally starts with
   `import 'server-only'`, which turns an accidental client import into a **build error**, not
   a runtime leak.
3. **`anon`/`authenticated` keep zero grants on `vrm`** (already true since migration 012).
   This is the real defence in depth, and it is stronger than RLS policies would be: if a
   user's access token *and* the publishable key both leaked, a direct PostgREST call against
   `vrm.sites` still returns nothing, because the role has no privilege on the schema to
   begin with. There is no policy to get subtly wrong because there is no grant to police.
4. **Authorization is enforced at one typed choke point**, `victron-monitor/web/lib/server/db/`
   — the TypeScript equivalent of what `vrm_portal/db.py` was going to be. Every
   tenant-facing function takes `customerId: string` as its **required first argument**; no
   function returns an unscoped result set; site-keyed operations go through
   `assertOwnsSite(customerId, siteId)` which **throws** `NotAuthorized` rather than returning
   false. Page and route-handler code may import only this module — never a raw Supabase
   client. `requireCustomer()` / `requireAdmin()` is the **first statement** of every route
   handler, server action, and protected page; navigation-level gating is UX, never the control.

**Why not per-user JWTs + RLS policies on `vrm.*`:**

- **The privileged path does not go away.** `vrm_api` must write `energy_daily`, upsert sites,
  and read across tables to render a report; it will hold a secret key no matter what. RLS
  cannot be the control for the process that bypasses it. So application-layer scoping is
  required *regardless* — the only question is whether we add a **second, parallel**
  authorization implementation (RLS predicates) that must be kept exactly consistent with the
  first. Two implementations of the same rule drift; the drift is silent; and the second one
  is only exercised on a path we would be creating specifically so it could be exercised.
- **The Phase 13 "second door, not a second lock" argument survives the stack change.** It was
  never really about Streamlit. Adding RLS policies means *also* granting `authenticated`
  privileges on `vrm` — i.e. deliberately opening a browser-reachable path to customer
  telemetry that does not exist today — in order to then constrain it. Rule 3 above declines
  to open the door at all, which is a strictly stronger position than opening it behind a lock.
- **What Next.js changes vs. Streamlit is the quality of the choke point, in our favour.**
  Phase 13's §1.1 partly rested on Streamlit having no per-request auth context and no way to
  make "forgot to scope this" a compile-time error. Next.js has both: `import 'server-only'`,
  a typed `customerId`-first API, and a per-request cookie session. The enforcement story got
  *better*, not worse — which is precisely why the honest answer to the revisit trigger is
  "keep app-layer scoping, and make it structurally enforced," not "bolt on RLS."

**Use the new Supabase key format** (`sb_secret_…` for the server, `sb_publishable_…` for the
auth cookie flow). A secret key sent from a browser returns 401 and cannot travel in an
`Authorization: Bearer` header at all — so the single worst mistake in this design fails
loudly at the first request instead of silently working. That property is worth the 10-minute
key migration on its own.

**Session mechanics:** `@supabase/ssr`'s `createServerClient` with Next.js `cookies()`, cookies
set `httpOnly: true, secure: true, sameSite: 'lax'`. Middleware refreshes the token on each
request per Supabase's documented pattern. `supabase.auth.getUser()` — never `getSession()` —
for any check that gates access. The Supabase session is used **only to establish identity**;
the `customer_id` it resolves to is then carried by our own server-side lookup, exactly as
`vrm_portal/auth.py:resolve_role()` does today. Unlike Phase 13 §1.10, sessions now survive a
hard refresh and new tabs for free — that non-goal is retired.

**New revisit trigger** (goes in migration 022's header): *if a browser, a mobile app, or a
third party ever needs to query Supabase directly — realtime subscriptions, offline sync, a
public API — then granting `authenticated` on `vrm`, issuing per-user JWTs, and writing RLS
policies keyed on `auth.uid()` via `vrm.customers.auth_user_id` must all happen together, as
one change, with a cross-tenant test suite. Never partially.*

### 1.3 The Python API's place in the trust boundary

`vrm_api` holds the same secret key the Next.js server does. It must not become a second
unguarded door.

- **It is never called from a browser.** Only the Next.js server calls it. There is no CORS
  allowance for any origin (CORS middleware is simply not installed); a browser preflight
  fails by construction.
- **Caller authentication:** every endpoint except `GET /health` requires
  `Authorization: Bearer <PIPELINE_API_KEY>`, a long random secret held only in the two
  runtimes' env, compared with `hmac.compare_digest`. Missing/wrong → 401 with no detail.
- **It re-validates tenancy independently.** Every `vrm`-schema endpoint takes `customer_id`
  *and* `site_id` and re-checks the ownership link itself before touching anything —
  it does **not** trust that the Next.js layer already checked. Two independent checks of the
  same fact, in the two processes that hold privilege, is the one place "defence in depth"
  genuinely applies here.
- **Narrow verbs only.** No endpoint takes a table name, a filter expression, a schema-free
  passthrough, or arbitrary SQL. The `monitoring` schema is reachable only via the explicit
  report endpoint with `actor="admin"` set, which only `/admin/*` code paths set.
- **No ambient file access.** CSVs are read from a Supabase Storage path scoped to the calling
  customer's prefix, never from a caller-supplied URL or local path.
- Errors returned to Next.js are typed codes plus a safe message; stack traces and Postgres
  error text stay in the API's logs and never reach a customer's browser.

### 1.4 Hosting: Vercel for the web app, Render (Docker) for the Python API

This blocked Phase 13's Step 6. Deciding it now, because the architecture depends on it.

| | Choice | Why |
|---|---|---|
| **Next.js app** | **Vercel**, Root Directory `victron-monitor/web`, custom domain | First-party Next.js 16 support (no adapter, no config), preview deploys per branch (a real review tool for a solo builder), free tier viable for launch, env-var management that keeps secrets out of the repo. The two Vercel limits that matter are both designed around in §1.5 and §1.6, not discovered later. |
| **Python API** | **Render**, Web Service **from `Dockerfile.api`**, custom domain `api.<domain>` | WeasyPrint needs Pango/Cairo system libraries, so a Dockerfile is mandatory and rules out any "just point it at requirements.txt" host. Render gives always-on instances at fixed, predictable prices ($7 Starter/512 MB, $25 Standard/2 GB), a real free tier for early testing, and no per-second metering surprises. Start on **Standard (2 GB)** — pandas over a 12 MB CSV is not a 512 MB workload — and measure at Step 8 before economising. |
| Rejected: Fly.io | | Pay-per-second with several metrics compounding; repeated reports of bills 2–4× expectations. Not what a solo operator wants behind a customer-facing upload button. |
| Rejected: Railway | | No free tier, everything metered per second; fine, but no advantage here over Render's fixed pricing. |
| Rejected: Cloud Run | | 32 MiB HTTP/1 request-body cap and cold starts on a WeasyPrint-sized image; scale-to-zero is the wrong trade when a customer is waiting for a report. |
| Rejected: putting the pipeline in Vercel Python functions | | WeasyPrint's system libs and pandas/numpy blow past serverless size limits, and report generation exceeds function duration budgets. Non-starter, stated so nobody re-proposes it. |

Runtime note: the container uses **`python:3.11-slim`**, not 3.9. The repo's 3.9 pin is a
local macOS accident (`CONTEXT.md` explains the two broken system Pythons), not a code
constraint — every module already uses `from __future__ import annotations`. Step 5's
validation includes proving the pipeline produces byte-identical report numbers on 3.11.

### 1.5 CSV upload path: browser → Supabase Storage (signed URL) → API pulls the object

A VRM export is 12 MB for a week and up to ~140 MB for an 80-day backfill. **Vercel caps
request bodies at 4.5 MB**, so the file cannot pass through a Next.js route handler. Decision:

1. Browser asks the Next.js server for an upload slot. The server (after `requireCustomer()`)
   calls Supabase Storage `createSignedUploadUrl()` for
   `vrm-monitor/uploads/{customer_id}/{uuid}.csv` and returns the signed URL only.
2. The browser `PUT`s the file straight to Supabase Storage. Nothing large touches Vercel.
3. The browser posts the *path* back; the Next.js server hands `{customer_id, path, …}` to
   `vrm_api`, which downloads and parses it.
4. The object is deleted after a successful commit, and any orphan older than 7 days is swept
   by the same job the API runs on startup. The CSV is fully re-derivable from VRM; keeping
   customer raw exports around is storage cost and liability with no benefit.

Consequences, stated up front rather than discovered: the **Supabase Free plan's 50 MB
Storage cap** becomes the customer-facing upload limit (§0.4 Q2). The UI states the limit
before the file picker and rejects oversized files client-side with the reason. Oscar's own
multi-month backfills continue to run through `pages/06_vrm_monitor.py`, which has no such
ceiling — one of several reasons that tool stays alive (§4).

### 1.6 Long work is a job, not a request

Parsing a CSV and rendering a report (Anthropic + Open-Meteo + WeasyPrint) take seconds to a
minute. Coupling that to an HTTP request means coupling it to Vercel's and Render's timeout
budgets and to the customer's flaky wifi. Decision: **`vrm_api` runs them as jobs.**

- New table `vrm.jobs` (migration 022): `id`, `customer_id`, `site_id`, `kind`
  (`ingest_preview` | `ingest_commit` | `report`), `status` (`queued`|`running`|`done`|`failed`),
  `params jsonb`, `result jsonb`, `error text`, `created_at`, `started_at`, `finished_at`.
- `POST /v1/…` returns `{job_id}` immediately; the browser polls a Next.js route handler that
  proxies `GET /v1/jobs/{id}` (scoped: the handler refuses a job whose `customer_id` isn't the
  session's).
- **Execution is in-process** (FastAPI background task on a bounded thread pool), not Celery or
  Redis. At first-customers scale a queue is infrastructure with no payoff. The honest cost:
  a container restart loses in-flight jobs — mitigated by marking any `running` job older than
  15 minutes as `failed` on startup, with a message telling the customer to retry. The upgrade
  path (a real worker) is written down in §5 and not taken now.
- **The preview→commit two-step is what makes this cheap.** `parse_export()`'s output is small
  (per-day rows), so `ingest_preview` stores the whole parse in `vrm.jobs.result`, the UI
  renders the preview from it, and `ingest_commit` writes from the stored result — the file is
  parsed exactly once. This preserves `tab_upload()`'s "never write on the first click" rule
  (`pages/06_vrm_monitor.py` L437–559) without paying for it twice.

### 1.7 Design system: port the CSS as component-scoped CSS Modules over shared tokens — not a Tailwind rewrite

- **`victron-monitor/web/styles/tokens.css`** is the single source of truth: the twelve custom
  properties from `landing_template.html` L37–50, plus derived ones the current CSS hardcodes
  inline (`--glow-victron: rgba(…)` for the four `box-shadow`s, `--radius-*`, the type scale).
  Every rgba() that today repeats `0,137,182` or `79,200,236` becomes a token — that is what
  makes §1.8's blue swap a one-line change instead of a find-and-replace across nine files.
- **CSS Modules per component**, not Tailwind. The existing CSS is hand-tuned (`clamp()` type
  scale, the `.readout::after` hairline gradient, the `.flow-trace` dashed traces, the
  `.report-frame` fade mask). Translating it into utility classes is a *rewrite* in which
  every visual regression hides inside a mechanical-looking diff. Moving each rule block into
  a co-located `.module.css` is a near-verbatim move that can be diffed against the original.
  Recorded as a deliberate trade: less utility-class velocity later, much higher fidelity now.
- **Fonts via `next/font/local`** pointing at the same four `.woff2` files, copied into
  `victron-monitor/web/app/fonts/`. The base64 inlining in `build.py` existed solely to satisfy
  the Artifact CSP; on a real host it is pure page weight. This deletes `build.py`'s reason to
  exist on the web side.
- **Component structure** (the part that makes the dashboard look like the landing page):

  ```
  components/ui/        Button (primary|ghost) · Panel · Stat · Eyebrow · SectionHead ·
                        Field/Input/Select/Textarea · Table · Badge · Led · Callout · ModeToggle
  components/marketing/ Nav · Hero · Readout · FlowSteps · ModuleGrid · ReportPreview ·
                        Pricing · AccessForm · Footer
  components/app/       AppShell (nav + role-aware links) · SiteTable · UploadDropzone ·
                        RangePicker · ReportSummary · JobProgress
  ```

  `components/ui/*` are extracted **from the marketing markup first** (Step 1) and then reused
  by the dashboard (Steps 4/6). Building them in the other order is how the two halves end up
  looking like different products again — the exact failure this whole pivot exists to fix.
  `Stat` is literally the landing page's `.stat` readout tile; the customer dashboard's KPI
  cards are that component, which is why the dashboard will feel like the page that sold it.
- The two `.mode-toggle` behaviours (Detallado/Resumen, Subscription/Single, installer/owner)
  become one `ModeToggle` client component with `useState`, replacing the
  `data-mode` + `querySelectorAll` script and its documented script-ordering bug
  (`landing_template.html` L887–896) — that bug class disappears with the script.
- The access form's `mailto:` composition stays exactly as it is (Phase 13 §0.3 Q4, confirmed),
  re-expressed as a client component. **No form posts anywhere.** Nav gains a **Log in** link.

### 1.8 Brand blue: retire `#0089B6`; adopt a photo-matched Victron blue — decide between two candidates on a swatch, don't inherit silently

The current `--victron: #0089B6` was Victron's RAL 5012 spec value, chosen before Oscar had
the real MultiPlus-II unit in front of him. He has since sampled the actual product and given
two candidates: **`#3481B8`** and **`#0588B6`**. This is an explicit decision point, not a
default-through.

Measured (WCAG 2.1 relative luminance, against this palette's actual grounds):

| Candidate | vs. white text | vs. `--ink #0B2231` | Character |
|---|---|---|---|
| `#0089B6` (current, RAL 5012) | 4.00 : 1 | 4.08 : 1 | baseline |
| **`#0588B6`** | 4.03 : 1 | 4.04 : 1 | visually a drop-in for the current value — same hue family, same chroma |
| `#3481B8` | 4.22 : 1 | 3.87 : 1 | greyer, softer, less "instrument"; best white-text contrast of the three |

**Recommendation: `#0588B6`**, because it is a true drop-in — every existing glow, gradient,
hairline and `featured` treatment was tuned against a colour of that chroma, so the whole
palette keeps working with a one-token change, and it is genuinely sampled from the hardware.
`#3481B8` is the pick only if a side-by-side shows the photo reads greyer than `#0588B6`
suggests; its lower contrast against the dark ground (3.87:1) makes it slightly *worse* for
the hairline/border uses of `--victron`.

**Step 1 must ship a `/styleguide` swatch page rendering the full component set under both
candidates via a query param**, so Oscar decides on real components, not hex codes. Record the
answer in this file when he picks.

**Related accessibility note the coder must surface, not silently fix:** the primary `.btn` is
white 13px uppercase text on `--victron`, i.e. ~4.0–4.2:1 — below WCAG AA's 4.5:1 for normal
text, and 13px does not qualify as large text under any candidate. Options, for Oscar:
(a) keep it (status quo, already shipped publicly); (b) add a derived `--victron-deep:
#046C90` (**5.91:1** with white) used *only* as the button fill, keeping the brighter blue for
accents and glow. (b) is a two-line change and is the recommendation, but it is a visual
decision, so it goes on the same swatch page rather than being applied unilaterally.

### 1.9 Invitations: `generate_link()` + Resend — kept, but for two of the original three reasons

Phase 13 §1.8 rested on three arguments. One of them is now void and must not be repeated as
if it still holds:

- ~~"Supabase's default invite link puts tokens in the URL fragment, which the server never
  sees and Streamlit cannot read."~~ **No longer decisive.** A Next.js client component can
  read `window.location.hash`, and the modern `@supabase/ssr` pattern uses a `token_hash`
  query param against an `/auth/confirm` route handler anyway. This argument is retired.
- **Still decisive:** Supabase's built-in email service is rate-limited and documented as
  not-for-production; making `invite_user_by_email()` usable means configuring custom SMTP
  regardless — at which point we are already integrating an email provider.
- **Still decisive:** the `token_hash` variant requires hand-editing an email template in the
  Supabase dashboard. That is undiffable, unreviewable state that no one can see from the
  repo. Building the link ourselves keeps the invite email in git as a Jinja2 template.
- **Still decisive:** Phase 12 has already committed to Resend for weekly report emails.
  Whichever phase lands first writes a **generic** `victron/mailer.py`
  (`send(to, subject, html, from_=None, reply_to=None)`, no invite-specific logic) and the
  other inherits it. Note the module now belongs in `victron/`, not the deleted `vrm_portal/`.

Flow, unchanged in substance from Phase 13 §1.8–§1.9: `admin.generate_link({"type": "invite",
"email": …})` → `hashed_token` → `{SITE_URL}/activate?token_hash=…&type=invite` → Resend →
the `/activate` page verifies with `verify_otp({token_hash, type})` **server-side**, renders
"Set your password," calls `updateUser({password})`, stamps `vrm.customers.activated_at`, and
redirects into `/app`. Re-sends and forgot-password use `type="recovery"` through the same
page. Expired/used links produce "This link has expired — ask for a new one," never a stack
trace.

**Empirical check — answered at Step 7 (2026-08-17):** does GoTrue issue a `recovery` link for
a user who was invited but never activated (email unconfirmed)? **Yes.** Tested directly
against this project's live Supabase instance with a throwaway address
(`phase14-empirical-<timestamp>@paulyco.com`): `generateLink({type: "invite"})` created the user
(unconfirmed — `email_confirmed_at` is `undefined`), and a follow-up
`generateLink({type: "recovery"})` on that same still-unconfirmed user returned `error: null`
and a real `hashed_token`, with no special handling needed. The throwaway user was deleted
immediately after (`admin.deleteUser()`); no link was ever clicked. **Practical effect:**
`lib/server/invites.ts:resendInvite()`/`sendPasswordReset()` still carry the `type: "magiclink"`
fallback the plan called for (cheap insurance, and this was one test against one project's
current GoTrue behaviour, not a guarantee that never changes), but in practice the `recovery`
branch is expected to succeed every time — the fallback is not expected to ever actually fire
for this reason. Phase 13's original open question is closed.

### 1.10 Copy and languages

- Marketing pages: **English only** (as today), hardcoded in components — this is prose, not
  UI strings, and pretending otherwise adds indirection to the one thing a human edits most.
- Customer dashboard: **bilingual via `lib/i18n/strings.ts`**, a straight port of
  `vrm_portal/strings.py`'s `{en: {...}, es: {...}}` shape and its `t(lang, key)` fallback
  behaviour (missing key → English → the key itself, never a crash). **No `next-intl` or ICU
  runtime**: two languages, flat keys, no pluralization rules in the existing copy.
  `session.uiLanguage` comes from `vrm.customers.ui_language`.
- Admin dashboard: **Spanish**, literals inline, ported near-verbatim from
  `pages/06_vrm_monitor.py` where the surface matches.

### 1.11 Report reads stay on the Python side

The Next.js layer does **not** reimplement `fetch_report_window` / `build_report_data` in
TypeScript, and does not query `vrm.energy_daily` / `vrm.daily_health` at all. It queries only
tenancy-shaped tables (`customers`, `sites`, `ingestion_log`, `jobs`) for its own UI. Anything
that computes a number a customer sees goes through `vrm_api`, so there is exactly one
implementation of the report's math, shared with `pages/06_vrm_monitor.py` and with Phase 12's
scheduled emails. The `available dates` and range-boundary constants
(`MAX_CUSTOM_RANGE_DAYS`, `MAX_OVERVIEW_RANGE_DAYS`) are **served by the API**, never
duplicated as TS constants — duplicating them is how the Detallado/Overview boundary silently
drifts between two surfaces.

### 1.12 What the customer surface must never do (carried from Phase 13 §1.11, re-expressed)

1. **Never call `ingest.upsert_customer()` from a customer-initiated path.** The customer's
   tenant comes from the session; `vrm_api` derives `site_id` from the stored
   `customer["slug"]`. A customer must not be able to create or rename a tenant.
2. **Never render a customer picker, a schema picker, or `monitoring` data** in `/app/*`.
   Customer reports are `rdb.VRM`, hardcoded.
3. **Never pass a `site_id` from a request body into `ingest.*` or `rdb.*`** without
   `assertOwnsSite()` in Next.js **and** the API's own re-check — even when the dropdown was
   already filtered. The dropdown is UI; the guard is the control.
4. **Never let a customer exceed `site_limit`** — checked in the server data layer, not in a
   component.
5. **Never write `battery_usable_kwh`** (GENERATED since migration 019). Write
   `battery_nominal_kwh` + `battery_dod_pct`.
6. **Never return a raw Postgres or Python error string to the browser.** Typed code + safe
   message; details to the server log.

---

## 2. Build steps

Each step is a vertical slice ending in something runnable plus a validation you can execute.
**Do not start step N+1 until step N's validation passes.**

---

### Step 0 — Make the supersession legible in the docs (do this first, ~15 minutes)

The architect agent could not apply these two edits (its `Edit` tool was disabled and both
files are too large to rewrite safely by hand). They are mechanical; do them before any code
so the repo's own history reads correctly from the first commit of this phase.

**Edit 1 — `PLAN_PHASE13.md`.** Insert the following block **immediately after line 1**
(`# Phase 13 — VRM Monitor Customer Portal: Auth, User Dashboard, Admin Dashboard`) and change
the `**Status:**` line on what is currently line 3 to read
`**Status:** SUPERSEDED — was: ready for the coder agent, with 5 open questions for Oscar flagged in §0.3`.
**Change nothing else in that file.**

```markdown
> ## ⚠️ SUPERSEDED (2026-08-16) — see [`PLAN_PHASE14.md`](PLAN_PHASE14.md)
>
> **Nothing below is deleted, because most of it is still the record of decisions that still
> hold.** What changed is the *shape*, not the goal: Oscar chose to rebuild VRM Monitor as
> **one unified Next.js site** (marketing page + customer portal + admin in one codebase,
> with the Python pipeline wrapped in an API) instead of the second Streamlit app this
> document plans. `PLAN_PHASE14.md` §7 is a decision-by-decision map of what carried forward
> and what was overridden. In short:
>
> - **Built and live from this plan — do not redo:** `database/migrations/021_vrm_portal_auth.sql`
>   (applied to the dev DB) and a working Streamlit login + role resolution, validated
>   end-to-end with a real test customer.
> - **Still correct and carried forward:** §1.3 (auth columns on `vrm.customers`, soft
>   pointer, no FK), §1.4 (`PLANS`), §1.5 (admin via `app_metadata.vrm_role` + the
>   role-resolution order), §1.8–§1.9 (invites via `generate_link()` + Resend — though one of
>   its three arguments, the URL-fragment one, is explicitly retired in `PLAN_PHASE14.md`
>   §1.9), §1.11, §4's non-goals, and every answer in §0.3.
> - **Reopened and re-decided:** §1.1 (access control). Its own revisit trigger — *"the moment
>   anything other than this Streamlit process talks to Supabase on a customer's behalf…
>   per-user JWTs + RLS policies become mandatory"* — **has now fired.** The answer is in
>   `PLAN_PHASE14.md` §1.2: all Supabase access stays server-side, no Supabase credential of
>   any kind reaches the browser, `anon`/`authenticated` keep zero grants on `vrm`, and
>   enforcement moves to a typed `server-only` choke point.
> - **Superseded as Streamlit-specific:** §1.2 (two-client rule), §1.6 (`vrm_portal/` layout
>   and the `sys.path` bootstrap), §1.7 (`st.navigation`), §1.10 (no session persistence —
>   now retired as a non-goal, since cookie sessions give it for free).
> - **`vrm_portal/` and `victron-monitor/portal/` are legacy.** Kept as porting reference
>   through Phase 14 Step 7, deleted at Step 8 (`PLAN_PHASE14.md` §6.1).
```

**Edit 2 — `PHASES.md`.** Four small changes, nothing removed:
1. In the status table, change the Phase 13 row to:
   `| 13 — VRM Monitor Customer Portal (Streamlit) | 🔶 Superseded by Phase 14 — Step 1 built & validated (migration 021, login, role resolution) |`
   and add below it:
   `| 14 — VRM Monitor unified Next.js site (marketing + portal + admin) + Python pipeline API | ⬜ Not started (supersedes Phase 13; see PLAN_PHASE14.md) |`
2. At the top of the `## Phase 13 — …` section body, insert:
   `> **Superseded by Phase 14** ([`PLAN_PHASE14.md`](PLAN_PHASE14.md)) — the goal stands, the Streamlit implementation does not. Step 1 (migration 021 + login + role resolution) was built and validated live and is **not** to be redone. Kept in full because its product decisions carried forward.`
3. Add a `## Phase 14 — …` section after it, mirroring the Phase 13 section's structure (goal,
   why, where it sits, decisions locked, tasks, non-goals, validation, open questions), each
   item pointing at the corresponding `PLAN_PHASE14.md` section rather than duplicating it.
4. Add a Phase 14 row to the timeline table (estimate: 12–18 days at the repo's part-time
   pace — this is materially larger than Phase 13's 5–8) and one line to the critical-path
   notes saying Phase 14 is off the critical path like 9–13, is triggered by the same business
   need Phase 13 was, and is the first phase in this repo to introduce a JS toolchain.

**Validate:** both files render correctly on GitHub; `PLAN_PHASE13.md`'s body below the banner
is byte-identical to what it was (`git diff` shows only the inserted block and the one status
line).

---

### Step 1 — Next.js scaffold + design system foundation

**Build**
- `victron-monitor/web/`: Next.js 16.3, TypeScript, App Router, ESLint, **no Tailwind**
  (§1.7). `.gitignore` for `node_modules`, `.next`, `.env*.local`. `package.json` scripts:
  `dev`, `build`, `start`, `lint`, `typecheck`.
- `styles/tokens.css` + `styles/base.css` — the token block from `landing_template.html`
  L37–50 plus the derived glow/radius/type tokens (§1.7), the `*`/`body`/`::selection`/
  `prefers-reduced-motion`/`a`/`img` base rules, and `.wrap`.
- `app/fonts/` — copy the four `.woff2` files from `victron-monitor/landing-page/assets/fonts/`;
  wire `next/font/local` with the same `font-weight` ranges and `display: swap`.
- `components/ui/*` per §1.7, each with a co-located `.module.css` carrying the rules moved
  from the template (Button ← `.btn`/`.btn.ghost`; Panel ← `.readout`/`.card`/`.price-card`
  chrome; Stat ← `.stat`; Eyebrow ← `.eyebrow` incl. the amber pulse; Field ← `.field`
  incl. focus ring; ModeToggle ← `.mode-toggle` as a `useState` client component).
- `app/styleguide/page.tsx` — every primitive in every state, **and the §1.8 A/B**: reading
  `?blue=0588B6|3481B8|0089B6` and `?btn=deep|flat`, it re-binds `--victron` /
  `--victron-deep` so Oscar can compare on real components.

**Validate**
- `npm run build` and `npm run typecheck` clean.
- `/styleguide` side-by-side against `victron-monitor/landing-page/landing_page.html` open in
  another tab: buttons, stats, eyebrows and fields are visually indistinguishable at 1440px.
- Fonts load from `next/font` (no base64 in the HTML source), and no FOUT on reload.
- Oscar picks a blue and a button treatment from `/styleguide`; **record the answer in §1.8
  of this file** before Step 2.

---

### Step 2 — The marketing site, as real pages

**Build**
- `app/(marketing)/page.tsx` composed from `components/marketing/*`: Nav, Hero (+ Readout),
  How-it-works, Modules grid (with the Detallado/Resumen `ModeToggle`), Sample report preview,
  Pricing (with the Subscription/Single `ModeToggle`), CTA + AccessForm (installer/owner
  toggle, `mailto:` composition preserved verbatim including the disabled-link keyboard guard),
  Footer.
- `public/` — `pauly_logo.png`, `sample_report.png` copied from `landing-page/assets/`.
- Nav gains **Log in** → `/login`, styled as the existing ghost button.
- Metadata: title, description, Open Graph image, favicon. `app/robots.ts` + `app/sitemap.ts`.
- Copy is ported **verbatim**. Any wording change is a separate, visible commit.

**Validate**
- Screenshot diff vs. the published Artifact at 1440 / 920 / 560 px — the three breakpoints
  the CSS actually defines. Differences must be explainable line by line.
- Both mode toggles work, including the pricing one that the old script-order bug broke.
- Keyboard: tab through nav → CTAs → form; focus rings visible (`:focus-visible` rules ported).
- Lighthouse: Performance ≥ 90, Accessibility ≥ 95 on desktop.
- **`grep -r "NEXT_PUBLIC_SUPABASE" victron-monitor/web` returns nothing** — start this habit
  before there is any auth code to leak.

---

### Step 3 — Auth: server-only Supabase, login, session, role resolution

**Build**
- `lib/server/supabase.ts` (`import 'server-only'`): `createServerClient` bound to Next.js
  `cookies()` for the auth/session client, and a separate secret-key client for data. Env:
  `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`. **No `NEXT_PUBLIC_*`.**
  A header comment carries the §1.2 rules in this repo's explanatory voice.
- `middleware.ts` — Supabase's documented token-refresh middleware, matched to `/app/*`,
  `/admin/*`, `/login`, `/activate`.
- `lib/server/auth.ts` — `getSessionContext()` implementing `vrm_portal/auth.py:resolve_role()`
  **exactly**: `app_metadata.vrm_role === 'admin'` → admin, no `customerId`; else look up
  `vrm.customers` by `auth_user_id` **and** `active` → customer; else a clean rejection with
  the same copy. Plus `requireCustomer()` / `requireAdmin()` which redirect (pages) or 403
  (route handlers). Uses `getUser()`, never `getSession()`.
- `app/(auth)/login/page.tsx` + a sign-in server action: generic "Incorrect email or password"
  for every credential failure (no account enumeration), distinct handling only for the
  not-linked case, and an inert "Forgot your password?" link (live at Step 7).
- `app/(portal)/app/layout.tsx` and `app/(admin)/admin/layout.tsx` — `AppShell` with role-aware
  nav, the signed-in email, and a sign-out action. Each renders a placeholder page showing the
  resolved role and `customerId`.
- `lib/i18n/strings.ts` — port `vrm_portal/strings.py` including the `t()` fallback chain.

**Validate**
- The **same three Supabase users Phase 13 already validated** behave identically: the linked
  test customer lands on `/app` with the right `customerId`; the `vrm_role: admin` user lands
  on `/admin` with no `customerId`; an unlinked (and separately, an inactive) user gets the
  clean rejection and **no session**, not a partial one.
- Sign out, hard-refresh, new tab: session behaviour is correct in each (this is the Phase 13
  §1.10 non-goal now being met for free — confirm it actually is).
- Hit `/app` and `/admin` while signed out and cross-role → redirect/403 from the guard, with
  the guard, not the nav, doing the work (test by URL, not by clicking).
- **Leak checks, all three:** `grep -r "NEXT_PUBLIC_SUPABASE" victron-monitor/web` → nothing;
  `grep -rE "sb_secret|service_role|SUPABASE_SECRET" .next/static` after a production build →
  nothing; and with a real user access token, `curl` PostgREST directly for `vrm.sites`
  (`Accept-Profile: vrm`) → permission denied / zero rows. Record the exact commands in the
  web app's README so they can be re-run.

---

### Step 4 — The tenant-scoped data layer + My Sites + Profile

**Build**
- `lib/server/db/` (every file `import 'server-only'`), the §1.2 choke point:
  `getCustomer(customerId)`, `updateCustomerProfile(customerId, fields)`,
  `listSites(customerId, {activeOnly})`, `getSite(customerId, siteId)`,
  `updateSite(customerId, siteId, fields)`, `siteCount(customerId)`,
  `canAddSite(customerId) → {ok, reason}`, `listIngestions(customerId, limit)`,
  `assertOwnsSite(customerId, siteId)` **throws** `NotAuthorized`.
  Typed field whitelists, copied from Phase 13 §Step 2: profile accepts only
  `name, contact_name, contact_email, country, ui_language` — **never** `plan, site_limit,
  active, slug, auth_user_id, auth_email`; site accepts only `display_name, pv_kwp,
  battery_nominal_kwh, battery_dod_pct, system_type, report_language, location, timezone,
  latitude, longitude, country, savings_rate, savings_currency, exports_to_grid, active` —
  never `customer_id, site_id, battery_usable_kwh, vrm_installation_id`.
- `lib/server/db/admin.ts` — the cross-customer counterpart (`listCustomers()` with site counts
  and last-upload, `createCustomer()`, `updateCustomer()`, `setActive()`, `listAllSites()`,
  `listAllIngestions()`), with a file-header rule that only `/admin/*` may import it.
- `lib/plans.ts` — the `PLANS` dict from Phase 13 §1.4, unchanged.
- `app/(portal)/app/sites/` — the customer's sites table + per-site edit form, the live
  "Usable battery = nominal × DoD/100" caption (it explains a generated column that otherwise
  reads as a missing field), an "Add a site" form gated by `canAddSite()` with upgrade copy +
  `mailto:` when over the limit, and the timezone/coordinate helpers.
- `app/(portal)/app/profile/` — read-only login email, plan label, sites used / limit, member
  since; editable profile fields; change password (re-authenticate with the current password
  first, server-side).

**Validate**
- `victron-monitor/web/scripts/test-scoping.ts` (run with `tsx`; there is no test framework in
  this repo and this step is not the place to introduce one): creates two throwaway customers
  each with a site, then asserts `getSite`, `updateSite`, `assertOwnsSite` and
  `listIngestions` all reject A's `customerId` + B's `siteId` with `NotAuthorized`, and that
  `listSites(A)` never contains B's site. Cleans up after itself. **This script is the
  regression test for §1.2 and must keep passing at every later step.**
- `updateCustomerProfile(cid, {plan: 'fleet', siteLimit: 999})` is rejected at the type level
  *and* at runtime — assert both.
- As customer A in a browser: only A's sites, no customer picker anywhere.
- Edit `pv_kwp` and `report_language`; confirm in Supabase, and confirm `battery_usable_kwh`
  recomputed itself.
- With `site_limit = 1` used, adding a site is blocked with upgrade copy, not a silent failure.
- Flip `ui_language` to `es` → the whole dashboard switches; **no English left behind** (this
  is the test that catches literals that bypassed `strings.ts`).

---

### Step 5 — `vrm_api`: the Python pipeline service

**Build**
- `database/migrations/022_vrm_portal_web.sql` — `vrm.jobs` (§1.6), plus `COMMENT ON` statements
  recording §1.2's access model and the **new** revisit trigger, and a note that it supersedes
  021's header note. Header comment in the explanatory style of 012/016/021. Idempotent.
  Add a 3-line pointer at the top of `021_vrm_portal_auth.sql` — comment only, no SQL change —
  saying its revisit trigger fired and 022/`PLAN_PHASE14.md` §1.2 carry the answer. **Do not
  rewrite 021's body: it has already been applied.**
- `vrm_api/` — FastAPI:
  - `main.py` (app, no CORS middleware — see §1.3), `deps.py` (bearer auth via
    `hmac.compare_digest`), `jobs.py` (create/run/poll + the 15-minute stale sweep on startup),
    `storage.py` (signed-URL download from Supabase Storage, upload of report PDFs),
    `tenancy.py` (the API's own independent `assert_owns_site`), `schemas.py` (Pydantic models).
  - `routers/ingest.py`: `POST /v1/ingest/preview` `{customer_id, site_name|site_id, storage_path,
    site_fields}` → job whose `result` is `parse_export()`'s output plus the derived
    `site_id`; `POST /v1/ingest/commit` `{job_id}` → `upsert_site` + `ingest_parsed` from the
    stored parse, **never `upsert_customer`** on a customer-actor request.
  - `routers/reports.py`: `POST /v1/reports` `{customer_id, site_id, start, end, schema,
    actor}` → job → `build_report_data` + `render_pdf` → PDF to
    `vrm-monitor/reports/{site_id}/{start}_{end}.pdf` → `result.storage_path`.
    `schema = "monitoring"` is accepted only with `actor == "admin"`.
  - `routers/meta.py`: `GET /v1/sites/{site_id}/available-dates`, `GET /v1/limits`
    (serves `MAX_CUSTOM_RANGE_DAYS` / `MAX_OVERVIEW_RANGE_DAYS` — §1.11).
  - `GET /v1/jobs/{id}`, `GET /health` (unauthenticated, no detail).
  - Imports `victron.*` / `database.*` **unchanged**. If a change there proves unavoidable, it
    is additive and called out in the step notes.
- `requirements-api.txt` — `-r requirements.txt` plus `fastapi`, `uvicorn[standard]`,
  `pydantic`. Keeps the Streamlit app's dependency set untouched.
- `Dockerfile.api` — `python:3.11-slim`, WeasyPrint's system libs (Pango, Cairo, gdk-pixbuf,
  libffi, fonts), `WORKDIR /app` at the repo root, `uvicorn vrm_api.main:app --host 0.0.0.0
  --port $PORT`.
- `vrm_api/README.md` — endpoints, env vars, local run, and the §1.3 trust-boundary rules.

**Validate**
- Locally (`uvicorn`, repo root): ingest a real VRM CSV through preview→commit and confirm the
  rows written are **identical** to the same file ingested through `pages/06_vrm_monitor.py`
  (compare `vrm.energy_daily` for the site, row for row).
- Re-run the same commit → row count does not grow, alarm episodes do not double
  (the `UNIQUE (site_id, date)` upsert path).
- Generate a report for a 7-day and a >31-day range; the PDF's numbers are identical to the
  same range from `pages/06_vrm_monitor.py`, and the Detallado/Overview mode matches.
- **Run the same two comparisons inside the Docker image (Python 3.11)** — this is the 3.9→3.11
  check (§1.4). Any difference stops the step.
- No bearer token → 401. Wrong token → 401. A `site_id` belonging to another customer → 403
  and nothing written, **even though this call comes from a trusted caller** (§1.3).
- A browser `fetch()` from any origin fails preflight.
- `POST /v1/reports` with `schema="monitoring"` and no `actor="admin"` → 403.

---

### Step 6 — Upload + Reports in the web app (the value slice)

**Build**
- `app/api/uploads/sign/route.ts` — `requireCustomer()` → `createSignedUploadUrl()` for
  `uploads/{customerId}/{uuid}.csv`; returns the URL only, never a key. Rejects over the
  configured size cap (§1.5) with the reason, before signing.
- `app/api/pipeline/*` — thin authenticated proxies to `vrm_api` that inject `customer_id`
  from the session and **never** from the request body, plus a job-polling route that refuses
  jobs belonging to another customer.
- `app/(portal)/app/upload/` — direct-to-Storage upload with progress; the two-step
  parse→preview→confirm exactly as `tab_upload()` does it (never write on the first click);
  the site dropdown or "New site…" gated by `canAddSite()`; the warnings list, the partial-day
  explainer, the savings/country captions, the size-cap caption; an **Uploads history** table
  from `listIngestions()` — `vrm.ingestion_log` exists precisely to answer "why did this report
  look wrong" and no UI has ever read it.
- `app/(portal)/app/` (Reports, the landing page of the dashboard) — site picker from
  `listSites`, range picker bounded to real data via `available-dates`, mode caption driven by
  the API's own limits (§1.11), coverage warning, KPI `Stat` tiles + chips + the energy-mix
  bar, weather-error and battery-stress/grid-quality warnings, and the download button
  (signed URL to the generated PDF, short TTL).
- `JobProgress` — polls, shows a real status, and fails with a human sentence.

**Validate**
- End to end as customer A: upload a real CSV to a new site → preview matches
  `pages/06_vrm_monitor.py`'s preview for the same file → confirm → rows land under A's
  `customer_id` → generate a report → download the PDF.
- Re-upload the same file: no duplicate rows, no doubled alarm episodes.
- **Tamper tests, from DevTools:** post another customer's `site_id` to the upload confirm and
  to the report route → 403, nothing written, and the same result when the request is aimed
  straight at `vrm_api` with a stolen bearer token (this is what §1.3's double check buys).
- Upload something over the size cap → refused client-side with the reason, and the sign route
  refuses it too if the client check is bypassed.
- Kill the API mid-job → the job ends `failed` with a retry message, not a spinner forever.
- `pages/06_vrm_monitor.py` still works unchanged against the same data.

---

### Step 7 — Admin dashboard + the invite flow

**Build**
- `victron/mailer.py` — generic Resend wrapper (§1.9), `RESEND_API_KEY` / `PORTAL_FROM_EMAIL`
  from env, typed error on failure, **no invite-specific logic** (Phase 12 imports this).
- `victron/templates/invite_email.html` — Jinja2, table layout + inline styles, no `data:`
  URIs (the Gmail constraint Phase 12 documents), brand colours from the chosen token.
- `lib/server/invites.ts` + `app/api/admin/invites/*` — `sendInvite(customerId)` via the
  Supabase admin API's `generateLink({type: 'invite'})` → build
  `{SITE_URL}/activate?token_hash=…&type=invite` → render + send → stamp `invited_at`,
  `auth_user_id`, `auth_email`. `resendInvite` / `sendPasswordReset` use `type: 'recovery'`
  (§1.9's empirical check happens here — write the result into §1.9).
  "Email already registered": linked to another customer → refuse with a clear message;
  unlinked → offer to link.
- `app/(auth)/activate/page.tsx` — server-side `verifyOtp({token_hash, type})` → "Set your
  password" (min 8, confirm) → `updateUser` → stamp `activated_at` → redirect to `/app`.
  Expired/used → the friendly message. The token never lands in a client component's props.
- `app/(auth)/forgot/` — request a reset; always the same neutral confirmation regardless of
  whether the address exists.
- `/admin/customers` (Spanish) — every customer with name, account type, plan, sites, last
  upload, auth status (`Sin invitar` / `Invitado <date>` / `Activo <date>`), active flag;
  create (name → slug preview, account type, plan → `site_limit` prefilled from `PLANS`,
  contact fields, login email, `ui_language`) + **Enviar invitación**; resend; edit;
  activate/deactivate.
- `/admin/sites` — cross-customer, editable, with customer reassignment.
- `/admin/upload` — upload on behalf of a chosen customer (the one place `upsert_customer` is
  legitimately reachable, and only from an admin session).
- `/admin/reports` — both schemas (`actor: "admin"`).
- `/admin/activity` — `vrm.ingestion_log` across customers, newest first, `warnings` expandable.

**Validate**
- Create a customer with an address Oscar controls → email arrives → link opens `/activate` →
  password set → lands on `/app` → `activated_at` stamped.
- Click the same link again → "expired / already used," no crash, no stack trace.
- Resend to a never-activated account → works, or the documented fallback does and §1.9 is
  updated with what actually happened.
- Forgot password → email → new password → sign in.
- Deactivate a customer → their login is cleanly rejected; reactivate → works.
- Admin sees every customer's sites; the customer sees only their own — same browser, two
  sessions, back to back.
- `scripts/test-scoping.ts` still passes.

---

### Step 8 — Deploy, cut over, retire the legacy, document

**Build / do**
- **Vercel** project: Root Directory `victron-monitor/web`, env vars `SUPABASE_URL`,
  `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY`, `PIPELINE_API_URL`, `PIPELINE_API_KEY`,
  `RESEND_API_KEY`, `PORTAL_FROM_EMAIL`, `SITE_URL`. Custom domain (§0.4 Q1). Preview
  deployments get a **separate** Supabase project or are disabled — a preview URL pointing at
  production data is a live customer-data leak waiting for a bad merge.
- **Render** Web Service from `Dockerfile.api`, Standard (2 GB) to start, `api.<domain>`, env
  `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PIPELINE_API_KEY`, `ANTHROPIC_API_KEY`.
- Supabase: create the private `vrm-monitor` bucket (`uploads/`, `reports/`), set the file-size
  limit per §0.4 Q2, and add the `Site URL` / redirect allowlist entries for the new domain.
- Security headers in `next.config.ts`: HSTS, `X-Content-Type-Options`, `Referrer-Policy`,
  frame-ancestors, and a CSP that permits only self + the Supabase Storage origin.
- **Retire the legacy** (§6): delete `vrm_portal/`, `victron-monitor/portal/` (including its
  `__pycache__`), and — once the domain is serving the new site — `victron-monitor/landing-page/`,
  each in its own commit whose message points at this plan. Update the Artifact to point at
  the new URL (or unpublish it) only *after* the new site is live and verified.
- Docs: `victron-monitor/web/README.md` (run locally, env vars, the three §Step 3 leak checks,
  deploy); update `victron-monitor/README.md`, `ARCHITECTURE.md` (new boxes: browser → Vercel
  → Supabase `vrm` + Resend; Vercel → Render `vrm_api` → Supabase; note that no browser ever
  touches Supabase), `PHASES.md`, and a `CONTEXT.md` entry in the existing style.

**Validate**
- From the deployed marketing page: Log in → sign in → upload → report → download, all on the
  real host. This is the real WeasyPrint-system-libs test.
- A ~50 MB CSV on the deployed API: watch memory; if it OOMs, size up and **record the required
  tier in `vrm_api/README.md`** rather than leaving it as tribal knowledge.
- Re-run the three leak checks against the production build.
- `scripts/test-scoping.ts` against the deployed environment.
- `git diff --stat` shows **no changes** to `app.py` or anything under `pages/`; `streamlit run
  app.py` still works with an unchanged sidebar; `pages/06_vrm_monitor.py` still generates a
  report.

---

## 3. Conventions the coder must follow

**Python (`vrm_api/`, `victron/mailer.py`)**
- `from __future__ import annotations` first, then the docstring — matching `victron/`.
- No ORM. `get_client()` from `database/supabase_client.py`, then
  `.schema("vrm").table(x).select/insert/update/upsert().execute()`.
- Never write a generated column (`vrm.sites.battery_usable_kwh`).
- Formatting through `utils/formatting.py`; money through `victron/savings.format_money`.
- Brand constants from `config.py`; countries from `config.COUNTRIES`.
- **Do not modify** `app.py`, anything under `pages/`, or the *signatures* of
  `database/supabase_client.py`, `database/vrm_report_db.py`, `victron/*.py`. Additive only if
  truly unavoidable, and say so in the step notes.

**TypeScript (`victron-monitor/web/`)**
- `import 'server-only'` at the top of every module under `lib/server/`. No exceptions.
- Server Components by default; `'use client'` only for genuinely interactive leaves
  (ModeToggle, upload progress, form validation).
- `requireCustomer()` / `requireAdmin()` is the **first statement** of every route handler,
  server action, and protected page — never inferred from layout nesting.
- No `any` on anything crossing the server boundary. Zod (or equivalent) parse every request
  body in a route handler before it reaches `lib/server/db/`.
- Never put a token, a `token_hash`, a session, or a key into a client component's props, into
  a URL, or into a log line.
- No secret is ever read outside `lib/server/`.

**Both**
- **Comments explain the non-obvious, in this repo's voice** — the way migration 012,
  `pages/06_vrm_monitor.py`, and migration 021 do, including what was tried and rejected.
  In particular, comment: why there is no `NEXT_PUBLIC_SUPABASE_*`; why `getUser()` and not
  `getSession()`; why the upload bypasses the Next.js server entirely; why the API re-checks
  ownership the Next.js layer already checked; and every `assertOwnsSite()` that looks
  redundant.
- **git on this machine:** stage in batches of 5–10 (`git-lfs` is configured but not
  installed — bulk `git add` and `git show --stat` hang). Use `timeout 90 git commit`.
  `node_modules/` must be ignored before the first `git add` in `victron-monitor/web/`.

---

## 4. Explicit non-goals

- **Public self-serve signup.** Oscar creates accounts. The landing page's early-access
  `mailto:` stays a `mailto:`.
- **Billing, payments, plan enforcement beyond `site_limit`, usage metering.** No Stripe.
- **Multiple users per customer.** One login per tenant, by explicit decision.
- **RLS policies / per-user JWTs / any browser-side Supabase client.** §1.2, with a written
  revisit trigger.
- **A real job queue** (Celery/RQ/Redis) or multi-instance API scaling. §1.6.
- **A test framework.** One scoping script and one styleguide page; introducing Vitest/Jest is
  a separate decision, not a side effect of this phase.
- **VRM API token ingestion** (`source = 'vrm_api'`). Still V2.
- **Scheduled/automatic report emails to customers.** That is Phase 12; this phase only leaves
  `victron/mailer.py` behind for it.
- **Per-customer report branding / white-labelling.** `vrm.customers.branding` stays empty.
- **Retiring `pages/06_vrm_monitor.py`.** It stays live and untouched, and remains the only
  path for >50 MB backfills (§1.5).
- **Admin impersonation** ("log in as this customer").
- **Marketing-site localisation, blog, CMS, analytics beyond Vercel's built-in.**

---

## 5. Risks and tradeoffs

| Risk | Assessment / mitigation |
|---|---|
| **A secret key or an unscoped query reaching the browser** | The one catastrophic failure. Mitigated structurally, not by discipline: no `NEXT_PUBLIC_SUPABASE_*` exists, `import 'server-only'` makes a client import a build error, the new `sb_secret_…` format 401s from a browser by design, and three leak checks run at Step 3 and again at Step 8. |
| **Two authorization implementations drifting** (Next.js layer and `vrm_api`) | Deliberate duplication (§1.3), so it is drift *toward* strictness, not away: both must agree for a request to succeed. `scripts/test-scoping.ts` covers the TS side; Step 5's 403 tests cover the API side. |
| **pandas over a large CSV on a 512 MB instance** | Real OOM risk; the pipeline has only ever run on Oscar's Mac and on his own files. Mitigated by starting on Render Standard (2 GB), measuring at Step 8, and recording the required tier. |
| **Python 3.9 (local) vs 3.11 (container) divergence** | Low but non-zero — pandas/numpy version resolution differs. Step 5 validates identical report numbers inside the image before anything ships. |
| **In-process jobs lost on container restart** | Accepted at this scale. Stale-job sweep + a retry message, never a permanent spinner. Upgrade path (a worker + a real queue) written down, not taken. |
| **Supabase Free plan's 50 MB Storage cap** | Blocks big backfills through the portal, not weekly customer uploads (~12 MB). Surfaced as §0.4 Q2 with the internal Streamlit tool as the documented alternative. |
| **Design fidelity regression during the CSS port** | The reason for CSS Modules over Tailwind (§1.7) and for screenshot diffs at three breakpoints (Step 2). The failure mode is a rewrite that looks like a move. |
| **Anthropic spend now triggered by strangers** | Report generation calls Claude. No quota in v1 beyond `site_limit` (§0.4 Q5). Watch it in the first weeks; `vrm.jobs` gives the per-customer count needed to act. |
| **The invite/recovery mechanics remain the least-verified part of the plan** | `generateLink` + `verifyOtp` are documented and the flow is standard, but the recovery-for-never-activated-user case is still unknown. Explicit empirical check in Step 7 with a named fallback. |
| **A Vercel preview deploy pointed at production data** | Named because it is easy to do by accident and hard to notice. Step 8 disables previews or gives them their own Supabase project. |
| **Scope: this is materially bigger than Phase 13's Streamlit port** | It buys one coherent product instead of two disconnected ones — Oscar's explicit choice. Steps 1–2 deliver a shippable marketing site before any auth work, so the phase produces value even if it pauses. |

---

## 6. What happens to the existing artifacts

### 6.1 The Streamlit portal (`vrm_portal/`, `victron-monitor/portal/`) — recommendation: keep as reference through Step 7, delete at Step 8

Not a silent decision either way, so here is the reasoning:

- **Why not delete now:** `vrm_portal/auth.py` is *validated, working* code for the exact
  problem Step 3 solves — role resolution, the clean-rejection rule, the not-linked sign-out,
  the refresh margin. Porting it to TypeScript with the original beside you is meaningfully
  safer than porting it from a plan doc. `strings.py` is the literal content of
  `lib/i18n/strings.ts`.
- **Why not keep indefinitely:** it is a *runnable second door* into the same data holding a
  service_role key, with no owner and no reason to be maintained. Dead code that boots is not
  dead code.
- **Therefore:** at the start of Step 3, add a header line to `victron-monitor/portal/app.py`
  and `vrm_portal/__init__.py` — `LEGACY: superseded by PLAN_PHASE14. Do not run or deploy.` —
  and delete both directories in a dedicated Step 8 commit referencing this plan. The git
  history keeps them; nothing is lost. Also delete the checked-in
  `victron-monitor/portal/__pycache__/`.
- `SUPABASE_ANON_KEY` stays in `.env.example` (the web app's publishable key replaces it, so
  update that comment block rather than deleting the line).

### 6.2 The landing page (`victron-monitor/landing-page/` + the published Artifact) — recommendation: keep live and frozen until cutover, then remove both

- It is Oscar's **live marketing page**. Taking it down before the Next.js site is serving on a
  real domain would leave the product with no public presence for the duration of the build.
- During Steps 1–2 it is the **design source of truth**: the port is diffed against
  `landing_page.html` rendered in a browser, so it must stay renderable exactly as-is. Do not
  edit it — not even to add the Log in link Phase 13 planned. That link now lives in the
  Next.js nav.
- The four `.woff2` faces and the two PNGs are **copied** (not moved) into
  `victron-monitor/web/` at Steps 1–2, so `build.py` keeps working until cutover.
- At Step 8, once the new site is verified live: update the Artifact to point at the new URL
  (or unpublish it), then delete `victron-monitor/landing-page/` in one commit that says where
  the design went. Keep one line in `victron-monitor/README.md` recording that the design
  system originated there.

### 6.3 Migration 021 — done, and confirmed still right

Every column it added describes the tenant, not the interface: `auth_user_id` / `auth_email`
are the Supabase-Auth linkage regardless of what renders the login form; `invited_at` /
`activated_at` are invite-flow state that §1.9 keeps unchanged; `account_type` still drives the
installer/owner copy split that the landing page itself sells; `site_limit` is still enforced
in application code; `ui_language` is still what makes the bilingual dashboard work. **Nothing
in it is Streamlit-shaped.** It stays exactly as applied; migration 022 records what changed
around it (§Step 5).

---

## 7. Decision map vs. `PLAN_PHASE13.md`

| Phase 13 | Status | Where |
|---|---|---|
| §1.1 service_role + app-layer scoping, no RLS, no per-user JWTs | **Reopened and re-decided.** Conclusion is compatible (no RLS, no browser JWTs) but the reasoning and the enforcement mechanism are new, and the "no browser Supabase client at all" rule is stronger than what 013 had. | §1.2 |
| §1.2 two Supabase clients, never one | **Superseded** — a `supabase-py` singleton hazard with no equivalent in `@supabase/ssr`'s per-request clients. The *principle* (auth client ≠ data client) survives in `lib/server/supabase.ts`. | §1.2 |
| §1.3 auth columns on `vrm.customers`, soft pointer, no FK | **Carried unchanged, already applied.** | §0.2, §6.3 |
| §1.4 `PLANS` in Python, not a DB CHECK | **Carried**, now `lib/plans.ts`. | §Step 4 |
| §1.5 admin via `app_metadata.vrm_role` + role-resolution order | **Carried verbatim.** | §Step 3 |
| §1.6 `vrm_portal/` + `victron-monitor/portal/app.py` layout, `sys.path` bootstrap | **Superseded** — Streamlit-specific. | §1.1 |
| §1.7 `st.navigation` role gating | **Superseded** — App Router route groups + guards. | §Step 3 |
| §1.8 `generate_link()` + Resend over `invite_user_by_email()` | **Carried, on two of its three original reasons.** The fragment argument is explicitly retired. | §1.9 |
| §1.9 activation screen | **Carried**, now `/activate`. | §Step 7 |
| §1.10 no session persistence across refresh | **Retired as a non-goal** — cookie sessions give it for free. | §1.2 |
| §1.11 what the customer surface must never do | **Carried, extended.** | §1.12 |
| §0.3 Q1 hosting, deferred | **Decided.** | §1.4 |
| §0.3 Q2–Q5 (English default, admin scope, `mailto:` stays, site limits) | **Carried unchanged.** | §0.2 |
