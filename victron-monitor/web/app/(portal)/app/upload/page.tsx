import type { Metadata } from 'next';
import { requireCustomer } from '@/lib/server/auth';
import { canAddSite, listIngestions, listSites } from '@/lib/server/db';
import { t } from '@/lib/i18n/strings';
import { UploadManager } from './UploadManager';

export const metadata: Metadata = {
  title: 'Upload CSV',
};

// `app/(portal)/app/upload` (PLAN_PHASE14.md §2 Step 6) — Server Component:
// fetches this customer's own sites, the add-site gate, and their upload
// history, then hands all three to the client-side `UploadManager` for the
// interactive parse -> preview -> confirm flow. `requireCustomer()` first,
// per §3, even though the layout above already called it — "never inferred
// from layout nesting."
export default async function UploadPage() {
  const session = await requireCustomer();

  const [sites, canAdd, ingestions] = await Promise.all([
    listSites(session.customerId),
    canAddSite(session.customerId),
    listIngestions(session.customerId),
  ]);

  return (
    <div>
      <h1>{t(session.uiLanguage, 'upload_title')}</h1>
      <p>{t(session.uiLanguage, 'upload_intro')}</p>
      <UploadManager sites={sites} lang={session.uiLanguage} canAdd={canAdd} ingestions={ingestions} />
    </div>
  );
}
