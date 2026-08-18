import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listCustomers } from '@/lib/server/db/admin';
import { CustomersManager } from './CustomersManager';

export const metadata: Metadata = {
  title: 'Clientes — Admin',
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
      <h1>Clientes</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Clientes externos del producto VRM Monitor — un esquema aparte de <code>clients</code> (el CRM de Pauly &amp; Co) y del
        esquema <code>monitoring</code> de los sitios propios.
      </p>
      <CustomersManager customers={customers} />
    </div>
  );
}
