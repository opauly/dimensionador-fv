import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { Panel } from '@/components/ui';
import { getSessionContext } from '@/lib/server/auth';
import { t } from '@/lib/i18n/strings';
import { ForgotForm } from './ForgotForm';
import styles from './forgot.module.css';

export const metadata: Metadata = {
  title: 'Reset password',
};

// `/forgot` (PLAN_PHASE14.md §2 Step 7) — same "already signed in? skip the
// form" pattern as `/login`'s own page.tsx.
export default async function ForgotPage() {
  const session = await getSessionContext();
  if (session !== null) {
    redirect(session.role === 'admin' ? '/admin' : '/app');
  }

  return (
    <Panel variant="readout" hairline className={styles.card}>
      <h1 className={styles.title}>{t('en', 'forgot_title')}</h1>
      <p className={styles.subtitle}>{t('en', 'forgot_subtitle')}</p>
      <ForgotForm />
    </Panel>
  );
}
