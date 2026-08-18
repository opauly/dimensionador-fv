// `GET /api/pipeline/limits` — proxies `vrm_api`'s `GET /v1/limits`
// unchanged. `MAX_CUSTOM_RANGE_DAYS` / `MAX_OVERVIEW_RANGE_DAYS` are never
// hand-copied into TypeScript (PLAN_PHASE14.md §1.11) — this route (and
// `ReportManager.tsx`, which calls it) is what keeps the Detallado/Overview
// boundary from drifting between the Python pipeline and this UI. Still
// behind `requireCustomerForRoute()` even though the numbers aren't
// tenant-scoped data — this proxy has no anonymous route at all, on
// purpose, so nothing here becomes an unauthenticated probe of `vrm_api`.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getLimits, toErrorResponse } from '@/lib/server/pipeline';

export async function GET() {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  try {
    const limits = await getLimits();
    return NextResponse.json(limits);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
