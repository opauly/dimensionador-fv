'use client';

import { Fragment, useState } from 'react';
import { Table } from '@/components/ui';
import type { IngestionLogRecord } from '@/lib/server/db';
import styles from './activity.module.css';

function warningMessages(warnings: unknown): string[] {
  if (!warnings) return [];
  if (Array.isArray(warnings)) return warnings.map(String);
  const messages = (warnings as { messages?: unknown }).messages;
  return Array.isArray(messages) ? messages.map(String) : [];
}

export function ActivityTable({
  ingestions,
  customerNameBySite,
  displayNameBySite,
}: {
  ingestions: IngestionLogRecord[];
  customerNameBySite: Record<string, string>;
  displayNameBySite: Record<string, string>;
}) {
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  if (ingestions.length === 0) {
    return <p className={styles.empty}>Todavía no hay cargas registradas.</p>;
  }

  return (
    <Table>
      <thead>
        <tr>
          <th>Cliente</th>
          <th>Sitio</th>
          <th>Archivo</th>
          <th>Origen</th>
          <th>Periodo</th>
          <th>Días</th>
          <th>Alarmas</th>
          <th>Avisos</th>
          <th>Subido</th>
        </tr>
      </thead>
      <tbody>
        {ingestions.map((log) => {
          const warnings = warningMessages(log.warnings);
          return (
            <Fragment key={log.id}>
              <tr>
                <td>{customerNameBySite[log.site_id] ?? '—'}</td>
                <td>{displayNameBySite[log.site_id] ?? log.site_id}</td>
                <td>{log.filename ?? '—'}</td>
                <td className="mono">{log.source}</td>
                <td>
                  {log.period_start?.slice(0, 10) ?? '—'} → {log.period_end?.slice(0, 10) ?? '—'}
                </td>
                <td>{log.rows_written ?? '—'}</td>
                <td>{log.alarm_events_written ?? '—'}</td>
                <td>
                  {warnings.length > 0 ? (
                    <button type="button" className={styles.expandButton} onClick={() => setExpanded((e) => ({ ...e, [log.id]: !e[log.id] }))}>
                      {warnings.length} {expanded[log.id] ? '▲' : '▼'}
                    </button>
                  ) : (
                    0
                  )}
                </td>
                <td>{new Date(log.uploaded_at).toLocaleString('es-CR')}</td>
              </tr>
              {expanded[log.id] && warnings.length > 0 && (
                <tr>
                  <td colSpan={9} className={styles.warningsRow}>
                    <ul>
                      {warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </Table>
  );
}
