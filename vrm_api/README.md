# vrm_api

Internal FastAPI service wrapping the VRM report pipeline
(`victron/vrm_csv.py`, `victron/ingest.py`, `victron/weekly_report.py`,
`database/vrm_report_db.py`) so `victron-monitor/web`'s Next.js server can
run CSV ingestion and generate reports without a rewrite. Full design:
[`PLAN_PHASE14.md`](../PLAN_PHASE14.md) §1.3 and §2 Step 5.

**This service is never called from a browser.** Only the Next.js server
calls it, over a private network path in production (Vercel → Render) and
over `localhost` in development. See "Trust boundary rules" below before
changing anything here.

## Run locally

From the **repo root** (not from inside `vrm_api/` — it imports `victron.*`
and `database.*` as top-level packages, and uvicorn needs the CWD to be the
root for that to resolve):

```bash
pip install -r requirements-api.txt
uvicorn vrm_api.main:app --reload
```

Needs the same `.env` the Streamlit app reads (`database/supabase_client.py`
loads it via `python-dotenv`, cwd-relative) — see "Env vars" below.

## Env vars

All already present in the repo-root `.env` (never committed; see
`.env.example`):

| Var | Used for |
|---|---|
| `SUPABASE_URL` | `database/supabase_client.py:get_client()` — same client the pipeline already uses. |
| `SUPABASE_SERVICE_ROLE_KEY` | Same client. This is the secret credential — see "Trust boundary rules." |
| `ANTHROPIC_API_KEY` | `victron/weekly_report.py:generate_narrative()`. Missing key fails soft (a placeholder paragraph), never an error. |
| `PIPELINE_API_KEY` | `vrm_api/deps.py` — the bearer token every route but `/health` requires. Long random secret, held only by this service and the Next.js server's env, never in a browser. |
| `ONVO_MODE` | `routers/billing.py:_onvo_mode()` — `test` or `live`. Scopes every `vrm.plans`/`vrm.subscriptions` read/write to the matching row (`§3.1`'s `mode` column on both tables, so a dev row can never point at a live price). Defaults to `test` if unset. |
| `ONVO_SECRET_KEY` | `vrm_api/onvo.py` **only** — the server-side ONVO API key (`Authorization: Bearer <key>` on every outbound call to `api.onvopay.com`). Never logged, never returned to a browser, never read by any other module in this repo. Test-mode keys (`onvo_test_secret_key_...`) for everything except a real production deploy — see `.env.example` and `PLAN_PHASE16.md` §0.6 Q9. |
| `ONVO_PUBLISHABLE_KEY` | `routers/billing.py:_publishable_key()` — handed to the **browser** (as part of `BillingSubscribeOut`/`BillingPaymentMethodSessionOut`) so the ONVO web SDK (`sdk.onvopay.com/sdk.js`) can render its own card form client-side. Safe to expose — it's the public half of the key pair, the same way a Stripe publishable key is. |

In production (Render), all seven vars above are set directly in the
service's environment — no `.env` file is deployed.

**`ONVO_WEBHOOK_SECRET` is deliberately NOT in this list — this service never
reads it.** It's read exclusively by `victron-monitor/web`'s
`app/api/webhooks/onvo/route.ts` (see `victron-monitor/web/README.md`'s env
vars section). See "The billing webhook trust boundary" below for why that
split is the point, not an oversight.

## Endpoints

Every route below except `GET /health` requires `Authorization: Bearer
<PIPELINE_API_KEY>`. Missing or wrong → `401`, same response either way (no
detail in the body — see `vrm_api/deps.py`).

### `GET /health`

The one unauthenticated route.

```
$ curl http://localhost:8000/health
{"status":"ok"}
```

### `POST /v1/ingest/preview`

Downloads a VRM CSV export from Supabase Storage (Step 6 uploads it there
first), parses it, and stores the result on a job. Never writes to
`vrm.sites` / `vrm.energy_daily` — that's `commit`'s job.

```json
// Request
{
  "customer_id": "5c2e...",
  "site_name_or_id": "Casa Principal",
  "storage_path": "uploads/5c2e.../a1b2c3.csv",
  "filename": "997979_0_Emtec_log_20260719-0000_to_20260725-1422.csv",
  "site_fields": {"pv_kwp": 8.5, "battery_nominal_kwh": 10, "battery_dod_pct": 90,
                  "system_type": "hybrid", "report_language": "es"}
}
```

`filename` is the browser's original filename, kept separate from
`storage_path`'s own name — Step 6 renames the object to `{uuid}.csv` before
it reaches Storage, which would otherwise blank out
`victron/vrm_csv.py:installation_id()` (parsed from the filename itself,
`<id>_<n>_<site>_log_...`) and the `ingestion_log.filename` audit column.
Optional/blank-default for backward compatibility, but every real caller
(the Next.js proxy) always sends it.
```json
// Response — 200
{"job_id": "9f1e..."}
```

Poll `GET /v1/jobs/{job_id}` until `status == "done"`; `result` is
`parse_export()`'s output (rows, alarm events, warnings, ...) plus the
derived `site_id` and whether it matched an existing site of this customer's.

### `POST /v1/ingest/commit`

Writes what a `done` `ingest_preview` job parsed. Takes only `job_id` — the
customer/site it writes to come from that job row, not from this request, so
there is nothing here for a caller to point at another tenant's site.

```json
// Request
{"job_id": "9f1e..."}
```
```json
// Response — 200
{"job_id": "3ab0..."}
```

`result` (once `done`) is `{"site_id", "rows_written", "alarm_events_written",
"period_start", "period_end"}`.

### `POST /v1/reports`

```json
// Request
{
  "customer_id": "5c2e...",
  "site_id": "acme-casa-principal",
  "start": "2026-07-01",
  "end": "2026-07-07",
  "schema": "vrm",
  "actor": "customer"
}
```
```json
// Response — 200
{"job_id": "b7d4..."}
```

`result` (once `done`) is `{"storage_path", "is_overview", "start", "end",
"summary"}` — `storage_path` is where the rendered PDF landed in the
`vrm-monitor` Storage bucket. `summary` (added for Step 6, additive —
`storage_path`/`is_overview`/`start`/`end` are unchanged) is the small
JSON-safe subset of `build_report_data()`'s output the web dashboard needs
to render the same KPI tiles/chips/energy-mix bar
`pages/06_vrm_monitor.py:tab_report()` shows on screen — see
`routers/reports.py:_report_summary()` for the exact field list and why it
exists (§1.11: the Next.js layer must never recompute this math itself).

`schema: "monitoring"` (Pauly & Co's own Cerbo GX fleet, unrelated to any
`vrm.customers` tenant) is only accepted with `actor: "admin"` — anything
else is a `403`, before any work is scheduled.

### `GET /v1/jobs/{id}`

```
$ curl -H "Authorization: Bearer $PIPELINE_API_KEY" http://localhost:8000/v1/jobs/9f1e...
{"id":"9f1e...","kind":"ingest_preview","status":"done","customer_id":"5c2e...",
 "site_id":null,"params":{...},"result":{...},"error":null,
 "created_at":"...","started_at":"...","finished_at":"..."}
```

Not customer-scoped at this layer — see `main.py:get_job()`'s docstring. The
Next.js proxy route that polls this on the browser's behalf is where a job
belonging to another customer gets refused (`PLAN_PHASE14.md` §1.6).

### `GET /v1/sites/{site_id}/available-dates?customer_id=...&schema=vrm|monitoring&actor=customer|admin`

Wraps `database/vrm_report_db.py:get_available_dates()`. `customer_id` is a
required query param — this endpoint's own tenancy re-check, independent of
whatever filtered the dropdown that produced `site_id`. `schema`/`actor`
default to `vrm`/`customer` (every pre-Step-7 caller is unaffected).

```
$ curl -H "Authorization: Bearer $PIPELINE_API_KEY" \
    "http://localhost:8000/v1/sites/acme-casa-principal/available-dates?customer_id=5c2e..."
{"dates":["2026-07-01","2026-07-02", ...]}
```

**Step 7 addition:** `schema=monitoring` is accepted only with `actor=admin`
(otherwise `403`) — `monitoring` sites have no `vrm.customers` owner, so
`customer_id` is only checked for *existing* (`tenancy.get_customer()`), not
for owning `site_id`. Verified live against real data:

```
$ curl -H "Authorization: Bearer $PIPELINE_API_KEY" \
    "http://localhost:8000/v1/sites/vista-atenas-lp-m3/available-dates?customer_id=<real-id>&schema=monitoring&actor=admin"
{"dates":["2026-07-06","2026-07-07", ...]}
$ curl -H "Authorization: Bearer $PIPELINE_API_KEY" \
    "http://localhost:8000/v1/sites/vista-atenas-lp-m3/available-dates?customer_id=<real-id>&schema=monitoring"
# 403 — actor defaults to "customer"
```

### `GET /v1/sites?schema=vrm|monitoring&actor=customer|admin`

**Step 7 addition.** Cross-*customer* site list for one schema — `{site_id,
display_name}` only. Always admin-gated (`403` unless `actor=admin`)
**regardless of `schema`**: there is no `customer_id` filter here at all, so
even `schema=vrm` would hand back every customer's sites in one call — see
`routers/meta.py:list_sites()`'s own comment. In practice
`victron-monitor/web` only ever calls this for `schema=monitoring`
(`lib/server/pipeline.ts:listSitesForSchema()`); the `vrm` branch exists for
symmetry, not because anything currently calls it that way — the web app's
own `lib/server/db/admin.ts:listAllSites()` already covers `vrm` directly,
with fuller rows (including which customer owns each site).

```
$ curl -H "Authorization: Bearer $PIPELINE_API_KEY" \
    "http://localhost:8000/v1/sites?schema=monitoring&actor=admin"
{"sites":[{"site_id":"vista-atenas-lp-m3","display_name":"Vista Atenas LP M3"}, ...]}
```

### `GET /v1/limits`

```
$ curl -H "Authorization: Bearer $PIPELINE_API_KEY" http://localhost:8000/v1/limits
{"max_custom_range_days":31,"max_overview_range_days":183}
```

Served here, not hand-copied into TypeScript (`PLAN_PHASE14.md` §1.11) — the
Detallado/Overview boundary has exactly one source of truth.

### `/v1/billing/*` — ONVO subscription billing (`PLAN_PHASE16.md`)

Added by Phase 16. Full design, tenancy reasoning, and the read-through
principle behind all of it: `routers/billing.py`'s own module docstring —
not duplicated here. All the judgement lives in `vrm_api/billing.py`
(`reconcile_customer()` / `apply_entitlements()`); all the ONVO transport
lives in `vrm_api/onvo.py`; this router only checks tenancy and calls both.

Same auth as every other router (`Authorization: Bearer $PIPELINE_API_KEY`),
same "no CORS, no docs" posture — a customer's browser never calls this
router directly, it always goes through `victron-monitor/web`'s own
`/api/vrm/billing/*` proxy routes, which inject `customer_id` from the
session and never from anything the browser sent.

| Route | What it does |
|---|---|
| `GET /v1/billing/status` | Current plan/subscription/payment-method/billing-address summary for one customer. Refreshes from ONVO first if the mirror is stale (§4.4) or the subscription is in a transitional status. |
| `GET /v1/billing/plans` | The sellable catalogue for this customer's `account_type`/`ONVO_MODE`, filtered to `self_serve` plans only if the customer is still `pending_subscription`. |
| `GET /v1/billing/invoices` | Paginated renewal history, mirrored from ONVO — never a live call on every page view. |
| `POST /v1/billing/subscription` | First-time subscribe. Creates the ONVO subscription (`paymentBehavior: allow_incomplete`, `trialPeriodDays: 7`, no `paymentMethodId` yet) and returns its id + the publishable key, so the browser can mount the ONVO SDK's card form against a real `subscriptionId`. |
| `POST /v1/billing/subscription/change` | Upgrade/downgrade. Cancel-and-restart (no in-place price change exists on ONVO's side — §0.2b finding 6), both directions immediate, no proration. |
| `POST /v1/billing/subscription/cancel` | Graceful (`cancelAtPeriodEnd`) by default; `mode: "immediate"` exists and is tenancy-checked the same as everything else, but has no customer-facing caller — Oscar's admin support action is the only intended caller. |
| `POST /v1/billing/subscription/resume` | Clears a pending graceful cancellation. |
| `POST /v1/billing/payment-method/session` | Returns the `subscriptionId`/`customerId`/publishable key the SDK widget needs to render a card-replacement form against an **existing** subscription. |
| `POST /v1/billing/payment-method` | Attaches a browser-created ONVO payment method id to the customer's subscription — only after re-reading it from ONVO and confirming it belongs to this customer (§6.4 control 3). |
| `PUT /v1/billing/address` | Updates the billing address on the default payment method. |
| `POST /v1/billing/refresh` | A plain reconcile — what the browser calls after the SDK's own `onSuccess` fires. Never trusts that callback's payload as state; it's only a hint to go re-read ONVO. |
| `POST /v1/billing/reconcile-due` | No `customer_id` — the daily scheduled-sweep entry point (§4.4's fourth reconcile trigger), called by `.github/workflows/billing-reconcile.yml`. Reconciles every subscription that's due and retries any `vrm.billing_events` row stuck in `status='error'`. One customer's ONVO error never aborts the sweep for the rest. |
| `POST /v1/billing/prune-signups` | No `customer_id` — the retention sweep for `vrm.signup_requests` (§3.7: unconsumed rows past `expires_at`+7d, consumed rows past `consumed_at`+30d) and `vrm.rate_limits` (§3.8: rows older than a 2-day safety margin past the longest rate-limit window). Called by the same daily workflow, right after `reconcile-due`. |
| `POST /v1/billing/webhook-event` | Intake for ONVO webhook deliveries, forwarded by `victron-monitor/web`'s `/api/webhooks/onvo` — see "The billing webhook trust boundary" below. |

```
$ curl -X POST -H "Authorization: Bearer $PIPELINE_API_KEY" \
    http://localhost:8000/v1/billing/reconcile-due
{"checked":0,"results":[]}
$ curl -X POST -H "Authorization: Bearer $PIPELINE_API_KEY" \
    http://localhost:8000/v1/billing/prune-signups
{"signup_requests_deleted":0,"rate_limits_deleted":0}
```

## Trust boundary rules (PLAN_PHASE14.md §1.3)

This service holds the same Supabase service-role privilege the Next.js
server does. Every rule below exists to keep it from becoming a second,
weaker door to the same data:

1. **Never called from a browser.** No CORS middleware is installed —
   not a permissive one, not a strict one, *none* — so a browser's preflight
   fails by construction (`main.py`'s module docstring has the full
   reasoning). If you find yourself wanting to add `CORSMiddleware` to make
   something in the web app "just work," that something is calling this API
   from the wrong place.
2. **Every route but `/health` requires the pipeline bearer key**
   (`vrm_api/deps.py`), compared with `hmac.compare_digest`. This
   authenticates "this request came from our own server," a different fact
   from "this Supabase session is valid" — it is not a substitute for
   tenancy checking, which is rule 3.
3. **Tenancy is re-checked independently of the caller**
   (`vrm_api/tenancy.py:assert_owns_site()`), on every route that touches a
   specific site. Next.js already checks this before calling here — this
   API checks again anyway, because it holds the same privileged credential
   Next.js does, and "the caller already checked" is not something this
   process can see.
4. **Narrow verbs only.** No endpoint takes a table name, a filter
   expression, or arbitrary SQL. `schema: "monitoring"` is reachable only
   through `POST /v1/reports` with `actor: "admin"` — nothing else in this
   API can reach that schema at all.
5. **No ambient file access.** Every CSV this service reads comes from an
   explicit Supabase Storage path a caller passed in, already scoped to that
   customer's upload prefix — never a caller-supplied URL, never a local
   path (`vrm_api/storage.py`).
6. **Errors never carry raw detail to the caller.** Postgres/Python
   exception text and stack traces go to this service's logs
   (`logging.exception`) only; HTTP responses and `vrm.jobs.error` carry a
   typed code or a short, pre-approved sentence (`main.py`'s exception
   handlers, `jobs.py:_safe_error_message()`).

### The billing webhook trust boundary (`PLAN_PHASE16.md` §4.1/§6.5)

`vrm_api` never receives a webhook delivery directly from the public
internet, and this is deliberate, not incidental. ONVO's dashboard is
configured to POST to `victron-monitor/web`'s `/api/webhooks/onvo` — **not**
to any URL on this service — and that Next.js route is the only thing that
ever talks to ONVO's raw delivery. It verifies `X-Webhook-Secret` against
`ONVO_WEBHOOK_SECRET` in constant time, rate-limits the request
(`vrm.rate_limits`, bucket `onvo_webhook`), and only then calls this
service's own `POST /v1/billing/webhook-event` — authenticated the same way
every other call from Next.js is, with `PIPELINE_API_KEY`, and carrying a
`secret_ok` boolean the Next.js layer already determined.

This keeps the two authentication stories cleanly separated instead of
teaching this service a second, weaker one: `vrm_api` already has exactly
one trust mechanism (rule 2 above, the pipeline bearer key, `Authorization:
Bearer $PIPELINE_API_KEY`) and one caller (Next.js's server) for every route
it exposes — a raw ONVO delivery landing here directly would mean either
adding a second, ONVO-specific auth check to a router that otherwise only
ever validates the pipeline key, or trusting `X-Webhook-Secret` in a service
that was designed around never accepting a request the Next.js layer hasn't
already vetted. Neither is worth it for one endpoint. If a bug in the
Next.js route ever did forward a rejected delivery anyway,
`post_webhook_event()` still records it faithfully (`secret_ok=False`) and
does no further processing beyond that — the row is what makes an attempted
forgery visible at all, not a second rejection here.

And because of `PLAN_PHASE16.md` §0.5's read-through principle, none of this
is actually load-bearing for correctness: a forged or replayed webhook body
can, at worst, cause this endpoint to re-read a real subscription from ONVO
with our own secret key — the same read `POST /v1/billing/refresh` and the
daily sweep already perform. It can never write state directly, because
nothing in this codebase ever applies a webhook payload's own fields to a
mirror row.

## Jobs (PLAN_PHASE14.md §1.6)

Ingestion and report generation run as FastAPI `BackgroundTasks` (Starlette's
own bounded thread pool — not Celery, not Redis; see `jobs.py`'s module
docstring for why that's the right trade at this scale) against `vrm.jobs`
(migration 023). A route handler creates a `queued` row and returns
`{job_id}` immediately; the caller polls `GET /v1/jobs/{id}`.

On startup, any job still `status = "running"` more than 15 minutes after
`started_at` is presumed orphaned by a restart and marked `failed` with a
retry message (`jobs.py:sweep_stale_jobs()`) — there is no queue to resume it
from, so a container restart genuinely does lose in-flight work; this just
turns "stuck forever" into "clearly failed, try again."
