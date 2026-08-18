import type { Metadata } from 'next';
import { redirect } from 'next/navigation';
import { Panel } from '@/components/ui';
import { getSessionContext } from '@/lib/server/auth';
import { t } from '@/lib/i18n/strings';
import { LoginForm } from './LoginForm';
import styles from './login.module.css';

export const metadata: Metadata = {
  title: 'Log in',
};

export default async function LoginPage() {
  // An already-signed-in visitor landing on /login (a stale bookmark, a
  // back-button, someone else's shared link) goes straight to their own
  // home instead of being shown a sign-in form they don't need. This reuses
  // `getSessionContext()` rather than `requireCustomer()`/`requireAdmin()`
  // — this route isn't guarded, it's the opposite of guarded, so "no
  // session" is the expected, non-error case here.
  const session = await getSessionContext();
  if (session !== null) {
    redirect(session.role === 'admin' ? '/admin' : '/app');
  }

  return (
    <Panel variant="readout" hairline className={styles.card}>
      <h1 className={styles.title}>{t('en', 'login_title')}</h1>
      <p className={styles.subtitle}>{t('en', 'login_subtitle')}</p>
      <LoginForm />
    </Panel>
  );
}
