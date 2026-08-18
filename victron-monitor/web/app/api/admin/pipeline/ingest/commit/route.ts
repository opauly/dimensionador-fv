// `POST /api/admin/pipeline/ingest/commit` — admin-side counterpart of
// `app/api/pipeline/ingest/commit`. No customer_id scoping on the job
// lookup (unlike the customer route's `getJobScoped()`) — an admin session
// has no `customerId` to scope by, and is allowed to commit any job by
// design; `getJob()` (vrm_api's own, not customer-scoped either — see its
// own docstring) is enough here.
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getJob, ingestCommit, toErrorResponse } from '@/lib/server/pipeline';

const bodySchema = z.object({ jobId: z.string().trim().min(1) });

export async function POST(request: Request) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const parsed = bodySchema.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: 'invalid_request' }, { status: 400 });

  try {
    const job = await getJob(parsed.data.jobId);
    if (!job || job.kind !== 'ingest_preview' || job.status !== 'done') {
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
