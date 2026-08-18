'use client';

// Table + create/edit forms + invite actions for `/admin/customers`
// (PLAN_PHASE14.md §2 Step 7). Row-level actions (enviar/reenviar
// invitación, activar/desactivar) are plain Server Actions invoked
// directly from `onClick` inside `startTransition` — the same "invoked
// directly ... wrapped in startTransition" shape
// `app/(portal)/app/sites/SiteForm.tsx:handleGeocodeClick` already
// establishes for a non-`<form>` server action call, not a new pattern.
import { Fragment, startTransition, useState } from 'react';
import { Button, Table } from '@/components/ui';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import { planLabel } from '@/lib/plans';
import { countryLabel } from '@/lib/countries';
import { CreateCustomerForm } from './CreateCustomerForm';
import { EditCustomerForm } from './EditCustomerForm';
import { resendInviteAction, sendInviteAction, setActiveAction } from './actions';
import styles from './customers.module.css';

function authStatusLabel(c: AdminCustomerRow): { text: string; className: string } {
  if (!c.auth_user_id) return { text: 'Sin invitar', className: styles.statusNone };
  if (!c.activated_at) return { text: `Invitado ${formatDate(c.invited_at)}`, className: styles.statusInvited };
  return { text: `Activo ${formatDate(c.activated_at)}`, className: styles.statusActive };
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('es-CR', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function CustomersManager({ customers }: { customers: AdminCustomerRow[] }) {
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [rowBusy, setRowBusy] = useState<Record<string, boolean>>({});
  const [rowError, setRowError] = useState<Record<string, string>>({});

  function runRowAction(id: string, fn: () => Promise<{ ok?: boolean; error?: string } | void>) {
    setRowBusy((b) => ({ ...b, [id]: true }));
    setRowError((e) => ({ ...e, [id]: '' }));
    startTransition(async () => {
      const result = await fn();
      setRowBusy((b) => ({ ...b, [id]: false }));
      if (result && 'error' in result && result.error) {
        setRowError((e) => ({ ...e, [id]: result.error! }));
      }
    });
  }

  return (
    <div>
      <Table>
        <thead>
          <tr>
            <th>Nombre</th>
            <th>Tipo</th>
            <th>Plan</th>
            <th>Sitios</th>
            <th>Última carga</th>
            <th>Acceso</th>
            <th>Activo</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {customers.map((c) => (
            <Fragment key={c.id}>
              <tr>
                <td>
                  {c.name}
                  <div className={styles.subtle}>
                    {c.slug} · {countryLabel(c.country)}
                  </div>
                </td>
                <td>{c.account_type === 'installer' ? 'Installer' : 'Owner'}</td>
                <td>{planLabel(c.plan)}</td>
                <td>
                  {c.siteCount}
                  {c.site_limit !== null ? ` / ${c.site_limit}` : ''}
                </td>
                <td>{c.lastUploadAt ? formatDate(c.lastUploadAt) : '—'}</td>
                <td>
                  <span className={authStatusLabel(c).className}>{authStatusLabel(c).text}</span>
                  {rowError[c.id] && <div className={styles.rowError}>{rowError[c.id]}</div>}
                </td>
                <td>
                  <span className={c.active ? styles.statusActive : styles.statusNone}>{c.active ? 'Sí' : 'No'}</span>
                </td>
                <td className={styles.actionsCell}>
                  <Button type="button" variant="ghost" onClick={() => setEditingId(editingId === c.id ? null : c.id)}>
                    Editar
                  </Button>
                  {c.auth_user_id ? (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={rowBusy[c.id]}
                      onClick={() => runRowAction(c.id, () => resendInviteAction(c.id))}
                    >
                      Reenviar invitación
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={rowBusy[c.id]}
                      onClick={() => runRowAction(c.id, () => sendInviteAction(c.id))}
                    >
                      Enviar invitación
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={rowBusy[c.id]}
                    onClick={() => runRowAction(c.id, () => setActiveAction(c.id, !c.active))}
                  >
                    {c.active ? 'Desactivar' : 'Activar'}
                  </Button>
                </td>
              </tr>
              {editingId === c.id && (
                <tr>
                  <td colSpan={8} className={styles.editRow}>
                    <EditCustomerForm customer={c} onDone={() => setEditingId(null)} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </Table>

      <div className={styles.actionsRow}>
        {!creating && (
          <Button type="button" onClick={() => setCreating(true)}>
            Nuevo cliente
          </Button>
        )}
      </div>

      {creating && (
        <div className={styles.panel}>
          <h3>Nuevo cliente</h3>
          <CreateCustomerForm onDone={() => setCreating(false)} />
        </div>
      )}
    </div>
  );
}
