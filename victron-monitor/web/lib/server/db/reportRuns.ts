import 'server-only';

// Read-only access to `vrm.report_runs` (PLAN_PHASE17.md §5.2, §8 Step 7) —
// the customer-facing report history and the admin recent-runs panel both
// read through this file. Every write to this table happens exclusively in
// `vrm_api/report_runs.py` (the scheduler's own ledger); nothing in this
// app ever inserts or updates a row here — there is deliberately no
// `createReportRun()`/`updateReportRun()` in this module.
import { getSupabaseAdmin } from '@/lib/server/supabase';

/** PLAN_PHASE17.md §3.4's status vocabulary. No CHECK constraint on the
 * database column (same reasoning as `vrm.subscriptions.status` — a
 * vocabulary that grows should not be able to fail an insert in a
 * background job), so this stays a plain `string` rather than a closed
 * union — `reportRunStatusLabel()` below falls back to the raw value for
 * anything it doesn't recognize instead of a type error. */
export type ReportRunRecord = {
  id: string;
  customer_id: string;
  site_id: string;
  trigger: 'scheduled' | 'manual' | 'admin';
  schedule: string | null;
  period_start: string;
  period_end: string;
  status: string;
  attempt_count: number;
  storage_path: string | null;
  job_id: string | null;
  recipients: string[] | null;
  email_status: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

const REPORT_RUN_COLUMNS =
  'id, customer_id, site_id, trigger, schedule, period_start, period_end, status, attempt_count, storage_path, job_id, recipients, email_status, error, created_at, updated_at';

/**
 * This customer's own report history, newest first — `/app`'s Reports area
 * (PLAN_PHASE17.md §3.7). Tenant-scoped by the `.eq('customer_id', ...)`
 * below, the same single-predicate pattern every other tenant-scoped list
 * in this directory uses (`sites.ts:listSites()`).
 */
export async function listReportRuns(customerId: string, limit = 50): Promise<ReportRunRecord[]> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('report_runs')
    .select(REPORT_RUN_COLUMNS)
    .eq('customer_id', customerId)
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data ?? []) as ReportRunRecord[];
}

/**
 * A single report-run row, scoped to `customerId` — the tenancy check for
 * the download route (`app/api/pipeline/reports/runs/[runId]/download`),
 * the same "the row itself proves ownership" shape `pipeline.ts:
 * getJobScoped()` uses for `vrm.jobs`. Returns `null` for "doesn't exist or
 * belongs to someone else" — deliberately not distinguished, same reasoning
 * as `tenancy.py:NotAuthorized` covering both cases with one outcome.
 */
export async function getReportRunScoped(runId: string, customerId: string): Promise<ReportRunRecord | null> {
  const { data, error } = await getSupabaseAdmin()
    .schema('vrm')
    .from('report_runs')
    .select(REPORT_RUN_COLUMNS)
    .eq('id', runId)
    .maybeSingle();
  if (error) throw error;
  if (!data || data.customer_id !== customerId) return null;
  return data as ReportRunRecord;
}
