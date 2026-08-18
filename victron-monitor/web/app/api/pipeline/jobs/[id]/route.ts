// `GET /api/pipeline/jobs/[id]` — the job-polling proxy PLAN_PHASE14.md
// §1.6 calls for: "the browser polls a Next.js route handler that proxies
// `GET /v1/jobs/{id}` (scoped: the handler refuses a job whose `customer_id`
// isn't the session's)". `vrm_api`'s own `GET /v1/jobs/{id}` answers to any
// holder of the pipeline key — it is deliberately not customer-scoped (see
// its own docstring) — so this route is where "is this actually your job"
// gets decided, not a formality restating a check `vrm_api` already made.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getJobScoped, toErrorResponse } from '@/lib/server/pipeline';

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const { id } = await params;
  try {
    // Refuses with 403 (not a filtered-away 404) a job whose customer_id
    // isn't this session's — the plan is explicit that this must be a
    // refusal, not silent filtering, per PLAN_PHASE14.md §2 Step 6.
    const job = await getJobScoped(id, session.customerId);
    return NextResponse.json(job);
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
