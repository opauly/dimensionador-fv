import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listAllIngestions, listAllSites, listCustomers } from '@/lib/server/db/admin';
import { ActivityTable } from './ActivityTable';

export const metadata: Metadata = {
  title: 'Activity — Admin',
};

// `/admin/activity` (PLAN_PHASE14.md §2 Step 7) — `vrm.ingestion_log`
// across all customers, newest first. `pages/06_vrm_monitor.py` never had
// this view at all (its own `_sites()`/`_customers()` helpers exist for
// the Sitios/Cargar/Reporte tabs, not an audit log) — this is the first
// UI anywhere in this repo that reads `ingestion_log` for "why did this
// report look wrong" across every customer at once, the reason that table
// exists (`lib/server/db/ingestions.ts`'s own comment).
export default async function AdminActivityPage() {
  await requireAdmin();
  const [ingestions, sites, customers] = await Promise.all([listAllIngestions(200), listAllSites(), listCustomers()]);

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
    </div>
  );
}
