import 'server-only';

// Signed download URLs for rendered report PDFs (PLAN_PHASE14.md §2 Step 6).
//
// This is the only Supabase Storage access this app does outside the
// upload-sign route (`app/api/uploads/sign`) — `vrm_api` owns the write
// (`vrm_api/routers/reports.py` uploads the PDF once a report job finishes),
// this just reads it back out with a short-lived URL so a customer's
// browser never holds a public or long-TTL link to their own report, only
// this app's own job-ownership check
// (`app/api/pipeline/reports/[jobId]/download`) stands between "give me
// this path" and getting a URL for it.
import { getSupabaseAdmin } from './supabase';

const BUCKET = 'vrm-monitor';
// Long enough for a click to actually start the download, short enough
// that a URL copied out of the network tab is useless a couple of minutes
// later — "short-TTL signed URL to the generated PDF, not a public URL"
// (PLAN_PHASE14.md §2 Step 6).
const DOWNLOAD_URL_TTL_SECONDS = 120;

export async function createReportDownloadUrl(storagePath: string): Promise<string> {
  const { data, error } = await getSupabaseAdmin().storage.from(BUCKET).createSignedUrl(storagePath, DOWNLOAD_URL_TTL_SECONDS);
  if (error || !data) {
    // Not a customer-facing message — route handlers that call this catch
    // and translate to a typed code, same rule as everywhere else Supabase
    // error text must not reach a browser (PLAN_PHASE14.md §1.12 rule 6).
    throw new Error(`Could not create a signed download URL for ${storagePath}: ${error?.message ?? 'unknown error'}`);
  }
  return data.signedUrl;
}
