// `POST /api/billing/payment-method` — PLAN_PHASE16.md §5.3/§8 Step 5.
// Proxies `vrm_api`'s own `POST /v1/billing/payment-method`: attaches a
// `payment_method_id` the browser already created directly against ONVO
// (via `PaymentMethodPanel.tsx`'s SDK widget, primed by
// `POST /api/billing/payment-method/session`) to the customer's CURRENT
// subscription. Same "forward the opaque id, never act on it ourselves"
// contract as `/api/billing/subscribe` — `vrm_api` re-verifies it
// (`_verify_payment_method()`) before ever trusting it.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingPaymentMethod, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({ payment_method_id: z.string().trim().min(1) });

export async function POST(request: Request) {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await billingPaymentMethod({
      customer_id: session.customerId,
      payment_method_id: parsed.data.payment_method_id,
    });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
