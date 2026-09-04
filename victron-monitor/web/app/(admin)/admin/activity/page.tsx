import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listAllIngestions, listAllReportRuns, listAllSites, listBillingEvents, listCustomers, listRecentSignups } from '@/lib/server/db/admin';
import { ActivityManager } from './ActivityManager';

export const metadata: Metadata = {
  title: 'Activity — Admin',
};

// `/admin/activity` (PLAN_PHASE14.md §2 Step 7; billing events + recent
// signups added PLAN_PHASE16.md §8 Step 6) — `vrm.ingestion_log` across
// all customers, most recent first, plus two more append-only/staging logs
// this same "cross-customer, most recent first" page reads directly rather
// than through `vrm_api` (no bulk-read endpoint exists for either, and none
// is needed — same reasoning as `listCustomers()`'s own subscription join).
// `pages/06_vrm_monitor.py` never had ANY of this — Phase 14 added the
// upload log, Phase 16 adds the two views that make an attempted webhook
// forgery and a signup spam wave visible to a human at all (§7's
// failure-modes table, same two rows).
export default async function AdminActivityPage() {
  await requireAdmin();
  const [ingestions, sites, customers, billingEvents, signups, reportRuns] = await Promise.all([
    listAllIngestions(200),
    listAllSites(),
    listCustomers(),
    listBillingEvents(100),
    listRecentSignups(50),
    listAllReportRuns(100),
  ]);

  const customerNameBySite = new Map<string, string>();
  const customerIdBySite = new Map<string, string>();
  const customerNameById = new Map(customers.map((c) => [c.id, c.name]));
  for (const s of sites) {
    customerNameBySite.set(s.site_id, customerNameById.get(s.customer_id) ?? '—');
    customerIdBySite.set(s.site_id, s.customer_id);
  }
  const displayNameBySite = new Map(sites.map((s) => [s.site_id, s.display_name]));

  return (
    <div>
      <h1>Activity</h1>
      <p className="mono page-desc">
        Upload log (<code>vrm.ingestion_log</code>) across all customers, most recent first.
      </p>
      <ActivityManager
        customers={customers}
        customerIdBySite={Object.fromEntries(customerIdBySite)}
        ingestions={ingestions}
        billingEvents={billingEvents}
        signups={signups}
        reportRuns={reportRuns}
        customerNameBySite={Object.fromEntries(customerNameBySite)}
        customerNameById={Object.fromEntries(customerNameById)}
        displayNameBySite={Object.fromEntries(displayNameBySite)}
      />
    </div>
  );
}
