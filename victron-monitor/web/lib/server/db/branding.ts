import 'server-only';

// Branding read + gated write (PLAN_PHASE17.md §4.5, §8 Step 5) — the
// Next.js-side half of Phase 17's tiered branding feature. The OTHER half,
// `vrm_api/branding.py:resolve_branding()`, is what a rendered report
// actually sees; this module's gate (`getBrandingAccess()`) exists only to
// decide whether `/app/branding` shows the editor or an upsell, and to
// refuse a write server-side when it shouldn't have reached one — hiding
// the editor is UX, never the control (the same rule PLAN_PHASE14.md has
// stated since Step 4, restated for this feature at §4.2).
//
// Deliberately never imports `db/admin.ts` (PLAN_PHASE17.md §4.5's own
// instruction) — the admin write path (`updateCustomer()` with `branding`
// added to `ADMIN_CUSTOMER_WHITELIST`) is separate and untiered, for Oscar
// setting a Fleet customer's branding by hand during onboarding.
import { getSupabaseAdmin } from '@/lib/server/supabase';
import { getWhiteLabelAllowed } from './reportLimits';
import type { CustomerRecord } from './types';

// Same denylist `vrm_api/branding.py`'s `_NOT_ENTITLED_STATUSES` /
// PLAN_PHASE17.md §3.6 use — deliberately duplicated across the language
// boundary rather than shared, the same call `vrm_api/tenancy.py`'s own
// docstring already makes for tenancy checks: two independent
// implementations of the same one-sentence rule.
//
// 'trial_expired' (vrm_api/billing.py, migration 030, 2026-08-29) added
// alongside the other four restatements of this exact denylist — see
// sites.ts's own comment for the full reasoning.
const NOT_ENTITLED_STATUSES = new Set(['incomplete', 'unpaid', 'canceled', 'trial_expired']);

/** The shape of `vrm.customers.branding` (PLAN_PHASE17.md §4.1) — the Zod
 * half of the "three places, one shape" documentation `vrm_api/schemas.py:
 * BrandingFields` and migration 026's `COMMENT ON COLUMN` also carry. Every
 * key optional. */
export type BrandingFields = {
  company_name?: string | null;
  logo_storage_path?: string | null;
  primary_color?: string | null;
  contact_name?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  website?: string | null;
};

const BRANDING_WHITELIST = [
  'company_name',
  'logo_storage_path',
  'primary_color',
  'contact_name',
  'contact_email',
  'contact_phone',
  'website',
] as const;

function isEntitled(customer: CustomerRecord): boolean {
  if (!customer.active) return false;
  if (customer.provisioning_state !== 'active') return false;
  if (customer.billing_status && NOT_ENTITLED_STATUSES.has(customer.billing_status)) return false;
  return true;
}

/** Whether `/app/branding` should show the editor (`true`) or the upsell
 * panel (`false`) for this customer — and the same check `updateBranding()`
 * re-runs before writing anything. Three independent gates, same as the
 * Python side (`vrm_api/branding.py:resolve_branding()`): account type
 * (added 2026-08-21 from live testing — an `owner` account has no third
 * party for a report to be "branded" at, so this doesn't apply regardless
 * of tier), the tier (`vrm.plan_limits.white_label`), and entitlement (the
 * denylist above). */
export async function getBrandingAccess(customer: CustomerRecord): Promise<boolean> {
  if (customer.account_type !== 'installer') return false;
  const whiteLabelAllowed = await getWhiteLabelAllowed(customer.plan);
  return whiteLabelAllowed && isEntitled(customer);
}

/** The raw, unvalidated jsonb — `{}` for every pre-Phase-17 customer.
 * Never handed to `victron/weekly_report.py` directly; only
 * `resolve_branding()` (Python) does that, after its own validation. This
 * function exists to populate the settings form's current values. */
export async function getBranding(customerId: string): Promise<BrandingFields> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .select('branding')
    .eq('id', customerId)
    .single();
  if (error) throw error;
  return (data?.branding as BrandingFields) ?? {};
}

export class BrandingNotAllowed extends Error {
  constructor() {
    super('This customer is not entitled to set custom branding.');
    this.name = 'BrandingNotAllowed';
  }
}

/** The gated, whitelisted write (PLAN_PHASE17.md §4.5). Re-checks
 * `getBrandingAccess()` itself — a direct POST to the action that calls
 * this, with a valid session but the wrong tier, must be refused here with
 * NOTHING written, independent of whatever the UI already hid. Wholesale
 * replace of the `branding` column (a form save, not a PATCH) — every key
 * not present in `fields` is dropped, matching "the settings form always
 * submits every field it shows." Field-level validation (colour
 * regex/luminance, text length) is the caller's job (`actions.ts`), so this
 * function can give a proper per-field error rather than a generic one;
 * the ACTUAL security backstop against a bad value is
 * `resolve_branding()`'s own re-validation at read time regardless of what
 * lands here. */
export async function updateBranding(customer: CustomerRecord, fields: BrandingFields): Promise<void> {
  const allowed = await getBrandingAccess(customer);
  if (!allowed) throw new BrandingNotAllowed();

  const payload: Record<string, unknown> = {};
  for (const key of BRANDING_WHITELIST) {
    if (key in fields) payload[key] = fields[key];
  }

  const { error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('customers')
    .update({ branding: payload })
    .eq('id', customer.id);
  if (error) throw error;
}
