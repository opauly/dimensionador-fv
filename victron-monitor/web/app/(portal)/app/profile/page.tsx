import type { Metadata } from 'next';
import { requireCustomerAllowPending } from '@/lib/server/auth';
import { getBillingStatus, getCustomer, getVrmLinkStatus, siteCount } from '@/lib/server/db';
import { t, type Lang, type StringKey } from '@/lib/i18n/strings';
import { planLabel } from '@/lib/plans';
import { formatDate, type DateLocale } from '@/lib/dates';
import { Button } from '@/components/ui';
import { ProfileForm } from './ProfileForm';
import { ChangePasswordForm } from './ChangePasswordForm';
import styles from './profile.module.css';

// Same per-file convention `VrmLinkPanel.tsx` already uses — see its own
// comment on `DATE_LOCALE` for why this isn't a shared export.
const DATE_LOCALE: Record<Lang, DateLocale> = { en: 'en-US', es: 'es-CR' };

// Same small per-file mapping `BillingManager.tsx` (`/app/billing`) uses
// for the exact same closed vocabulary (§0.2b finding 4) — duplicated
// rather than shared for the same reason `DATE_LOCALE` is duplicated across
// this app's client components: a two-line const isn't worth a shared
// module import for something this page only needs once.
const BILLING_STATUS_LABEL_KEY: Record<string, StringKey> = {
  trialing: 'billing_status_trialing',
  active: 'billing_status_active',
  past_due: 'billing_status_past_due',
  canceled: 'billing_status_canceled',
  unpaid: 'billing_status_unpaid',
  incomplete: 'billing_status_incomplete',
  incomplete_expired: 'billing_status_incomplete_expired',
  // See BillingManager.tsx's own comment — a local-only value, never an
  // ONVO status.
  trial_expired: 'billing_status_trial_expired',
};

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

// `app/(portal)/app/profile` (PLAN_PHASE14.md §2 Step 4). One of the three
// call sites that opt out of `requireCustomer()`'s pending-account gate via
// `requireCustomerAllowPending()` (PLAN_PHASE16.md §6.4/§8 Step 5.5) — a
// `pending_subscription` customer still needs to sign out and change their
// password, and both affordances live on this page. The read-only block
// below is deliberately built from `session`/`customer`/`siteCount()`
// directly in this Server Component — none of it is editable, so none of
// it needs to be client-side state.
export default async function ProfilePage() {
  const session = await requireCustomerAllowPending();
  const [customer, activeSites, vrmStatus, billingStatus] = await Promise.all([
    getCustomer(session.customerId),
    siteCount(session.customerId),
    getVrmLinkStatus(session.customerId),
    getBillingStatus(session.customerId),
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

      {/* Billing status card (PLAN_PHASE16.md §8 Step 5) — same "compact
         status text + link" shape as the VRM connection card above, not an
         inline billing flow (that lives entirely at /app/billing). */}
      <div className={styles.section}>
        <h2>{t(lang, 'profile_billing_title')}</h2>
        <p className={styles.readonlyValue}>
          {billingStatus.plan_key
            ? `${planLabel(billingStatus.plan_key)} · ${
                billingStatus.status
                  ? t(lang, BILLING_STATUS_LABEL_KEY[billingStatus.status] ?? 'billing_status_unknown')
                  : t(lang, 'billing_status_unknown')
              }`
            : t(lang, 'profile_billing_no_plan')}
        </p>
        <Button href="/app/billing" variant="ghost">
          {t(lang, 'profile_billing_manage_cta')}
        </Button>
      </div>

      {/* Report Branding used to have its own status card here, duplicating
         the "Branding" link already in the main nav (app/(portal)/app/
         layout.tsx) — real live-test feedback, 2026-08-29: confusing to
         redirect from Profile to a whole separate tab for something with
         its own nav entry. Removed rather than kept as a shortcut; the
         entitlement-gated `brandingAllowed` read above page.tsx no longer
         has a reader either, so it goes with it. */}

      <div className={styles.section}>
        <h2>{t(lang, 'profile_basic_info_title')}</h2>
        <ProfileForm customer={customer} lang={lang} />
      </div>

      <div className={styles.section}>
        <h2>{t(lang, 'profile_change_password_title')}</h2>
        <ChangePasswordForm lang={lang} />
      </div>
    </div>
  );
}
