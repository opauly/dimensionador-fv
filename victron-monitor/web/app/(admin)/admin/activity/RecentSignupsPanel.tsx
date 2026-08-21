'use client';

// `/admin/activity`'s "Recent signups" panel (PLAN_PHASE16.md §3.7, §7,
// §8 Step 6) — reads `vrm.signup_requests` directly, newest first. Per the
// coder brief: "the only place a signup spam wave is visible before it
// shows up in the Resend bill." Placed on THIS page, next to billing
// events, rather than on `/admin/customers` — both are the same kind of
// concern (abuse/forgery visibility a human would otherwise never see),
// and `/admin/customers` is already the page that lists what a signup
// eventually BECOMES (a `vrm.customers` row with `origin='self_serve'`),
// not what it started as.
//
// `consumed_at` set = the visitor actually clicked their verification link
// and (per §5.5) is a real, if not-yet-paying, `vrm.customers` row now —
// `customer_id` links straight to it. Unconsumed = still just an email
// address that asked for a link; `expires_at` (24h, §3.7) is shown so a
// stale, never-clicked row reads as "expired," not "broken."
import type { AccountType } from '@/lib/server/db/types';
import type { AdminSignupRow } from '@/lib/server/db/admin';
import { formatDateTime } from '@/lib/dates';
import { Table } from '@/components/ui';
import styles from './activity.module.css';

function accountTypeLabel(t: AccountType): string {
  return t === 'installer' ? 'Installer' : 'Owner';
}

export function RecentSignupsPanel({
  signups,
  customerNameById,
}: {
  signups: AdminSignupRow[];
  customerNameById: Record<string, string>;
}) {
  if (signups.length === 0) {
    return <p className={styles.empty}>No signup requests recorded yet.</p>;
  }

  return (
    <Table>
      <thead>
        <tr>
          <th>Email</th>
          <th>Name</th>
          <th>Type</th>
          <th>Requested</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {signups.map((s) => {
          const expired = s.expired;
          return (
            <tr key={s.id}>
              <td className="mono">{s.email}</td>
              <td>{s.name}</td>
              <td>{accountTypeLabel(s.account_type)}</td>
              <td>{formatDateTime(s.created_at)}</td>
              <td>
                {s.consumed_at ? (
                  <span className={styles.appliedBadge}>
                    Verified {formatDateTime(s.consumed_at)}
                    {s.customer_id && ` → ${customerNameById[s.customer_id] ?? s.customer_id}`}
                  </span>
                ) : expired ? (
                  <span className={styles.subtleBadge}>Expired, unverified</span>
                ) : (
                  <span className={styles.subtleBadge}>Awaiting verification</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}
