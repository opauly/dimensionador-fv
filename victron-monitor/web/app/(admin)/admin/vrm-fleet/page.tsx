import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAdmin } from '@/lib/server/auth';
import { listCustomers } from '@/lib/server/db/admin';
import { VrmFleetManager } from './VrmFleetManager';

export const metadata: Metadata = {
  title: 'Link installations — VRM Fleet — Admin',
};

// `/admin/vrm-fleet` (PLAN_PHASE15.md §3.3 / §8 Step 4b) — Oscar's own VRM
// install base (VRM_ADMIN_TOKEN), browsed live and linked/synced onto any
// customer's site. The admin-side counterpart of the customer's own
// "Victron VRM account" panel (`/app/sites`, Step 5) — same underlying
// `vrm_api` pipeline (`vrm_remote.py`/`vrm_series.py`/`vrm_daily.py`), a
// different token source and a different authorization model (§3.3: this
// is Oscar's OWN credential, never a customer's — see that section for why
// this does not reopen §0.5 Q6).
//
// No longer a top-level nav tab (merged into "VRM Fleet" -> `/admin/fleet`,
// 2026-08-31) — reached instead via that dashboard's "Link a new
// installation" link, hence the breadcrumb back to it below. The moment a
// site is linked here it's `source='vrm_api'` + `active=true`, which is the
// only requirement `refresh-snapshots` checks (vrm_fleet.py) — it starts
// showing up in the live dashboard's ~15-minute snapshot sweep automatically,
// no separate enrollment step.
export default async function AdminVrmFleetPage() {
  await requireAdmin();
  const customers = await listCustomers();

  return (
    <div>
      <div className="mono" style={{ fontSize: 12, color: 'var(--mute)', marginBottom: 6 }}>
        <Link href="/admin/fleet" style={{ color: 'var(--mute)' }}>VRM Fleet</Link> / <span style={{ color: 'var(--paper-dim)' }}>Link installations</span>
      </div>
      <h1>Link installations</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Installations visible with Pauly&amp;Co&apos;s VRM token. Link any of them to a customer (existing or new) and sync
        their data directly from the VRM API, without exporting or uploading a CSV. A linked, active site is picked up
        automatically by the live dashboard&apos;s ~15-minute snapshot sync — no separate step.
      </p>
      <VrmFleetManager customers={customers} />
    </div>
  );
}
