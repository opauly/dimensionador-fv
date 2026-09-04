import 'server-only';

// Cap A's Next.js-side ceiling (PLAN_PHASE17.md §2.2, §8 Step 3) — reads
// `vrm.plan_limits` directly (the same table `vrm_api/report_limits.py`'s
// `resolve_limits()` reads on the Python side) so
// `app/api/pipeline/reports/route.ts` can check a LOWER manual-regeneration
// ceiling before ever calling `vrm_api`. `vrm_api`'s own, higher ceiling
// (`check_manual_cap()`) is a SEPARATE, independent check against a
// DIFFERENT `vrm.rate_limits` bucket — see that module's own docstring for
// why sharing a bucket between the two layers would be wrong, not just
// redundant.
import { getSupabaseAdmin } from '@/lib/server/supabase';

const DEFAULT_PLAN_KEY = 'default';

export type ManualReportLimits = {
  perHour: number;
  perDay: number;
};

/**
 * `vrm.customers.plan` -> `vrm.plan_limits` row, falling back to
 * `'default'` for `null`/an unrecognized plan string — the identical
 * resolution rule `vrm_api/report_limits.py:resolve_limits()` implements on
 * the Python side (PLAN_PHASE17.md §5.1). Never resolves to "no limit":
 * the `'default'` row is mandatory (migration 026); if it's somehow
 * missing this throws rather than silently treating a broken seed as
 * unlimited.
 */
export async function getManualReportLimits(plan: string | null): Promise<ManualReportLimits> {
  const key = plan || DEFAULT_PLAN_KEY;

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('manual_reports_per_hour, manual_reports_per_day')
    .eq('plan_key', key)
    .maybeSingle();
  if (error) throw error;
  if (data) return { perHour: data.manual_reports_per_hour, perDay: data.manual_reports_per_day };

  const { data: defaultRow, error: defaultError } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('manual_reports_per_hour, manual_reports_per_day')
    .eq('plan_key', DEFAULT_PLAN_KEY)
    .maybeSingle();
  if (defaultError) throw defaultError;
  if (!defaultRow) {
    throw new Error("vrm.plan_limits has no 'default' row — migration 026 must be applied.");
  }
  return { perHour: defaultRow.manual_reports_per_hour, perDay: defaultRow.manual_reports_per_day };
}

/**
 * `vrm.plan_limits.white_label` for `vrm.customers.plan`, same resolution
 * rule as `getManualReportLimits()` above (PLAN_PHASE17.md §4.2 rule 1).
 * Used by `lib/server/db/branding.ts:getBrandingAccess()` — this is the
 * UI-facing half of the same gate `vrm_api/branding.py:
 * _white_label_allowed()` enforces server-side at render time; hiding the
 * editor here is UX, never the control.
 */
export async function getWhiteLabelAllowed(plan: string | null): Promise<boolean> {
  const key = plan || DEFAULT_PLAN_KEY;

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('white_label')
    .eq('plan_key', key)
    .maybeSingle();
  if (error) throw error;
  if (data) return data.white_label;

  const { data: defaultRow, error: defaultError } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('white_label')
    .eq('plan_key', DEFAULT_PLAN_KEY)
    .maybeSingle();
  if (defaultError) throw defaultError;
  if (!defaultRow) {
    throw new Error("vrm.plan_limits has no 'default' row — migration 026 must be applied.");
  }
  return defaultRow.white_label;
}

/**
 * `vrm.plan_limits.live_dashboard` for `vrm.customers.plan` (migration 041),
 * same resolution rule as `getWhiteLabelAllowed()` above. Used by
 * `lib/server/db/fleetDashboard.ts:getDashboardAccess()` — the UI-facing
 * half of the gate for the customer-facing Fleet Dashboard (`/app/dashboard`,
 * 2026-09-03); hiding the page is UX, never the control — the
 * `/api/pipeline/vrm-fleet/*` routes it depends on re-check this too.
 */
export async function getDashboardAllowed(plan: string | null): Promise<boolean> {
  const key = plan || DEFAULT_PLAN_KEY;

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('live_dashboard')
    .eq('plan_key', key)
    .maybeSingle();
  if (error) throw error;
  if (data) return data.live_dashboard;

  const { data: defaultRow, error: defaultError } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('live_dashboard')
    .eq('plan_key', DEFAULT_PLAN_KEY)
    .maybeSingle();
  if (defaultError) throw defaultError;
  if (!defaultRow) {
    throw new Error("vrm.plan_limits has no 'default' row — migration 026 must be applied.");
  }
  return defaultRow.live_dashboard;
}

/**
 * Cap B's own ceiling (PLAN_PHASE17.md §2.2 point 2, §2.3) — the number
 * `SitesManager.tsx`'s bulk "apply to all sites" action shows *before*
 * confirming (§3.7, §2.2 "moment 1"). This is a UI-side PROJECTION only, an
 * estimate to inform the decision — the real, live enforcement is
 * `vrm_api/report_limits.py:check_scheduled_cap()`, which runs against the
 * customer's actual current billing period every time `run-due` considers
 * one of their sites. Deliberately does not re-derive that exact
 * billing-period arithmetic here; a rough per-period estimate is what a
 * customer needs to see before clicking a button, not a live count.
 */
export async function getScheduledCapLimit(plan: string | null): Promise<number> {
  const key = plan || DEFAULT_PLAN_KEY;

  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('scheduled_reports_per_period')
    .eq('plan_key', key)
    .maybeSingle();
  if (error) throw error;
  if (data) return data.scheduled_reports_per_period;

  const { data: defaultRow, error: defaultError } = await getSupabaseAdmin()
    .schema('vrm')
    .from('plan_limits')
    .select('scheduled_reports_per_period')
    .eq('plan_key', DEFAULT_PLAN_KEY)
    .maybeSingle();
  if (defaultError) throw defaultError;
  if (!defaultRow) {
    throw new Error("vrm.plan_limits has no 'default' row — migration 026 must be applied.");
  }
  return defaultRow.scheduled_reports_per_period;
}

/** Rough reports-per-billing-period estimate for one site on a given
 * cadence — `~30`/period for daily, `~4.3`/period for weekly (365.25/12/7),
 * `1`/period for monthly. Deliberately approximate (see
 * `getScheduledCapLimit()`'s own comment) — good enough to warn a customer
 * before they click a button, not a substitute for Cap B's real, live
 * count. */
export function estimatedReportsPerPeriod(schedule: 'off' | 'daily' | 'weekly' | 'monthly'): number {
  switch (schedule) {
    case 'daily':
      return 30;
    case 'weekly':
      return 4.3;
    case 'monthly':
      return 1;
    case 'off':
      return 0;
  }
}
