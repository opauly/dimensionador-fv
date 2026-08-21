// `PUT /api/billing/address` — PLAN_PHASE16.md §5.3/§8 Step 5. Proxies
// `vrm_api`'s own `PUT /v1/billing/address`, which writes to ONVO first and
// mirrors only from the subsequent reconcile — never from this request body
// directly (§0.5). Zod shape mirrors `vrm_api/schemas.py:BillingAddressIn`
// field-for-field (ONVO's own billing-address shape).
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingAddress, toErrorResponse } from '@/lib/server/pipeline';

const addressSchema = z.object({
  city: z.string().trim().max(200).optional(),
  country: z.string().trim().max(2).optional(),
  line1: z.string().trim().max(200).optional(),
  line2: z.string().trim().max(200).optional(),
  postalCode: z.string().trim().max(20).optional(),
  state: z.string().trim().max(200).optional(),
});

const bodySchema = z.object({ address: addressSchema });

export async function PUT(request: Request) {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await billingAddress({ customer_id: session.customerId, address: parsed.data.address });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
