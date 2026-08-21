'use client';

// `PUT /api/billing/address` (PLAN_PHASE16.md §5.3 / §8 Step 5). ONVO's only
// real home for a billing address is a payment method's `billing.address`
// (`vrm_api/onvo.py`'s own docstring, restated in `routers/billing.py:
// put_address()`) — so this form is disabled with an explanatory hint until
// a payment method exists, rather than accepting input that would 400.
// Written to ONVO first server-side, then mirrored from the reconcile
// (§0.5) — this component never renders what it just typed as the new
// truth; it renders `onSaved`'s fresh `BillingStatusOut` instead, same as
// every other billing mutation in this app.
import { useState } from 'react';
import { Button, Field, Input, Select } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import type { BillingAddressIn, BillingStatusOut } from '@/lib/server/pipeline';
import styles from './billing.module.css';

const COUNTRY_CODES = Object.keys(COUNTRIES);

export type BillingAddressFormProps = {
  lang: Lang;
  address: BillingAddressIn;
  hasPaymentMethod: boolean;
  onSaved: (status: BillingStatusOut) => void;
};

export function BillingAddressForm({ lang, address, hasPaymentMethod, onSaved }: BillingAddressFormProps) {
  const [form, setForm] = useState<BillingAddressIn>({
    line1: address.line1 ?? '',
    line2: address.line2 ?? '',
    city: address.city ?? '',
    state: address.state ?? '',
    postalCode: address.postalCode ?? '',
    country: address.country ?? DEFAULT_COUNTRY,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  function update(patch: Partial<BillingAddressIn>) {
    setForm((f) => ({ ...f, ...patch }));
    setSuccess(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch('/api/billing/address', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address: form }),
      });
      if (!res.ok) {
        setError(t(lang, 'billing_address_error_generic'));
        return;
      }
      const status = (await res.json()) as BillingStatusOut;
      setSuccess(true);
      onSaved(status);
    } catch {
      setError(t(lang, 'billing_address_error_generic'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.panel}>
      <h2>{t(lang, 'billing_address_title')}</h2>
      {!hasPaymentMethod ? (
        <p className={styles.status}>{t(lang, 'billing_address_no_payment_method')}</p>
      ) : (
        <>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'billing_address_line1_label')} htmlFor="billing-address-line1">
              <Input
                id="billing-address-line1"
                value={form.line1 ?? ''}
                onChange={(e) => update({ line1: e.target.value })}
                disabled={saving}
              />
            </Field>
            <Field
              label={t(lang, 'billing_address_line2_label')}
              htmlFor="billing-address-line2"
              optional
              optionalLabel={` ${t(lang, 'field_optional')}`}
            >
              <Input
                id="billing-address-line2"
                value={form.line2 ?? ''}
                onChange={(e) => update({ line2: e.target.value })}
                disabled={saving}
              />
            </Field>
          </div>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'billing_address_city_label')} htmlFor="billing-address-city">
              <Input
                id="billing-address-city"
                value={form.city ?? ''}
                onChange={(e) => update({ city: e.target.value })}
                disabled={saving}
              />
            </Field>
            <Field label={t(lang, 'billing_address_state_label')} htmlFor="billing-address-state">
              <Input
                id="billing-address-state"
                value={form.state ?? ''}
                onChange={(e) => update({ state: e.target.value })}
                disabled={saving}
              />
            </Field>
          </div>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'billing_address_postal_code_label')} htmlFor="billing-address-postal">
              <Input
                id="billing-address-postal"
                value={form.postalCode ?? ''}
                onChange={(e) => update({ postalCode: e.target.value })}
                disabled={saving}
              />
            </Field>
            <Field label={t(lang, 'billing_address_country_label')} htmlFor="billing-address-country">
              <Select
                id="billing-address-country"
                value={form.country ?? DEFAULT_COUNTRY}
                onChange={(e) => update({ country: e.target.value })}
                disabled={saving}
              >
                {COUNTRY_CODES.map((code) => (
                  <option key={code} value={code}>
                    {COUNTRIES[code]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          {error && <p className={styles.error}>{error}</p>}
          {success && <p className={styles.success}>{t(lang, 'billing_address_success')}</p>}

          <div className={styles.formActions}>
            <Button type="button" onClick={handleSave} disabled={saving}>
              {saving ? t(lang, 'billing_address_saving') : t(lang, 'billing_address_save_button')}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
