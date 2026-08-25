import type { Metadata } from 'next';
import { Panel } from '@/components/ui';
import { verifyUnsubscribeToken } from '@/lib/server/reportUnsubscribe';
import { confirmUnsubscribeAction } from './actions';
import { UnsubscribeClient } from './UnsubscribeClient';
import styles from './unsubscribe.module.css';

export const metadata: Metadata = {
  title: 'Unsubscribe',
};

// `/unsubscribe` (PLAN_PHASE17.md §0.6 Q5, §8 Step 8) — the landing page
// for the "stop receiving this report" link in a scheduled report email
// sent to a third-party recipient (`vrm_api/report_delivery.py:
// make_unsubscribe_token()`). No session, no login — a visitor here has
// never had a VRM Monitor account and never will; the signed token IS the
// authorization, the same "public link, no session, but cryptographically
// proven" shape `/activate` already uses for a different capability.
//
// `token` is read from `searchParams` here (this page's own server-rendered
// input) and verified TWICE by design: once here, only to decide what to
// render (an invalid link shows an error instead of a button), and again,
// independently, inside `confirmUnsubscribeAction()` itself when the
// button is actually clicked — the second check is the real control, this
// one is just UX. The token is bound into the Server Action
// (`.bind(null, token)`) rather than ever being handed to
// `UnsubscribeClient` as an inspectable prop — see `../activate/page.tsx`'s
// own comment for why that distinction matters (a bound Server Action
// reference is opaque to the client bundle; a literal string prop is not).
export default async function UnsubscribePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const token = typeof params.token === 'string' ? params.token : null;
  const target = token ? verifyUnsubscribeToken(token) : null;

  if (!token || !target) {
    return (
      <Panel variant="readout" hairline className={styles.card}>
        <h1 className={styles.title}>Invalid link</h1>
        <p className={styles.body}>This unsubscribe link is invalid.</p>
      </Panel>
    );
  }

  const boundConfirm = confirmUnsubscribeAction.bind(null, token);

  return (
    <Panel variant="readout" hairline className={styles.card}>
      <h1 className={styles.title}>Stop receiving this report?</h1>
      <p className={styles.body}>
        <strong>{target.email}</strong> will no longer receive scheduled reports for this site. This does not
        affect anyone else who receives it.
      </p>
      <UnsubscribeClient confirmAction={boundConfirm} />
    </Panel>
  );
}
