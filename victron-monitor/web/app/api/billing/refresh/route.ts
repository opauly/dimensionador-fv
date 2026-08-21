// `POST /api/billing/refresh` — PLAN_PHASE16.md §5.3/§8 Step 5. Proxies
// `vrm_api`'s own `POST /v1/billing/refresh` — a plain reconcile, what
// `PaymentMethodPanel.tsx` calls after the ONVO SDK's own `onSuccess` fires
// (§5.2: "onSuccess is a hint to refresh, never a state change" — its exact
// payload shape is undocumented, §0.2, so this app never parses it into
// state, only uses it as a trigger to re-read the truth from here).
//
// Rate-limited per customer (§5.3's own note: "Rate-limiting this per
// customer is Next.js's job" — `vrm_api`'s own endpoint has none of its
// own, same division of responsibility §6.5 already uses for the webhook).
// DB-backed (§3.8/§6.5's own reasoning — an in-process counter would be
// near-useless on a serverless deployment), keyed by `customer_id` so one
// customer's retry storm can never exhaust another's budget.
import { NextResponse } from 'next/server';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingRefresh, toErrorResponse } from '@/lib/server/pipeline';
import { checkRateLimit } from '@/lib/server/ratelimit';

const RATE_LIMIT_WINDOW_SECONDS = 60;
const RATE_LIMIT_MAX = 12;

export async function POST() {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const allowed = await checkRateLimit('billing_refresh', session.customerId, RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_MAX);
  if (!allowed) return NextResponse.json({ error: 'rate_limited' }, { status: 429 });

  try {
    const result = await billingRefresh(session.customerId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
