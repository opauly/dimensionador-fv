// `POST /api/billing/resume` — PLAN_PHASE16.md §5.3/§8 Step 5. Proxies
// `vrm_api`'s own `POST /v1/billing/subscription/resume`, which clears a
// pending `cancelAtPeriodEnd` (confirmed live, §0.2b finding 12). No
// request body — nothing to carry beyond `customer_id`, which is always
// `session.customerId`.
import { NextResponse } from 'next/server';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingResume, toErrorResponse } from '@/lib/server/pipeline';

export async function POST() {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  try {
    const result = await billingResume(session.customerId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
