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

// `vrm.site_anomalies` (migration 038) — see FleetOverviewRow.active_anomalies'
// own comment. `detail`'s shape varies by `anomaly_type` (the table's own
// COMMENT ON COLUMN says so) — kept as a loose record here rather than a
// narrower type per known anomaly_type, since all four (`unexpected_silence`,
// `quiet_drift`, `underperformance`, `incomplete_charging` — migration 040)
// are real, live-written shapes whose own thresholds/keys may still change
// during tuning (PLAN_PHASE19_FLEET_P3.md §7 item 1: thresholds are
// "starting points, not locked").
export type SiteAnomalyRow = {
  id: string;
  site_id: string;
  anomaly_type: string;
  detected_at: string;
  detail: Record<string, unknown> | null;
};

export type FleetOverviewRow = {
  site_id: string;
  display_name: string;
  customer_id: string;
  customer_name: string;
  system_type: SiteRecord['system_type'];
  pv_kwp: number | null;
  battery_usable_kwh: number | null;
  // The site's own configured timezone (its Cerbo's local time), same
  // field `victron/vrm_live.py`/`vrm_shape.py` already pass to VRM — a
  // live reading is timestamped in THIS, not the app-wide
  // America/Costa_Rica default `lib/dates.ts:formatDateTime()` otherwise
  // assumes. `null` falls back to that default (a site with no configured
  // timezone, effectively "unknown" rather than "definitely UTC").
  timezone: string | null;
  vrm_last_synced_at: string | null;
  connection_status: FleetConnectionStatus;
  health_score: number | null;
  health_status: string | null;
  health_date: string | null;
  // The reasons behind health_score, straight from vrm.compute_daily_health()
  // (migration 012) — semicolon-joined (e.g. "High grid dependency; Low
  // battery voltage (45.2V)"), or "Normal operation" when nothing was
  // penalized. `null` only when there's no daily_health row at all yet.
  health_notes: string | null;
  // Live-only (2026-09-01): counts categories present in the MOST RECENT
  // live snapshot's raw.alarms/raw.critical_alerts, nothing else — not an
  // episode/history count. A category active yesterday but cleared by the
  // latest ~15-minute fetch does not count; one that just started does,
  // even if it started five minutes ago. 0 whenever there's no live
  // snapshot yet, same as every other live-only field here.
  active_alarms: number;
  active_critical_alerts: number;
  // Fleet Dashboard Phase 3 (2026-09-03) — every OPEN (`cleared_at IS
  // NULL`) `vrm.site_anomalies` row for this site (migration 038), any
  // `anomaly_type`. `unexpected_silence` (3b) is written by
  // `victron/anomaly_silence.py` via the ~15-minute `refresh-snapshots`
  // sweep; `quiet_drift`/`underperformance` (3a/3c) are written by
  // `victron/anomaly_drift.py` via the daily
  // `POST /v1/vrm-fleet/detect-anomalies-daily` sweep. This query itself
  // (below) already reads every `anomaly_type` generically — no change
  // needed here when a new type starts being written. `[]`, never omitted,
  // when this site has no open anomaly.
  active_anomalies: SiteAnomalyRow[];
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
  // Per-solar-charger breakdown (victron/vrm_live.py:_pv_power_from_diagnostics(),
  // 2026-09-01) — `null` on a single-charger site (nothing to break down) or
  // one with no PV at all; on a multi-charger site, entries sum to exactly
  // `live_pv_power_w`.
  live_pv_chargers: { instance: number; power_w: number }[] | null;
  // A live snapshot value that has ever landed non-null means there's SOME
  // grid reading to show — originally assumed that always meant a physical
  // grid meter, corrected 2026-09-01: most sites have no dedicated meter
  // and this is instead the inverter/charger's own AC input measurement
  // (`live_grid_source: 'inverter'`) — see victron/vrm_live.py's
  // GRID_POWER_CODES/INVERTER_INPUT_CODES comment for why the two read
  // meaningfully different values on the one site checked with both, and
  // are never conflated. `live_grid_source` is `null` only when this site
  // publishes no grid signal of either kind.
  has_grid_meter: boolean;
  live_grid_source: 'meter' | 'inverter' | null;
  // Per-phase live load breakdown (a1/a2, i.e. L1/L2) — same shape/intent
  // as live_pv_chargers, entries sum to exactly live_load_power_w.
  live_load_phases: { phase: string; power_w: number }[] | null;
  // Fleet Dashboard Phase 2.5 (2026-08-30) — every one of these is derived
  // from the most recent `vrm.energy_daily`/`vrm.daily_health` row using
  // exactly the formulas IE-0499's own requirements doc §4 specifies
  // (`self_sufficiency = 1 - grid_kwh/load_kwh`, etc.) — no new ingestion,
  // this data has been sitting on those two tables all along. `null` when
  // that day's denominator is zero/missing rather than a divide-by-zero or
  // a fabricated 0%.
  health_metrics_date: string | null;
  specific_yield_kwh_per_kwp: number | null;
  self_sufficiency_pct: number | null;
  self_consumption_pct: number | null;
  dod_pct: number | null;
  grid_dependency_pct: number | null;
  // Everything computed the same way `victron/weekly_report.py` computes
  // it for the PDF report (see `_periodIndicators()`) — battery cycles,
  // stress label, outage minutes/count, min/max/avg SOC, days
  // self-sufficient — over the last 7 and last 30 days of
  // `vrm.energy_daily` rows respectively, so the per-site page's
  // week/month toggle needs no extra fetch, just a client-side switch
  // between two already-computed objects. NOT read from
  // `vrm.daily_health.battery_cycles`, which still fabricates a 0.0 for
  // every VRM-API site (migration 012, unfixed).
  week: PeriodIndicators;
  month: PeriodIndicators;
};

export type FleetOverview = {
  sites: FleetOverviewRow[];
  rollup: {
    site_count: number;
    online_count: number;
    avg_health_score: number | null;
    total_active_alarms: number;
    total_active_critical_alerts: number;
    // Fleet Dashboard Phase 3 — count of OPEN vrm.site_anomalies rows
    // across every site, any anomaly_type (unexpected_silence, quiet_drift,
    // underperformance, incomplete_charging).
    total_active_anomalies: number;
  };
};

// Based on `site_snapshots.captured_at` (the ~15-minute `refresh-snapshots`
// sweep), NOT `vrm_last_synced_at` (the daily energy_daily/report sync) —
// found live 2026-08-31 that those two can disagree for days at a time
// (the daily sync can stall on a bad date range or a standing VRM error
// while the live snapshot sweep keeps succeeding every 15 minutes
// regardless, since it's a completely separate code path). An admin reading
// "online" reasonably means "is this site talking to VRM right now," which
// is exactly what the snapshot sweep answers and the daily sync does not.
// 45 minutes = 3x the sweep's own interval, tolerating one missed run
// without flagging a genuinely live site as stale.
const _ONLINE_WITHIN_MS = 45 * 60 * 1000;

function _connectionStatus(liveCapturedAt: string | null, now: number): FleetConnectionStatus {
  if (!liveCapturedAt) return 'never_synced';
  const age = now - new Date(liveCapturedAt).getTime();
  return age <= _ONLINE_WITHIN_MS ? 'online' : 'stale';
}

// `site_snapshots.raw` is a loosely-typed jsonb blob (see migration 031's
// own comment on that column) — pulled apart here rather than trusted
// as-is, same defensive parsing every other jsonb-sourced field in this
// file already does.
function _pvChargersFromRaw(raw: unknown): { instance: number; power_w: number }[] | null {
  if (!raw || typeof raw !== 'object') return null;
  const list = (raw as Record<string, unknown>).pv_chargers;
  if (!Array.isArray(list) || list.length === 0) return null;
  const parsed = list
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({ instance: Number(e.instance), power_w: Number(e.power_w) }))
    .filter((e) => Number.isFinite(e.instance) && Number.isFinite(e.power_w));
  return parsed.length > 0 ? parsed : null;
}

function _loadPhasesFromRaw(raw: unknown): { phase: string; power_w: number }[] | null {
  if (!raw || typeof raw !== 'object') return null;
  const list = (raw as Record<string, unknown>).load_phases;
  if (!Array.isArray(list) || list.length === 0) return null;
  const parsed = list
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({ phase: String(e.phase), power_w: Number(e.power_w) }))
    .filter((e) => e.phase.length > 0 && Number.isFinite(e.power_w));
  return parsed.length > 0 ? parsed : null;
}

function _gridSourceFromRaw(raw: unknown): 'meter' | 'inverter' | null {
  if (!raw || typeof raw !== 'object') return null;
  const source = (raw as Record<string, unknown>).grid_source;
  return source === 'meter' || source === 'inverter' ? source : null;
}

/** IE-0499's own §4 formulas, applied to the most recent `energy_daily`
 * row: specific yield = pv_kwh / pv_kwp; self-sufficiency = 1 -
 * grid_kwh/load_kwh (approximated here as `pv_kwh - grid_export_kwh` for
 * "load" — this table has no direct `load_kwh` column read into this
 * query, and PV-minus-exports is the same quantity the doc's own
 * self-consumption formula already uses); DoD = 100% - min_soc. `null`
 * whenever the row itself is missing or a denominator is zero, never a
 * fabricated 0%/divide-by-zero.
 *
 * `pv_kwp_snapshot` (meant to freeze the capacity a given day's yield was
 * computed against, surviving a later capacity change) is `null` on every
 * real row as of 2026-08-30 — checked live, not assumed, and it's a real
 * gap in the ingestion pipeline this function doesn't own. `fallbackKwp`
 * (the site's CURRENT `pv_kwp`) is what actually makes yield computable
 * today; swap back to `pv_kwp_snapshot`-only once that column is actually
 * populated at ingestion time. */
function _dailyIndicators(
  energy: { pv_kwh: number | null; grid_kwh: number | null; grid_export_kwh: number | null; pv_kwp_snapshot: number | null; min_soc: number | null } | undefined,
  fallbackKwp: number | null
): {
  specificYield: number | null; selfSufficiency: number | null; selfConsumption: number | null; dod: number | null;
} {
  if (!energy) return { specificYield: null, selfSufficiency: null, selfConsumption: null, dod: null };
  const pv = energy.pv_kwh ?? null;
  const grid = energy.grid_kwh ?? null;
  const exported = energy.grid_export_kwh ?? 0;
  const kwp = energy.pv_kwp_snapshot ?? fallbackKwp ?? null;
  const minSoc = energy.min_soc ?? null;

  const specificYield = pv !== null && kwp !== null && kwp > 0 ? Math.round((pv / kwp) * 100) / 100 : null;
  const selfConsumption = pv !== null && pv > 0 ? Math.round(((pv - exported) / pv) * 1000) / 10 : null;

  const consumedLocally = pv !== null ? Math.max(pv - exported, 0) : null;
  const totalLoad = consumedLocally !== null && grid !== null ? consumedLocally + grid : null;
  const selfSufficiency = totalLoad !== null && totalLoad > 0 && grid !== null
    ? Math.round((1 - grid / totalLoad) * 1000) / 10
    : null;

  const dod = minSoc !== null ? Math.round((100 - minSoc) * 10) / 10 : null;

  return { specificYield, selfSufficiency, selfConsumption, dod };
}

export type BatteryStress = 'normal' | 'working_hard' | 'high_stress' | 'no_data';

export type PeriodIndicators = {
  // Equivalent full cycles over the window. Two possible bases, same split
  // `vrm.compute_daily_health()` (migration 039) now uses per-day:
  //   - Exact: sum real discharge over the window, divide by usable
  //     capacity — computed exactly the way
  //     `victron/weekly_report.py:build_report_data()` does for the PDF
  //     report. `null` only when EVERY day in the window has both charge
  //     and discharge NULL (every VRM-API site, by design) — a CSV-sourced
  //     site can have a real zero-discharge day, which must stay a real 0.
  //   - Estimated (VRM-API sites, migration 039): sum each day's own SOC
  //     swing `(max_soc - min_soc) / 100` across the window — an
  //     approximation (assumes ~one discharge/recharge swing per day), but
  //     real, not a fabricated 0. `batteryCyclesEstimated` distinguishes
  //     which basis produced `batteryCycles`, so the UI can label it.
  batteryCycles: number | null;
  batteryCyclesEstimated: boolean;
  // Same 3-tier-plus-"no data" label `weekly_report.py` shows on the PDF,
  // thresholds scaled by the window's own length the same way that
  // module's own comment describes ("a 30-day custom range naturally
  // accumulates ~4x the cycles a 7-day one does for the exact same daily
  // usage pattern... these thresholds... scale with the window's length")
  // — a month window must not read as "High stress" purely for being
  // longer than a week. `'no_data'` is a genuine fourth state, not lumped
  // in with `'normal'` — the report's own comment on why: "'Normal' would
  // actively assert everything's fine for data that is actually just
  // absent." The estimated basis uses its own, much smaller-scale
  // thresholds (see `_EST_CYCLES_*_PER_DAY`) — SOC swing is bounded to
  // [0,1] per day, so reusing the exact metric's 7.0/10.0-per-week
  // thresholds would make it structurally incapable of ever firing.
  batteryStress: BatteryStress;
  outageMinutes: number;
  outageCount: number;
  minSoc: number | null;
  maxSoc: number | null;
  avgSoc: number | null;
  daysSelfSufficient: number;
  daysWithData: number;
};

const _BATTERY_CYCLES_HIGH = 10.0;
const _BATTERY_CYCLES_MID = 7.0;
// Per-day, matching vrm.compute_daily_health()'s estCyclesHigh/Mid defaults
// (migration 039) — calibrated against the real distribution of daily SOC
// swings across the current VRM-API fleet (523 days: median 0.45, p90 0.74,
// max ever seen 0.82). Summed across the window below, same "per-day rate
// scaled by how many real days you have" shape the exact metric already
// uses via `weekScale`.
const _EST_CYCLES_HIGH_PER_DAY = 0.85;
const _EST_CYCLES_MID_PER_DAY = 0.65;

function _periodIndicators(
  rows: {
    grid_kwh: number | null;
    min_soc: number | null;
    max_soc: number | null;
    avg_soc: number | null;
    outage_count: number | null;
    outage_minutes: number | null;
    battery_charge_kwh: number | null;
    battery_discharge_kwh: number | null;
  }[],
  batteryUsableKwh: number | null
): PeriodIndicators {
  const batteryKwhAvailable = !(
    rows.every((r) => r.battery_charge_kwh === null) && rows.every((r) => r.battery_discharge_kwh === null)
  );
  const exactCycles = rows.length > 0 && batteryKwhAvailable
    ? Math.round((rows.reduce((sum, r) => sum + (r.battery_discharge_kwh ?? 0), 0) / (batteryUsableKwh || 1)) * 100) / 100
    : null;
  // Estimated fallback — only when the exact metric has nothing to work
  // with. A day missing either end of its SOC swing contributes 0, same
  // "treat missing as 0 within a sum, not null" convention the exact
  // metric already uses for `battery_discharge_kwh ?? 0`.
  const estCycles = rows.length > 0 && !batteryKwhAvailable
    ? Math.round(
        rows.reduce((sum, r) => sum + (r.min_soc !== null && r.max_soc !== null ? (r.max_soc - r.min_soc) / 100 : 0), 0) * 100
      ) / 100
    : null;
  const batteryCyclesEstimated = exactCycles === null && estCycles !== null;
  const batteryCycles = batteryCyclesEstimated ? estCycles : exactCycles;

  // `weekScale` from the actual row COUNT, same as `weekly_report.py`'s own
  // `len(days) / 7` — a site with gaps in its history gets thresholds
  // scaled to how much real data it actually has, not the window's nominal
  // length.
  const weekScale = rows.length > 0 ? rows.length / 7 : 1;
  const batteryStress: BatteryStress =
    batteryCycles === null ? 'no_data'
    : batteryCyclesEstimated
      ? (batteryCycles > _EST_CYCLES_HIGH_PER_DAY * rows.length ? 'high_stress'
         : batteryCycles > _EST_CYCLES_MID_PER_DAY * rows.length ? 'working_hard'
         : 'normal')
    : batteryCycles > _BATTERY_CYCLES_HIGH * weekScale ? 'high_stress'
    : batteryCycles > _BATTERY_CYCLES_MID * weekScale ? 'working_hard'
    : 'normal';

  const minSocValues = rows.map((r) => r.min_soc).filter((v): v is number => v !== null);
  const maxSocValues = rows.map((r) => r.max_soc).filter((v): v is number => v !== null);
  const avgSocValues = rows.map((r) => r.avg_soc).filter((v): v is number => v !== null);

  return {
    batteryCycles,
    batteryCyclesEstimated,
    batteryStress,
    outageMinutes: Math.round(rows.reduce((sum, r) => sum + (r.outage_minutes ?? 0), 0) * 10) / 10,
    outageCount: rows.reduce((sum, r) => sum + (r.outage_count ?? 0), 0),
    minSoc: minSocValues.length > 0 ? Math.min(...minSocValues) : null,
    maxSoc: maxSocValues.length > 0 ? Math.max(...maxSocValues) : null,
    avgSoc: avgSocValues.length > 0 ? Math.round((avgSocValues.reduce((a, b) => a + b, 0) / avgSocValues.length) * 10) / 10 : null,
    daysSelfSufficient: rows.filter((r) => (r.grid_kwh ?? 0) <= 0).length,
    daysWithData: rows.length,
  };
}

/** Live-only "Active Alarms"/"Active Critical Alerts" count (2026-09-01) —
 * counts `true` entries in a `site_snapshots.raw.alarms`/`raw.critical_alerts`
 * blob (see `victron/vrm_live.py:check_live_alarms()`). Deliberately NOT
 * episode/history-based any more: a category present in the latest live
 * fetch counts, one absent from it (including "no live snapshot at all")
 * does not — this is a live dashboard, not a historical alarm log. */
function _activeCountFromRaw(raw: unknown, key: 'alarms' | 'critical_alerts'): number {
  if (!raw || typeof raw !== 'object') return 0;
  const states = (raw as Record<string, unknown>)[key];
  if (!states || typeof states !== 'object') return 0;
  return Object.values(states as Record<string, unknown>).filter((v) => v === true).length;
}

/** Every `source='vrm_api'` site's current status in one call — connection
 * freshness, latest health score, open alarm/critical-alert counts, and
 * (2026-09-03) open `vrm.site_anomalies` rows (Fleet Dashboard Phase 3b).
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
  // `energy_daily` alone needs a deeper window than the other tables above —
  // the "This month" toggle on the per-site page needs 30 real days to sum
  // over, not just 14.
  const lookback30Date = new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

  const { data: sites, error: sitesError } = await admin
    .schema('vrm')
    .from('sites')
    .select('site_id, display_name, customer_id, system_type, pv_kwp, battery_usable_kwh, timezone, vrm_last_synced_at')
    .eq('source', 'vrm_api')
    .eq('active', true)
    .order('display_name');
  if (sitesError) throw sitesError;
  const siteRows = sites ?? [];
  const siteIds = siteRows.map((s) => s.site_id);

  if (siteIds.length === 0) {
    return {
      sites: [],
      rollup: {
        site_count: 0, online_count: 0, avg_health_score: null,
        total_active_alarms: 0, total_active_critical_alerts: 0, total_active_anomalies: 0,
      },
    };
  }

  const [
    { data: customers, error: customersError },
    { data: health, error: healthError },
    { data: snapshots, error: snapshotsError },
    { data: energyDaily, error: energyDailyError },
    { data: anomalies, error: anomaliesError },
  ] = await Promise.all([
    admin.schema('vrm').from('customers').select('id, name'),
    // `battery_cycles` deliberately NOT selected here — `vrm.compute_daily_health()`
    // (migration 012) still does `COALESCE(battery_discharge_kwh, 0) / capacity`,
    // fabricating a confident 0.0 for every VRM-API site (that field is
    // NULL there by design — see `energyDaily`'s own comment below). Cycles
    // are computed independently a few lines down, mirroring
    // `weekly_report.py`'s own already-correct guard instead of trusting
    // that column.
    // `notes` — the same human-readable reasons `vrm.compute_daily_health()`
    // (migration 012) already builds while scoring (e.g. "High grid
    // dependency; Low battery voltage (45.2V)") and stores right alongside
    // the score, previously computed and thrown away by never being
    // selected here. Surfaced on the per-site page so a low score isn't
    // just a bare number with no way to tell what actually needs attention.
    admin.schema('vrm').from('daily_health').select('site_id, date, health_score, health_status, grid_dependency_pct, notes').in('site_id', siteIds).gte('date', lookbackDate),
    // `alarm_events`/`critical_alerts` deliberately NOT fetched here any
    // more (2026-09-01) — this is a live monitoring dashboard, and those
    // tables are the HISTORICAL sync's own record (through yesterday only,
    // for report/health-score purposes). "Active Alarms"/"Active Critical
    // Alerts" below now read straight from the live snapshot's own
    // raw.alarms/raw.critical_alerts instead — present in the latest live
    // fetch means shown, not present means not shown, no episode/history
    // reasoning involved. For real alarm HISTORY, the official VRM portal
    // is the source of truth, not this dashboard.
    // Fleet Dashboard Phase 2 — one row per site already (migration 031's
    // PRIMARY KEY on site_id), so no "latest per site" grouping needed
    // here the way daily_health above needs one.
    admin.schema('vrm').from('site_snapshots').select('site_id, captured_at, pv_power_w, load_power_w, battery_power_w, grid_power_w, soc_pct, raw').in('site_id', siteIds),
    // Fleet Dashboard Phase 2.5 — the raw kWh/SOC/yield fields IE-0499 §4's
    // formulas are built from (self-sufficiency, self-consumption, DoD,
    // specific yield, battery cycles). Same lookback window as daily_health
    // above. `battery_charge_kwh`/`battery_discharge_kwh` are NULL on every
    // row for a VRM-API site by design (`victron/vrm_series.py`'s own
    // docstring point 2b — VRM's derived flow-diagram totals disagreed with
    // a real battery monitor by up to 97%/58%) — fetched anyway so cycles
    // can apply the same all-null guard `weekly_report.py` already does,
    // rather than trusting `vrm.daily_health.battery_cycles`, which still
    // fabricates a 0.0 for exactly this case (migration 012, unfixed).
    admin.schema('vrm').from('energy_daily')
      .select('site_id, date, pv_kwh, grid_kwh, grid_export_kwh, pv_kwp_snapshot, min_soc, max_soc, avg_soc, outage_count, outage_minutes, battery_charge_kwh, battery_discharge_kwh')
      .in('site_id', siteIds).gte('date', lookback30Date),
    // Fleet Dashboard Phase 3b (migration 038) — every OPEN anomaly across
    // every site in one query, same "no bulk vrm_api endpoint exists for
    // this and none is needed, direct Postgres read" precedent every other
    // query in this function already follows (see this function's own
    // header comment).
    admin.schema('vrm').from('site_anomalies')
      .select('id, site_id, anomaly_type, detected_at, detail')
      .in('site_id', siteIds).is('cleared_at', null).order('detected_at', { ascending: false }),
  ]);
  if (customersError) throw customersError;
  if (healthError) throw healthError;
  if (snapshotsError) throw snapshotsError;
  if (energyDailyError) throw energyDailyError;
  if (anomaliesError) throw anomaliesError;

  const customerNameById = new Map((customers ?? []).map((c) => [c.id as string, c.name as string]));
  const snapshotBySite = new Map((snapshots ?? []).map((s) => [s.site_id as string, s]));
  const anomaliesBySite = new Map<string, SiteAnomalyRow[]>();
  for (const row of (anomalies ?? []) as SiteAnomalyRow[]) {
    const list = anomaliesBySite.get(row.site_id) ?? [];
    list.push(row);
    anomaliesBySite.set(row.site_id, list);
  }

  // Latest daily_health row per site — but "latest" means the most recent
  // COMPLETE day, not just the highest date. A row whose own notes say
  // "Partial day" was scored from an incomplete sync window (confirmed live
  // 2026-09-03: a backfill bounded by "now" at sync time rather than that
  // date's own midnight-to-midnight span — every site's rows for two
  // different, fully-elapsed past dates all showed the identical ~21h
  // coverage, which is a sync-timing artifact, not real per-site outages)
  // — not the concrete, trustworthy signal a customer/admin should see as
  // "the" site's health. Highest-date-among-complete-days wins; a tie (two
  // dump_types for the same date) keeps the higher health_score, same
  // dedup rule `database/vrm_report_db.py:bucket_health_days()` already
  // uses for exactly this "which row represents this date" question. Only
  // falls back to a partial row when literally nothing complete exists yet
  // in the lookback window (a brand-new site with no full day scored yet) —
  // better to show something, clearly labeled as partial, than nothing.
  const healthRowsBySite = new Map<string, { date: string; health_score: number | null; health_status: string | null; grid_dependency_pct: number | null; notes: string | null }[]>();
  for (const row of health ?? []) {
    const list = healthRowsBySite.get(row.site_id) ?? [];
    list.push({ date: row.date, health_score: row.health_score, health_status: row.health_status, grid_dependency_pct: row.grid_dependency_pct, notes: row.notes });
    healthRowsBySite.set(row.site_id, list);
  }
  const isPartialDay = (notes: string | null) => !!notes && notes.includes('Partial day');
  const latestHealthBySite = new Map<string, { date: string; health_score: number | null; health_status: string | null; grid_dependency_pct: number | null; notes: string | null }>();
  for (const [siteId, rows] of healthRowsBySite) {
    rows.sort((a, b) => (a.date === b.date ? (b.health_score ?? -1) - (a.health_score ?? -1) : b.date.localeCompare(a.date)));
    latestHealthBySite.set(siteId, rows.find((r) => !isPartialDay(r.notes)) ?? rows[0]);
  }

  // Latest energy_daily row per site — same "highest date wins" rule.
  const latestEnergyBySite = new Map<string, { date: string; pv_kwh: number | null; grid_kwh: number | null; grid_export_kwh: number | null; pv_kwp_snapshot: number | null; min_soc: number | null }>();
  for (const row of energyDaily ?? []) {
    const existing = latestEnergyBySite.get(row.site_id);
    if (!existing || row.date > existing.date) {
      latestEnergyBySite.set(row.site_id, row);
    }
  }

  // Every row from the last 7/30 days per site (not just the latest) — what
  // `_periodIndicators()` below sums/aggregates over, mirroring
  // `weekly_report.py`'s own framing exactly for whichever window a caller
  // asks for. A single day's discharge/outage figure is too noisy to mean
  // much alone; a week's or month's total/spread is the same grain the PDF
  // report already shows.
  type EnergyRowPeriod = {
    grid_kwh: number | null;
    min_soc: number | null;
    max_soc: number | null;
    avg_soc: number | null;
    outage_count: number | null;
    outage_minutes: number | null;
    battery_charge_kwh: number | null;
    battery_discharge_kwh: number | null;
  };
  const sevenDaysAgo = new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const last7dEnergyBySite = new Map<string, EnergyRowPeriod[]>();
  const last30dEnergyBySite = new Map<string, EnergyRowPeriod[]>();
  for (const row of energyDaily ?? []) {
    const entry: EnergyRowPeriod = {
      grid_kwh: row.grid_kwh,
      min_soc: row.min_soc,
      max_soc: row.max_soc,
      avg_soc: row.avg_soc,
      outage_count: row.outage_count,
      outage_minutes: row.outage_minutes,
      battery_charge_kwh: row.battery_charge_kwh,
      battery_discharge_kwh: row.battery_discharge_kwh,
    };
    // `lookback30Date` already bounds `energyDaily` to 30 days, so every
    // row here belongs in the month map; only the more recent ones also
    // belong in the week map.
    const monthList = last30dEnergyBySite.get(row.site_id) ?? [];
    monthList.push(entry);
    last30dEnergyBySite.set(row.site_id, monthList);
    if (row.date >= sevenDaysAgo) {
      const weekList = last7dEnergyBySite.get(row.site_id) ?? [];
      weekList.push(entry);
      last7dEnergyBySite.set(row.site_id, weekList);
    }
  }

  const rows: FleetOverviewRow[] = siteRows.map((s) => {
    const latestHealth = latestHealthBySite.get(s.site_id);
    const snapshot = snapshotBySite.get(s.site_id);
    const energy = latestEnergyBySite.get(s.site_id);
    const indicators = _dailyIndicators(energy, s.pv_kwp);
    return {
      site_id: s.site_id,
      display_name: s.display_name,
      customer_id: s.customer_id,
      customer_name: customerNameById.get(s.customer_id) ?? '—',
      system_type: s.system_type,
      pv_kwp: s.pv_kwp,
      battery_usable_kwh: s.battery_usable_kwh,
      timezone: s.timezone,
      vrm_last_synced_at: s.vrm_last_synced_at,
      connection_status: _connectionStatus(snapshot?.captured_at ?? null, now),
      health_score: latestHealth?.health_score ?? null,
      health_status: latestHealth?.health_status ?? null,
      health_date: latestHealth?.date ?? null,
      health_notes: latestHealth?.notes ?? null,
      active_alarms: _activeCountFromRaw(snapshot?.raw, 'alarms'),
      active_critical_alerts: _activeCountFromRaw(snapshot?.raw, 'critical_alerts'),
      active_anomalies: anomaliesBySite.get(s.site_id) ?? [],
      live_captured_at: snapshot?.captured_at ?? null,
      live_pv_power_w: snapshot?.pv_power_w ?? null,
      live_load_power_w: snapshot?.load_power_w ?? null,
      live_battery_power_w: snapshot?.battery_power_w ?? null,
      live_grid_power_w: snapshot?.grid_power_w ?? null,
      live_soc_pct: snapshot?.soc_pct ?? null,
      live_pv_chargers: _pvChargersFromRaw(snapshot?.raw),
      has_grid_meter: (snapshot?.grid_power_w ?? null) !== null,
      live_grid_source: _gridSourceFromRaw(snapshot?.raw),
      live_load_phases: _loadPhasesFromRaw(snapshot?.raw),
      health_metrics_date: energy?.date ?? null,
      specific_yield_kwh_per_kwp: indicators.specificYield,
      self_sufficiency_pct: indicators.selfSufficiency,
      self_consumption_pct: indicators.selfConsumption,
      dod_pct: indicators.dod,
      grid_dependency_pct: latestHealth?.grid_dependency_pct ?? null,
      week: _periodIndicators(last7dEnergyBySite.get(s.site_id) ?? [], s.battery_usable_kwh),
      month: _periodIndicators(last30dEnergyBySite.get(s.site_id) ?? [], s.battery_usable_kwh),
    };
  });

  const scores = rows.map((r) => r.health_score).filter((v): v is number => v !== null);
  const rollup = {
    site_count: rows.length,
    online_count: rows.filter((r) => r.connection_status === 'online').length,
    avg_health_score: scores.length > 0 ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null,
    total_active_alarms: rows.reduce((a, r) => a + r.active_alarms, 0),
    total_active_critical_alerts: rows.reduce((a, r) => a + r.active_critical_alerts, 0),
    total_active_anomalies: rows.reduce((a, r) => a + r.active_anomalies.length, 0),
  };

  return { sites: rows, rollup };
}

/** The single-site version of `getFleetOverview()`'s own row shape, for
 * `/admin/fleet/[site_id]`. Reuses that function outright rather than
 * restating its five-way parallel query and indicator math for one row —
 * at fleet sizes this dashboard is built for (single digits today), fetching
 * every site to serve one page is negligible cost for guaranteeing the
 * drill-down and the table can never compute the same indicator two
 * different ways. Worth splitting into a real single-site query if the
 * fleet grows enough for that assumption to stop holding. `null` (not a
 * throw) when `siteId` doesn't match any `source='vrm_api'` site — the
 * caller's own job to decide that's a 404. */
export async function getFleetSiteDetail(siteId: string): Promise<FleetOverviewRow | null> {
  const overview = await getFleetOverview();
  return overview.sites.find((s) => s.site_id === siteId) ?? null;
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
