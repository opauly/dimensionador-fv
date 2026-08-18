'use client';

// The `/activate` client half (PLAN_PHASE14.md §2 Step 7).
//
// `verifyAction` is a bound Server Action reference — see
// `actions.ts`'s header comment for why `page.tsx` hands this down instead
// of the raw `token_hash`/`type`. A Server Action passed as a prop is not
// plain serialized data: Next.js's RSC wire format represents it as an
// opaque server-reference id, resolvable only by actually invoking it (the
// framework's own mechanism for "call this specific server function," not
// a JSON value a client could read, log, or copy out of React DevTools the
// way a literal `tokenHash` prop would be). That is the property this
// component leans on: it never has the token in scope as data, only the
// ability to ask the server to redeem it once.
import { startTransition, useActionState, useEffect, useRef, useState } from 'react';
import { Button, Field, Input } from '@/components/ui';
import { t } from '@/lib/i18n/strings';
import { setActivationPasswordAction, type SetPasswordState, type VerifyResult } from './actions';
import styles from './activate.module.css';

type Phase = 'verifying' | 'ready' | 'expired';

export function ActivateClient({ verifyAction }: { verifyAction: () => Promise<VerifyResult> }) {
  const [phase, setPhase] = useState<Phase>('verifying');
  // `verify_otp` is single-use server-side — calling it twice for the same
  // token isn't idempotent, it's a *second, different* outcome (the token
  // is already consumed, so the retry genuinely fails). React's Strict Mode
  // intentionally double-invokes effects in development (mount -> cleanup ->
  // mount again, on the same fiber) specifically to surface exactly this
  // class of bug — it isn't a rare edge case, it fires on every dev-mode
  // page load, so both halves of this need to survive it correctly:
  //
  //   1. `firedRef` (persists across the fake unmount/remount, unlike a
  //      local variable) makes sure `verifyAction()` itself is only ever
  //      called once — set on the run that calls it, never reset.
  //   2. `cancelledRef` is reset to `false` at the *start* of every effect
  //      run, including the second (fake) one — not just declared once.
  //      Mount -> cleanup -> mount all happen synchronously, before any
  //      microtask from the in-flight `verifyAction()` promise can run, so
  //      by the time that promise actually resolves, the second run has
  //      already un-cancelled it. A plain `let cancelled` closed over only
  //      the *first* run stays permanently `true` after that run's own
  //      (fake) cleanup fires — silently discarding a real success and
  //      leaving the UI stuck on "Verifying…" forever. Caught by testing
  //      this for real against a live invite link, not assumed.
  const firedRef = useRef(false);
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    if (!firedRef.current) {
      firedRef.current = true;
      startTransition(() => {
        verifyAction().then((result) => {
          if (cancelledRef.current) return;
          setPhase(result.ok ? 'ready' : 'expired');
        });
      });
    }
    return () => {
      cancelledRef.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === 'verifying') {
    return <p className={styles.status}>{t('en', 'activate_verifying')}</p>;
  }

  if (phase === 'expired') {
    return (
      <div>
        <h2 className={styles.subtitle}>{t('en', 'activate_expired_title')}</h2>
        <p className={styles.body}>{t('en', 'activate_expired_body')}</p>
      </div>
    );
  }

  return <SetPasswordForm />;
}

function SetPasswordForm() {
  const [state, formAction, pending] = useActionState<SetPasswordState, FormData>(setActivationPasswordAction, {});

  return (
    <form action={formAction} className={styles.form} noValidate>
      <Field label={t('en', 'activate_password')} htmlFor="activate-password" required>
        <Input id="activate-password" name="password" type="password" autoComplete="new-password" minLength={8} required disabled={pending} />
      </Field>
      <Field label={t('en', 'activate_confirm_password')} htmlFor="activate-confirm" required>
        <Input
          id="activate-confirm"
          name="confirm_password"
          type="password"
          autoComplete="new-password"
          minLength={8}
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
        {pending ? t('en', 'activate_setting') : t('en', 'activate_submit')}
      </Button>
    </form>
  );
}
