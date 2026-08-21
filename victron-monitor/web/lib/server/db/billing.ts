import 'server-only';

// Billing reads for `/app/billing` (PLAN_PHASE16.md §5.1 / §8 Step 5) — the
// `billing.ts` sibling of `vrmLink.ts`, with the same deliberate difference:
// it wraps `vrm_api`'s own read endpoints (via `lib/server/pipeline.ts`)
// rather than querying Supabase directly. Billing state — plan, subscription
// status, payment-method display fields, site usage — is `vrm_api`'s own
// fact to report, re-read from ONVO on a staleness bound (§4.4), not
// something this app should re-derive from `vrm.customers`/`vrm.subscriptions`
// columns it has no business reading directly (PLAN_PHASE14.md §1.11).
//
// Mutations (subscribe/change/cancel/resume/payment-method/address/refresh)
// are NOT wrapped here — they're called directly from `app/api/billing/*`
// route handlers via `lib/server/pipeline.ts`, the same division of labor
// `app/api/vrm/connect/route.ts` already uses for `vrmLinkConnect()` (this
// directory's read-only modules wrap Server-Component-time GETs; a Route
// Handler calls the pipeline module directly for a mutation it's already
// tenancy-checked itself).
//
// `customerId` first, same convention as every other function in this
// directory — always `session.customerId`, never a value from a request
// body.
import {
  billingInvoices,
  billingPlans,
  billingStatus,
  type BillingInvoicesOut,
  type BillingPlanOut,
  type BillingStatusOut,
} from '@/lib/server/pipeline';

export type { BillingStatusOut, BillingPlanOut, BillingInvoiceOut, BillingInvoicesOut, BillingAddressIn } from '@/lib/server/pipeline';

export async function getBillingStatus(customerId: string): Promise<BillingStatusOut> {
  return billingStatus(customerId);
}

export async function getBillingPlans(customerId: string): Promise<BillingPlanOut[]> {
  const { plans } = await billingPlans(customerId);
  return plans;
}

export async function getBillingInvoices(
  customerId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<BillingInvoicesOut> {
  return billingInvoices(customerId, opts);
}
