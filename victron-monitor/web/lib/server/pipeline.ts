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
 */
export class PipelineError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message?: string) {
    super(message ?? code);
    this.name = 'PipelineError';
    this.status = status;
    this.code = code;
  }
}

/** Route handlers call this after catching anything from this module;
 * returns `null` for errors that aren't this module's — the caller should
 * rethrow those (they're a real bug, not a pipeline-shaped failure). */
export function toErrorResponse(err: unknown): NextResponse | null {
  if (err instanceof PipelineError) {
    return NextResponse.json({ error: err.code }, { status: err.status });
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
    try {
      const body = (await res.json()) as { code?: string; detail?: string | { code?: string } };
      const nestedCode = typeof body.detail === 'object' && body.detail !== null ? body.detail.code : undefined;
      code = body.code ?? nestedCode ?? code;
    } catch {
      // No body, or not JSON — keep the generic code.
    }
    throw new PipelineError(res.status, code);
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
