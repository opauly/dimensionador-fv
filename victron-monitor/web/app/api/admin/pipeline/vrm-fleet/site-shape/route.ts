// `GET /api/admin/pipeline/vrm-fleet/site-shape` — proxies `vrm_api`'s
// `GET /v1/vrm-fleet/site-shape` (Fleet Dashboard Phase 2.5). Same shape as
// `vrm-fleet/sync/route.ts`: no `assertOwnsSite()` (no customer session on
// this side either), `requireAdminForRoute()` is the only gate, matching
// every other `app/api/admin/pipeline/*` route. Called client-side (not a
// Server Component data fetch) because the range toggle and series
// checkboxes on `/admin/fleet/[site_id]` need to re-fetch on every click —
// this route is what `SiteShapeChart.tsx`'s `fetch()` calls.
import { NextResponse } from 'next/server';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getSiteShape, toErrorResponse, type SiteShapeRange } from '@/lib/server/pipeline';

const VALID_RANGES: SiteShapeRange[] = ['today', 'week', 'month'];

export async function GET(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const url = new URL(request.url);
  const siteId = url.searchParams.get('siteId')?.trim();
  const range = url.searchParams.get('range');
  if (!siteId || !range || !VALID_RANGES.includes(range as SiteShapeRange)) {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 });
  }

  try {
    const result = await getSiteShape(siteId, range as SiteShapeRange);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
