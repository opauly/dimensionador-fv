// `GET /api/billing/plans` — PLAN_PHASE16.md §5.1/§8 Step 5. Proxies
// `vrm_api`'s own `GET /v1/billing/plans`, which already filters by
// `active`/`mode`/`account_types`, and additionally by `self_serve` when
// this customer is still `provisioning_state='pending_subscription'`
// (§3.1) — `PlanPicker.tsx` renders exactly what this returns with no
// further client-side filtering.
import { NextResponse } from 'next/server';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingPlans, toErrorResponse } from '@/lib/server/pipeline';

export async function GET() {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  try {
    const result = await billingPlans(session.customerId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
