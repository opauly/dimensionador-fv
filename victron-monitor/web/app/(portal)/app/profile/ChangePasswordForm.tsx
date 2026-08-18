'use client';

import { useActionState } from 'react';
import { Button, Field, Input } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import { changePasswordAction, type PasswordFormState } from './actions';
import styles from './profile.module.css';

const INITIAL_STATE: PasswordFormState = {};

// Deliberately three plain, uncontrolled password inputs and nothing else
// client-side — no live "passwords match" check, no strength meter. The
// only thing that decides whether a password change succeeds is the Server
// Action re-authenticating with `current_password`
// (`./actions.ts:changePasswordAction`); this form's job is just to collect
// the three values and show whatever that action reports back.
export function ChangePasswordForm({ lang }: { lang: Lang }) {
  const [state, formAction, pending] = useActionState(changePasswordAction, INITIAL_STATE);

  return (
    <form action={formAction} className={styles.form} key={state.success ? 'reset' : 'form'}>
      <div className={styles.fieldRow}>
        <Field label={t(lang, 'profile_current_password')} htmlFor="pw-current" required>
          <Input id="pw-current" name="current_password" type="password" autoComplete="current-password" required disabled={pending} />
        </Field>
      </div>
      <div className={styles.fieldRow}>
        <Field label={t(lang, 'profile_new_password')} htmlFor="pw-new" required>
          <Input
            id="pw-new"
            name="new_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            disabled={pending}
          />
        </Field>
        <Field label={t(lang, 'profile_confirm_password')} htmlFor="pw-confirm" required>
          <Input
            id="pw-confirm"
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            required
            disabled={pending}
          />
        </Field>
      </div>

      {state.error && <p className={styles.error}>{state.error}</p>}
      {state.success && <p className={styles.success}>{t(lang, 'profile_change_password_success')}</p>}

      <Button type="submit" disabled={pending}>
        {pending ? t(lang, 'profile_saving') : t(lang, 'profile_change_password_button')}
      </Button>
    </form>
  );
}
