import type { Metadata } from 'next';
import { requireCustomer } from '@/lib/server/auth';
import { getCustomer, getVrmLinkStatus, siteCount } from '@/lib/server/db';
import { t, type Lang } from '@/lib/i18n/strings';
import { planLabel } from '@/lib/plans';
import { formatDate, type DateLocale } from '@/lib/dates';
import { Button } from '@/components/ui';
import { ProfileForm } from './ProfileForm';
import { ChangePasswordForm } from './ChangePasswordForm';
import styles from './profile.module.css';

// Same per-file convention `VrmLinkPanel.tsx` already uses — see its own
// comment on `DATE_LOCALE` for why this isn't a shared export.
const DATE_LOCALE: Record<Lang, DateLocale> = { en: 'en-US', es: 'es-CR' };

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
  const [customer, activeSites, vrmStatus] = await Promise.all([
    getCustomer(session.customerId),
    siteCount(session.customerId),
    getVrmLinkStatus(session.customerId),
  ]);

  const lang = session.uiLanguage;
  // Same condition `VrmConnectionBanner.tsx` uses — see its own comment for
  // why `!connected` is part of it (a just-reconnected account still carries
  // a stale `token_last_error` until the next successful sync).
  const vrmBroken = !vrmStatus.connected && (Boolean(vrmStatus.token_revoked_at) || Boolean(vrmStatus.token_last_error));
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

      <div className={styles.section}>
        <h2>{t(lang, 'profile_vrm_title')}</h2>
        {vrmStatus.connected ? (
          <p className={styles.readonlyValue}>
            {t(lang, 'vrm_link_connected_account_label')}: {vrmStatus.vrm_account_email ?? '—'}
            {' · '}
            {t(lang, 'vrm_link_connected_since_label')}:{' '}
            {vrmStatus.connected_since ? formatDate(vrmStatus.connected_since, DATE_LOCALE[lang]) : '—'}
          </p>
        ) : vrmBroken ? (
          <p className={styles.error}>{t(lang, 'vrm_link_broken_banner')}</p>
        ) : (
          <p className={styles.readonlyValue}>{t(lang, 'profile_vrm_not_connected')}</p>
        )}
        <Button href="/app/sites" variant="ghost">
          {t(lang, 'profile_vrm_manage_cta')}
        </Button>
      </div>

      <ProfileForm customer={customer} lang={lang} />

      <div className={styles.section}>
        <h2>{t(lang, 'profile_change_password_title')}</h2>
        <ChangePasswordForm lang={lang} />
      </div>
    </div>
  );
}
