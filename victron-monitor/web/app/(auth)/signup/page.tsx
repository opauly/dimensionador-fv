import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import Link from 'next/link';
import { Panel } from '@/components/ui';
import { getSessionContext } from '@/lib/server/auth';
import { listSelfServePlans, type SelfServePlanOut } from '@/lib/server/db/signup';
import type { AccountType } from '@/lib/server/db/types';
import { t } from '@/lib/i18n/strings';
import { SignupForm } from './SignupForm';
import styles from './signup.module.css';

export const metadata: Metadata = {
  title: 'Sign up',
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// `/signup` (PLAN_PHASE16.md §5.5 Step 1, §8 Step 5.5). This IS the public
// entry point §6.6 opens: the first request in this app's life that can
// insert a database row with no credential of any kind. Everything this
// page renders is either static copy or a server-side read of the
// self-serve plan catalogue (`listSelfServePlans()`, §5.5 Step 4) — the
// actual write lives entirely behind `SignupForm.tsx`'s Server Action.
export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Same "already signed in? skip the form" pattern as `/login`/`/forgot`.
  const session = await getSessionContext();
  if (session !== null) {
    redirect(session.role === 'admin' ? '/admin' : '/app');
  }

  const params = await searchParams;
  const status = typeof params.status === 'string' ? params.status : null;

  // §5.5 Step 2: a redeemed/expired/tampered token all land here with the
  // SAME status — one friendly message with links to /login and /forgot,
  // never a raw error page and never three different messages for three
  // different failure reasons.
  if (status === 'link_used') {
    return (
      <Panel variant="readout" hairline className={styles.card}>
        <h1 className={styles.title}>{t('en', 'signup_link_used_title')}</h1>
        <p className={styles.body}>{t('en', 'signup_link_used_body')}</p>
        <div className={styles.linkRow}>
          <Link href="/login" className={styles.backLink}>
            {t('en', 'signup_link_used_login')}
          </Link>
          <Link href="/forgot" className={styles.backLink}>
            {t('en', 'signup_link_used_forgot')}
          </Link>
        </div>
      </Panel>
    );
  }

  const rawPlan = typeof params.plan === 'string' ? params.plan : null;
  const initialPlanId = rawPlan && UUID_RE.test(rawPlan) ? rawPlan : null;

  const [installerPlans, ownerPlans] = await Promise.all([listSelfServePlans('installer'), listSelfServePlans('owner')]);

  // §5.5 Step 4: an empty catalogue (Q14 unanswered, or the wrong
  // ONVO_MODE) renders a "get in touch" card, never an empty picker with a
  // dead submit button.
  if (installerPlans.length === 0 && ownerPlans.length === 0) {
    return (
      <Panel variant="readout" hairline className={styles.card}>
        <h1 className={styles.title}>{t('en', 'signup_closed_title')}</h1>
        <p className={styles.body}>{t('en', 'signup_closed_body')}</p>
        <a href="mailto:proyectos@paulyco.com?subject=VRM%20Monitor%20-%20Sign%20up" className={styles.backLink}>
          {t('en', 'signup_closed_cta')}
        </a>
      </Panel>
    );
  }

  const plansByAccountType: Record<AccountType, SelfServePlanOut[]> = { installer: installerPlans, owner: ownerPlans };

  // A `?plan=` id that only exists on the owner list (not installer's)
  // starts the account-type toggle on "owner" so the preselected plan is
  // actually visible; every other case (no plan, an installer-only or
  // shared plan, an id that matches nothing) defaults to "installer" —
  // matches `Pricing.tsx`'s own two "Get started" buttons, both of which
  // are installer-tier cards.
  const initialAccountType: AccountType =
    initialPlanId && !installerPlans.some((p) => p.id === initialPlanId) && ownerPlans.some((p) => p.id === initialPlanId)
      ? 'owner'
      : 'installer';

  return (
    <Panel variant="readout" hairline className={styles.card}>
      {/* Title + subtitle now live inside SignupForm itself, not here —
          the subtitle ("7-day trial, card required...") is pre-submission
          context and must NOT carry over to the post-submission
          confirmation view, which SignupForm renders in place of the form
          once `state.submitted` is true. A Server Component parent can't
          branch on that client-side state, so both views' heading copy
          moved into the one component that actually knows which is showing
          (Oscar's request, 2026-08-21). */}
      <SignupForm plansByAccountType={plansByAccountType} initialAccountType={initialAccountType} initialPlanId={initialPlanId} />
    </Panel>
  );
}
