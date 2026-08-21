// `POST /api/billing/cancel` — PLAN_PHASE16.md §5.3/§8 Step 5 (Q4: graceful
// cancel only in the customer-facing UI). Proxies `vrm_api`'s own
// `POST /v1/billing/subscription/cancel`, which itself also implements
// `mode: 'immediate'` — but that value is deliberately NOT in this route's
// Zod schema: Q4's answer is "graceful only in v1, with immediate available
// to Oscar from /admin as a support action" (§0.6 Q4), and `vrm_api`'s own
// docstring says explicitly that the only thing standing between a
// customer and an immediate cancel is which route calls it, not a role
// check inside `vrm_api` itself. Restricting this customer-facing route's
// schema to the single literal `'at_period_end'` IS that boundary — Step 6
// (admin, someone else's job) is expected to be the only caller that ever
// sends `'immediate'`, through its own route, never through this one.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingCancel, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({ mode: z.literal('at_period_end') });

export async function POST(request: Request) {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await billingCancel({ customer_id: session.customerId, mode: parsed.data.mode });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
