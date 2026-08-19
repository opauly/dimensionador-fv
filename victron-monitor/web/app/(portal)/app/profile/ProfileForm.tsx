'use client';

import { useActionState } from 'react';
import { Button, Field, Input, Select } from '@/components/ui';
import { t, FORCE_LANG, type Lang } from '@/lib/i18n/strings';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import type { CustomerRecord } from '@/lib/server/db';
import { updateProfileAction, type ProfileFormState } from './actions';
import styles from './profile.module.css';

const COUNTRY_CODES = Object.keys(COUNTRIES);
const INITIAL_STATE: ProfileFormState = {};

// The editable half of `app/(portal)/app/profile` — exactly the five
// fields `lib/server/db/customers.ts:PROFILE_WHITELIST` allows, no more.
// There's no `plan`/`site_limit`/`active` input anywhere in this file: not
// because they're hidden or disabled, but because they don't exist here at
// all — the read-only block above this form (rendered by `page.tsx`) is
// where those actually show.
export function ProfileForm({ customer, lang }: { customer: CustomerRecord; lang: Lang }) {
  const [state, formAction, pending] = useActionState(updateProfileAction, INITIAL_STATE);

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label={t(lang, 'profile_field_name')} htmlFor="profile-name" required>
          <Input id="profile-name" name="name" defaultValue={customer.name} required disabled={pending} />
        </Field>
        <Field label={t(lang, 'profile_field_ui_language')} htmlFor="profile-ui-language">
          {/* A `disabled` form control is excluded from FormData entirely —
             without the hidden input below, disabling this <select> while
             FORCE_LANG is active would silently drop `ui_language` from
             every submit, and `updateProfileAction`'s Zod schema requires
             it (`z.enum(['en','es'])`), so the WHOLE profile form —
             name/contact/country too — would start failing to save, not
             just the language piece. Caught before shipping, not from a
             bug report. */}
          {FORCE_LANG !== null && <input type="hidden" name="ui_language" value={customer.ui_language} />}
          <Select
            id="profile-ui-language"
            name={FORCE_LANG === null ? 'ui_language' : undefined}
            defaultValue={customer.ui_language}
            disabled={pending || FORCE_LANG !== null}
          >
            <option value="en">{t(lang, 'lang_en')}</option>
            <option value="es">{t(lang, 'lang_es')}</option>
          </Select>
          {FORCE_LANG !== null && (
            <p className={styles.hint}>{t(lang, 'profile_ui_language_locked_hint')}</p>
          )}
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field
          label={t(lang, 'profile_field_contact_name')}
          htmlFor="profile-contact-name"
          optional
          optionalLabel={` ${t(lang, 'field_optional')}`}
        >
          <Input id="profile-contact-name" name="contact_name" defaultValue={customer.contact_name ?? ''} disabled={pending} />
        </Field>
        <Field
          label={t(lang, 'profile_field_contact_email')}
          htmlFor="profile-contact-email"
          optional
          optionalLabel={` ${t(lang, 'field_optional')}`}
        >
          <Input
            id="profile-contact-email"
            name="contact_email"
            type="email"
            defaultValue={customer.contact_email ?? ''}
            disabled={pending}
          />
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label={t(lang, 'profile_field_country')} htmlFor="profile-country">
          <Select id="profile-country" name="country" defaultValue={customer.country ?? DEFAULT_COUNTRY} disabled={pending}>
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {COUNTRIES[code]}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {state.error && <p className={styles.error}>{state.error}</p>}
      {state.success && <p className={styles.success}>{t(lang, 'profile_save_success')}</p>}

      <Button type="submit" disabled={pending}>
        {pending ? t(lang, 'profile_saving') : t(lang, 'profile_save_button')}
      </Button>
    </form>
  );
}
