import type { Metadata } from 'next';
import { requireCustomerAllowPending } from '@/lib/server/auth';
import { getBillingStatus } from '@/lib/server/db';
import { BillingManager } from './BillingManager';

export const metadata: Metadata = {
  title: 'Billing',
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// `app/(portal)/app/billing` (PLAN_PHASE16.md §8 Step 5). One of the three
// call sites that opt out of `requireCustomer()`'s pending-account gate via
// `requireCustomerAllowPending()` (§6.4/§8 Step 5.5) — this page IS the
// destination that gate redirects a `pending_subscription` customer to, so
// gating it too would redirect it to itself.
//
// `firstRun` is derived here, once, from the SAME status read the page
// already needs for the rest of `BillingManager` — not a second query
// (`BillingStatusOut.provisioning_state`, §5.1's own docstring: "so
// `/app/billing` can render its first-run variant from the same object it
// already fetches, rather than a second query").
export default async function BillingPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const session = await requireCustomerAllowPending();
  const status = await getBillingStatus(session.customerId);
  const firstRun = status.provisioning_state === 'pending_subscription';

  // `?plan=` — the id the customer picked on `/signup` (PLAN_PHASE16.md
  // §5.5 Step 2's redirect target: `/app/billing?plan=<plan_id>`). Only
  // ever used to highlight a card in `PlanPicker`, never to auto-select or
  // auto-submit anything — validated as a real uuid shape here (same
  // pattern `/signup/page.tsx` already uses) so a malformed/stale value
  // just fails the `initialPlanId` match silently instead of doing
  // anything with an unvalidated string.
  const params = await searchParams;
  const rawPlan = typeof params.plan === 'string' ? params.plan : null;
  const initialPlanId = rawPlan && UUID_RE.test(rawPlan) ? rawPlan : null;

  return <BillingManager status={status} lang={session.uiLanguage} firstRun={firstRun} initialPlanId={initialPlanId} />;
}
