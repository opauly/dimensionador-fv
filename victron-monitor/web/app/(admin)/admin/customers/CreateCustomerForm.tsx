'use client';

// Create-customer form (PLAN_PHASE14.md §2 Step 7): name -> live slug
// preview, account type, plan (site_limit prefilled from `PLANS`,
// editable), contact fields, login email, ui_language, then **Create and
// send invite** — a single submit that both creates the `vrm.customers` row
// and sends the first invite (`actions.ts:createCustomerAction`), since the
// plan describes these as one flow, not two separate steps an admin has to
// remember to do in order.
import { useActionState, useEffect, useState } from 'react';
import { Button, Field, Input, Select } from '@/components/ui';
import { slugify } from '@/lib/slug';
import { PLANS, type PlanKey } from '@/lib/plans';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import { createCustomerAction, type CreateCustomerState } from './actions';
import styles from './customers.module.css';

const PLAN_KEYS = Object.keys(PLANS) as PlanKey[];
const COUNTRY_CODES = Object.keys(COUNTRIES);

export function CreateCustomerForm({ onDone }: { onDone: () => void }) {
  const [state, formAction, pending] = useActionState<CreateCustomerState, FormData>(createCustomerAction, {});
  const [name, setName] = useState('');
  const [plan, setPlan] = useState<PlanKey>('trial');
  const [siteLimit, setSiteLimit] = useState<string>(String(PLANS.trial.sites ?? ''));

  const slugPreview = name.trim() ? (() => {
    try {
      return slugify(name);
    } catch {
      return '—';
    }
  })() : '—';

  useEffect(() => {
    // Closes the panel automatically only on a fully clean success — if the
    // row was created but the invite send failed (`state.inviteWarning`),
    // the panel stays open (see the `state.success` branch below, which
    // swaps to a read-only confirmation rather than leaving the form
    // resubmittable — a second submit at that point would create a SECOND
    // customer row, not retry the invite).
    if (state.success && !state.inviteWarning) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onDone intentionally excluded, see SiteForm.tsx's own precedent for this exact pattern
  }, [state.success, state.inviteWarning]);

  function handlePlanChange(value: string) {
    const key = value as PlanKey;
    setPlan(key);
    const limit = PLANS[key]?.sites;
    setSiteLimit(limit === null || limit === undefined ? '' : String(limit));
  }

  // The customer row already exists at this point — swap to a read-only
  // confirmation instead of the (still-populated, resubmittable) form, so
  // there's no way to accidentally create a second row while reading the
  // invite-send warning. "Resend invite" from the table is the
  // recovery path from here, not resubmitting this form.
  if (state.success) {
    return (
      <div className={styles.form}>
        <p className={styles.success}>Customer created.</p>
        {state.inviteWarning && <p className={styles.warning}>{state.inviteWarning}</p>}
        <div className={styles.formActions}>
          <Button type="button" onClick={onDone}>
            Close
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label="Name" htmlFor="cc-name" required>
          <Input id="cc-name" name="name" required disabled={pending} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Slug (site_id)" htmlFor="cc-slug-preview">
          <Input id="cc-slug-preview" value={slugPreview} disabled readOnly />
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Account type" htmlFor="cc-account-type">
          <Select id="cc-account-type" name="accountType" defaultValue="owner" disabled={pending}>
            <option value="owner">Owner (site owner)</option>
            <option value="installer">Installer</option>
          </Select>
        </Field>
        <Field label="Dashboard language" htmlFor="cc-ui-language">
          <Select id="cc-ui-language" name="uiLanguage" defaultValue="en" disabled={pending}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Plan" htmlFor="cc-plan">
          <Select id="cc-plan" name="plan" value={plan} onChange={(e) => handlePlanChange(e.target.value)} disabled={pending}>
            {PLAN_KEYS.map((key) => (
              <option key={key} value={key}>
                {PLANS[key].label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Site limit" htmlFor="cc-site-limit" optional optionalLabel=" (empty = unlimited)">
          <Input
            id="cc-site-limit"
            name="siteLimit"
            type="number"
            min="0"
            step="1"
            value={siteLimit}
            onChange={(e) => setSiteLimit(e.target.value)}
            disabled={pending}
          />
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Login email" htmlFor="cc-auth-email" required>
          <Input id="cc-auth-email" name="authEmail" type="email" required disabled={pending} />
        </Field>
        <Field label="Country" htmlFor="cc-country">
          <Select id="cc-country" name="country" defaultValue={DEFAULT_COUNTRY} disabled={pending}>
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {COUNTRIES[code]}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Contact name" htmlFor="cc-contact-name" optional>
          <Input id="cc-contact-name" name="contactName" disabled={pending} />
        </Field>
        <Field label="Contact email" htmlFor="cc-contact-email" optional>
          <Input id="cc-contact-email" name="contactEmail" type="email" disabled={pending} />
        </Field>
      </div>

      {state.error && <p className={styles.error}>{state.error}</p>}

      <div className={styles.formActions}>
        <Button type="submit" disabled={pending}>
          {pending ? 'Creating…' : 'Create and send invite'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
