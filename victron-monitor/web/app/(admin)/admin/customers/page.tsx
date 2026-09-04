import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listCustomers } from '@/lib/server/db/admin';
import { CustomersManager } from './CustomersManager';

export const metadata: Metadata = {
  title: 'Customers — Admin',
};

// `/admin/customers` (PLAN_PHASE14.md §2 Step 7) — the admin dashboard's
// landing page. Cross-customer by design: `listCustomers()` is
// `lib/server/db/admin.ts`'s own unscoped read, only importable from
// `/admin/*` (that file's own header comment). `requireAdmin()` first, per
// §3, even though `AdminLayout` already called it.
export default async function AdminCustomersPage() {
  await requireAdmin();
  const customers = await listCustomers();

  return (
    <div>
      <h1>Customers</h1>
      <p className="mono page-desc">
        External customers of the VRM Monitor product — a schema separate from <code>clients</code> (Pauly &amp; Co&apos;s CRM)
        and from the <code>monitoring</code> schema of Oscar&apos;s own sites.
      </p>
      <CustomersManager customers={customers} />
    </div>
  );
}
