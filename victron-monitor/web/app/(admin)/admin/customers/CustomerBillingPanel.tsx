'use client';

// Per-customer billing detail/actions for `/admin/customers`
// (PLAN_PHASE16.md §0.6 Q11, §8 Step 6). Rendered in the same "expandable
// row below the table row" slot `EditCustomerForm.tsx` already occupies for
// "Edit" — a second, independent toggle (`billingOpenId` in
// `CustomersManager.tsx`), not nested inside the edit form, since editing a
// customer's name/plan/site_limit and acting on their ONVO subscription are
// two different kinds of action with two different blast radii.
//
// Three actions, all real `vrm_api` calls through the SAME endpoints
// `/app/billing` itself uses (`actions.ts`'s own header comment) — NO card
// field anywhere here, ever (Q11: "no card entry by Oscar, ever"):
//   - Refresh — a plain reconcile, safe to click any time.
//   - Cancel (period end / immediate) — a real, confirm-gated mutation.
//   - Promote to active — only shown for a `pending_subscription` customer,
//     confirm-gated, and may legitimately be a no-op (see its own handler).
import { startTransition, useState } from 'react';
import { Button } from '@/components/ui';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import { billingCancelAction, billingRefreshAction, promoteToActiveAction } from './actions';
import styles from './customers.module.css';

type Message = { kind: 'success' | 'error' | 'info'; text: string };

export function CustomerBillingPanel({ customer }: { customer: AdminCustomerRow }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<Message | null>(null);

  function run(successText: string, fn: () => Promise<{ ok?: boolean; error?: string; message?: string }>) {
    setBusy(true);
    setMessage(null);
    startTransition(async () => {
      const result = await fn();
      setBusy(false);
      if (result.error) {
        setMessage({ kind: 'error', text: result.error });
      } else if (result.message) {
        setMessage({ kind: 'info', text: result.message });
      } else {
        setMessage({ kind: 'success', text: successText });
      }
    });
  }

  const messageClassName =
    message?.kind === 'error' ? styles.error : message?.kind === 'info' ? styles.warning : styles.success;

  return (
    <div>
      <h3>Billing — {customer.name}</h3>
      <p className={styles.subtle}>
        Plan {customer.plan} · Billing status {customer.billing_status ?? 'none'} · Origin{' '}
        {customer.origin === 'self_serve' ? 'Self-serve' : 'Admin'} · Provisioning{' '}
        {customer.provisioning_state === 'pending_subscription' ? 'Pending signup' : 'Active'}
      </p>

      <div className={styles.actionsCell} style={{ marginTop: 10 }}>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => run('Refreshed.', () => billingRefreshAction(customer.id))}
        >
          Refresh (reconcile)
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            if (!window.confirm(`Cancel ${customer.name}'s subscription at the end of the current billing period?`)) return;
            run('Cancellation scheduled for period end.', () => billingCancelAction(customer.id, 'at_period_end'));
          }}
        >
          Cancel (period end)
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={() => {
            if (
              !window.confirm(
                `Cancel ${customer.name}'s subscription IMMEDIATELY? They lose access right away — this is the admin-only ` +
                  'escape hatch (not the graceful option customers can choose themselves). This cannot be undone from here.',
              )
            )
              return;
            run('Cancelled immediately.', () => billingCancelAction(customer.id, 'immediate'));
          }}
        >
          Cancel now (immediate)
        </Button>
        {customer.provisioning_state === 'pending_subscription' && (
          <Button
            type="button"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              if (
                !window.confirm(
                  `Promote ${customer.name} to active? Only do this if their card genuinely works and ONVO shows an ` +
                    "entitled subscription, but the automatic promotion never fired. If they haven't actually paid, this " +
                    'correctly does nothing.',
                )
              )
                return;
              run('Promoted to active.', () => promoteToActiveAction(customer.id));
            }}
          >
            Promote to active
          </Button>
        )}
      </div>

      {message && <p className={messageClassName}>{message.text}</p>}
    </div>
  );
}
