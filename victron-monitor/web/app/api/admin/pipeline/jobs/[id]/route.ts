// `GET /api/admin/pipeline/jobs/[id]` — admin-side counterpart of
// `app/api/pipeline/jobs/[id]`. Not customer-scoped: an admin session has
// no `customerId`, and is allowed to see any job by design (this is the
// same `AppShell` role that reaches `/admin/sites` across every customer —
// PLAN_PHASE14.md §2 Step 7's own validation checklist for that).
import { NextResponse } from 'next/server';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getJob, toErrorResponse } from '@/lib/server/pipeline';

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const { id } = await params;
  try {
    const job = await getJob(id);
    if (!job) return NextResponse.json({ error: 'not_found' }, { status: 404 });
    return NextResponse.json(job);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
