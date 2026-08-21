import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listAllIngestions, listAllSites, listBillingEvents, listCustomers, listRecentSignups } from '@/lib/server/db/admin';
import { ActivityTable } from './ActivityTable';
import { BillingEventsTable } from './BillingEventsTable';
import { RecentSignupsPanel } from './RecentSignupsPanel';

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
  const [ingestions, sites, customers, billingEvents, signups] = await Promise.all([
    listAllIngestions(200),
    listAllSites(),
    listCustomers(),
    listBillingEvents(100),
    listRecentSignups(50),
  ]);

  const customerNameBySite = new Map<string, string>();
  const customerNameById = new Map(customers.map((c) => [c.id, c.name]));
  for (const s of sites) {
    customerNameBySite.set(s.site_id, customerNameById.get(s.customer_id) ?? '—');
  }
  const displayNameBySite = new Map(sites.map((s) => [s.site_id, s.display_name]));

  return (
    <div>
      <h1>Activity</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Upload log (<code>vrm.ingestion_log</code>) across all customers, most recent first.
      </p>
      <ActivityTable ingestions={ingestions} customerNameBySite={Object.fromEntries(customerNameBySite)} displayNameBySite={Object.fromEntries(displayNameBySite)} />

      <h2 style={{ marginTop: 36 }}>Billing events</h2>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        ONVO webhook deliveries (<code>vrm.billing_events</code>), most recent first — including rejected-secret
        deliveries, the only visible evidence an attempted forgery happened.
      </p>
      <BillingEventsTable events={billingEvents} customerNameById={Object.fromEntries(customerNameById)} />

      <h2 style={{ marginTop: 36 }}>Recent signups</h2>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Public <code>/signup</code> requests (<code>vrm.signup_requests</code>), most recent first — the only place a
        spam wave is visible before it shows up in the Resend bill.
      </p>
      <RecentSignupsPanel signups={signups} customerNameById={Object.fromEntries(customerNameById)} />
    </div>
  );
}
