'use client';

// Shared Origin filter for `/admin/activity`'s four cross-customer tables
// (PLAN_PHASE14.md §2 Step 7 / PLAN_PHASE16.md §8 Step 6 tables) — same
// admin/self-serve distinction `/admin/customers` filters by (its own
// `origin` column): Oscar's own admin-linked installations vs. real
// signed-up subscribers. One control here governs all four tables rather
// than four separate ones, since they're all views of the same
// cross-customer activity log at different granularities.
//
// A row with no resolvable customer (a rejected/forged billing webhook, an
// unverified signup) always stays visible regardless of the filter — it
// can't be classified by origin, and hiding it would defeat the one thing
// this page exists to surface (PLAN_PHASE16.md §7's "the only evidence an
// attempt happened").
import { useMemo, useState } from 'react';
import { Select } from '@/components/ui';
import type { IngestionLogRecord, ReportRunRecord } from '@/lib/server/db';
import type { BillingEventRecord } from '@/lib/server/db/types';
import type { AdminCustomerRow, AdminSignupRow } from '@/lib/server/db/admin';
import { ActivityTable } from './ActivityTable';
import { BillingEventsTable } from './BillingEventsTable';
import { RecentSignupsPanel } from './RecentSignupsPanel';
import { ReportRunsTable } from './ReportRunsTable';
import styles from './activity.module.css';

type OriginFilter = 'all' | 'admin' | 'self_serve';

export function ActivityManager({
  customers,
  customerIdBySite,
  ingestions,
  billingEvents,
  signups,
  reportRuns,
  customerNameBySite,
  customerNameById,
  displayNameBySite,
}: {
  customers: AdminCustomerRow[];
  customerIdBySite: Record<string, string>;
  ingestions: IngestionLogRecord[];
  billingEvents: BillingEventRecord[];
  signups: AdminSignupRow[];
  reportRuns: ReportRunRecord[];
  customerNameBySite: Record<string, string>;
  customerNameById: Record<string, string>;
  displayNameBySite: Record<string, string>;
}) {
  const [originFilter, setOriginFilter] = useState<OriginFilter>('all');
  const originById = useMemo(() => new Map(customers.map((c) => [c.id, c.origin])), [customers]);

  function matchesOrigin(customerId: string | null | undefined): boolean {
    if (originFilter === 'all' || !customerId) return true;
    return originById.get(customerId) === originFilter;
  }

  const filteredIngestions = useMemo(
    () => ingestions.filter((log) => matchesOrigin(customerIdBySite[log.site_id])),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- matchesOrigin is rebuilt fresh every render from stable inputs already listed
    [ingestions, customerIdBySite, originById, originFilter],
  );
  const filteredBillingEvents = useMemo(
    () => billingEvents.filter((ev) => matchesOrigin(ev.customer_id)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [billingEvents, originById, originFilter],
  );
  const filteredSignups = useMemo(
    () => signups.filter((s) => matchesOrigin(s.customer_id)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signups, originById, originFilter],
  );
  const filteredReportRuns = useMemo(
    () => reportRuns.filter((run) => matchesOrigin(run.customer_id)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [reportRuns, originById, originFilter],
  );

  return (
    <div>
      <div className={styles.filtersRow}>
        <label className={styles.filterLabel}>
          Origin
          <Select value={originFilter} onChange={(e) => setOriginFilter(e.target.value as OriginFilter)}>
            <option value="all">All</option>
            <option value="admin">Admin</option>
            <option value="self_serve">Self-serve</option>
          </Select>
        </label>
      </div>

      <ActivityTable ingestions={filteredIngestions} customerNameBySite={customerNameBySite} displayNameBySite={displayNameBySite} />

      <h2 style={{ marginTop: 36 }}>Billing events</h2>
      <p className="mono page-desc">
        ONVO webhook deliveries (<code>vrm.billing_events</code>), most recent first — including rejected-secret
        deliveries, the only visible evidence an attempted forgery happened.
      </p>
      <BillingEventsTable events={filteredBillingEvents} customerNameById={customerNameById} />

      <h2 style={{ marginTop: 36 }}>Recent signups</h2>
      <p className="mono page-desc">
        Public <code>/signup</code> requests (<code>vrm.signup_requests</code>), most recent first — the only place a
        spam wave is visible before it shows up in the Resend bill.
      </p>
      <RecentSignupsPanel signups={filteredSignups} customerNameById={customerNameById} />

      <h2 style={{ marginTop: 36 }}>Scheduled reports</h2>
      <p className="mono page-desc">
        <code>vrm.report_runs</code>, most recent first — the detection surface for &quot;the scheduled-reports
        cron silently stopped&quot; (a GitHub Actions workflow with no commits for 60 days gets disabled
        automatically). &quot;Run due reports now&quot; is the same manual spot-check a <code>workflow_dispatch</code>{' '}
        trigger gives the GitHub Actions side.
      </p>
      <ReportRunsTable runs={filteredReportRuns} customerNameById={customerNameById} displayNameBySite={displayNameBySite} />
    </div>
  );
}
