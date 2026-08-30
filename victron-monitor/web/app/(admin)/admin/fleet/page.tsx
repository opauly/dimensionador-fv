import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { getFleetOverview, type FleetConnectionStatus, type FleetOverviewRow } from '@/lib/server/db/admin';
import { Panel, Table } from '@/components/ui';
import { formatDateTime } from '@/lib/dates';
import styles from './fleet.module.css';

export const metadata: Metadata = {
  title: 'Fleet Health — Admin',
};

// `/admin/fleet` — the ops overview a UCR capstone project's own
// requirements doc calls "Dashboard de flota" (Oscar is sponsoring that
// project separately with the same idea; this is built independently now,
// against this product's own real data, not tied to that project's
// timeline). Admin-only by design (confirmed with Oscar, 2026-08-30) — no
// entitlement/tenancy gating, same as every other `/admin/**` page.
//
// Every field comes from `getFleetOverview()` (lib/server/db/admin.ts),
// which reads EXISTING tables only (`vrm.sites`, `vrm.daily_health`,
// `vrm.alarm_events`, `vrm.critical_alerts`, `vrm.customers`) — no new
// migration, no new vrm_api endpoint, same "query Supabase directly from
// the Next.js server" shape `/admin/activity` already uses for a
// cross-customer read with no other consumer to justify a bulk API.
//
// A pure Server Component, no client interactivity — this is a read-only
// status board, not an editor, so there's no state to lift into a 'use
// client' Manager the way most other admin pages need.
function connectionLabel(status: FleetConnectionStatus): string {
  if (status === 'online') return 'Online';
  if (status === 'stale') return 'Stale';
  return 'Never synced';
}

function connectionClass(status: FleetConnectionStatus): string {
  if (status === 'online') return styles.dotOnline;
  if (status === 'stale') return styles.dotStale;
  return styles.dotNever;
}

// Same 4-tier thresholds `vrm_api/report_delivery.py:_health_score_colors()`
// already uses for the emailed report's own health badge — kept visually
// consistent with what a customer's report shows, not a second scale
// invented for this admin-only view.
function healthClass(score: number | null): string {
  if (score === null) return styles.healthNone;
  if (score >= 90) return styles.healthExcellent;
  if (score >= 80) return styles.healthGood;
  if (score >= 70) return styles.healthFair;
  return styles.healthPoor;
}

function row(site: FleetOverviewRow) {
  return (
    <tr key={site.site_id}>
      <td>
        <div>{site.display_name}</div>
        <div className={styles.sub}>{site.customer_name}</div>
      </td>
      <td>
        <span className={`${styles.dot} ${connectionClass(site.connection_status)}`} aria-hidden="true" />
        {connectionLabel(site.connection_status)}
        <div className={styles.sub}>{site.vrm_last_synced_at ? formatDateTime(site.vrm_last_synced_at, 'en-US') : '—'}</div>
      </td>
      <td>
        <span className={`${styles.healthBadge} ${healthClass(site.health_score)}`}>
          {site.health_score === null ? '—' : `${site.health_score}/100`}
        </span>
        {site.health_date && <div className={styles.sub}>as of {site.health_date}</div>}
      </td>
      <td>{site.active_alarms > 0 ? <span className={styles.alarmCount}>{site.active_alarms}</span> : '0'}</td>
      <td>{site.active_critical_alerts > 0 ? <span className={styles.alarmCount}>{site.active_critical_alerts}</span> : '0'}</td>
      <td>
        {site.live_captured_at ? (
          <>
            <div>{formatWatts(site.live_pv_power_w)} PV &middot; {formatWatts(site.live_load_power_w)} load</div>
            <div className={styles.sub}>
              {formatWatts(site.live_battery_power_w)} batt &middot; {site.live_soc_pct === null ? '—' : `${site.live_soc_pct}%`} SOC
            </div>
            <div className={styles.sub}>as of {formatDateTime(site.live_captured_at, 'en-US')}</div>
          </>
        ) : (
          <span className={styles.sub}>No live reading yet</span>
        )}
      </td>
      <td className={styles.sub}>{site.system_type}</td>
    </tr>
  );
}

// `null` (signal not published by this installation, or no snapshot yet)
// reads as an em dash, same convention every other "no data" field on this
// page already uses — never a fabricated "0 W".
function formatWatts(w: number | null): string {
  if (w === null) return '—';
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
}

export default async function AdminFleetPage() {
  await requireAdmin();
  const overview = await getFleetOverview();

  return (
    <div>
      <h1>Fleet Health</h1>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Every <code>source=&apos;vrm_api&apos;</code> site&apos;s current status — the most recent{' '}
        <code>vrm.daily_health</code> score, any alarm/critical-alert episode still open, and (Phase 2) a live
        PV/load/battery/SOC reading refreshed every ~15 minutes by <code>vrm-fleet/refresh-snapshots</code>. Grid
        power only shows where the installation has a real physical grid meter — most don&apos;t, and that column
        reads &quot;—&quot; there rather than a guessed number.
      </p>

      <div className={styles.rollupRow}>
        <Panel className={styles.rollupCard}>
          <span className={styles.rollupLabel}>Sites monitored</span>
          <span className={styles.rollupValue}>{overview.rollup.site_count}</span>
        </Panel>
        <Panel className={styles.rollupCard}>
          <span className={styles.rollupLabel}>Online</span>
          <span className={styles.rollupValue}>
            {overview.rollup.online_count} / {overview.rollup.site_count}
          </span>
        </Panel>
        <Panel className={styles.rollupCard}>
          <span className={styles.rollupLabel}>Avg health score</span>
          <span className={styles.rollupValue}>{overview.rollup.avg_health_score === null ? '—' : `${overview.rollup.avg_health_score}/100`}</span>
        </Panel>
        <Panel className={styles.rollupCard}>
          <span className={styles.rollupLabel}>Active alarms</span>
          <span className={styles.rollupValue}>{overview.rollup.total_active_alarms}</span>
        </Panel>
        <Panel className={styles.rollupCard}>
          <span className={styles.rollupLabel}>Active critical alerts</span>
          <span className={styles.rollupValue}>{overview.rollup.total_active_critical_alerts}</span>
        </Panel>
      </div>

      {overview.sites.length === 0 ? (
        <p className={styles.sub}>No VRM-API-connected sites yet.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Site</th>
              <th>Connection</th>
              <th>Health</th>
              <th>Alarms</th>
              <th>Critical alerts</th>
              <th>Live</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>{overview.sites.map(row)}</tbody>
        </Table>
      )}
    </div>
  );
}
