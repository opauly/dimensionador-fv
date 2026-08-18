import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listAllSites, listCustomers } from '@/lib/server/db/admin';
import { AdminSitesManager } from './AdminSitesManager';

export const metadata: Metadata = {
  title: 'Sitios — Admin',
};

// `/admin/sites` (PLAN_PHASE14.md §2 Step 7) — cross-customer sites table,
// mirroring `pages/06_vrm_monitor.py:tab_sites()`'s own "Clientes y
// sitios" view, plus a customer-reassignment control that view never
// needed (the Streamlit tool only ever wrote sites through
// `ingest.upsert_site()`, never moved one between customers).
export default async function AdminSitesPage() {
  await requireAdmin();
  const [sites, customers] = await Promise.all([listAllSites(), listCustomers()]);

  return (
    <div>
      <h1>Sitios</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Todos los sitios del esquema <code>vrm</code>, de todos los clientes.
      </p>
      <AdminSitesManager sites={sites} customers={customers} />
    </div>
  );
}
