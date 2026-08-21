// `GET /api/billing/invoices` — PLAN_PHASE16.md §5.1/§8 Step 5. Proxies
// `vrm_api`'s own `GET /v1/billing/invoices`, newest first, paginated.
// `limit`/`offset` are read from the query string and re-validated here
// (never trusted as-is) before being forwarded — `vrm_api`'s own Query(...)
// bounds (1-100 / >=0) are the real enforcement, this is just so a bad
// value fails as `invalid_request` instead of a raw 422 from `vrm_api`.
import { NextResponse } from 'next/server';
import { requireCustomerForRouteAllowPending } from '@/lib/server/auth';
import { billingInvoices, toErrorResponse } from '@/lib/server/pipeline';

export async function GET(request: Request) {
  const session = await requireCustomerForRouteAllowPending();
  if (session instanceof NextResponse) return session;

  const { searchParams } = new URL(request.url);
  const limitRaw = searchParams.get('limit');
  const offsetRaw = searchParams.get('offset');
  const limit = limitRaw !== null ? Number(limitRaw) : undefined;
  const offset = offsetRaw !== null ? Number(offsetRaw) : undefined;
  if ((limit !== undefined && (!Number.isInteger(limit) || limit < 1 || limit > 100)) ||
      (offset !== undefined && (!Number.isInteger(offset) || offset < 0))) {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  }

  try {
    const result = await billingInvoices(session.customerId, { limit, offset });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
