// `GET /api/pipeline/vrm-fleet/site-savings` — customer-scoped counterpart
// of `/api/admin/pipeline/vrm-fleet/site-savings`. Same shape as this
// directory's own `site-shape/route.ts`: `assertOwnsSite()` +
// `getDashboardAccess()` before ever calling `getSiteSavings()`. See that
// file's own comment for why both checks are independently required.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, getCustomer, getDashboardAccess, NotAuthorized } from '@/lib/server/db';
import { getSiteSavings, toErrorResponse, type SiteShapeRange } from '@/lib/server/pipeline';

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
    const result = await getSiteSavings(siteId, range as SiteShapeRange);
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
