import { t, type Lang } from '@/lib/i18n/strings';
import type { VrmLinkStatusOut } from '@/lib/server/db';
import styles from './VrmConnectionBanner.module.css';

export type VrmConnectionBannerProps = {
  status: VrmLinkStatusOut;
  lang: Lang;
};

// The failure-surfacing banner (PLAN_PHASE15.md §8 Step 6, §9's table) —
// rendered at the top of `/app` and `/app/sites`, the two places §9 says a
// broken VRM connection must be visible to the customer. A plain Server
// Component (no 'use client' — nothing here is interactive), so both pages
// can render it straight off their own `getVrmLinkStatus()` read with no
// extra client round trip.
//
// "Broken" is `!connected` AND (`token_revoked_at` set OR `token_last_error`
// present). §9's own condition is stated without the `!connected` half, but
// live validation (PLAN_PHASE15.md §8 Step 6's own coder-report) found a
// real false positive without it: `vrm.set_customer_vrm_token()` clears
// `vrm_token_revoked_at` on reconnect but does NOT clear
// `vrm_token_last_error` — only the NEXT SUCCESSFUL sync does
// (`vrm_sync.py`'s own success branch) — so a customer who just reconnected
// and is looking at the real "Connected" panel, with their account email on
// screen, would otherwise still be told their connection "stopped working"
// until they click Sync once. `status.connected` is the one field that is
// always current (computed fresh by `vrm_link.py:get_status()` on every
// read, never a stale leftover), so gating on it is the smallest fix that
// removes the false positive without changing what "broken" means for
// every other row of §9's table. `token_revoked_at` still gets stamped by
// BOTH an auth failure and a deliberate disconnect (see
// `lib/server/db/types.ts:CustomerRecord.vrm_token_revoked_at`'s own
// comment) — this banner does not try to tell those apart, because
// "reconnect to resume automatic updates" is equally the right next step
// either way, and a customer who just clicked Disconnect already saw that
// happen on the same page (`VrmLinkPanel.tsx`'s own disconnected view).
export function VrmConnectionBanner({ status, lang }: VrmConnectionBannerProps) {
  const broken = !status.connected && (Boolean(status.token_revoked_at) || Boolean(status.token_last_error));
  if (!broken) return null;

  return (
    <div className={styles.banner} role="alert">
      <p>{t(lang, 'vrm_link_broken_banner')}</p>
    </div>
  );
}
