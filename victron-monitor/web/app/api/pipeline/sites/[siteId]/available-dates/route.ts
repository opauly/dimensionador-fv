// `GET /api/pipeline/sites/[siteId]/available-dates` — bounds the Reports
// page's range picker to real data (PLAN_PHASE14.md §2 Step 6). Wraps
// `vrm_api`'s own `GET /v1/sites/{site_id}/available-dates`, which itself
// re-checks `customer_id` owns `site_id` — this route's `assertOwnsSite()`
// is the Next-side half of that same two-independent-checks pattern.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, NotAuthorized } from '@/lib/server/db';
import { getAvailableDates, toErrorResponse } from '@/lib/server/pipeline';

export async function GET(_request: Request, { params }: { params: Promise<{ siteId: string }> }) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const { siteId } = await params;
  try {
    await assertOwnsSite(session.customerId, siteId);
    const dates = await getAvailableDates(siteId, session.customerId);
    return NextResponse.json({ dates });
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
