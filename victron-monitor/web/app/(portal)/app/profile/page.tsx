import type { Metadata } from 'next';
import { requireCustomer } from '@/lib/server/auth';
import { getCustomer, siteCount } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';
import { planLabel } from '@/lib/plans';
import { ProfileForm } from './ProfileForm';
import { ChangePasswordForm } from './ChangePasswordForm';
import styles from './profile.module.css';

export const metadata: Metadata = {
  title: 'Profile',
};

function formatMemberSince(createdAt: string, lang: 'en' | 'es'): string {
  try {
    return new Intl.DateTimeFormat(lang === 'es' ? 'es-CR' : 'en-US', {
      year: 'numeric',
      month: 'long',
    }).format(new Date(createdAt));
  } catch {
    return createdAt;
  }
}

// `app/(portal)/app/profile` (PLAN_PHASE14.md §2 Step 4). `requireCustomer()`
// first, per §3. The read-only block below is deliberately built from
// `session`/`customer`/`siteCount()` directly in this Server Component —
// none of it is editable, so none of it needs to be client-side state.
export default async function ProfilePage() {
  const session = await requireCustomer();
  const [customer, activeSites] = await Promise.all([getCustomer(session.customerId), siteCount(session.customerId)]);

  const lang = session.uiLanguage;
  const sitesUsedLabel =
    customer.site_limit === null
      ? `${activeSites} (${t(lang, 'profile_sites_unlimited')})`
      : `${activeSites} / ${customer.site_limit}`;

  return (
    <div>
      <h1>{t(lang, 'profile_title')}</h1>

      <div className={styles.readonly}>
        <div className={styles.readonlyItem}>
          <span className={styles.readonlyLabel}>{t(lang, 'profile_login_email')}</span>
          <span className={styles.readonlyValue}>{session.email}</span>
        </div>
        <div className={styles.readonlyItem}>
          <span className={styles.readonlyLabel}>{t(lang, 'profile_plan')}</span>
          <span className={styles.readonlyValue}>{planLabel(customer.plan)}</span>
        </div>
        <div className={styles.readonlyItem}>
          <span className={styles.readonlyLabel}>{t(lang, 'profile_sites_used')}</span>
          <span className={styles.readonlyValue}>{sitesUsedLabel}</span>
        </div>
        <div className={styles.readonlyItem}>
          <span className={styles.readonlyLabel}>{t(lang, 'profile_member_since')}</span>
          <span className={styles.readonlyValue}>{formatMemberSince(customer.created_at, lang)}</span>
        </div>
      </div>

      <ProfileForm customer={customer} lang={lang} />

      <div className={styles.section}>
        <h2>{t(lang, 'profile_change_password_title')}</h2>
        <ChangePasswordForm lang={lang} />
      </div>
    </div>
  );
}
