import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { listCustomers } from '@/lib/server/db/admin';
import { VrmFleetManager } from './VrmFleetManager';

export const metadata: Metadata = {
  title: 'VRM Fleet — Admin',
};

// `/admin/vrm-fleet` (PLAN_PHASE15.md §3.3 / §8 Step 4b) — Oscar's own VRM
// install base (VRM_ADMIN_TOKEN), browsed live and linked/synced onto any
// customer's site. The admin-side counterpart of the customer's own
// "Victron VRM account" panel (`/app/sites`, Step 5) — same underlying
// `vrm_api` pipeline (`vrm_remote.py`/`vrm_series.py`/`vrm_daily.py`), a
// different token source and a different authorization model (§3.3: this
// is Oscar's OWN credential, never a customer's — see that section for why
// this does not reopen §0.5 Q6).
export default async function AdminVrmFleetPage() {
  await requireAdmin();
  const customers = await listCustomers();

  return (
    <div>
      <h1>VRM Fleet</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Installations visible with Pauly&amp;Co&apos;s VRM token. Link any of them to a customer (existing or new) and sync
        their data directly from the VRM API, without exporting or uploading a CSV.
      </p>
      <VrmFleetManager customers={customers} />
    </div>
  );
}
