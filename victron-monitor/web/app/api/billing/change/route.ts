// `POST /api/billing/change` — PLAN_PHASE16.md §5.3/§8 Step 5 (Q3 final:
// cancel-and-restart, no proration, both directions immediate). Proxies
// `vrm_api`'s own `POST /v1/billing/subscription/change`. `plan_id` is OUR
// OWN `vrm.plans.id`, re-validated server-side (§6.4 control 3). `confirm`
// is the over-site-limit guard's second call (§5.3/Q5(b)) — the first call
// without it, when the target plan's site_limit is below the customer's
// active site count, comes back `409 over_site_limit` with the real numbers
// (`requires_confirmation`, `current_site_count`, `new_site_limit`), which
// `PlanPicker.tsx` surfaces before ever sending `confirm: true`.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingChange, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({
  plan_id: z.string().trim().min(1),
  confirm: z.boolean().optional(),
});

export async function POST(request: Request) {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await billingChange({
      customer_id: session.customerId,
      plan_id: parsed.data.plan_id,
      confirm: parsed.data.confirm ?? false,
    });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
