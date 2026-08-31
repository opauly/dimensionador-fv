// `GET /api/admin/pipeline/vrm-fleet/site-savings` — proxies `vrm_api`'s
// `GET /v1/vrm-fleet/site-savings` (Fleet Dashboard Phase 2.5). Same shape
// as `site-shape/route.ts`: `requireAdminForRoute()` is the only gate,
// called client-side from `ShapeChart.tsx` on every range change.
import { NextResponse } from 'next/server';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getSiteSavings, toErrorResponse, type SiteShapeRange } from '@/lib/server/pipeline';

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
    const result = await getSiteSavings(siteId, range as SiteShapeRange);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
