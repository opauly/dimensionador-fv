// `POST /api/admin/pipeline/reports/run-due` — proxies `vrm_api`'s
// `POST /v1/reports/run-due` (PLAN_PHASE17.md §3.4/§3.7/§8 Step 7). The
// "Run due now" button on `/admin/activity` — the manual spot-check
// affordance for a scheduler that otherwise only runs from a GitHub Actions
// cron (Step 9, not built yet), same reasoning §3.7 gives for why this
// button exists at all: "the detection surface for 'the cron silently
// stopped.'" `requireAdminForRoute()` is the only gate — there is no
// customer session on this side, same as every other
// `app/api/admin/pipeline/*` route.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { reportsRunDue, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({ maxSites: z.number().int().positive().max(100).optional() });

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => ({})));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const result = await reportsRunDue(parsed.data.maxSites ?? 10);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
