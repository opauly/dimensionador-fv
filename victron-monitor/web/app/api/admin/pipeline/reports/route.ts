// `POST /api/admin/pipeline/reports` — admin-side counterpart of
// `app/api/pipeline/reports` (PLAN_PHASE14.md §2 Step 7's `/admin/reports`:
// "both `vrm` and `monitoring` schemas selectable, `actor: 'admin'` set on
// every call"). Unlike the customer route, `schema` IS a real request field
// here — this is the one surface allowed to ask for `monitoring` at all
// (§1.12 rule 2 only restricts the *customer-facing* surface).
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { assertOwnsSite, NotAuthorized } from '@/lib/server/db';
import { createReport, getLimits, toErrorResponse } from '@/lib/server/pipeline';

function daysBetween(start: string, end: string): number {
  const a = new Date(`${start}T00:00:00Z`).getTime();
  const b = new Date(`${end}T00:00:00Z`).getTime();
  return Math.round((b - a) / 86_400_000) + 1;
}

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'expected YYYY-MM-DD');

const bodySchema = z.object({
  customerId: z.string().trim().min(1),
  siteId: z.string().trim().min(1),
  start: isoDate,
  end: isoDate,
  schema: z.enum(['vrm', 'monitoring']),
});

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    // Only `vrm` sites have an ownership fact to check — `monitoring` sites
    // have no `vrm.customers` owner at all (PLAN_PHASE14.md §1.12 rule 2's
    // own reasoning, restated for meta.py's `available-dates` extension).
    // `vrm_api/routers/reports.py` re-derives the same distinction
    // independently regardless of what this check already confirmed.
    if (parsed.data.schema === 'vrm') {
      await assertOwnsSite(parsed.data.customerId, parsed.data.siteId);
    }

    const numDays = daysBetween(parsed.data.start, parsed.data.end);
    if (numDays > 0) {
      const limits = await getLimits();
      if (numDays > limits.max_overview_range_days) {
        return NextResponse.json({ error: 'range_too_long', maxDays: limits.max_overview_range_days }, { status: 400 });
      }
    }

    const result = await createReport({
      customer_id: parsed.data.customerId,
      site_id: parsed.data.siteId,
      start: parsed.data.start,
      end: parsed.data.end,
      schema: parsed.data.schema,
      actor: 'admin',
    });
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
