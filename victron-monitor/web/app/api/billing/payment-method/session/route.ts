// `POST /api/billing/payment-method/session` — PLAN_PHASE16.md §5.3,
// corrected at Step 5 (2026-08-20) alongside `/api/billing/subscribe`.
// Proxies `vrm_api`'s own `POST /v1/billing/payment-method/session`: the
// REPLACE-CARD path for a customer who ALREADY has a live subscription
// (first-time subscribe gets its `onvo_subscription_id` straight from
// `POST /api/billing/subscribe` and never calls this route at all). Hands
// back `{onvo_subscription_id, onvo_customer_id, publishable_key}` — the
// ONVO SDK widget (`PaymentMethodPanel.tsx`) needs the real subscription id
// to render a working card form, not just a customer id. None of these
// values is a secret (§6.2: a vendor does not put a credential in a
// `<script>` parameter; the publishable key is designed to be public) but
// this route still only ever reaches the browser as a fetch response a
// Client Component asked for, never a build-time `NEXT_PUBLIC_*` inlining
// (§6.1). Refused with `no_active_subscription` if the customer has no live
// subscription to attach a new card to.
import { NextResponse } from 'next/server';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingPaymentMethodSession, toErrorResponse } from '@/lib/server/pipeline';

export async function POST() {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  try {
    const result = await billingPaymentMethodSession(session.customerId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
