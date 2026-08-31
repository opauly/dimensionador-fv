import 'server-only';

// Thin client for `vrm_api` (PLAN_PHASE14.md §1.3, §2 Step 6). Every
// function here injects the `PIPELINE_API_KEY` bearer token — this module
// must never be reachable from anything that isn't itself server-only,
// because the moment that key reaches a browser it stops meaning "this
// really is our own Next.js server," which is the one fact
// `vrm_api/deps.py:require_pipeline_key()` trusts it to mean.
//
// This module deliberately does NOT call `requireCustomer()` itself — it
// has no access to the request/cookies, and folding auth in here would make
// it easy to believe a call through this module is safe by construction.
// It isn't: every route handler under `app/api/pipeline/*` and
// `app/api/uploads/*` must call `requireCustomerForRoute()` as its own first
// statement (PLAN_PHASE14.md §3) and run its own `assertOwnsSite()` /
// `getJobScoped()` check before calling anything exported from here — this
// module only knows how to talk to `vrm_api`, not who is allowed to ask it to.
import { NextResponse } from 'next/server';

function requirePipelineEnv(): { url: string; key: string } {
  const url = process.env.PIPELINE_API_URL;
  const key = process.env.PIPELINE_API_KEY;
  if (!url || !key) {
    throw new Error('PIPELINE_API_URL / PIPELINE_API_KEY not set. See victron-monitor/web/README.md.');
  }
  return { url: url.replace(/\/+$/, ''), key };
}

// Generous headroom for a slow hop to Render, not a budget for the job
// itself — job *creation* is a single Postgres insert (fast); the actual
// parse/report work runs in vrm_api's background thread pool regardless of
// how long any one HTTP call here takes (PLAN_PHASE14.md §1.6). The browser
// finds out the real outcome by polling `GET /api/pipeline/jobs/[id]`, not
// by this fetch staying open.
const PIPELINE_TIMEOUT_MS = 30_000;

/**
 * The one error type this module throws. Route handlers convert it to a
 * response via `toErrorResponse()` below — deliberately never let `err.message`
 * or a raw fetch failure reach `NextResponse.json()` un-mapped, since a
 * connection-refused message can contain vrm_api's own host/port
 * (PLAN_PHASE14.md §1.12 rule 6, one process further removed from Postgres
 * than usual).
 *
 * `detail` (PLAN_PHASE16.md §8 Step 5 addition): some `vrm_api` errors carry
 * more than a bare `{code}` — `POST /v1/billing/subscription/change`'s own
 * `over_site_limit` (`routers/billing.py:post_subscription_change()`) is the
 * first one, returning `requires_confirmation`/`current_site_count`/
 * `new_site_limit` alongside the code so `PlanPicker.tsx` can render the
 * real numbers in its confirmation copy (`billing_change_confirm_body`'s own
 * `{current}`/`{limit}` placeholders) instead of a generic error. Additive
 * only: every existing caller that only ever reads `err.code` is unaffected.
 */
export class PipelineError extends Error {
  status: number;
  code: string;
  detail?: Record<string, unknown>;
  constructor(status: number, code: string, message?: string, detail?: Record<string, unknown>) {
    super(message ?? code);
    this.name = 'PipelineError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

/** Route handlers call this after catching anything from this module;
 * returns `null` for errors that aren't this module's — the caller should
 * rethrow those (they're a real bug, not a pipeline-shaped failure). */
export function toErrorResponse(err: unknown): NextResponse | null {
  if (err instanceof PipelineError) {
    return NextResponse.json({ error: err.code, ...err.detail }, { status: err.status });
  }
  return null;
}

async function pipelineFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const { url, key } = requirePipelineEnv();
  try {
    return await fetch(`${url}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${key}` },
      signal: AbortSignal.timeout(PIPELINE_TIMEOUT_MS),
      cache: 'no-store',
    });
  } catch {
    // Network failure / vrm_api down / DNS / timeout — this is the "kill
    // the API mid-request" case (PLAN_PHASE14.md §2 Step 6 validation).
    // `pipeline_unreachable` is a typed code a route handler and, in turn,
    // JobProgress can act on without ever seeing the underlying error text.
    throw new PipelineError(502, 'pipeline_unreachable', 'Could not reach the report pipeline.');
  }
}

async function pipelineJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await pipelineFetch(path, init);
  if (!res.ok) {
    // vrm_api's own exception handlers (main.py) always answer with a typed
    // `{"code": ...}` body, never a stack trace — so relaying the status is
    // safe; only the body's *shape* is untrusted enough to need a fallback.
    // A plain `raise HTTPException(status_code=..., detail={"code": ...})`
    // (no custom exception-handler class, e.g. `routers/vrm_fleet.py`'s own
    // typed 400/404/409s) is wrapped by FastAPI's default handling into
    // `{"detail": {"code": ...}}`, one level deeper than a custom handler's
    // flat `{"code": ...}` (`main.py`'s `NotAuthorized`/
    // `VrmAccountAlreadyLinked` handlers) — both shapes are real and both
    // are checked here, so a route handler calling this module never has to
    // know which style the vrm_api endpoint it's hitting happens to use.
    let code = 'pipeline_error';
    let detail: Record<string, unknown> | undefined;
    try {
      const body = (await res.json()) as { code?: string; detail?: string | Record<string, unknown> };
      if (typeof body.detail === 'object' && body.detail !== null) {
        // Nested-shape case — pull `code` out and keep every OTHER field as
        // `detail` (see `PipelineError`'s own comment: `over_site_limit`'s
        // `requires_confirmation`/`current_site_count`/`new_site_limit`).
        const { code: nestedCode, ...rest } = body.detail;
        code = body.code ?? (typeof nestedCode === 'string' ? nestedCode : undefined) ?? code;
        if (Object.keys(rest).length > 0) detail = rest;
      } else {
        code = body.code ?? code;
      }
    } catch {
      // No body, or not JSON — keep the generic code.
    }
    throw new PipelineError(res.status, code, undefined, detail);
  }
  return (await res.json()) as T;
}

function jsonInit(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

// ── Wire types, mirroring vrm_api/schemas.py — not re-derived from it (a
// FastAPI OpenAPI-codegen step would be the honest long-term fix; not worth
// introducing a generator for one internal API at this scale) ─────────────
export type JobKind = 'ingest_preview' | 'ingest_commit' | 'report';
export type JobStatus = 'queued' | 'running' | 'done' | 'failed';

export type JobOut = {
  id: string;
  kind: JobKind;
  status: JobStatus;
  customer_id: string | null;
  site_id: string | null;
  params: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};

/** Mirrors `vrm_api/schemas.py:SiteFieldsIn` field-for-field — see that
 * model's own docstring for why this whitelist is re-stated a third time
 * (once in `lib/server/db/sites.ts`, once here as the shape this module
 * sends, once again in `vrm_api` itself). */
export type SiteFieldsIn = {
  display_name?: string;
  pv_kwp?: number | null;
  battery_nominal_kwh?: number | null;
  battery_dod_pct?: number | null;
  system_type?: 'grid_zero' | 'off_grid' | 'hybrid';
  report_language?: 'es' | 'en';
  location?: string | null;
  timezone?: string;
  latitude?: number | null;
  longitude?: number | null;
  country?: string;
  savings_rate?: number | null;
  savings_currency?: string | null;
  exports_to_grid?: boolean;
};

export async function ingestPreview(body: {
  customer_id: string;
  site_name_or_id: string;
  storage_path: string;
  /** The browser's original filename — see `vrm_api/schemas.py:IngestPreviewRequest`'s
   * own comment for why this travels separately from `storage_path` (which
   * is always a uuid-renamed Storage object name by the time it gets here). */
  filename: string;
  site_fields: SiteFieldsIn;
}): Promise<{ job_id: string }> {
  return pipelineJson('/v1/ingest/preview', jsonInit(body));
}

export async function ingestCommit(jobId: string): Promise<{ job_id: string }> {
  return pipelineJson('/v1/ingest/commit', jsonInit({ job_id: jobId }));
}

export async function createReport(body: {
  customer_id: string;
  site_id: string;
  start: string;
  end: string;
  schema: 'vrm' | 'monitoring';
  actor: 'customer' | 'admin';
}): Promise<{ job_id: string }> {
  return pipelineJson('/v1/reports', jsonInit(body));
}

export async function getJob(jobId: string): Promise<JobOut | null> {
  const res = await pipelineFetch(`/v1/jobs/${encodeURIComponent(jobId)}`, { method: 'GET' });
  if (res.status === 404) return null;
  if (!res.ok) throw new PipelineError(res.status, 'pipeline_error');
  return (await res.json()) as JobOut;
}

/**
 * `vrm_api`'s `GET /v1/jobs/{id}` is deliberately NOT customer-scoped — its
 * own docstring says so, and says this proxy is where that scoping happens
 * (PLAN_PHASE14.md §1.6). Every route in this app that reads a job by id
 * (the poll route, ingest/commit, the report-download route) must go
 * through this function rather than `getJob()` directly, so "a job
 * belonging to another customer" always fails the same way (403, nothing
 * about the job leaked) no matter which route handler asked.
 */
export async function getJobScoped(jobId: string, customerId: string): Promise<JobOut> {
  const job = await getJob(jobId);
  if (!job || job.customer_id !== customerId) {
    throw new PipelineError(403, 'not_authorized', 'Not authorized.');
  }
  return job;
}

export async function getAvailableDates(siteId: string, customerId: string): Promise<string[]> {
  const data = await pipelineJson<{ dates: string[] }>(
    `/v1/sites/${encodeURIComponent(siteId)}/available-dates?customer_id=${encodeURIComponent(customerId)}`,
    { method: 'GET' },
  );
  return data.dates;
}

// ── Admin-only additions (PLAN_PHASE14.md §2 Step 7) ───────────────────────
// `/admin/reports` needs the `monitoring` schema selectable alongside `vrm`
// (§1.12 rule 2's customer-facing prohibition doesn't apply to `/admin/*`).
// `monitoring` sites have no `vrm.customers` owner at all, so the existing
// customer-scoped `getAvailableDates()`/`assertOwnsSite()` shape above
// cannot express "give me this monitoring site's dates" — these two
// functions call the schema/actor-gated extensions Step 7 added to
// `vrm_api/routers/meta.py` (additive; every existing call above is
// unaffected). Only ever called from `/admin/*` route handlers/actions —
// same convention as `lib/server/db/admin.ts`, restated here since this
// module has no file-level import restriction of its own.

export type Schema = 'vrm' | 'monitoring';

/** `customerId` still required even for `schema: 'monitoring'` — not to
 * scope the site (monitoring sites have no owner), but because `vrm_api`'s
 * own `tenancy.get_customer()` re-check (and, for a report job,
 * `vrm.jobs.customer_id`'s NOT NULL foreign key) both need *some* real
 * `vrm.customers` row named, by design (`vrm_api/routers/meta.py`'s own
 * comment on this). `/admin/reports` surfaces this plainly rather than
 * picking a customer silently on the admin's behalf. */
export async function getAvailableDatesAdmin(siteId: string, customerId: string, schema: Schema): Promise<string[]> {
  const params = new URLSearchParams({ customer_id: customerId, schema, actor: 'admin' });
  const data = await pipelineJson<{ dates: string[] }>(`/v1/sites/${encodeURIComponent(siteId)}/available-dates?${params}`, {
    method: 'GET',
  });
  return data.dates;
}

/** `owner` mirrors `vrm_api/schemas.py:SiteSummaryOut.owner` (bug-fix pass
 * 2026-08-18, Bug 3) — `monitoring.sites.owner`'s real-person name, `null`
 * for `schema: 'vrm'` rows (that schema's own `customer_id` FK is the real
 * ownership fact there). `/admin/reports` uses this to narrow the
 * `monitoring` site picker by the selected customer's name. */
export type SiteSummary = { site_id: string; display_name: string; owner: string | null };

/** Cross-*customer* site list for one schema — see
 * `vrm_api/routers/meta.py:list_sites()`'s own comment for why this is
 * unconditionally admin-gated regardless of `schema`. `/admin/reports`
 * only actually calls this for `schema: 'monitoring'` in practice — the
 * `vrm` branch already has a better-suited source,
 * `lib/server/db/admin.ts:listAllSites()` (full rows, including which
 * customer owns each one), so there's no reason for `/admin/reports` to
 * prefer this thinner cross-vrm_api round trip for `vrm`. */
export async function listSitesForSchema(schema: Schema): Promise<SiteSummary[]> {
  const params = new URLSearchParams({ schema, actor: 'admin' });
  const data = await pipelineJson<{ sites: SiteSummary[] }>(`/v1/sites?${params}`, { method: 'GET' });
  return data.sites;
}

export type Limits = { max_custom_range_days: number; max_overview_range_days: number };

export async function getLimits(): Promise<Limits> {
  return pipelineJson('/v1/limits', { method: 'GET' });
}

// ── VRM fleet (PLAN_PHASE15.md §3.3 / §8 Step 4b) ───────────────────────
// Oscar's OWN VRM fleet (`VRM_ADMIN_TOKEN`, read only inside `vrm_api` —
// never sent through this module, never reaches Next.js at all), reachable
// only from `/admin/vrm-fleet` (`requireAdminForRoute()` gates every route
// handler that calls the three functions below — this module itself has no
// opinion on who may call it, same disclaimer as every other function in
// this file). Mirrors `vrm_api/schemas.py`'s `VrmFleet*` models field-for-
// field, same "restated, not re-derived" convention as `SiteFieldsIn` above.

export type VrmFleetLinkedSite = {
  customer_id: string;
  customer_name: string | null;
  site_id: string;
  site_display_name: string;
  vrm_sync_enabled: boolean;
  vrm_last_synced_at: string | null;
};

export type VrmFleetInstallation = {
  id_site: number;
  name: string | null;
  identifier: string | null;
  /** Empty = unlinked. More than one entry is possible (§1.1: the unique
   * constraint is per-customer, not global) — a single installation can be
   * linked under more than one `customer_id` at once. */
  links: VrmFleetLinkedSite[];
  /** Bug-fix pass 2026-08-18, Bug 1 — a pre-fill sourced from
   * `monitoring.sites` for this same physical installation, when one was
   * found (`vrm_api/routers/vrm_fleet.py:_monitoring_suggestions_by_installation()`).
   * `null` most of the time; never auto-applied by anything that reads this
   * — `VrmFleetManager.tsx` only ever copies it into the (fully editable)
   * link form's initial state. */
  suggested_fields: SiteFieldsIn | null;
};

export async function listVrmFleetInstallations(): Promise<VrmFleetInstallation[]> {
  const data = await pipelineJson<{ installations: VrmFleetInstallation[] }>('/v1/vrm-fleet/installations', { method: 'GET' });
  return data.installations;
}

export async function linkVrmFleetInstallation(body: {
  vrm_installation_id: number;
  /** Exactly one of `customer_id`/`new_customer_name` — `vrm_api`'s own
   * 400 (`exactly_one_customer_field_required`) is the enforcement point;
   * this function does not pre-validate. */
  customer_id?: string;
  new_customer_name?: string;
  site_name_or_id: string;
  site_fields?: SiteFieldsIn;
}): Promise<{ customer_id: string; customer_is_existing: boolean; site_id: string; site_is_existing: boolean }> {
  return pipelineJson('/v1/vrm-fleet/link', jsonInit(body));
}

export async function syncVrmFleetSite(body: { site_id: string; start: string; end: string }): Promise<{ job_id: string }> {
  return pipelineJson('/v1/vrm-fleet/sync', jsonInit(body));
}

export type SiteShapeRange = 'today' | 'week' | 'month';

/** Mirrors `vrm_api/schemas.py:SiteShapeOut` — 24 hour-of-day buckets,
 * `null` where that site published nothing usable, `grid` all-`null` on a
 * site with no physical meter. Fetched fresh from VRM on every call
 * (Fleet Dashboard Phase 2.5) — never cached/stored on this side either. */
export type SiteShapeOut = {
  solar: (number | null)[];
  load: (number | null)[];
  battery: (number | null)[];
  grid: (number | null)[];
};

export async function getSiteShape(siteId: string, range: SiteShapeRange): Promise<SiteShapeOut> {
  const qs = new URLSearchParams({ site_id: siteId, range });
  return pipelineJson(`/v1/vrm-fleet/site-shape?${qs.toString()}`, { method: 'GET' });
}

// ── VRM link (PLAN_PHASE15.md §3.1 / §8 Step 5) ─────────────────────────
// A CUSTOMER'S OWN VRM personal access token — never `VRM_ADMIN_TOKEN`
// (that's the `VrmFleet*` functions above). Mirrors `vrm_api/schemas.py`'s
// `VrmLink*`/`VrmSyncRequest` models field-for-field, same "restated, not
// re-derived" convention as `SiteFieldsIn`. Every function here takes
// `customer_id` explicitly rather than reading it from anywhere implicit —
// callers (route handlers under `app/api/vrm/*`) MUST always pass
// `session.customerId`, never a value out of the request body (§3.2 control
// 1 restated one layer down from `SiteFieldsIn`'s own callers).

export type VrmInstallationOut = {
  id_site: number;
  name: string | null;
  identifier: string | null;
};

/** `POST /v1/vrm-link/validate`'s response — writes NOTHING to Postgres or
 * Vault (PLAN_PHASE15.md §3.1 step 1). No field here can carry the token
 * back out — see `vrm_api/schemas.py:VrmLinkValidateOut`'s own docstring. */
export type VrmLinkValidateOut = {
  vrm_user_id: string;
  vrm_account_email: string | null;
  installations: VrmInstallationOut[];
};

export async function vrmLinkValidate(body: { customer_id: string; token: string }): Promise<VrmLinkValidateOut> {
  return pipelineJson('/v1/vrm-link/validate', jsonInit(body));
}

/** One customer decision from §3.1 step 2's mapping UI — "ignore" is simply
 * omitting an installation from the `mappings` array sent to `vrmLinkConnect()`,
 * mirroring `vrm_api/schemas.py:VrmLinkMapping`'s own docstring. `site_name_or_id`
 * reuses `IngestPreviewRequest`'s ambiguous-by-design field: an existing
 * site's `site_id`, or a new site's display name. */
export type VrmLinkMapping = {
  vrm_installation_id: number;
  site_name_or_id: string;
  site_fields?: SiteFieldsIn;
};

export type VrmLinkSiteResult = {
  vrm_installation_id: number;
  site_id: string;
  site_is_existing: boolean;
};

export type VrmLinkConnectOut = {
  vrm_user_id: string;
  vrm_account_email: string | null;
  sites: VrmLinkSiteResult[];
};

export async function vrmLinkConnect(body: {
  customer_id: string;
  token: string;
  mappings: VrmLinkMapping[];
}): Promise<VrmLinkConnectOut> {
  return pipelineJson('/v1/vrm-link/connect', jsonInit(body));
}

export type VrmLinkDisconnectOut = { sites_reverted: number };

export async function vrmLinkDisconnect(customerId: string): Promise<VrmLinkDisconnectOut> {
  return pipelineJson('/v1/vrm-link/disconnect', jsonInit({ customer_id: customerId }));
}

export type VrmLinkSiteStatus = {
  site_id: string;
  display_name: string;
  vrm_last_synced_at: string | null;
  vrm_last_sync_error: string | null;
  vrm_sync_enabled: boolean;
};

/** `GET /v1/vrm-link/status`'s response — connection STATE only, never a
 * token (PLAN_PHASE15.md §2.5 rule 2; see `VrmLinkStatusOut`'s own docstring
 * in `vrm_api/schemas.py` — no field here could carry one by construction). */
export type VrmLinkStatusOut = {
  connected: boolean;
  vrm_account_email: string | null;
  connected_since: string | null;
  token_revoked_at: string | null;
  token_last_error: string | null;
  sites: VrmLinkSiteStatus[];
};

export async function vrmLinkStatus(customerId: string): Promise<VrmLinkStatusOut> {
  const params = new URLSearchParams({ customer_id: customerId });
  return pipelineJson(`/v1/vrm-link/status?${params}`, { method: 'GET' });
}

/**
 * `POST /v1/vrm-sync` — a customer's own connected site, synced with THEIR
 * OWN stored token (read fresh, per run, inside `vrm_api` — never sent
 * through this module). `site_id` here is only ever safe to call with once
 * the caller has already run `assertOwnsSite(customer_id, site_id)` — this
 * function does not check that itself (same division of responsibility as
 * `ingestPreview()` above); `vrm_api`'s own `tenancy.assert_owns_site()`
 * re-derives the same fact independently regardless (§3.2 control 3's
 * enforcement point lives there, not here).
 */
export async function vrmSync(body: {
  customer_id: string;
  site_id: string;
  start: string;
  end: string;
}): Promise<{ job_id: string }> {
  return pipelineJson('/v1/vrm-sync', jsonInit(body));
}

// ── Billing (PLAN_PHASE16.md §5.1-5.3 / §8 Step 5) ──────────────────────
// Mirrors `vrm_api/schemas.py`'s `Billing*` models field-for-field, same
// "restated, not re-derived" convention as `VrmLink*`/`SiteFieldsIn` above.
// Every function takes `customer_id` explicitly — callers (route handlers
// under `app/api/billing/*`) MUST always pass `session.customerId`, never a
// value out of the request body (§6.4 control 1, restated one layer down).
//
// No `onvo_subscription_id`/`onvo_customer_id` is ever read OUT of a
// `BillingStatusOut` — that type doesn't carry one (§5.1: "the browser has
// no legitimate use for it"). The two exceptions, `BillingSubscribeOut` and
// `BillingPaymentMethodSessionOut`, exist ONLY because the ONVO web SDK
// genuinely needs `onvo_subscription_id`/`onvo_customer_id` to render
// against (§5.2 step 5) — and even those never carry a `paymentMethodId`
// the browser didn't already create itself directly against ONVO
// (§0.2b finding 7).

/** `GET /v1/billing/status`'s response (§5.1) — mirrors
 * `vrm_api/schemas.py:BillingStatusOut` field-for-field. The common "fresh
 * state" shape every mutation function below also returns, since every
 * `vrm_api` billing mutation ends in its own `reconcile_customer()` call and
 * returns this same shape (§4.4's post-mutation trigger) — the browser never
 * has to guess what changed from a request it just made. */
export type BillingStatusOut = {
  customer_id: string;
  plan_key: string | null;
  plan_label_key: string | null;
  billing_status: string | null;
  provisioning_state: string;
  status: string | null;
  billing_interval: string | null;
  currency: string | null;
  amount_minor: number | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  trial_end: string | null;
  pm_brand: string | null;
  pm_last4: string | null;
  pm_exp_month: number | null;
  pm_exp_year: number | null;
  billing_address: BillingAddressIn;
  site_limit: number | null;
  active_sites: number;
  over_limit: boolean;
};

export async function billingStatus(customerId: string): Promise<BillingStatusOut> {
  const params = new URLSearchParams({ customer_id: customerId });
  return pipelineJson(`/v1/billing/status?${params}`, { method: 'GET' });
}

/** One `vrm.plans` row (§5.1) — mirrors `BillingPlanOut`. Deliberately no
 * `onvo_product_id`/`onvo_price_id` (that model's own docstring: no reason
 * for even an authenticated browser to hold a map of our ONVO catalogue). */
export type BillingPlanOut = {
  id: string;
  plan_key: string;
  plan_label_key: string;
  billing_interval: string;
  currency: string;
  amount_minor: number;
  site_limit: number | null;
  self_serve: boolean;
  is_current: boolean;
};

export async function billingPlans(customerId: string): Promise<{ plans: BillingPlanOut[] }> {
  const params = new URLSearchParams({ customer_id: customerId });
  return pipelineJson(`/v1/billing/plans?${params}`, { method: 'GET' });
}

export type BillingInvoiceOut = {
  id: string;
  status: string | null;
  currency: string | null;
  total_minor: number | null;
  subtotal_minor: number | null;
  original_total_minor: number | null;
  period_start: string | null;
  period_end: string | null;
  attempt_count: number | null;
  last_payment_attempt: string | null;
  next_payment_attempt: string | null;
};

export type BillingInvoicesOut = { invoices: BillingInvoiceOut[]; has_more: boolean };

export async function billingInvoices(
  customerId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<BillingInvoicesOut> {
  const params = new URLSearchParams({ customer_id: customerId });
  if (opts.limit !== undefined) params.set('limit', String(opts.limit));
  if (opts.offset !== undefined) params.set('offset', String(opts.offset));
  return pipelineJson(`/v1/billing/invoices?${params}`, { method: 'GET' });
}

/** `POST /v1/billing/subscription`'s body (§5.2, corrected at Step 5,
 * 2026-08-20 — see `vrm_api/routers/billing.py:post_subscription()`'s own
 * docstring for the full "why"). `plan_id` is OUR OWN `vrm.plans.id` —
 * never an ONVO `priceId` (§6.4). There is deliberately NO
 * `payment_method_id` here: the ONVO subscription this call creates comes
 * back with NO card attached at all — the SDK widget that collects the
 * card needs the returned `onvo_subscription_id` to render in the first
 * place, so a browser cannot possibly hold a `payment_method_id` before
 * calling this. `PaymentMethodPanel.tsx` renders the SDK widget AGAINST
 * this response, and the card is attached afterward by the widget itself,
 * only ever confirmed by a subsequent `POST /api/billing/refresh`. */
export async function billingSubscribe(body: {
  customer_id: string;
  plan_id: string;
}): Promise<{ onvo_subscription_id: string; onvo_customer_id: string; publishable_key: string }> {
  return pipelineJson('/v1/billing/subscription', jsonInit(body));
}

/** `POST /v1/billing/subscription/change` (§5.3, Q3 final: cancel-and-
 * restart, no proration, both directions immediate). `confirm` is the
 * over-site-limit guard's second call — see `BillingChangeRequest`'s own
 * docstring in `vrm_api/schemas.py`. */
export async function billingChange(body: {
  customer_id: string;
  plan_id: string;
  confirm?: boolean;
}): Promise<BillingStatusOut> {
  return pipelineJson('/v1/billing/subscription/change', jsonInit(body));
}

/** `POST /v1/billing/subscription/cancel` (§5.3, Q4). `mode: 'immediate'`
 * is a real, tenancy-checked `vrm_api` capability but has no customer-facing
 * caller in this app (Q4: graceful-only in v1's UI) — Step 6 (admin) is
 * expected to be the only thing that ever sends it. */
export async function billingCancel(body: {
  customer_id: string;
  mode: 'at_period_end' | 'immediate';
}): Promise<BillingStatusOut> {
  return pipelineJson('/v1/billing/subscription/cancel', jsonInit(body));
}

export async function billingResume(customerId: string): Promise<BillingStatusOut> {
  return pipelineJson('/v1/billing/subscription/resume', jsonInit({ customer_id: customerId }));
}

/** `POST /v1/billing/payment-method/session` (§5.3, corrected at Step 5,
 * 2026-08-20 alongside `billingSubscribe()`) — the REPLACE-CARD path for a
 * customer who ALREADY has a live subscription (first-time subscribe gets
 * its `onvo_subscription_id` straight from `billingSubscribe()` and never
 * calls this). Hands back the customer's current live `onvo_subscription_id`
 * — the SDK widget needs that real id to render a working card form,
 * exactly like first-time subscribe does. Throws (via `toErrorResponse()`'s
 * `no_active_subscription` code) if the customer has no live subscription
 * to attach a new card to — see
 * `vrm_api/routers/billing.py:post_payment_method_session()`'s own
 * docstring. */
export async function billingPaymentMethodSession(
  customerId: string,
): Promise<{ onvo_subscription_id: string; onvo_customer_id: string; publishable_key: string }> {
  return pipelineJson('/v1/billing/payment-method/session', jsonInit({ customer_id: customerId }));
}

/** `POST /v1/billing/payment-method` (§5.3) — attaches an already-known
 * `payment_method_id` to the customer's current subscription, re-verified
 * server-side before being trusted. NOT part of the corrected SDK-widget
 * flow (§5.2 point 3 / §5.3, Step 5 2026-08-20): the widget itself attaches
 * a newly-entered card to the `subscriptionId` it was given, and this app
 * only ever learns that happened via `billingRefresh()` — see
 * `vrm_api/schemas.py:BillingPaymentMethodRequest`'s own docstring. Kept
 * here as a lower-level primitive; not currently called by any route in
 * this app. */
export async function billingPaymentMethod(body: {
  customer_id: string;
  payment_method_id: string;
}): Promise<BillingStatusOut> {
  return pipelineJson('/v1/billing/payment-method', jsonInit(body));
}

/** ONVO's own billing-address shape (`billing.address` on a payment method),
 * mirrored field-for-field from `vrm_api/schemas.py:BillingAddressIn`. */
export type BillingAddressIn = {
  city?: string | null;
  country?: string | null;
  line1?: string | null;
  line2?: string | null;
  postalCode?: string | null;
  state?: string | null;
};

export async function billingAddress(body: {
  customer_id: string;
  address: BillingAddressIn;
}): Promise<BillingStatusOut> {
  return pipelineJson('/v1/billing/address', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

/** `POST /v1/billing/refresh` (§5.3) — a plain reconcile, what the browser
 * calls after the SDK's own `onSuccess` fires (§5.2: "a hint to refresh,
 * never a state change"). Rate-limited per customer by the route handler
 * that calls this (§6.5) — this function itself has no rate limit of its
 * own, matching `vrm_api`'s own division of responsibility. */
export async function billingRefresh(customerId: string): Promise<BillingStatusOut> {
  return pipelineJson('/v1/billing/refresh', jsonInit({ customer_id: customerId }));
}

// ── Billing webhook intake (PLAN_PHASE16.md §4.1, §4.2, §6.5) ───────────
// Called ONLY from `app/api/webhooks/onvo/route.ts`, and ONLY after that
// route has already verified `X-Webhook-Secret` in constant time and
// rate-limited the request — see that route's own header comment.
// `secret_ok` is always `true` on this path (a rejected secret never
// reaches this function at all; the route writes its own
// `vrm.billing_events` row directly via `getSupabaseAdmin()` for that
// case, per `vrm_api/schemas.py:BillingWebhookEventRequest`'s own
// docstring). Mirrors that schema field-for-field, same "restated, not
// re-derived" convention as every other function in this module.
export async function billingWebhookEvent(body: { secret_ok: true; payload: Record<string, unknown> }): Promise<{ ok: boolean }> {
  return pipelineJson('/v1/billing/webhook-event', jsonInit(body));
}

// ── Scheduled reports (PLAN_PHASE17.md §3.4, §8 Step 6/7) ───────────────
// `POST /v1/reports/run-due` is the scheduled-reports fan-out — normally
// called by `.github/workflows/scheduled-reports.yml` (Step 9, not built
// yet), never by a browser. The ONLY caller in this app is the
// `/admin/activity` "Run due now" button, gated by `requireAdminForRoute()`
// one layer up (`app/api/admin/pipeline/reports/run-due/route.ts`) — the
// same manual-spot-check affordance `workflow_dispatch:` gives the GitHub
// Actions side.
export type ReportRunDueResult = { site_id: string; status: string; error?: string | null };
export type ReportsRunDueOut = { sites_checked: number; processed: number; remaining: number; results: ReportRunDueResult[] };

export async function reportsRunDue(maxSites = 10): Promise<ReportsRunDueOut> {
  return pipelineJson('/v1/reports/run-due', jsonInit({ max_sites: maxSites }));
}
