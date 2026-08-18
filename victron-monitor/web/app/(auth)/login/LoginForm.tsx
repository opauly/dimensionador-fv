'use client';

// Client-side only for the submit-pending state and inline error display —
// the actual auth call happens in `actions.ts`'s Server Action, never here
// (PLAN_PHASE14.md §3: "the login form needs client-side state for the
// submit button/error display, but the actual auth call should go through
// a server action, not a client-side Supabase client"). There is no
// Supabase import anywhere in this file.
import { useActionState } from 'react';
import Link from 'next/link';
import { Button, Field, Input } from '@/components/ui';
import { t } from '@/lib/i18n/strings';
import { signInAction, type LoginFormState } from './actions';
import styles from './login.module.css';

const INITIAL_STATE: LoginFormState = {};

export function LoginForm() {
  const [state, formAction, pending] = useActionState(signInAction, INITIAL_STATE);

  return (
    <form action={formAction} className={styles.form} noValidate>
      <Field label={t('en', 'login_email')} htmlFor="login-email" required>
        <Input id="login-email" name="email" type="email" autoComplete="email" required disabled={pending} />
      </Field>
      <Field label={t('en', 'login_password')} htmlFor="login-password" required>
        <Input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          disabled={pending}
        />
      </Field>

      {state.error && (
        <p role="alert" className={styles.error}>
          {state.error}
        </p>
      )}

      <Button type="submit" disabled={pending} className={styles.submit}>
        {pending ? '…' : t('en', 'login_submit')}
      </Button>

      <Link href="/forgot" className={styles.forgot}>
        {t('en', 'login_forgot_password')}
      </Link>
    </form>
  );
}
