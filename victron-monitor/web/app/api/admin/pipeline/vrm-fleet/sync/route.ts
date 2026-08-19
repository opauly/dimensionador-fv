// `POST /api/admin/pipeline/vrm-fleet/sync` — proxies `vrm_api`'s
// `POST /v1/vrm-fleet/sync` (PLAN_PHASE15.md §3.3 / §8 Step 4b). No
// `assertOwnsSite()` here — deliberately: there is no customer session on
// this side either (an admin session has no `customerId`), and `vrm_api`'s
// own router already explains why a per-site ownership check does not apply
// to this flow (`vrm_api/routers/vrm_fleet.py`'s module docstring). The
// admin gate is `requireAdminForRoute()` below, the same first-statement
// pattern every other `app/api/admin/pipeline/*` route already uses.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { syncVrmFleetSite, toErrorResponse } from '@/lib/server/pipeline';

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'expected YYYY-MM-DD');

const bodySchema = z.object({
  siteId: z.string().trim().min(1),
  start: isoDate,
  end: isoDate,
});

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  const body = parsed.data;

  try {
    const result = await syncVrmFleetSite({ site_id: body.siteId, start: body.start, end: body.end });
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
