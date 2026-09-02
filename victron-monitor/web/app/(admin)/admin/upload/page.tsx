import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listCustomers } from '@/lib/server/db/admin';
import { AdminUploadManager } from './AdminUploadManager';

export const metadata: Metadata = {
  title: 'Upload CSV — Admin',
};

// `/admin/upload` (PLAN_PHASE14.md §2 Step 7) — same upload UX as
// `/app/upload`, but with a customer picker first: the one legitimate
// admin-session path to "upload on behalf of a chosen customer," reachable
// only from `requireAdmin()`.
export default async function AdminUploadPage() {
  await requireAdmin();
  // Deactivated customers (QA fixtures, cancelled trials) never belong in a
  // live picker regardless of origin — `/admin/customers` is where Oscar
  // still manages/reactivates them. The admin-vs-self-serve distinction
  // itself is a filter inside AdminUploadManager, not a hard exclusion here,
  // since Oscar's own admin-linked installations are still real customer
  // records he may need to pick.
  const customers = (await listCustomers()).filter((c) => c.active);

  return (
    <div>
      <h1>Upload VRM CSV export</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Upload a file on behalf of a customer. The file is processed and a summary is shown before anything is written to the
        database.
      </p>
      <AdminUploadManager customers={customers} />
    </div>
  );
}
