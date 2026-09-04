import 'server-only';

// Customer-facing Fleet Dashboard (`/app/dashboard`, 2026-09-03) — the
// tenant-scoped counterpart of the admin-only `/admin/fleet`
// (`lib/server/db/admin.ts:getFleetOverview()`). Deliberately never imports
// `db/admin.ts` (same rule `branding.ts`'s own header comment states for
// itself) — every function here takes `customerId` first and does its OWN
// `vrm.sites` query filtered to it, then hands that already-scoped row set
// to `fleetOverviewCore.ts`'s shared `buildFleetOverview()` for the row
// shape/indicator math both dashboards share. See that file's own header
// comment for why sharing THAT part is safe even though `admin.ts` itself
// is off-limits here.
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { getDashboardAllowed } from './reportLimits';
import { buildFleetOverview, FLEET_SITE_SELECT_FIELDS } from './fleetOverviewCore';
import type { FleetOverview, FleetOverviewRow, FleetSiteInput } from './fleetOverviewCore';
import type { CustomerRecord } from './types';

// Same denylist `branding.ts`'s own `NOT_ENTITLED_STATUSES` carries —
// deliberately duplicated rather than shared, matching that file's own
// comment on why (two independent implementations of the same one-sentence
// rule, not a shared import that could silently drift for one feature but
// not the other).
const NOT_ENTITLED_STATUSES = new Set(['incomplete', 'unpaid', 'canceled', 'trial_expired']);

function isEntitled(customer: CustomerRecord): boolean {
  if (!customer.active) return false;
  if (customer.provisioning_state !== 'active') return false;
  if (customer.billing_status && NOT_ENTITLED_STATUSES.has(customer.billing_status)) return false;
  return true;
}

/** Whether `/app/dashboard` should show real content (`true`) or the
 * upsell panel (`false`) for this customer, and the same check
 * `app/api/pipeline/vrm-fleet/*` re-run before serving live shape/savings
 * data. Two gates: the tier (`vrm.plan_limits.live_dashboard` — Growth/Fleet
 * only, Oscar's decision 2026-09-03) and entitlement (the denylist above).
 * No account_type restriction (unlike `getBrandingAccess()`'s `owner`
 * exclusion) — there's no "third party" concept this feature needs a
 * counterparty for, so gating is by plan tier alone. In practice that's
 * moot anyway: `lib/plans.ts`'s `PLANS.growth`/`PLANS.fleet` are already
 * `accountTypes: ['installer']`, so an `owner` account can never reach a
 * plan with `live_dashboard=true` in the first place. */
export async function getDashboardAccess(customer: CustomerRecord): Promise<boolean> {
  const dashboardAllowed = await getDashboardAllowed(customer.plan);
  return dashboardAllowed && isEntitled(customer);
}

/** The customer-scoped version of `admin.ts:getFleetOverview()` — same row
 * shape, same indicator math (`fleetOverviewCore.ts`), filtered to exactly
 * one customer's own `vrm.sites` rows. Call `getDashboardAccess()` first;
 * this function itself does not re-check entitlement — same split
 * `sites.ts`'s tenant-scoped functions already use (the gate is the
 * caller's job, the query is this function's). */
export async function getCustomerFleetOverview(customerId: string): Promise<FleetOverview> {
  const { data: sites, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('sites')
    .select(FLEET_SITE_SELECT_FIELDS)
    .eq('source', 'vrm_api')
    .eq('active', true)
    .eq('customer_id', customerId)
    .order('display_name');
  if (error) throw error;
  return buildFleetOverview((sites ?? []) as unknown as FleetSiteInput[]);
}

/** The single-site drill-down for `/app/dashboard/[site_id]`. `null` when
 * `siteId` doesn't belong to `customerId` (including "belongs to a
 * DIFFERENT customer") — `getCustomerFleetOverview()`'s own query already
 * scoped `sites` to this customer, so a site that isn't in its result
 * either doesn't exist or isn't this customer's; either way, the caller's
 * job to treat that as a 404, exactly like `admin.ts:getFleetSiteDetail()`
 * does for a nonexistent site_id. */
export async function getCustomerFleetSiteDetail(customerId: string, siteId: string): Promise<FleetOverviewRow | null> {
  const overview = await getCustomerFleetOverview(customerId);
  return overview.sites.find((s) => s.site_id === siteId) ?? null;
}
