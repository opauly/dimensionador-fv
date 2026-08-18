// The `plan` vocabulary — a straight, unchanged port of `PLAN_PHASE13.md`
// §1.4's `PLANS` dict (`vrm_portal/plans.py` in the Streamlit original,
// never actually written since Phase 13 was superseded before Step 5).
// `vrm.customers.plan` stays a free-text column on purpose (see the
// migration and §1.4's own reasoning): pricing is marketing-owned and
// changes faster than a migration, so the vocabulary lives here, not in a
// DB CHECK constraint.
//
// Not `lib/server/` — this is plain data with no secret and no Supabase
// call, and `app/(portal)/app/profile` (a Server Component) needs the
// label; nothing about it requires `server-only`.

export type PlanKey = 'trial' | 'single_report' | 'starter' | 'growth' | 'fleet';

export type AccountType = 'owner' | 'installer';

export type PlanDef = {
  key: PlanKey;
  label: string;
  /** Max sites under this plan; `null` = unlimited (today, only 'fleet'). */
  sites: number | null;
  accountTypes: readonly AccountType[];
};

export const PLANS: Record<PlanKey, PlanDef> = {
  trial: { key: 'trial', label: 'Trial', sites: 1, accountTypes: ['owner', 'installer'] },
  single_report: { key: 'single_report', label: 'Single Report', sites: 1, accountTypes: ['owner'] },
  starter: { key: 'starter', label: 'Starter', sites: 10, accountTypes: ['installer', 'owner'] },
  growth: { key: 'growth', label: 'Growth', sites: 50, accountTypes: ['installer'] },
  fleet: { key: 'fleet', label: 'Fleet', sites: null, accountTypes: ['installer'] },
};

/** `vrm.customers.plan` is free text, so an unrecognized value (a typo, a
 * plan retired after a customer was created on it) must render as *something*
 * rather than crash a Server Component — falls back to the raw value. */
export function planLabel(plan: string): string {
  return (PLANS as Record<string, PlanDef | undefined>)[plan]?.label ?? plan;
}

/** The plan's own site cap, distinct from `vrm.customers.site_limit` (the
 * actual value enforced by `lib/server/db/sites.ts:canAddSite()`).
 * `site_limit` is meant to be defaulted from this at customer-create time
 * (Step 7's admin create-customer flow) and is then the source of truth —
 * this function exists for that defaulting, and for display ("Trial plan,
 * normally 1 site") when `site_limit` has drifted from the plan's own
 * number for a hand-negotiated deal. */
export function planSiteLimit(plan: string): number | null {
  return (PLANS as Record<string, PlanDef | undefined>)[plan]?.sites ?? null;
}
