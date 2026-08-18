'use server';

import 'server-only';

// Server Actions for `/admin/reports` (PLAN_PHASE14.md §2 Step 7) — the
// plain reads this page needs that aren't the report-job flow itself
// (which goes through `app/api/admin/pipeline/reports*`, matching
// `JobProgress`'s fetch-based polling contract). Called directly from
// `AdminReportsManager.tsx`'s effects, same "plain async Server Action"
// shape as `app/(admin)/admin/upload/actions.ts`.
import { requireAdmin } from '@/lib/server/auth';
import { getAvailableDatesAdmin, getLimits, listSitesForSchema, type Limits, type Schema, type SiteSummary } from '@/lib/server/pipeline';

export async function getReportLimitsAction(): Promise<Limits | null> {
  await requireAdmin();
  try {
    return await getLimits();
  } catch {
    return null;
  }
}

export async function listMonitoringSitesAction(): Promise<SiteSummary[]> {
  await requireAdmin();
  try {
    return await listSitesForSchema('monitoring');
  } catch {
    return [];
  }
}

export async function getAvailableDatesForAdminAction(siteId: string, customerId: string, schema: Schema): Promise<string[]> {
  await requireAdmin();
  if (!siteId || !customerId) return [];
  try {
    return await getAvailableDatesAdmin(siteId, customerId, schema);
  } catch {
    // Same "empty list, not a thrown error" resilience the customer-facing
    // `ReportManager.tsx` already has for its own `fetch(...).catch(() =>
    // setDates([]))` — an admin picking a mismatched site/customer pair
    // (or vrm_api being briefly unreachable) should see "no data," not a
    // client-side error boundary.
    return [];
  }
}
