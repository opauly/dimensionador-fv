import type { Metadata } from 'next';
import { requireCustomer } from '@/lib/server/auth';
import { canAddSite, getCustomer, listSites } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';
import { SitesManager } from './SitesManager';
import styles from './sites.module.css';

export const metadata: Metadata = {
  title: 'My Sites',
};

// `app/(portal)/app/sites` (PLAN_PHASE14.md §2 Step 4) — Server Component:
// fetches this customer's own sites and the add-site gate, then hands both
// to the client-side `SitesManager` for the interactive table/forms.
// `requireCustomer()` first, per §3, even though the layout above already
// called it — "never inferred from layout nesting."
export default async function SitesPage() {
  const session = await requireCustomer();

  // `listSites` and `canAddSite` both take only `session.customerId` —
  // there is no `site_id` or `customer_id` anywhere in this page that came
  // from a query param or a form; every site this page can possibly show
  // or edit is already scoped before it reaches the client.
  const [sites, canAdd, customer] = await Promise.all([
    listSites(session.customerId),
    canAddSite(session.customerId),
    getCustomer(session.customerId),
  ]);

  return (
    <div>
      <h1>{t(session.uiLanguage, 'sites_title')}</h1>
      <p className={styles.intro}>{t(session.uiLanguage, 'sites_intro')}</p>
      <SitesManager sites={sites} lang={session.uiLanguage} canAdd={canAdd} siteLimit={customer.site_limit} />
    </div>
  );
}
