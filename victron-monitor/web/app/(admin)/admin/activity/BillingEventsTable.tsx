'use client';

// `/admin/activity`'s "Billing events" section (PLAN_PHASE16.md §3.5, §7,
// §8 Step 6) — the append-only `vrm.billing_events` receipt log, newest
// first. Folded into this existing page as a second table below
// `ActivityTable` (rather than a standalone `/admin/billing-events` route)
// — the smaller, cleaner diff the coder brief explicitly allows, given this
// page already exists as "cross-customer log, most recent first" and this
// is exactly that, for a different source table.
//
// `secret_ok=false` rows are the ONE thing this table must make visibly
// distinguishable — per §7's failure-modes table, that row is "the only
// evidence an attempt happened" for a forged/leaked-secret webhook
// delivery. Marked with `.forgedBadge` (the design system's one warning
// color, `--signal` — same token `ActivityTable.tsx`'s own
// `.replacedBadge` already uses for "worth a look at a glance").
import { Fragment, useState } from 'react';
import { Table } from '@/components/ui';
import { formatDateTime } from '@/lib/dates';
import type { BillingEventRecord } from '@/lib/server/db/types';
import styles from './activity.module.css';

function statusClassName(status: string, secretOk: boolean): string {
  if (!secretOk) return styles.forgedBadge;
  if (status === 'error') return styles.forgedBadge;
  if (status === 'applied') return styles.appliedBadge;
  return styles.subtleBadge;
}

export function BillingEventsTable({
  events,
  customerNameById,
}: {
  events: BillingEventRecord[];
  customerNameById: Record<string, string>;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (events.length === 0) {
    return <p className={styles.empty}>No billing webhook deliveries recorded yet.</p>;
  }

  return (
    <Table>
      <thead>
        <tr>
          <th>Received</th>
          <th>Event type</th>
          <th>Secret</th>
          <th>Status</th>
          <th>Customer</th>
          <th>Error</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {events.map((ev) => (
          <Fragment key={ev.id}>
            <tr>
              <td>{formatDateTime(ev.received_at)}</td>
              <td className="mono">{ev.event_type ?? '—'}</td>
              <td>
                {ev.secret_ok ? (
                  'OK'
                ) : (
                  <span className={styles.forgedBadge}>REJECTED — bad/missing secret</span>
                )}
              </td>
              <td>
                <span className={statusClassName(ev.status, ev.secret_ok)}>{ev.status}</span>
              </td>
              <td>{ev.customer_id ? (customerNameById[ev.customer_id] ?? ev.customer_id) : '—'}</td>
              <td className={styles.subtle}>{ev.error ?? '—'}</td>
              <td>
                <button
                  type="button"
                  className={styles.expandButton}
                  onClick={() => setExpanded((e) => ({ ...e, [ev.id]: !e[ev.id] }))}
                >
                  payload {expanded[ev.id] ? '▲' : '▼'}
                </button>
              </td>
            </tr>
            {expanded[ev.id] && (
              <tr>
                <td colSpan={7} className={styles.warningsRow}>
                  <pre className={styles.payload}>{JSON.stringify(ev.payload, null, 2)}</pre>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </Table>
  );
}
