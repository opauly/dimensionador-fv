// `POST /api/billing/subscribe` — PLAN_PHASE16.md §5.2/§8 Step 5, corrected
// 2026-08-20. Proxies `vrm_api`'s own `POST /v1/billing/subscription`.
// `plan_id` is OUR OWN `vrm.plans.id` (re-validated server-side inside
// `vrm_api`, §6.4 control 3) — never an ONVO `priceId`. Deliberately NO
// `payment_method_id` in the body any more: the ONVO subscription this call
// creates has no card attached at all — the SDK widget that collects the
// card needs the returned `onvo_subscription_id` to render in the first
// place (`PaymentMethodPanel.tsx`), so a browser cannot possibly hold a
// `payment_method_id` before calling this. `requireCustomerForRouteAllowPending()`
// first; `customer_id` is always `session.customerId`, never anything from
// the body.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingSubscribe, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({
  plan_id: z.string().trim().min(1),
});

export async function POST(request: Request) {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await billingSubscribe({
      customer_id: session.customerId,
      plan_id: parsed.data.plan_id,
    });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
