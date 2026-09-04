// `GET /api/pipeline/vrm-fleet/site-shape` — the customer-scoped
// counterpart of `/api/admin/pipeline/vrm-fleet/site-shape` (2026-09-03,
// customer-facing Fleet Dashboard). Two independent checks before ever
// calling `getSiteShape()`, same "the dropdown is UI; the guard is the
// control" discipline `assertOwnsSite()`'s own doc comment states: (1) the
// requested `siteId` actually belongs to this customer (assertOwnsSite —
// without this, a Growth customer could read ANY other customer's live PV/
// load/battery data just by guessing a site_id), and (2) this customer's
// plan is entitled to the dashboard at all (getDashboardAccess — a Starter
// customer must not get real data back just because they found the URL).
// Called client-side from `ShapeChart.tsx` (via its `apiBasePath` prop) on
// every range change, same as the admin route.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, getCustomer, getDashboardAccess, NotAuthorized } from '@/lib/server/db';
import { getSiteShape, toErrorResponse, type SiteShapeRange } from '@/lib/server/pipeline';

const VALID_RANGES: SiteShapeRange[] = ['today', 'week', 'month'];

export async function GET(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const url = new URL(request.url);
  const siteId = url.searchParams.get('siteId')?.trim();
  const range = url.searchParams.get('range');
  if (!siteId || !range || !VALID_RANGES.includes(range as SiteShapeRange)) {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  }

  try {
    const customer = await getCustomer(session.customerId);
    const allowed = await getDashboardAccess(customer);
    if (!allowed) return NextResponse.json({ error: 'not_entitled' }, { status: 403 });

    await assertOwnsSite(session.customerId, siteId);
    const result = await getSiteShape(siteId, range as SiteShapeRange);
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
