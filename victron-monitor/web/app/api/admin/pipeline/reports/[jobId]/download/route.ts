// `GET /api/admin/pipeline/reports/[jobId]/download` — admin-side
// counterpart of `app/api/pipeline/reports/[jobId]/download`. Not
// customer-scoped, same reasoning as the admin jobs-poll route.
import { NextResponse } from 'next/server';
import { requireAdminForRoute } from '@/lib/server/auth';
import { getJob, toErrorResponse } from '@/lib/server/pipeline';
import { createReportDownloadUrl } from '@/lib/server/storage';

export async function GET(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const session = await requireAdminForRoute();
  if (session instanceof NextResponse) return session;

  const { jobId } = await params;
  try {
    const job = await getJob(jobId);
    const storagePath = job?.result?.storage_path;
    if (!job || job.kind !== 'report' || job.status !== 'done' || typeof storagePath !== 'string') {
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
