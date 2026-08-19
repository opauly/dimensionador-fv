'use client';

import { useActionState, useEffect } from 'react';
import { Button, Field, Input, Select, Textarea } from '@/components/ui';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import { PLANS, type PlanKey } from '@/lib/plans';
import { COUNTRIES } from '@/lib/countries';
import { updateCustomerAction, type UpdateCustomerState } from './actions';
import styles from './customers.module.css';

const PLAN_KEYS = Object.keys(PLANS) as PlanKey[];
const COUNTRY_CODES = Object.keys(COUNTRIES);

// Edit form for one customer row — the admin-only counterpart of
// `app/(portal)/app/profile/ProfileForm.tsx`, but with the wider whitelist
// only `/admin/*` may write (`plan`, `site_limit`, `account_type` — never
// reachable from a customer's own `/app/profile`, see
// `lib/server/db/admin.ts:ADMIN_CUSTOMER_WHITELIST`'s own comment).
// `auth_email`/invite state is deliberately NOT editable here — that's
// `CustomersManager`'s "Send/Resend invite" buttons
// (`lib/server/invites.ts`), a distinct action from a generic field edit.
export function EditCustomerForm({ customer, onDone }: { customer: AdminCustomerRow; onDone: () => void }) {
  const boundAction = updateCustomerAction.bind(null, customer.id);
  const [state, formAction, pending] = useActionState<UpdateCustomerState, FormData>(boundAction, {});

  useEffect(() => {
    if (state.success) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onDone intentionally excluded, see SiteForm.tsx's own precedent
  }, [state.success]);

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label="Name" htmlFor={`ec-name-${customer.id}`} required>
          <Input id={`ec-name-${customer.id}`} name="name" defaultValue={customer.name} required disabled={pending} />
        </Field>
        <Field label="Account type" htmlFor={`ec-type-${customer.id}`}>
          <Select id={`ec-type-${customer.id}`} name="accountType" defaultValue={customer.account_type} disabled={pending}>
            <option value="owner">Owner (site owner)</option>
            <option value="installer">Installer</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Plan" htmlFor={`ec-plan-${customer.id}`}>
          <Select id={`ec-plan-${customer.id}`} name="plan" defaultValue={customer.plan} disabled={pending}>
            {PLAN_KEYS.includes(customer.plan as PlanKey) ? null : <option value={customer.plan}>{customer.plan}</option>}
            {PLAN_KEYS.map((key) => (
              <option key={key} value={key}>
                {PLANS[key].label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Site limit" htmlFor={`ec-limit-${customer.id}`} optional optionalLabel=" (empty = unlimited)">
          <Input
            id={`ec-limit-${customer.id}`}
            name="siteLimit"
            type="number"
            min="0"
            step="1"
            defaultValue={customer.site_limit ?? ''}
            disabled={pending}
          />
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Country" htmlFor={`ec-country-${customer.id}`}>
          <Select id={`ec-country-${customer.id}`} name="country" defaultValue={customer.country ?? 'CR'} disabled={pending}>
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {COUNTRIES[code]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Dashboard language" htmlFor={`ec-lang-${customer.id}`}>
          <Select id={`ec-lang-${customer.id}`} name="uiLanguage" defaultValue={customer.ui_language} disabled={pending}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Contact name" htmlFor={`ec-contact-name-${customer.id}`} optional>
          <Input id={`ec-contact-name-${customer.id}`} name="contactName" defaultValue={customer.contact_name ?? ''} disabled={pending} />
        </Field>
        <Field label="Contact email" htmlFor={`ec-contact-email-${customer.id}`} optional>
          <Input
            id={`ec-contact-email-${customer.id}`}
            name="contactEmail"
            type="email"
            defaultValue={customer.contact_email ?? ''}
            disabled={pending}
          />
        </Field>
      </div>

      <Field label="Internal notes" htmlFor={`ec-notes-${customer.id}`} optional>
        <Textarea id={`ec-notes-${customer.id}`} name="notes" rows={2} defaultValue={customer.notes ?? ''} disabled={pending} />
      </Field>

      <p className={styles.subtle}>
        Login email: <strong>{customer.auth_email ?? '— not set —'}</strong> — not editable from this form; changing the
        login email of an already-invited customer is not supported yet.
      </p>

      {state.error && <p className={styles.error}>{state.error}</p>}

      <div className={styles.formActions}>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : 'Save'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
