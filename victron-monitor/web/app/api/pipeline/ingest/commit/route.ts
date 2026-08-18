// `POST /api/pipeline/ingest/commit` — the "actually write it" leg. Takes
// only the *preview* job's id, not a customer/site id of its own to trust
// or distrust (PLAN_PHASE14.md §2 Step 6) — the tenant and the parsed data
// are both already fixed, unforgeably, on that stored job row.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getJobScoped, ingestCommit, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({ jobId: z.string().trim().min(1) });

export async function POST(request: Request) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    // `getJobScoped()` is this route's own "the caller already checked, but
    // I don't trust that" step — it re-derives who owns `jobId` from the
    // job row itself, so a commit call for a preview job that belongs to
    // another customer 403s here even before it reaches vrm_api's own
    // (separately enforced) tenant fixing in `ingest_commit`.
    const job = await getJobScoped(parsed.data.jobId, session.customerId);
    if (job.kind !== 'ingest_preview' || job.status !== 'done') {
      return NextResponse.json({ error: 'job_not_ready' }, { status: 409 });
    }
    const result = await ingestCommit(parsed.data.jobId);
    return NextResponse.json(result);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
