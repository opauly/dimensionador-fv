'use client';

import { Fragment, startTransition, useState } from 'react';
import { Button, Select, Table } from '@/components/ui';
import { formatDateTime as formatDateTimeShared } from '@/lib/dates';
import type { SiteRecord } from '@/lib/server/db';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import { AdminSiteEditForm } from './AdminSiteEditForm';
import { reassignSiteAction } from './actions';
import styles from './sites.module.css';

const SYSTEM_TYPE_LABEL: Record<string, string> = {
  hybrid: 'Hybrid',
  off_grid: 'Off-grid',
  grid_zero: 'Grid-zero',
};

const SOURCE_LABEL: Record<string, string> = {
  vrm_api: 'VRM API',
  csv_upload: 'CSV',
};

function formatDateTime(iso: string | null): string {
  // Delegates to lib/dates.ts's deterministic formatter (2026-08-19 — a
  // real Next.js hydration error surfaced this exact pattern elsewhere in
  // the admin UI). Kept as a local wrapper only for the null-safe
  // signature every call site in this file already relies on.
  if (!iso) return '—';
  return formatDateTimeShared(iso);
}

export function AdminSitesManager({ sites, customers }: { sites: SiteRecord[]; customers: AdminCustomerRow[] }) {
  const [editingSiteId, setEditingSiteId] = useState<string | null>(null);
  const [reassignTarget, setReassignTarget] = useState<Record<string, string>>({});
  const [reassignBusy, setReassignBusy] = useState<Record<string, boolean>>({});
  const [reassignError, setReassignError] = useState<Record<string, string>>({});

  const customerNameById = new Map(customers.map((c) => [c.id, c.name]));

  function handleReassign(siteId: string) {
    const target = reassignTarget[siteId];
    if (!target) return;
    setReassignBusy((b) => ({ ...b, [siteId]: true }));
    setReassignError((e) => ({ ...e, [siteId]: '' }));
    startTransition(async () => {
      const result = await reassignSiteAction(siteId, target);
      setReassignBusy((b) => ({ ...b, [siteId]: false }));
      if (result.error) setReassignError((e) => ({ ...e, [siteId]: result.error! }));
    });
  }

  return (
    <div>
      <Table>
        <thead>
          <tr>
            <th>Site</th>
            <th>site_id</th>
            <th>Customer</th>
            <th>Type</th>
            <th>kWp</th>
            <th>Usable battery (kWh)</th>
            <th>Source</th>
            <th>Last VRM sync</th>
            <th>Active</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sites.map((s) => (
            <Fragment key={s.site_id}>
              <tr>
                <td>{s.display_name}</td>
                <td className="mono">{s.site_id}</td>
                <td>{customerNameById.get(s.customer_id) ?? '—'}</td>
                <td>{SYSTEM_TYPE_LABEL[s.system_type] ?? s.system_type}</td>
                <td>{s.pv_kwp ?? '—'}</td>
                <td>{s.battery_usable_kwh ?? '—'}</td>
                <td className="mono">{SOURCE_LABEL[s.source] ?? s.source}</td>
                <td>
                  {/* `vrm_sync_enabled === false` on an otherwise `vrm_api` site is
                     §9's "installation removed / no longer shared" row — the site
                     kept its data and its source, but syncing has been paused;
                     surfaced here, next to the timestamp/error it explains, rather
                     than as a separate column. */}
                  {s.source === 'vrm_api' ? (
                    <>
                      {formatDateTime(s.vrm_last_synced_at)}
                      {!s.vrm_sync_enabled && <div className={styles.syncPaused}>Sync paused</div>}
                      {s.vrm_last_sync_error && <div className={styles.syncError}>{s.vrm_last_sync_error}</div>}
                    </>
                  ) : (
                    '—'
                  )}
                </td>
                <td>
                  <span className={s.active ? styles.statusActive : styles.statusInactive}>{s.active ? 'Yes' : 'No'}</span>
                </td>
                <td>
                  <Button type="button" variant="ghost" onClick={() => setEditingSiteId(editingSiteId === s.site_id ? null : s.site_id)}>
                    Edit
                  </Button>
                </td>
              </tr>
              {editingSiteId === s.site_id && (
                <tr>
                  <td colSpan={10} className={styles.editRow}>
                    <AdminSiteEditForm site={s} onDone={() => setEditingSiteId(null)} />

                    <div className={styles.reassignRow}>
                      <span className={styles.reassignLabel}>Reassign to another customer:</span>
                      <Select
                        value={reassignTarget[s.site_id] ?? s.customer_id}
                        onChange={(e) => setReassignTarget((t) => ({ ...t, [s.site_id]: e.target.value }))}
                        disabled={reassignBusy[s.site_id]}
                      >
                        {customers.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </Select>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={reassignBusy[s.site_id] || (reassignTarget[s.site_id] ?? s.customer_id) === s.customer_id}
                        onClick={() => handleReassign(s.site_id)}
                      >
                        Reassign
                      </Button>
                      {reassignError[s.site_id] && <span className={styles.error}>{reassignError[s.site_id]}</span>}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </Table>
    </div>
  );
}
