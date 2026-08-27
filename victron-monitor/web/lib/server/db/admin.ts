import 'server-only';

// ══════════════════════════════════════════════════════════════════════
// ADMIN-ONLY — nothing in this module is tenant-scoped.
//
// Only code under `app/(admin)/admin/**` may import this file. That is a
// convention enforced by this comment and code review, the same way
// `vrm_portal/admin_db.py`'s module docstring enforced it in the Streamlit
// original (PLAN_PHASE13.md §1.6) — there is no build-time mechanism (an
// ESLint boundary rule, a separate package) stopping `app/(portal)/app/**`
// from importing it too. Being honest about that here rather than
// implying a guarantee that doesn't exist: every function below takes NO
// `customerId` argument and returns cross-customer data by design, so an
// accidental import into the customer surface is a real tenant-isolation
// bug, not a lint nit — read `lib/server/db/sites.ts` / `customers.ts`
// instead for anything reachable from `/app/*`.
// ══════════════════════════════════════════════════════════════════════
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { slugify } from '@/lib/slug';
import { planSiteLimit } from '@/lib/plans';
import type {
  AccountType,
  BillingEventRecord,
  CustomerRecord,
  Lang,
  SiteRecord,
  IngestionLogRecord,
  SignupRequestRecord,
} from './types';
import type { ReportRunRecord } from './reportRuns';

export type AdminCustomerRow = CustomerRecord & {
  siteCount: number;
  lastUploadAt: string | null;
  /** From the customer's current LIVE `vrm.subscriptions` row
   * (`canceled_at IS NULL`) — `null` for a customer with no live
   * subscription (never subscribed, or fully lapsed). Distinct from
   * `CustomerRecord.billing_status`, which is the entitlement writer's own
   * cache and carries no date (PLAN_PHASE16.md §8 Step 6: "plan, billing
   * status, next renewal date, whether a cancellation is pending"). */
  nextRenewalAt: string | null;
  /** `vrm.subscriptions.cancel_at_period_end` for the current live
   * subscription — `false` (not `null`) when there is no live subscription
   * at all, since "no cancellation is pending" is the correct reading of
   * that case too. */
  cancelPending: boolean;
};

/**
 * Every customer, with the derived figures every admin list in
 * `pages/06_vrm_monitor.py`'s `tab_sites()` shows inline (site count) or
 * that Step 7's `/admin/customers` needs ("last upload"), plus — as of
 * PLAN_PHASE16.md §8 Step 6 — each customer's current live subscription's
 * renewal date / cancel-pending flag. Computed here, once, rather than N+1
 * queries per row from the page.
 */
export async function listCustomers(): Promise<AdminCustomerRow[]> {
  const admin = getSupabaseAdmin();

  const { data: customers, error: customersError } = await admin
    .schema('vrm')
    .from('customers')
    .select('*')
    .order('name');
  if (customersError) throw customersError;

  const { data: sites, error: sitesError } = await admin.schema('vrm').from('sites').select('site_id, customer_id');
  if (sitesError) throw sitesError;

  const siteRows = (sites ?? []) as { site_id: string; customer_id: string }[];
  const customerIdBySite = new Map(siteRows.map((s) => [s.site_id, s.customer_id]));
  const siteCountByCustomer = new Map<string, number>();
  for (const s of siteRows) {
    siteCountByCustomer.set(s.customer_id, (siteCountByCustomer.get(s.customer_id) ?? 0) + 1);
  }

  // `ingestion_log` has no `customer_id` column (see `ingestions.ts`'s own
  // comment) — map through `site_id` the same way, then keep only the
  // newest timestamp seen per customer instead of loading full history.
  const { data: logs, error: logsError } = await admin
    .schema('vrm')
    .from('ingestion_log')
    .select('site_id, uploaded_at')
    .order('uploaded_at', { ascending: false });
  if (logsError) throw logsError;

  const lastUploadByCustomer = new Map<string, string>();
  for (const log of (logs ?? []) as { site_id: string; uploaded_at: string }[]) {
    const customerId = customerIdBySite.get(log.site_id);
    if (!customerId) continue;
    // Rows arrived newest-first, so the first one seen per customer is the
    // most recent — no need to compare timestamps.
    if (!lastUploadByCustomer.has(customerId)) lastUploadByCustomer.set(customerId, log.uploaded_at);
  }

  // The current LIVE subscription per customer only (`canceled_at IS
  // NULL`) — migration 025's own partial unique index means there is at
  // most one, so no "most recent wins" tie-break is needed here the way
  // `vrm_api/billing.py:_current_mirror_subscription()` needs one for its
  // broader "current, possibly lapsed" reading.
  const { data: subs, error: subsError } = await admin
    .schema('vrm')
    .from('subscriptions')
    .select('customer_id, current_period_end, cancel_at_period_end')
    .is('canceled_at', null);
  if (subsError) throw subsError;

  const liveSubByCustomer = new Map(
    ((subs ?? []) as { customer_id: string; current_period_end: string | null; cancel_at_period_end: boolean }[]).map(
      (s) => [s.customer_id, s],
    ),
  );

  return ((customers ?? []) as CustomerRecord[]).map((c) => {
    const liveSub = liveSubByCustomer.get(c.id);
    return {
      ...c,
      siteCount: siteCountByCustomer.get(c.id) ?? 0,
      lastUploadAt: lastUploadByCustomer.get(c.id) ?? null,
      nextRenewalAt: liveSub?.current_period_end ?? null,
      cancelPending: liveSub?.cancel_at_period_end ?? false,
    };
  });
}

export type CreateCustomerFields = {
  name: string;
  /** Defaults to `slugify(name)` — see `lib/slug.ts`. Only pass this to
   * override the derived slug (e.g. a name collision Oscar wants to
   * disambiguate by hand). */
  slug?: string;
  accountType: AccountType;
  plan: string;
  /** Overrides `lib/plans.ts:planSiteLimit(plan)`'s default for a
   * hand-negotiated deal — same "value on the row, not a recompute from
   * `plan` every time" reasoning migration 021's own comment gives. */
  siteLimit?: number | null;
  contactName?: string | null;
  contactEmail?: string | null;
  country?: string | null;
  uiLanguage?: Lang;
  /** The login email the create-customer form collects (PLAN_PHASE14.md
   * §2 Step 7: "login email" is one of the create-form's own fields,
   * separate from `contactEmail`). Written to `auth_email` at creation
   * time — NOT `auth_user_id`/`invited_at`, which stay null until
   * `lib/server/invites.ts:sendInvite()` actually generates and sends a
   * link. Storing the intended login email up front (rather than only
   * once an invite is sent) is what lets migration 021's own
   * case-insensitive unique index on `auth_email` catch a duplicate login
   * address at creation time, before Oscar has clicked "Enviar
   * invitación" and possibly confused two customers for a moment. */
  authEmail?: string | null;
};

/**
 * Creates a `vrm.customers` row. Deliberately does NOT touch
 * `auth_user_id`/`invited_at`/`activated_at` — those are invite-flow state,
 * stamped by `lib/server/invites.ts` (Step 7) once an email actually goes
 * out (or a password is actually set), not at row-creation time. A
 * customer can exist here with no login yet; that is the normal state
 * between "Oscar created the account" and "Oscar sent the invite." (Its own
 * `auth_email` — the *intended* login address — is the one exception; see
 * `CreateCustomerFields.authEmail`'s own comment.)
 */
export async function createCustomer(fields: CreateCustomerFields): Promise<CustomerRecord> {
  const slug = fields.slug ? slugify(fields.slug) : slugify(fields.name);
  const siteLimit = fields.siteLimit !== undefined ? fields.siteLimit : planSiteLimit(fields.plan);

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .insert({
      name: fields.name,
      slug,
      account_type: fields.accountType,
      plan: fields.plan,
      site_limit: siteLimit,
      contact_name: fields.contactName ?? null,
      contact_email: fields.contactEmail ?? null,
      country: fields.country ?? null,
      ui_language: fields.uiLanguage ?? 'en',
      auth_email: fields.authEmail ?? null,
    })
    .select('*')
    .single();
  if (error) throw error;
  return data as CustomerRecord;
}

// Everything an admin may legitimately change about a customer record
// after creation — the mirror image of `customers.ts:PROFILE_WHITELIST`,
// but wider on purpose (this is the surface *only* `/admin/*` reaches).
// Still excludes `slug` (the site_id namespace — changing it after sites
// exist would orphan every `site_id` already minted from it) and
// `auth_user_id`/`auth_email`/`invited_at`/`activated_at` (invite-flow
// state Step 7's `lib/server/invites.ts` owns, not a generic field edit).
const ADMIN_CUSTOMER_WHITELIST = [
  'name',
  'contact_name',
  'contact_email',
  'country',
  'ui_language',
  'account_type',
  'plan',
  'site_limit',
  'active',
  'notes',
  // PLAN_PHASE17.md §4.5 — so Oscar can set a Fleet customer's branding by
  // hand during onboarding. Untiered on purpose: an admin write bypasses
  // getBrandingAccess() entirely (this whitelist is the only gate on this
  // path), the same way every other admin override in this file already
  // does for site_limit/plan.
  'branding',
] as const;

export type AdminCustomerUpdateFields = Partial<Pick<CustomerRecord, (typeof ADMIN_CUSTOMER_WHITELIST)[number]>>;

export async function updateCustomer(
  customerId: string,
  fields: AdminCustomerUpdateFields,
): Promise<CustomerRecord> {
  const allowed = new Set<string>(ADMIN_CUSTOMER_WHITELIST);
  const payload: Record<string, unknown> = {};
  for (const key of Object.keys(fields)) {
    if (allowed.has(key)) payload[key] = (fields as Record<string, unknown>)[key];
  }
  if (Object.keys(payload).length === 0) {
    const { data, error } = await getSupabaseAdmin().schema('vrm').from('customers').select('*').eq('id', customerId).single();
    if (error) throw error;
    return data as CustomerRecord;
  }
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .update(payload)
    .eq('id', customerId)
    .select('*')
    .single();
  if (error) throw error;
  return data as CustomerRecord;
}

/** Deactivating a customer must not require deleting their auth user
 * (PLAN_PHASE13.md §1.5) — `resolveRole()` already rejects an inactive
 * customer at the same clean-rejection branch as an unlinked one, so
 * flipping this one column is the entire "revoke access" operation. */
export async function setActive(customerId: string, active: boolean): Promise<CustomerRecord> {
  return updateCustomer(customerId, { active });
}

export async function listAllSites(): Promise<SiteRecord[]> {
  const { data, error } = await getSupabaseAdmin().schema('vrm').from('sites').select('*').order('display_name');
  if (error) throw error;
  return (data ?? []) as SiteRecord[];
}

// Same field whitelist as `sites.ts:SITE_WHITELIST`, restated here rather
// than imported — that module's constant is a local, unexported `const`
// (each tenancy file in this directory keeps its own whitelist + its own
// `pickWhitelisted`, rather than sharing one; see `customers.ts`'s own
// comment on why the runtime filter matters independently of the type).
// Still excludes `customer_id`/`site_id` — reassignment is its own function
// below (`reassignSite`), a deliberate, explicit action rather than one
// more field in a generic update, the same "setActive() vs. a generic field
// edit" split this file already uses for `active`.
// The four schedule columns plus recipients joined this whitelist so an
// admin can see and fix a customer's own schedule directly, instead of
// walking them through re-doing it themselves — the same five columns
// `sites.ts:SITE_WHITELIST` carries, restated here for the same reason the
// rest of this whitelist is restated rather than imported (see this
// constant's own header comment above).
const ADMIN_SITE_WHITELIST = [
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
] as const;

export type AdminSiteUpdateFields = Partial<Pick<SiteRecord, (typeof ADMIN_SITE_WHITELIST)[number]>>;

function pickWhitelisted<T extends Record<string, unknown>>(fields: T, allowed: readonly (keyof T)[]): Partial<T> {
  const allowedSet = new Set<keyof T>(allowed);
  const out: Partial<T> = {};
  for (const key of Object.keys(fields) as (keyof T)[]) {
    if (allowedSet.has(key)) out[key] = fields[key];
  }
  return out;
}

// Same rule as `sites.ts:ScheduleRequiresVrmApi` / `sanitizeRecipients()` —
// restated here rather than imported (same reasoning as the whitelist
// above). This isn't a tenant-trust check being loosened for admin: a
// `source='csv_upload'` site has no live connection for a schedule to ever
// fire against, migration 026's own CHECK constraint rejects the write at
// the database level regardless of which app surface sent it, and an admin
// bypassing that here would just trade a clear error message for a raw
// Postgres constraint violation instead of actually enabling anything.
export class AdminScheduleRequiresVrmApi extends Error {
  constructor() {
    super('A report schedule can only be set on a site connected via the VRM API.');
    this.name = 'AdminScheduleRequiresVrmApi';
  }
}

const ADMIN_MAX_REPORT_RECIPIENTS = 5;
const ADMIN_EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function sanitizeRecipients(payload: Record<string, unknown>): void {
  if (!('report_recipients' in payload)) return;
  const raw = payload.report_recipients;
  const list = Array.isArray(raw) ? raw : [];
  payload.report_recipients = list
    .filter((e): e is string => typeof e === 'string' && ADMIN_EMAIL_RE.test(e.trim()))
    .map((e) => e.trim())
    .slice(0, ADMIN_MAX_REPORT_RECIPIENTS);
}

export async function getAnySite(siteId: string): Promise<SiteRecord> {
  const { data, error } = await getSupabaseAdmin().schema('vrm').from('sites').select('*').eq('site_id', siteId).single();
  if (error) throw error;
  return data as SiteRecord;
}

/** Cross-customer site edit — the admin-side counterpart of
 * `sites.ts:updateSite()`, minus the `assertOwnsSite()` call (there is no
 * "owns" check for an admin session; `/admin/sites` is allowed to touch any
 * customer's site by design). */
export async function updateAnySite(siteId: string, fields: AdminSiteUpdateFields): Promise<SiteRecord> {
  const payload = pickWhitelisted(fields as Record<string, unknown>, ADMIN_SITE_WHITELIST as readonly string[]);
  if (Object.keys(payload).length === 0) return getAnySite(siteId);
  sanitizeRecipients(payload);

  if ('report_schedule' in payload && payload.report_schedule !== 'off') {
    const { data: sourceRow, error: sourceError } = await getSupabaseAdmin()
      .schema('vrm')
      .from('sites')
      .select('source')
      .eq('site_id', siteId)
      .single();
    if (sourceError) throw sourceError;
    if (sourceRow.source !== 'vrm_api') throw new AdminScheduleRequiresVrmApi();
  }

  const { data, error } = await getSupabaseAdmin().schema('vrm').from('sites').update(payload).eq('site_id', siteId).select('*').single();
  if (error) throw error;
  return data as SiteRecord;
}

/**
 * Moves a site to a different customer — the one write `/admin/sites`
 * needs that has no customer-facing equivalent at all (§1.12 rule 1: a
 * customer must never create OR rename a tenant; reassigning a site to a
 * different tenant is the same class of action). `site_id` stays exactly as
 * it was minted (`<old-customer-slug>-<site-slug>`) — reassignment does not
 * re-namespace it, so `vrm.energy_daily`/`vrm.ingestion_log` history keeps
 * resolving to the same `site_id` after the move; only the ownership
 * pointer changes.
 */
export async function reassignSite(siteId: string, newCustomerId: string): Promise<SiteRecord> {
  // Fails loudly (not a silent FK violation surfaced as a generic Postgres
  // error) if `newCustomerId` doesn't name a real customer — same "must be
  // real" contract every other cross-entity write in this app enforces
  // before touching anything.
  const { data: customerRows, error: customerError } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .select('id')
    .eq('id', newCustomerId)
    .limit(1);
  if (customerError) throw customerError;
  if (!customerRows || customerRows.length === 0) {
    throw new Error(`No such customer ${newCustomerId}.`);
  }

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .update({ customer_id: newCustomerId })
    .eq('site_id', siteId)
    .select('*')
    .single();
  if (error) throw error;
  return data as SiteRecord;
}

export async function listAllIngestions(limit = 100): Promise<IngestionLogRecord[]> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('ingestion_log')
    .select('*')
    .order('uploaded_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as IngestionLogRecord[];
}

/**
 * `vrm.billing_events`, newest first (PLAN_PHASE16.md §3.5 / §8 Step 6) —
 * `/admin/activity`'s "Billing events" section, the only place in this
 * product an attempted webhook forgery (`secret_ok=false`) is ever visible
 * to a human (§7's failure-modes table, same row). Direct Postgres read,
 * same reasoning as `listCustomers()`'s new subscription join above — no
 * `vrm_api` bulk-read endpoint exists for this and none is needed.
 */
export async function listBillingEvents(limit = 100): Promise<BillingEventRecord[]> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('billing_events')
    .select('*')
    .order('received_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as BillingEventRecord[];
}

export type AdminSignupRow = SignupRequestRecord & {
  /** Computed HERE, once, server-side at read time — not by
   * `RecentSignupsPanel.tsx` itself, which is a Client Component and would
   * otherwise need to call `Date.now()` directly inside its render body (an
   * impure call React's own purity rule, `react-hooks/purity`, correctly
   * rejects — the same "derived figure computed once in this module"
   * pattern `listCustomers()`'s own `siteCount`/`lastUploadAt` already
   * use, for the same reason). `false` once `consumed_at` is set — an
   * already-redeemed row is never "expired," it succeeded. */
  expired: boolean;
};

/**
 * `vrm.signup_requests`, newest first (PLAN_PHASE16.md §3.7 / §8 Step 6) —
 * `/admin/activity`'s "Recent signups" panel, "the only place a signup
 * spam wave is visible before it shows up in the Resend bill" (§8 Step 6's
 * own framing). Deliberately never selects `token_hash` — that column
 * exists so a database dump is never a set of working account-creation
 * links (migration 025's own comment on that column), and this admin view
 * has no legitimate use for it either.
 */
export async function listRecentSignups(limit = 50): Promise<AdminSignupRow[]> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('signup_requests')
    .select('id, email, name, account_type, created_at, expires_at, consumed_at, customer_id')
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  const now = Date.now();
  return ((data ?? []) as SignupRequestRecord[]).map((row) => ({
    ...row,
    expired: !row.consumed_at && new Date(row.expires_at).getTime() < now,
  }));
}

/**
 * `vrm.report_runs`, newest first (PLAN_PHASE17.md §5.2 / §8 Step 7) —
 * `/admin/activity`'s recent-runs panel, the detection surface for "the
 * scheduled-reports cron silently stopped" (§0.5/§3.7). Same "no bulk
 * `vrm_api` endpoint exists for this and none is needed" reasoning
 * `listBillingEvents()` above already states for a different table — every
 * write to this table happens exclusively in `vrm_api/report_runs.py`,
 * nothing here ever inserts or updates a row.
 */
export async function listAllReportRuns(limit = 100): Promise<ReportRunRecord[]> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('report_runs')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as ReportRunRecord[];
}
