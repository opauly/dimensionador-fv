import 'server-only';

// Site-record half of the tenant-scoping choke point (PLAN_PHASE14.md §1.2
// rule 4 / §2 Step 4). Every function here takes `customerId` first, and
// every function that reaches a *specific* site does it through
// `assertOwnsSite()` rather than trusting a `site_id` a caller already
// filtered client-side — "the dropdown is UI; the guard is the control"
// (§1.12 rule 3), which is exactly what `scripts/test-scoping.ts` exists to
// keep true.
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { slugify, makeSiteId } from '@/lib/slug';
import { getCustomer } from './customers';
import { getWhiteLabelAllowed } from './reportLimits';
import { NotAuthorized } from './errors';
import type { CustomerRecord, SiteRecord } from './types';

/**
 * Throws `NotAuthorized` unless `siteId` belongs to `customerId`. This is
 * the one query every other site-scoped function in this file routes
 * through — a single place to get the tenancy predicate right, rather than
 * repeating `.eq('customer_id', ...).eq('site_id', ...)` at every call site
 * and risking one of them drifting (e.g. a copy-pasted query that forgot
 * the `customer_id` filter).
 */
export async function assertOwnsSite(customerId: string, siteId: string): Promise<void> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select('id')
    .eq('customer_id', customerId)
    .eq('site_id', siteId)
    .limit(1);
  if (error) throw error;
  if (!data || data.length === 0) {
    throw new NotAuthorized(`Customer ${customerId} does not own site ${siteId}.`);
  }
}

export async function listSites(
  customerId: string,
  opts: { activeOnly?: boolean } = {},
): Promise<SiteRecord[]> {
  let query = getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select('*')
    .eq('customer_id', customerId)
    .order('display_name');
  if (opts.activeOnly) query = query.eq('active', true);
  const { data, error } = await query;
  if (error) throw error;
  return (data ?? []) as SiteRecord[];
}

export async function getSite(customerId: string, siteId: string): Promise<SiteRecord> {
  await assertOwnsSite(customerId, siteId);
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select('*')
    .eq('site_id', siteId)
    .single();
  if (error) throw error;
  return data as SiteRecord;
}

// ── The site whitelist, enforced twice — same shape as
// `customers.ts:ProfileUpdateFields`, see that file's header comment for
// the full reasoning (type-level Pick + runtime pickWhitelisted). Never
// `customer_id` (that would let a customer move a site to another tenant),
// `site_id` (the site's identity), `vrm_installation_id` (VRM-sync-owned),
// or `battery_usable_kwh` — that one is GENERATED (migration 019) and
// Postgres would reject the write outright even if it slipped through this
// whitelist, but the whitelist genuinely excludes it rather than leaning on
// that as the real defence (PLAN_PHASE14.md is explicit that this must not
// be the only thing catching a mistake here).
// PLAN_PHASE17.md §3/§5.3/§8 Step 7 — the five schedule columns joined
// this whitelist. `report_schedule*` writes get a SECOND, independent check
// below (`assertScheduleAllowed()`) beyond just being whitelisted: §3.1
// point 2 requires that a non-`vrm_api` site's schedule can never be
// written from here, server-side, regardless of what `SiteForm.tsx` shows
// — "hide an editor is UX, never the control," restated for this feature.
const SITE_WHITELIST = [
  'display_name',
  'pv_kwp',
  'battery_nominal_kwh',
  'battery_dod_pct',
  'system_type',
  'report_language',
  'location',
  'timezone',
  'latitude',
  'longitude',
  'country',
  'savings_rate',
  'savings_currency',
  'exports_to_grid',
  'active',
  'report_schedule',
  'report_schedule_weekday',
  'report_schedule_day_of_month',
  'report_schedule_hour',
  'report_recipients',
  'report_modules',
] as const;

// PLAN_PHASE17.md §0.6 Q5 (Oscar's decision, 2026-08-25: third-party
// recipients allowed, capped at 5 per site) / §8 Step 8. Enforced HERE,
// server-side, independent of `SiteForm.tsx`'s own client-side cap — "hide
// an editor is UX, never the control," restated for a numeric limit rather
// than a boolean gate. `vrm_api/report_delivery.py:MAX_RECIPIENTS` is the
// same number, independently enforced a second time at send time (that
// module's own docstring: the database value is never trusted alone).
export const MAX_REPORT_RECIPIENTS = 5;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export type SiteUpdateFields = Partial<Pick<SiteRecord, (typeof SITE_WHITELIST)[number]>>;

function pickWhitelisted<T extends Record<string, unknown>>(
  fields: T,
  allowed: readonly (keyof T)[],
): Partial<T> {
  const allowedSet = new Set<keyof T>(allowed);
  const out: Partial<T> = {};
  for (const key of Object.keys(fields) as (keyof T)[]) {
    if (allowedSet.has(key)) out[key] = fields[key];
  }
  return out;
}

/** PLAN_PHASE17.md §3.1 point 2 / §0.7 — thrown when a write would set
 * `report_schedule` to anything but `'off'` on a `source='csv_upload'`
 * site. This is enforcement layer 2 of 3 (migration 026's own CHECK
 * constraint is layer 1; `SiteForm.tsx` not rendering the cadence fields
 * for a CSV site at all is layer 3, UX only). Independent of the UI: a
 * tampered request body reaches this check regardless of what any form
 * shows. */
export class ScheduleRequiresVrmApi extends Error {
  constructor() {
    super('A report schedule can only be set on a site connected via the VRM API.');
    this.name = 'ScheduleRequiresVrmApi';
  }
}

function schedulingRequested(payload: Record<string, unknown>): boolean {
  return 'report_schedule' in payload && payload.report_schedule !== 'off';
}

/** PLAN_PHASE17.md §0.6 Q5 / §8 Step 8 — caps `report_recipients` at
 * `MAX_REPORT_RECIPIENTS` and drops anything that doesn't look like an
 * email, rather than rejecting the whole write. A malformed value already
 * saved before this check existed, or a value a tampered request tried to
 * sneak past the client-side cap, must not become a 500 — it just never
 * lands. Mutates nothing if the field isn't present in `payload` at all. */
function sanitizeRecipients(payload: Record<string, unknown>): void {
  if (!('report_recipients' in payload)) return;
  const raw = payload.report_recipients;
  const list = Array.isArray(raw) ? raw : [];
  payload.report_recipients = list
    .filter((e): e is string => typeof e === 'string' && EMAIL_RE.test(e.trim()))
    .map((e) => e.trim())
    .slice(0, MAX_REPORT_RECIPIENTS);
}

// PLAN_PHASE18.md's Decisions section (originally 9 ids, migration 028) plus
// §7's Phase 2 additions (migration 029) — same 13 ids `victron/weekly_
// report.py:ALL_MODULES` and migration 029's widened CHECK constraint use.
// Duplicated here rather than shared across the language boundary, same
// call every other tenancy-adjacent check in this codebase already makes
// (this file's own SITE_WHITELIST restatement in lib/server/db/admin.ts,
// for one).
export const REPORT_MODULES = [
  'energy_mix', 'battery_health', 'grid_quality', 'events',
  'soc_chart', 'solar_performance', 'weather', 'trend', 'savings',
  'critical_alerts', 'grid_meter_detail', 'generator_runtime', 'tank_level',
] as const;
const REPORT_MODULES_SET = new Set<string>(REPORT_MODULES);

// Same denylist branding.ts / vrm_api/report_modules.py use — a denylist ON
// PURPOSE, so a legacy hand-created customer with billing_status='none'
// isn't accidentally excluded by a naive allowlist.
const NOT_ENTITLED_STATUSES = new Set(['incomplete', 'unpaid', 'canceled']);

/** Whether `/app/sites`' per-site edit form should show the module
 * checklist (`true`) or hide it entirely (`false`) for this customer — and
 * the same check `updateSite()` uses to decide whether a `report_modules`
 * write actually lands. Mirrors `branding.ts:getBrandingAccess()` exactly:
 * same tier/account-type population, reusing the same `white_label`
 * plan_limits flag rather than a second identically-seeded column (both
 * features are scoped to the same real population — an installer curating
 * what THEIR clients see). Duplicated rather than imported from
 * branding.ts, same reasoning that file's own header comment gives for
 * never importing `db/admin.ts`. */
export async function getReportModulesAccess(customer: CustomerRecord): Promise<boolean> {
  if (customer.account_type !== 'installer') return false;
  if (!customer.active) return false;
  if (customer.provisioning_state !== 'active') return false;
  if (customer.billing_status && NOT_ENTITLED_STATUSES.has(customer.billing_status)) return false;
  return getWhiteLabelAllowed(customer.plan);
}

/** Filters `report_modules` down to known ids only (a stale/renamed id, or
 * a tampered request, never reaches the database) and — the real control,
 * not just client-side hiding — drops the field entirely for a customer
 * `getReportModulesAccess()` says isn't entitled, rather than failing the
 * whole update. `updateSite()` handles many unrelated fields in one call;
 * silently ignoring the one field this customer can't use matches
 * `sanitizeRecipients()`'s own "never a 500 over this" shape, not
 * `ScheduleRequiresVrmApi`'s "reject the write" shape — there is no invalid
 * *state* being prevented here, only an entitlement a UI should not have
 * offered in the first place. */
async function sanitizeReportModules(payload: Record<string, unknown>, customerId: string): Promise<void> {
  if (!('report_modules' in payload)) return;
  const customer = await getCustomer(customerId);
  if (!(await getReportModulesAccess(customer))) {
    delete payload.report_modules;
    return;
  }
  const raw = payload.report_modules;
  const list = Array.isArray(raw) ? raw : [];
  const valid = list.filter((m): m is string => typeof m === 'string' && REPORT_MODULES_SET.has(m));
  payload.report_modules = valid.length > 0 ? valid : null;
}

export async function updateSite(
  customerId: string,
  siteId: string,
  fields: SiteUpdateFields,
): Promise<SiteRecord> {
  // First statement: the same rule §1.2 rule 4 states for pages/route
  // handlers applies here too, one layer down — a caller that already
  // filtered its dropdown to the customer's own sites still gets this
  // check for free, and a caller that didn't (a tampered request body) gets
  // stopped here instead of writing another tenant's row.
  await assertOwnsSite(customerId, siteId);

  const payload = pickWhitelisted(fields as Record<string, unknown>, SITE_WHITELIST as readonly string[]);
  if (Object.keys(payload).length === 0) {
    return getSite(customerId, siteId);
  }
  sanitizeRecipients(payload);
  // Only pays for the extra customer read when report_modules is actually
  // part of this write — a plain field edit that never touches it skips
  // this entirely.
  await sanitizeReportModules(payload, customerId);

  // Only pays for the extra read when a schedule is actually being turned
  // on — a plain field edit on an already-'off' site never hits this.
  if (schedulingRequested(payload)) {
    const { data: sourceRow, error: sourceError } = await getSupabaseAdmin()
      .schema('vrm')
      .from('sites')
      .select('source')
      .eq('site_id', siteId)
      .single();
    if (sourceError) throw sourceError;
    if (sourceRow.source !== 'vrm_api') throw new ScheduleRequiresVrmApi();
  }

  // `.select('*')` after `.update()` returns the post-write row in the same
  // round trip, including `battery_usable_kwh` — Postgres recomputes a
  // GENERATED STORED column synchronously as part of the UPDATE itself, so
  // there is no separate re-fetch needed to see the new usable-kWh figure
  // after a nominal/DoD edit.
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .update(payload)
    .eq('site_id', siteId)
    .select('*')
    .single();
  if (error) throw error;
  return data as SiteRecord;
}

/** Counts *active* sites against `site_limit` — a customer who deactivates
 * a retired site frees up the slot for a new one without calling Oscar,
 * which is the whole point of `active` existing on `vrm.sites` as a soft
 * delete rather than a hard one (history stays queryable either way). */
export async function siteCount(customerId: string): Promise<number> {
  const { count, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select('id', { count: 'exact', head: true })
    .eq('customer_id', customerId)
    .eq('active', true);
  if (error) throw error;
  return count ?? 0;
}

export type CanAddSiteResult = { ok: true } | { ok: false; reason: 'site_limit_reached' };

/**
 * `site_limit === null` means unlimited — migration 021's own column
 * comment states this explicitly ("NULL = unlimited (the 'fleet' plan)").
 * `reason` is a string-table *key*, not prose, so `app/(portal)/app/sites`
 * can render it through `t(lang, reason)` rather than this server-only
 * module baking English or Spanish copy into a `NotAuthorized`-adjacent
 * value that a bilingual page then has no way to translate.
 */
export async function canAddSite(customerId: string): Promise<CanAddSiteResult> {
  const customer = await getCustomer(customerId);
  if (customer.site_limit === null) return { ok: true };
  const count = await siteCount(customerId);
  if (count < customer.site_limit) return { ok: true };
  return { ok: false, reason: 'site_limit_reached' };
}

export type CreateSiteFields = SiteUpdateFields;

/**
 * Creates a new site under the caller's *own* tenant — the TS analogue of
 * `victron/ingest.py:upsert_site()`, but deliberately narrower: it never
 * takes a `customer_id` argument from anywhere but the trusted session, and
 * it derives `site_id` from the customer's own `slug` rather than accepting
 * one, so a customer can never create or address another tenant's
 * namespace (§1.12 rule 1's "never call `upsert_customer()` from a
 * customer-initiated path" extends to never letting a customer pick their
 * own `site_id` prefix either).
 *
 * Callers MUST check `canAddSite()` first — this function does not enforce
 * `site_limit` itself, the same division of responsibility
 * `PLAN_PHASE13.md §2 Step 3`'s original design used (the UI decides
 * whether to show the form at all; this is just the write).
 *
 * PLAN_PHASE17.md §3.1/§0.7 — this function ALWAYS creates a
 * `source='csv_upload'` site (there is no `source` field in
 * `CreateSiteFields`/`SITE_WHITELIST` — a `vrm_api`-sourced site is only
 * ever created by `vrm_api/routers/vrm_link.py:post_connect()`, which
 * applies `default_report_schedule` itself, on the Python side). A
 * `report_schedule` in `fields` is therefore always rejected here, the same
 * `ScheduleRequiresVrmApi` a tampered `updateSite()` call gets — never
 * silently dropped, and never silently accepted for a site this function
 * cannot create as anything but `csv_upload`.
 */
export async function createSite(
  customerId: string,
  displayName: string,
  fields: CreateSiteFields = {},
): Promise<SiteRecord> {
  const customer = await getCustomer(customerId);
  const siteId = makeSiteId(customer.slug, slugify(displayName));
  const payload = pickWhitelisted(fields as Record<string, unknown>, SITE_WHITELIST as readonly string[]);
  if (schedulingRequested(payload)) throw new ScheduleRequiresVrmApi();
  sanitizeRecipients(payload);

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .insert({
      customer_id: customerId,
      site_id: siteId,
      display_name: displayName,
      ...payload,
    })
    .select('*')
    .single();
  if (error) throw error;
  return data as SiteRecord;
}

export type BulkScheduleFields = Pick<
  SiteRecord,
  'report_schedule' | 'report_schedule_weekday' | 'report_schedule_day_of_month' | 'report_schedule_hour'
>;

/**
 * "Apply this schedule to all my sites" (PLAN_PHASE17.md §3.7) — one write
 * targeting every ACTIVE `source='vrm_api'` site this customer owns. Never
 * touches a `csv_upload` site (§0.7 makes that write invalid regardless;
 * this function simply never attempts it, by filtering the query rather
 * than relying on `updateSite()`'s own rejection to catch it one row at a
 * time). Returns the number of sites actually updated — `0` is a legitimate
 * outcome (a customer with no `vrm_api` sites yet) and the caller should
 * say so, not treat it as an error.
 */
export async function applyScheduleToAllSites(customerId: string, fields: BulkScheduleFields): Promise<number> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .update(fields)
    .eq('customer_id', customerId)
    .eq('source', 'vrm_api')
    .eq('active', true)
    .select('site_id');
  if (error) throw error;
  return (data ?? []).length;
}

/** Read-only count of this customer's ACTIVE `vrm_api` sites — what the
 * bulk action's Cap B projection (§2.2 "moment 1") multiplies the chosen
 * cadence's per-site estimate by, before anything is saved. */
export async function countSchedulableSites(customerId: string): Promise<number> {
  const { count, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select('id', { count: 'exact', head: true })
    .eq('customer_id', customerId)
    .eq('source', 'vrm_api')
    .eq('active', true);
  if (error) throw error;
  return count ?? 0;
}
