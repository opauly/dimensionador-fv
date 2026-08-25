// `GET /api/pipeline/reports/runs/[runId]/download` — the scheduled-report
// counterpart of `app/api/pipeline/reports/[jobId]/download/route.ts`
// (PLAN_PHASE17.md §3.7, §8 Step 7). A DIFFERENT route, not a reuse of the
// jobId one: a scheduled run is never a `vrm.jobs` row (Step 6's run-due is
// synchronous, no job created) — its own `vrm.report_runs.id` is the only
// handle a customer's browser ever gets, and `getReportRunScoped()`'s own
// `customer_id` check is what stops that id from naming another tenant's
// report, the same "the row itself proves ownership" shape `getJobScoped()`
// already uses for `vrm.jobs`.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getReportRunScoped } from '@/lib/server/db';
import { createReportDownloadUrl } from '@/lib/server/storage';

export async function GET(_request: Request, { params }: { params: Promise<{ runId: string }> }) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const { runId } = await params;
  const run = await getReportRunScoped(runId, session.customerId);
  if (!run || run.status !== 'done' || !run.storage_path) {
    return NextResponse.json({ error: 'not_ready' }, { status: 409 });
  }

  const url = await createReportDownloadUrl(run.storage_path);
  return NextResponse.json({ url, filename: `Report - ${run.site_id} - ${run.period_end}.pdf` });
}
