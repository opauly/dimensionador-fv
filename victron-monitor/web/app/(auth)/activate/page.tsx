import type { Metadata } from 'next';
import { Panel } from '@/components/ui';
import { t } from '@/lib/i18n/strings';
import { setActivationPasswordAction, verifyActivationTokenAction } from './actions';
import { ActivateClient } from './ActivateClient';
import styles from './activate.module.css';

export const metadata: Metadata = {
  title: 'Activate your account',
};

/**
 * Open-redirect guard (PLAN_PHASE16.md §5.5 Step 3, §8 Step 5.5 build item
 * 5) — `next` is attacker-influenced (it comes straight off the URL an
 * email link was built from, `lib/server/signup.ts:redeemSignupToken()`'s
 * own `next=/app/billing?plan=...` today, but nothing stops a crafted
 * `/activate?...&next=https://evil.example` link from arriving too). Must
 * be a same-origin RELATIVE path beginning with `/app`, and must not begin
 * with `//` — a scheme-relative URL (`//evil.example.com`) a browser
 * resolves as absolute even though it reads as "relative" to a naive
 * string check. Anything else (a bare domain, `https://...`, `/admin`, `/`,
 * malformed input, or simply absent) falls back to `/app`.
 *
 * Lives HERE, in `page.tsx`, rather than `actions.ts` — see
 * `setActivationPasswordAction()`'s own comment: `actions.ts` has `'use
 * server'` at the top, which turns every export into a Server Action
 * reference and requires every one of them to be `async`; a plain
 * synchronous helper exported from that file breaks the whole module at
 * compile time.
 */
function sanitizeNextPath(value: string | null): string {
  if (!value) return '/app';
  if (value.startsWith('//')) return '/app';
  if (!value.startsWith('/app')) return '/app';
  return value;
}

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
  // PLAN_PHASE16.md §5.5 Step 3 — validated here, server-side, alongside
  // `tokenHash`/`type`; see `sanitizeNextPath()` above for the open-redirect
  // reasoning. `redeemSignupToken()`
  // (`lib/server/signup.ts`) is the one real caller today
  // (`next=/app/billing?plan=...`); every other `/activate` link (admin
  // invites, resends, password resets) has no `next` at all and falls back
  // to `/app`, unchanged from before this step.
  const nextPath = sanitizeNextPath(typeof params.next === 'string' ? params.next : null);

  if (!tokenHash || !type) {
    return (
      <Panel variant="readout" hairline className={styles.card}>
        <h1 className={styles.title}>{t('en', 'activate_invalid_title')}</h1>
        <p className={styles.body}>{t('en', 'activate_invalid_body')}</p>
      </Panel>
    );
  }

  const boundVerify = verifyActivationTokenAction.bind(null, tokenHash, type);
  const boundSetPassword = setActivationPasswordAction.bind(null, nextPath);

  return (
    <Panel variant="readout" hairline className={styles.card}>
      <h1 className={styles.title}>{t('en', 'activate_title')}</h1>
      <p className={styles.subtitleIntro}>{t('en', 'activate_subtitle')}</p>
      <ActivateClient verifyAction={boundVerify} setPasswordAction={boundSetPassword} />
    </Panel>
  );
}
