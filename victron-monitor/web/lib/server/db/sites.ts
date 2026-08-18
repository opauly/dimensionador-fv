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
import { NotAuthorized } from './errors';
import type { SiteRecord } from './types';

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
] as const;

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
 */
export async function createSite(
  customerId: string,
  displayName: string,
  fields: CreateSiteFields = {},
): Promise<SiteRecord> {
  const customer = await getCustomer(customerId);
  const siteId = makeSiteId(customer.slug, slugify(displayName));
  const payload = pickWhitelisted(fields as Record<string, unknown>, SITE_WHITELIST as readonly string[]);

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
