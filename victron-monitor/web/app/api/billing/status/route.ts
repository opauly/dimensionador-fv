// `GET /api/billing/status` — PLAN_PHASE16.md §5.1/§8 Step 5. Proxies
// `vrm_api`'s own `GET /v1/billing/status`, which applies §4.4's on-read
// staleness refresh itself; this route adds nothing beyond the tenancy
// check. `requireCustomerForRouteAllowPending()` first statement, `customer_id` is
// always `session.customerId` — same shape as `app/api/vrm/connect/route.ts`.
//
// `...AllowPending`, not the plain `requireCustomerForRoute()` every other
// `app/api/*` route uses (PLAN_PHASE16.md §6.4/§8 Step 5.5): every route
// under `app/api/billing/*` is one of the three opt-outs from the
// pending-account gate, because a `pending_subscription` customer's ONLY
// job in this app is to finish this exact flow (see plans/status/subscribe
// below) — gating billing itself would make first-time checkout
// impossible. Same choice repeated verbatim across every file in this
// directory; documented once here rather than in all eleven.
import { NextResponse } from 'next/server';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingStatus, toErrorResponse } from '@/lib/server/pipeline';

export async function GET() {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  try {
    const result = await billingStatus(session.customerId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
