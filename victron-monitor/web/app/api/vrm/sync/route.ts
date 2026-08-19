// `POST /api/vrm/sync` — kicks off a `vrm_sync` job for one of this
// customer's own already-connected sites (PLAN_PHASE15.md §8 Step 5).
// `requireCustomerForRoute()` first statement; `assertOwnsSite()` re-checked
// here even though the site list this button renders from was already
// scoped to this customer (§1.12 rule 3, same reasoning as
// `ingest/preview/route.ts`) — `vrm_api`'s own `tenancy.assert_owns_site()`
// re-derives the same fact independently regardless (§3.2 control 3's real
// enforcement point). Returns `{job_id}`, same shape every other
// job-creating route in this app already returns — the browser polls it via
// the existing, kind-agnostic `/api/pipeline/jobs/[id]` proxy and
// `JobProgress`, unchanged.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, NotAuthorized } from '@/lib/server/db';
import { vrmSync, toErrorResponse } from '@/lib/server/pipeline';

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'expected YYYY-MM-DD');

const bodySchema = z.object({
  siteId: z.string().trim().min(1),
  start: isoDate,
  end: isoDate,
});

export async function POST(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  const body = parsed.data;

  try {
    await assertOwnsSite(session.customerId, body.siteId);
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    throw err;
  }

  try {
    const result = await vrmSync({ customer_id: session.customerId, site_id: body.siteId, start: body.start, end: body.end });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
