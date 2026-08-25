'use client';

// The customer-facing report history (PLAN_PHASE17.md §3.7, §8 Step 7) —
// every `vrm.report_runs` row for this customer, most recent first. A
// sibling of `ReportManager.tsx` on the same page, not a replacement: that
// component is "generate a report right now," this one is "what has
// already run, automatically or otherwise." Read-only except for the
// per-row download button, which mirrors `ReportManager.tsx:handleDownload()`'s
// own signed-URL pattern exactly — a DIFFERENT route
// (`/api/pipeline/reports/runs/[runId]/download`), since a scheduled run is
// never a `vrm.jobs` row (see that route's own header comment).
import { useState } from 'react';
import { Table } from '@/components/ui';
import { formatDate, formatDateTime } from '@/lib/dates';
import { t, type Lang } from '@/lib/i18n/strings';
import type { ReportRunRecord, SiteRecord } from '@/lib/server/db';
import styles from './reports.module.css';

export type ReportHistoryProps = {
  runs: ReportRunRecord[];
  sites: SiteRecord[];
  lang: Lang;
};

// `vrm_api/report_runs.py`'s own vocabulary. `skipped_not_due` is
// deliberately absent — it never has a period to key a `vrm.report_runs`
// row on, so it can never appear in data this component actually renders
// (see `reportRuns.ts`'s own comment on why `listReportRuns()` can never
// return one).
const STATUS_LABEL_KEY: Record<string, string> = {
  done: 'reports_history_status_done',
  skipped_no_data: 'reports_history_status_skipped_no_data',
  skipped_capped: 'reports_history_status_skipped_capped',
  skipped_not_entitled: 'reports_history_status_skipped_not_entitled',
  failed: 'reports_history_status_failed',
  abandoned: 'reports_history_status_abandoned',
};

function statusClassName(status: string): string {
  if (status === 'done') return styles.statusDone;
  if (status === 'failed' || status === 'abandoned' || status === 'skipped_capped' || status === 'skipped_not_entitled') {
    return styles.statusNeedsAttention;
  }
  return styles.statusNeutral;
}

export function ReportHistory({ runs, sites, lang }: ReportHistoryProps) {
  const displayNameBySite = new Map(sites.map((s) => [s.site_id, s.display_name]));
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  async function handleDownload(runId: string) {
    setDownloadError(null);
    setDownloadingId(runId);
    try {
      const res = await fetch(`/api/pipeline/reports/runs/${encodeURIComponent(runId)}/download`);
      if (!res.ok) {
        setDownloadError(t(lang, 'reports_history_download_error'));
        return;
      }
      const { url } = (await res.json()) as { url: string };
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch {
      setDownloadError(t(lang, 'reports_history_download_error'));
    } finally {
      setDownloadingId(null);
    }
  }

  if (runs.length === 0) {
    return (
      <div className={styles.panel}>
        <h2>{t(lang, 'reports_history_title')}</h2>
        <p className={styles.caption}>{t(lang, 'reports_history_empty')}</p>
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <h2>{t(lang, 'reports_history_title')}</h2>
      <p className={styles.caption}>{t(lang, 'reports_history_intro')}</p>
      {downloadError && <p className={styles.error}>{downloadError}</p>}
      <Table>
        <thead>
          <tr>
            <th>{t(lang, 'reports_history_col_site')}</th>
            <th>{t(lang, 'reports_history_col_period')}</th>
            <th>{t(lang, 'reports_history_col_status')}</th>
            <th>{t(lang, 'reports_history_col_date')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{displayNameBySite.get(run.site_id) ?? run.site_id}</td>
              <td>
                {formatDate(run.period_start)} → {formatDate(run.period_end)}
              </td>
              <td>
                <span className={statusClassName(run.status)}>
                  {t(lang, (STATUS_LABEL_KEY[run.status] as Parameters<typeof t>[1] | undefined) ?? 'reports_history_status_failed')}
                </span>
              </td>
              <td>{formatDateTime(run.created_at)}</td>
              <td>
                {run.status === 'done' && (
                  <button
                    type="button"
                    className={styles.downloadButton}
                    onClick={() => handleDownload(run.id)}
                    disabled={downloadingId === run.id}
                  >
                    {downloadingId === run.id ? t(lang, 'reports_history_downloading') : t(lang, 'reports_history_download')}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}
