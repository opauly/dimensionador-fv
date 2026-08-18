// `POST /api/pipeline/reports` — starts a report-rendering job for one of
// this customer's own sites (PLAN_PHASE14.md §2 Step 6). `schema` and
// `actor` are never read from the request body: this route hardcodes
// `schema: 'vrm'` / `actor: 'customer'` on every call it makes to `vrm_api`,
// because a customer-facing surface must never reach the `monitoring`
// schema or claim to be an admin (§1.12 rule 2) — there is no field in
// `bodySchema` a client could even set to try.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { assertOwnsSite, NotAuthorized } from '@/lib/server/db';
import { createReport, getLimits, toErrorResponse } from '@/lib/server/pipeline';

function daysBetween(start: string, end: string): number {
  const a = new Date(`${start}T00:00:00Z`).getTime();
  const b = new Date(`${end}T00:00:00Z`).getTime();
  return Math.round((b - a) / 86_400_000) + 1;
}

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

  try {
    // Next's half of §1.3's "two independent checks" — `vrm_api`'s own
    // `routers/reports.py` re-derives the same ownership fact from
    // `vrm.sites` before it schedules any work, regardless of what this
    // call already confirmed.
    await assertOwnsSite(session.customerId, parsed.data.siteId);

    // `database/vrm_report_db.py:fetch_report_window()` also enforces
    // `MAX_OVERVIEW_RANGE_DAYS`, but it does so by raising a plain
    // `ValueError` — `vrm_api/jobs.py:_safe_error_message()` only passes
    // `VrmCsvError`/`NotAuthorized` through verbatim, so that ValueError
    // would otherwise surface as the generic "Internal error" sentence
    // instead of a message a customer can act on. `ReportManager.tsx`
    // already disables the Generate button past this boundary (computed
    // from this same `GET /api/pipeline/limits` call) — this is that check's
    // server-side twin, so a request that bypasses the disabled button still
    // gets a clear, typed rejection instead of reaching vrm_api's fallback.
    const numDays = daysBetween(parsed.data.start, parsed.data.end);
    if (numDays > 0) {
      const limits = await getLimits();
      if (numDays > limits.max_overview_range_days) {
        return NextResponse.json({ error: 'range_too_long', maxDays: limits.max_overview_range_days }, { status: 400 });
      }
    }

    const result = await createReport({
      customer_id: session.customerId,
      site_id: parsed.data.siteId,
      start: parsed.data.start,
      end: parsed.data.end,
      schema: 'vrm',
      actor: 'customer',
    });
    return NextResponse.json(result);
  } catch (err) {
    if (err instanceof NotAuthorized) return NextResponse.json({ error: 'not_authorized' }, { status: 403 });
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
