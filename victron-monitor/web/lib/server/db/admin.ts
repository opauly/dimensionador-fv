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

// ══════════════════════════════════════════════════════════════════════
// Fleet overview (admin ops dashboard, 2026-08-30) — informed by a UCR
// capstone project's own requirements doc (a separate, standalone project
// Oscar is sponsoring with the same idea), built independently and now,
// against data this pipeline already computes. Every field below is read
// from an EXISTING table — no new migration, no new vrm_api endpoint.
// Same "no bulk-read endpoint exists for this, and none is needed" call
// `/admin/activity` (page.tsx's own comment) already makes for a
// cross-customer admin view: this queries Supabase directly from the
// Next.js server, the same way listAllSites()/listCustomers() above do,
// rather than adding a new FastAPI router just to proxy the same read.
export type FleetConnectionStatus = 'online' | 'stale' | 'never_synced';

export type FleetOverviewRow = {
  site_id: string;
  display_name: string;
  customer_id: string;
  customer_name: string;
  system_type: SiteRecord['system_type'];
  pv_kwp: number | null;
  battery_usable_kwh: number | null;
  vrm_last_synced_at: string | null;
  connection_status: FleetConnectionStatus;
  health_score: number | null;
  health_status: string | null;
  health_date: string | null;
  active_alarms: number;
  active_critical_alerts: number;
  // Fleet Dashboard Phase 2 (2026-08-30) — from `vrm.site_snapshots`
  // (migration 031), upserted by the ~15-minute `refresh-snapshots` sweep
  // (`vrm_api/routers/vrm_fleet.py`). `null` for every field, including
  // `live_captured_at`, means no snapshot has landed for this site yet —
  // never a fabricated 0, same "no data is better than fabricated data"
  // rule the whole pipeline already follows.
  live_captured_at: string | null;
  live_pv_power_w: number | null;
  live_load_power_w: number | null;
  live_battery_power_w: number | null;
  live_grid_power_w: number | null;
  live_soc_pct: number | null;
};

export type FleetOverview = {
  sites: FleetOverviewRow[];
  rollup: {
    site_count: number;
    online_count: number;
    avg_health_score: number | null;
    total_active_alarms: number;
    total_active_critical_alerts: number;
  };
};

// A site synced within this window reads "online" — 48h, not billing.py's
// own 5-minute `_STALE_AFTER` (that constant answers a completely different
// question: "is this ONVO subscription mirror fresh enough to trust
// without a live re-check"). This fleet's real sync cadence is daily
// (scheduled reports) or on-demand (a customer's own "Sync now"/an admin
// fleet sync) — 48h tolerates a normal day-to-day gap and a quiet weekend
// without flagging every site as "stale" between two ordinary syncs.
const _ONLINE_WITHIN_MS = 48 * 60 * 60 * 1000;

function _connectionStatus(lastSyncedAt: string | null, now: number): FleetConnectionStatus {
  if (!lastSyncedAt) return 'never_synced';
  const age = now - new Date(lastSyncedAt).getTime();
  return age <= _ONLINE_WITHIN_MS ? 'online' : 'stale';
}

/** For each (site_id, alarm, source) episode key, the WARNING/CLEARED
 * severity of its MOST RECENT event within `rows` — a WARNING with no
 * later CLEARED means that episode is still open right now. `rows` should
 * already be sorted or unsorted; this scans all of them and keeps the
 * latest by timestamp per key, the same "fetch raw rows, group in code"
 * shape `database/vrm_report_db.py:get_alarm_episode_counts_by_category()`
 * already uses server-side, mirrored here since this is a Next.js-side
 * read with no Python equivalent to call into. */
function _countOpenEpisodes(rows: { site_id: string; alarm?: string | null; category?: string | null; severity: string | null; timestamp: string | null }[]): Map<string, number> {
  const latestByKey = new Map<string, { severity: string | null; ts: number }>();
  for (const r of rows) {
    if (!r.timestamp) continue;
    const label = r.alarm ?? r.category ?? 'unknown';
    const key = `${r.site_id}::${label}`;
    const ts = new Date(r.timestamp).getTime();
    const existing = latestByKey.get(key);
    if (!existing || ts > existing.ts) latestByKey.set(key, { severity: r.severity, ts });
  }
  const openCountBySite = new Map<string, number>();
  for (const [key, latest] of latestByKey) {
    if (latest.severity !== 'WARNING') continue;
    const siteId = key.split('::')[0];
    openCountBySite.set(siteId, (openCountBySite.get(siteId) ?? 0) + 1);
  }
  return openCountBySite;
}

/** Every `source='vrm_api'` site's current status in one call — connection
 * freshness, latest health score, and open alarm/critical-alert counts.
 * `monitoring`-schema (Node-RED) sites are deliberately excluded: they have
 * no `vrm.daily_health` row shaped the same way, and mixing the two would
 * make "average fleet health" mean two different things silently. */
export async function getFleetOverview(): Promise<FleetOverview> {
  const admin = getSupabaseAdmin();
  const now = Date.now();
  // Generous enough to always contain the real most-recent health row (a
  // site can go a few days without a fresh sync) and any genuinely open
  // alarm/critical-alert episode (an episode that's been open longer than
  // this would be a real, separate "stuck" bug worth its own investigation,
  // not something this dashboard needs to keep scanning further back for).
  const lookbackIso = new Date(now - 14 * 24 * 60 * 60 * 1000).toISOString();
  const lookbackDate = lookbackIso.slice(0, 10);

  const { data: sites, error: sitesError } = await admin
    .schema('vrm')
    .from('sites')
    .select('site_id, display_name, customer_id, system_type, pv_kwp, battery_usable_kwh, vrm_last_synced_at')
    .eq('source', 'vrm_api')
    .order('display_name');
  if (sitesError) throw sitesError;
  const siteRows = sites ?? [];
  const siteIds = siteRows.map((s) => s.site_id);

  if (siteIds.length === 0) {
    return { sites: [], rollup: { site_count: 0, online_count: 0, avg_health_score: null, total_active_alarms: 0, total_active_critical_alerts: 0 } };
  }

  const [
    { data: customers, error: customersError },
    { data: health, error: healthError },
    { data: alarms, error: alarmsError },
    { data: criticalAlerts, error: criticalError },
    { data: snapshots, error: snapshotsError },
  ] = await Promise.all([
    admin.schema('vrm').from('customers').select('id, name'),
    admin.schema('vrm').from('daily_health').select('site_id, date, health_score, health_status').in('site_id', siteIds).gte('date', lookbackDate),
    admin.schema('vrm').from('alarm_events').select('site_id, alarm, severity, timestamp').in('site_id', siteIds).gte('timestamp', lookbackIso),
    admin.schema('vrm').from('critical_alerts').select('site_id, category, severity, timestamp').in('site_id', siteIds).gte('timestamp', lookbackIso),
    // Fleet Dashboard Phase 2 — one row per site already (migration 031's
    // PRIMARY KEY on site_id), so no "latest per site" grouping needed
    // here the way daily_health above needs one.
    admin.schema('vrm').from('site_snapshots').select('site_id, captured_at, pv_power_w, load_power_w, battery_power_w, grid_power_w, soc_pct').in('site_id', siteIds),
  ]);
  if (customersError) throw customersError;
  if (healthError) throw healthError;
  if (alarmsError) throw alarmsError;
  if (criticalError) throw criticalError;
  if (snapshotsError) throw snapshotsError;

  const customerNameById = new Map((customers ?? []).map((c) => [c.id as string, c.name as string]));
  const snapshotBySite = new Map((snapshots ?? []).map((s) => [s.site_id as string, s]));

  // Latest daily_health row per site — highest `date` wins; a tie (two
  // dump_types for the same date) keeps the higher health_score, same
  // dedup rule `database/vrm_report_db.py:bucket_health_days()` already
  // uses for exactly this "which row represents this date" question.
  const latestHealthBySite = new Map<string, { date: string; health_score: number | null; health_status: string | null }>();
  for (const row of health ?? []) {
    const existing = latestHealthBySite.get(row.site_id);
    if (!existing || row.date > existing.date || (row.date === existing.date && (row.health_score ?? -1) > (existing.health_score ?? -1))) {
      latestHealthBySite.set(row.site_id, { date: row.date, health_score: row.health_score, health_status: row.health_status });
    }
  }

  const openAlarmsBySite = _countOpenEpisodes((alarms ?? []).map((a) => ({ site_id: a.site_id, alarm: a.alarm, severity: a.severity, timestamp: a.timestamp })));
  const openCriticalBySite = _countOpenEpisodes((criticalAlerts ?? []).map((c) => ({ site_id: c.site_id, category: c.category, severity: c.severity, timestamp: c.timestamp })));

  const rows: FleetOverviewRow[] = siteRows.map((s) => {
    const latestHealth = latestHealthBySite.get(s.site_id);
    const snapshot = snapshotBySite.get(s.site_id);
    return {
      site_id: s.site_id,
      display_name: s.display_name,
      customer_id: s.customer_id,
      customer_name: customerNameById.get(s.customer_id) ?? '—',
      system_type: s.system_type,
      pv_kwp: s.pv_kwp,
      battery_usable_kwh: s.battery_usable_kwh,
      vrm_last_synced_at: s.vrm_last_synced_at,
      connection_status: _connectionStatus(s.vrm_last_synced_at, now),
      health_score: latestHealth?.health_score ?? null,
      health_status: latestHealth?.health_status ?? null,
      health_date: latestHealth?.date ?? null,
      active_alarms: openAlarmsBySite.get(s.site_id) ?? 0,
      active_critical_alerts: openCriticalBySite.get(s.site_id) ?? 0,
      live_captured_at: snapshot?.captured_at ?? null,
      live_pv_power_w: snapshot?.pv_power_w ?? null,
      live_load_power_w: snapshot?.load_power_w ?? null,
      live_battery_power_w: snapshot?.battery_power_w ?? null,
      live_grid_power_w: snapshot?.grid_power_w ?? null,
      live_soc_pct: snapshot?.soc_pct ?? null,
    };
  });

  const scores = rows.map((r) => r.health_score).filter((v): v is number => v !== null);
  const rollup = {
    site_count: rows.length,
    online_count: rows.filter((r) => r.connection_status === 'online').length,
    avg_health_score: scores.length > 0 ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null,
    total_active_alarms: rows.reduce((a, r) => a + r.active_alarms, 0),
    total_active_critical_alerts: rows.reduce((a, r) => a + r.active_critical_alerts, 0),
  };

  return { sites: rows, rollup };
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
  'report_modules',
] as const;

// PLAN_PHASE18.md's Decisions section (originally 9 ids) plus §7's Phase 2
// additions — same 13 ids `sites.ts:REPORT_MODULES`,
// `victron/weekly_report.py:ALL_MODULES`, and migration 029's widened CHECK
// constraint use.
const ADMIN_REPORT_MODULES = new Set([
  'energy_mix', 'battery_health', 'grid_quality', 'events',
  'soc_chart', 'solar_performance', 'weather', 'trend', 'savings',
  'critical_alerts', 'grid_meter_detail', 'generator_runtime', 'tank_level',
]);

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

// Deliberately NO tier/entitlement check here, unlike
// `sites.ts:sanitizeReportModules()` — same "the admin write path is
// separate and untiered" precedent `branding.ts`'s own header comment
// states for branding (Oscar setting a Fleet customer's selection by hand,
// or a hand-negotiated exception, during onboarding or support). Only known
// module ids are validated; an empty result is stored as `null` (falls back
// to "every module on" when resolved), same as the customer-facing path.
function sanitizeReportModules(payload: Record<string, unknown>): void {
  if (!('report_modules' in payload)) return;
  const raw = payload.report_modules;
  const list = Array.isArray(raw) ? raw : [];
  const valid = list.filter((m): m is string => typeof m === 'string' && ADMIN_REPORT_MODULES.has(m));
  payload.report_modules = valid.length > 0 ? valid : null;
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
  sanitizeReportModules(payload);

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
