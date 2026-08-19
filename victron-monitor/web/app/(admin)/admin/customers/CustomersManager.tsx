'use client';

// Table + create/edit forms + invite actions for `/admin/customers`
// (PLAN_PHASE14.md §2 Step 7). Row-level actions (send/resend invite,
// activate/deactivate) are plain Server Actions invoked directly from
// `onClick` inside `startTransition` — the same "invoked directly ...
// wrapped in startTransition" shape
// `app/(portal)/app/sites/SiteForm.tsx:handleGeocodeClick` already
// establishes for a non-`<form>` server action call, not a new pattern.
import { Fragment, startTransition, useState } from 'react';
import { Button, Table } from '@/components/ui';
import { formatDate as formatDateShared } from '@/lib/dates';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import { planLabel } from '@/lib/plans';
import { countryLabel } from '@/lib/countries';
import { CreateCustomerForm } from './CreateCustomerForm';
import { EditCustomerForm } from './EditCustomerForm';
import { resendInviteAction, sendInviteAction, setActiveAction, disconnectVrmLinkAction } from './actions';
import styles from './customers.module.css';

function authStatusLabel(c: AdminCustomerRow): { text: string; className: string } {
  if (!c.auth_user_id) return { text: 'Not invited', className: styles.statusNone };
  if (!c.activated_at) return { text: `Invited ${formatDate(c.invited_at)}`, className: styles.statusInvited };
  return { text: `Active ${formatDate(c.activated_at)}`, className: styles.statusActive };
}

// The VRM link column (PLAN_PHASE15.md §8 Step 6) — three states, same
// `vrm_token_revoked_at`-set-by-either-path reasoning
// `lib/server/db/types.ts:CustomerRecord.vrm_token_revoked_at`'s own
// comment gives: a deliberate disconnect and a broken token both land in
// "Token revocado <date>" here, because from this table's point of view
// both mean the same thing — no live connection right now — and
// `vrm_token_last_error` (surfaced instead on the customer's own
// `/app`/`/app/sites` banner, not repeated here) is what distinguishes WHY
// for anyone who needs to know.
function vrmLinkStatusLabel(c: AdminCustomerRow): { text: string; className: string; connected: boolean } {
  if (c.vrm_token_revoked_at) {
    return { text: `Token revoked ${formatDate(c.vrm_token_revoked_at)}`, className: styles.statusRevoked, connected: false };
  }
  if (c.vrm_token_added_at) {
    return {
      text: `Connected ${c.vrm_account_email ?? '—'} since ${formatDate(c.vrm_token_added_at)}`,
      className: styles.statusActive,
      connected: true,
    };
  }
  return { text: 'Not connected', className: styles.statusNone, connected: false };
}

function formatDate(iso: string | null): string {
  // Delegates to lib/dates.ts's deterministic formatter (2026-08-19 — a
  // real Next.js hydration error surfaced this exact pattern elsewhere in
  // the admin UI). Kept as a local wrapper only for the null-safe
  // signature every call site in this file already relies on.
  if (!iso) return '—';
  return formatDateShared(iso);
}

export function CustomersManager({ customers }: { customers: AdminCustomerRow[] }) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});

  function runRowAction(id: string, fn: () => Promise<{ ok?: boolean; error?: string } | void>) {
    setRowBusy((b) => ({ ...b, [id]: true }));
    setRowError((e) => ({ ...e, [id]: '' }));
    startTransition(async () => {
      const result = await fn();
      setRowBusy((b) => ({ ...b, [id]: false }));
      if (result && 'error' in result && result.error) {
        setRowError((e) => ({ ...e, [id]: result.error! }));
      }
    });
  }

  return (
    <div>
      <Table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Plan</th>
            <th>Sites</th>
            <th>Last upload</th>
            <th>Access</th>
            <th>VRM</th>
            <th>Active</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {customers.map((c) => {
            const vrmLink = vrmLinkStatusLabel(c);
            return (
            <Fragment key={c.id}>
              <tr>
                <td>
                  {c.name}
                  <div className={styles.subtle}>
                    {c.slug} · {countryLabel(c.country)}
                  </div>
                </td>
                <td>{c.account_type === 'installer' ? 'Installer' : 'Owner'}</td>
                <td>{planLabel(c.plan)}</td>
                <td>
                  {c.siteCount}
                  {c.site_limit !== null ? ` / ${c.site_limit}` : ''}
                </td>
                <td>{c.lastUploadAt ? formatDate(c.lastUploadAt) : '—'}</td>
                <td>
                  <span className={authStatusLabel(c).className}>{authStatusLabel(c).text}</span>
                  {rowError[c.id] && <div className={styles.rowError}>{rowError[c.id]}</div>}
                </td>
                <td>
                  <span className={vrmLink.className}>{vrmLink.text}</span>
                </td>
                <td>
                  <span className={c.active ? styles.statusActive : styles.statusNone}>{c.active ? 'Yes' : 'No'}</span>
                </td>
                <td className={styles.actionsCell}>
                  <Button type="button" variant="ghost" onClick={() => setEditingId(editingId === c.id ? null : c.id)}>
                    Edit
                  </Button>
                  {c.auth_user_id ? (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={rowBusy[c.id]}
                      onClick={() => runRowAction(c.id, () => resendInviteAction(c.id))}
                    >
                      Resend invite
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={rowBusy[c.id]}
                      onClick={() => runRowAction(c.id, () => sendInviteAction(c.id))}
                    >
                      Send invite
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={rowBusy[c.id]}
                    onClick={() => runRowAction(c.id, () => setActiveAction(c.id, !c.active))}
                  >
                    {c.active ? 'Deactivate' : 'Activate'}
                  </Button>
                  {vrmLink.connected && (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={rowBusy[c.id]}
                      onClick={() => {
                        if (!window.confirm(`Disconnect ${c.name}'s VRM account? Data already imported will not be deleted.`)) return;
                        runRowAction(c.id, () => disconnectVrmLinkAction(c.id));
                      }}
                    >
                      Disconnect VRM
                    </Button>
                  )}
                </td>
              </tr>
              {editingId === c.id && (
                <tr>
                  <td colSpan={9} className={styles.editRow}>
                    <EditCustomerForm customer={c} onDone={() => setEditingId(null)} />
                  </td>
                </tr>
              )}
            </Fragment>
            );
          })}
        </tbody>
      </Table>

      <div className={styles.actionsRow}>
        {!creating && (
          <Button type="button" onClick={() => setCreating(true)}>
            New customer
          </Button>
        )}
      </div>

      {creating && (
        <div className={styles.panel}>
          <h3>New customer</h3>
          <CreateCustomerForm onDone={() => setCreating(false)} />
        </div>
      )}
    </div>
  );
}
