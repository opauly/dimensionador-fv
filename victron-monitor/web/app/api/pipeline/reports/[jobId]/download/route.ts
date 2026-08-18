// `GET /api/pipeline/reports/[jobId]/download` — hands the browser a
// short-TTL signed URL for a finished report's PDF, never a public or
// long-lived one (PLAN_PHASE14.md §2 Step 6). `jobId`, not a storage path,
// is what the browser gets to name: the path itself only ever comes out of
// a job this route has already confirmed belongs to the caller
// (`getJobScoped()`), so there is no way to ask this route for an arbitrary
// object in the bucket.
import { NextResponse } from 'next/server';
import { requireCustomerForRoute } from '@/lib/server/auth';
import { getJobScoped, toErrorResponse } from '@/lib/server/pipeline';
import { createReportDownloadUrl } from '@/lib/server/storage';

export async function GET(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const session = await requireCustomerForRoute();
  if (session instanceof NextResponse) return session;

  const { jobId } = await params;
  try {
    const job = await getJobScoped(jobId, session.customerId);
    const storagePath = job.result?.storage_path;
    if (job.kind !== 'report' || job.status !== 'done' || typeof storagePath !== 'string') {
      return NextResponse.json({ error: 'not_ready' }, { status: 409 });
    }

    const url = await createReportDownloadUrl(storagePath);
    const summary = job.result?.summary as { siteName?: string; endStr?: string } | undefined;
    const filename = summary?.siteName && summary?.endStr ? `Report - ${summary.siteName} - ${summary.endStr}.pdf` : 'report.pdf';
    return NextResponse.json({ url, filename });
  } catch (err) {
    const res = toErrorResponse(err);
    if (res) return res;
    throw err;
  }
}
