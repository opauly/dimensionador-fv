'use client';

// `/admin/activity`'s recent-runs panel + "Run due now" button
// (PLAN_PHASE17.md §3.7, §8 Step 7) — the detection surface for "the
// scheduled-reports cron silently stopped" (§0.5's own named failure mode:
// GitHub Actions scheduled workflows are best-effort and get disabled
// outright after 60 days of repo inactivity). "Run due now" hits
// `POST /api/admin/pipeline/reports/run-due`, the same
// `requireAdminForRoute()`-gated proxy pattern every other
// `app/api/admin/pipeline/*` route uses (see that route's own header
// comment) — `router.refresh()` afterward re-fetches this table's own
// Server Component data, the same convention `VrmFleetManager.tsx` already
// uses after a sync completes.
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Table } from '@/components/ui';
import { formatDateTime } from '@/lib/dates';
import type { ReportRunRecord } from '@/lib/server/db';
import styles from './activity.module.css';

function statusClassName(status: string): string {
  if (status === 'done') return styles.appliedBadge;
  if (status === 'failed' || status === 'abandoned' || status === 'skipped_capped' || status === 'skipped_not_entitled') {
    return styles.forgedBadge;
  }
  return styles.subtleBadge;
}

export function ReportRunsTable({
  runs,
  customerNameById,
  displayNameBySite,
}: {
  runs: ReportRunRecord[];
  customerNameById: Record<string, string>;
  displayNameBySite: Record<string, string>;
}) {
  const router = useRouter();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRunDue() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch('/api/admin/pipeline/reports/run-due', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        setError('Could not run the scheduled-reports check.');
        return;
      }
      const data = (await res.json()) as { sites_checked: number; processed: number; remaining: number };
      setResult(
        `Checked: ${data.sites_checked} · processed: ${data.processed}${data.remaining > 0 ? ` · remaining: ${data.remaining} (run again)` : ''}`,
      );
      router.refresh();
    } catch {
      setError('Could not reach the report service.');
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        <Button type="button" variant="ghost" onClick={handleRunDue} disabled={running}>
          {running ? 'Running…' : 'Run due reports now'}
        </Button>
        {result && <span className={styles.subtle}>{result}</span>}
      </div>
      {error && <p className={styles.forgedBadge}>{error}</p>}

      {runs.length === 0 ? (
        <p className={styles.empty}>No report runs recorded yet.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Run at</th>
              <th>Customer</th>
              <th>Site</th>
              <th>Trigger</th>
              <th>Period</th>
              <th>Status</th>
              <th>Error</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>{formatDateTime(run.created_at)}</td>
                <td>{customerNameById[run.customer_id] ?? run.customer_id}</td>
                <td>{displayNameBySite[run.site_id] ?? run.site_id}</td>
                <td className="mono">{run.trigger}</td>
                <td>
                  {run.period_start} → {run.period_end}
                </td>
                <td>
                  <span className={statusClassName(run.status)}>{run.status}</span>
                </td>
                <td className={styles.subtle}>{run.error ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </div>
  );
}
