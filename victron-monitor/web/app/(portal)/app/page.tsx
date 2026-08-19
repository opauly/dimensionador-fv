import type { Metadata } from 'next';
import { requireCustomer } from '@/lib/server/auth';
import { getVrmLinkStatus, listSites } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';
import { VrmConnectionBanner } from '@/components/app';
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
  const [sites, vrmStatus] = await Promise.all([listSites(session.customerId), getVrmLinkStatus(session.customerId)]);

  return (
    <div>
      <h1>{t(session.uiLanguage, 'reports_title')}</h1>
      <p>{t(session.uiLanguage, 'reports_intro')}</p>
      <VrmConnectionBanner status={vrmStatus} lang={session.uiLanguage} />
      <ReportManager sites={sites} lang={session.uiLanguage} />
    </div>
  );
}
