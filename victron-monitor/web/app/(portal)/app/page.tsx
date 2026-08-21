import type { Metadata } from 'next';
import { requireCustomer } from '@/lib/server/auth';
import { getBillingStatus, getVrmLinkStatus, listSites } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';
import { BillingBanners, VrmConnectionBanner } from '@/components/app';
import { ReportManager } from './ReportManager';

export const metadata: Metadata = {
  title: 'Reports',
};

// `app/(portal)/app` (Reports — the dashboard's actual landing page,
// PLAN_PHASE14.md §2 Step 6) — replaces Step 3's placeholder. Server
// Component: fetches this customer's own sites (never more), hands them to
// the client-side `ReportManager` for the range picker / job polling /
// summary rendering. `requireCustomer()` first, per §3, even though the
// layout above already called it — "never inferred from layout nesting."
export default async function ReportsPage() {
  const session = await requireCustomer();
  // `getVrmLinkStatus()` alongside `listSites()` — the same connection-state
  // read `/app/sites` already makes, added here so a broken VRM connection
  // (PLAN_PHASE15.md §8 Step 6 / §9) is visible from the moment a customer
  // lands on the dashboard, not only if they happen to visit "My Sites".
  // `getBillingStatus()` alongside them (PLAN_PHASE16.md §7/§8 Step 6) — a
  // `past_due`/over-limit banner is visible from the same landing page, not
  // only on `/app/billing`. `requireCustomer()` (not …AllowPending) above
  // means this is always an already-`active` customer, so the read is
  // always meaningful here (a pending signup never reaches this page).
  const [sites, vrmStatus, billingStatus] = await Promise.all([
    listSites(session.customerId),
    getVrmLinkStatus(session.customerId),
    getBillingStatus(session.customerId),
  ]);

  return (
    <div>
      <h1>{t(session.uiLanguage, 'reports_title')}</h1>
      <p>{t(session.uiLanguage, 'reports_intro')}</p>
      <VrmConnectionBanner status={vrmStatus} lang={session.uiLanguage} />
      <BillingBanners status={billingStatus} lang={session.uiLanguage} />
      <ReportManager sites={sites} lang={session.uiLanguage} />
    </div>
  );
}
