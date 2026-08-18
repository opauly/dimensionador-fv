import type { Metadata } from 'next';
import { Panel } from '@/components/ui';
import { t } from '@/lib/i18n/strings';
import { verifyActivationTokenAction } from './actions';
import { ActivateClient } from './ActivateClient';
import styles from './activate.module.css';

export const metadata: Metadata = {
  title: 'Activate your account',
};

// `/activate` (PLAN_PHASE14.md §2 Step 7) — the landing page for every
// invite/re-send/password-reset link this app sends
// (`{SITE_URL}/activate?token_hash=...&type=invite|recovery|magiclink`).
//
// `searchParams` here is this page's own server-rendered input (Next.js
// resolves it before this Server Component ever runs) — reading
// `token_hash`/`type` from it and using them ONLY to build a bound Server
// Action (never as a literal value handed to `ActivateClient`'s props) is
// the "the token never lands in a client component's props" rule
// PLAN_PHASE14.md §3's conventions call for. See `actions.ts`'s header
// comment for the full reasoning.
export default async function ActivatePage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const tokenHash = typeof params.token_hash === 'string' ? params.token_hash : null;
  const type = typeof params.type === 'string' ? params.type : null;

  if (!tokenHash || !type) {
    return (
      <Panel variant="readout" hairline className={styles.card}>
        <h1 className={styles.title}>{t('en', 'activate_invalid_title')}</h1>
        <p className={styles.body}>{t('en', 'activate_invalid_body')}</p>
      </Panel>
    );
  }

  const boundVerify = verifyActivationTokenAction.bind(null, tokenHash, type);

  return (
    <Panel variant="readout" hairline className={styles.card}>
      <h1 className={styles.title}>{t('en', 'activate_title')}</h1>
      <p className={styles.subtitleIntro}>{t('en', 'activate_subtitle')}</p>
      <ActivateClient verifyAction={boundVerify} />
    </Panel>
  );
}
