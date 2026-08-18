import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listAllSites, listCustomers } from '@/lib/server/db/admin';
import { AdminReportsManager } from './AdminReportsManager';

export const metadata: Metadata = {
  title: 'Reportes — Admin',
};

// `/admin/reports` (PLAN_PHASE14.md §2 Step 7) — like `/app`'s report
// generation, but both `vrm` and `monitoring` schemas selectable, with
// `actor: "admin"` set on every call (`app/api/admin/pipeline/reports`).
// `vrmSites` comes straight from `listAllSites()` (already built, Step 4)
// rather than a round trip through `vrm_api`'s new `GET /v1/sites` — that
// endpoint's real reason to exist is `monitoring`, which has no
// `vrm.customers`-backed table to read here (see
// `lib/server/pipeline.ts:listSitesForSchema()`'s own comment).
export default async function AdminReportsPage() {
  await requireAdmin();
  const [vrmSites, customers] = await Promise.all([listAllSites(), listCustomers()]);

  return (
    <div>
      <h1>Reportes</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        El mismo generador sirve para los dos esquemas: <code>vrm</code> (clientes externos, desde CSV) y{' '}
        <code>monitoring</code> (sitios propios con Cerbo GX y Node-RED).
      </p>
      <AdminReportsManager vrmSites={vrmSites} customers={customers} />
    </div>
  );
}
