import type { Metadata } from 'next';
import Link from 'next/link';
import { requireAdmin } from '@/lib/server/auth';
import { getFleetOverview, type FleetConnectionStatus, type FleetOverviewRow } from '@/lib/server/db/admin';
import { Table } from '@/components/ui';
import { formatDateTime, formatDateTimeInZone } from '@/lib/dates';
import { FleetFreshness } from './FleetFreshness';
import { FlowDiagram } from './FlowDiagram';
import { ShapeChart } from './ShapeChart';
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
// Phase 2.5 (2026-08-30) built this out from a plain table into: expandable
// KPI cards (native <details>, no client JS needed for that alone), a
// virtual-plant flow diagram, per-site specific yield, and a "View live →"
// link into `/admin/fleet/[site_id]`. The interactive shape chart is the
// one piece that genuinely needs a Client Component (`ShapeChart.tsx`) —
// everything else on this page stays server-rendered.
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

// `null` (signal not published by this installation, or no snapshot yet)
// reads as an em dash, same convention every other "no data" field on this
// page already uses — never a fabricated "0 W".
function formatWatts(w: number | null): string {
  if (w === null) return '—';
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
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
            <div className={styles.sub}>as of {formatDateTimeInZone(site.live_captured_at, site.timezone, 'en-US')}</div>
          </>
        ) : (
          <span className={styles.sub}>No live reading yet</span>
        )}
      </td>
      <td>
        {site.specific_yield_kwh_per_kwp === null ? (
          <span className={styles.sub}>—</span>
        ) : (
          <span className={styles.yield}>{site.specific_yield_kwh_per_kwp} kWh/kWp</span>
        )}
      </td>
      <td className={styles.sub}>{site.system_type}</td>
      <td>
        <Link href={`/admin/fleet/${encodeURIComponent(site.site_id)}`} className={styles.viewLive}>
          View live →
        </Link>
      </td>
    </tr>
  );
}

export default async function AdminFleetPage() {
  await requireAdmin();
  const overview = await getFleetOverview();

  const sites = overview.sites;
  const solarSites = sites.filter((s) => s.live_pv_power_w !== null);
  const loadSites = sites.filter((s) => s.live_load_power_w !== null);
  const batterySites = sites.filter((s) => s.live_battery_power_w !== null);
  const meteredSites = sites.filter((s) => s.has_grid_meter);
  const socSites = sites.filter((s) => s.live_soc_pct !== null);

  const totalSolar = solarSites.reduce((a, s) => a + (s.live_pv_power_w ?? 0), 0);
  const totalLoad = loadSites.reduce((a, s) => a + (s.live_load_power_w ?? 0), 0);
  const totalBattery = batterySites.reduce((a, s) => a + (s.live_battery_power_w ?? 0), 0);
  const totalGrid = meteredSites.reduce((a, s) => a + (s.live_grid_power_w ?? 0), 0);
  const avgSoc = socSites.length > 0 ? Math.round((socSites.reduce((a, s) => a + (s.live_soc_pct ?? 0), 0) / socSites.length) * 10) / 10 : null;
  const lowestSoc = socSites.length > 0 ? socSites.reduce((min, s) => ((s.live_soc_pct ?? 0) < (min.live_soc_pct ?? 0) ? s : min)) : null;

  // The fleet-wide "how fresh is this" badge is about the VIEWER's own
  // clock, not any one site's — computed here (server-side, cheap: just a
  // max over already-fetched rows) and handed to `FleetFreshness`, the one
  // Client Component on this page, to actually render in the browser's
  // own timezone.
  const capturedTimestamps = sites.map((s) => s.live_captured_at).filter((v): v is string => v !== null);
  const mostRecentCapturedAt = capturedTimestamps.length > 0
    ? capturedTimestamps.reduce((latest, ts) => (ts > latest ? ts : latest))
    : null;

  return (
    <div>
      <div className={styles.pageHead}>
        <h1>Fleet Health</h1>
        {mostRecentCapturedAt && (
          <div className={styles.liveBadge}>
            <span className={styles.pulse} />
            <FleetFreshness mostRecentCapturedAt={mostRecentCapturedAt} />
          </div>
        )}
      </div>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Every <code>source=&apos;vrm_api&apos;</code> site&apos;s current status — the most recent{' '}
        <code>vrm.daily_health</code>/<code>vrm.energy_daily</code> figures, any alarm/critical-alert episode still
        open, and a live PV/load/battery/SOC reading refreshed every ~15 minutes by{' '}
        <code>vrm-fleet/refresh-snapshots</code>. Grid power only shows for the site(s) that actually have a
        physical grid meter — checked per site from real data, not assumed.
      </p>

      <p className={styles.rollupHint}>Click any card to see the per-site numbers behind it.</p>
      <div className={styles.rollupRow}>
        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Sites monitored</span>
            <span className={styles.rollupValue}>{overview.rollup.site_count}</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{connectionLabel(s.connection_status)}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Online</span>
            <span className={styles.rollupValue}>
              {overview.rollup.online_count} / {overview.rollup.site_count}
            </span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{connectionLabel(s.connection_status)}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Avg health score</span>
            <span className={styles.rollupValue}>{overview.rollup.avg_health_score === null ? '—' : `${overview.rollup.avg_health_score}/100`}</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{s.health_score === null ? '—' : `${s.health_score}/100`}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Active alarms</span>
            <span className={styles.rollupValue}>{overview.rollup.total_active_alarms}</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{s.active_alarms}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Active critical alerts</span>
            <span className={styles.rollupValue}>{overview.rollup.total_active_critical_alerts}</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{s.active_critical_alerts}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Avg SOC</span>
            <span className={styles.rollupValue}>{avgSoc === null ? '—' : `${avgSoc}%`}</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{s.live_soc_pct === null ? '—' : `${s.live_soc_pct}%`}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Grid-metered</span>
            <span className={styles.rollupValue}>
              {meteredSites.length}/{sites.length}
            </span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sites.map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <span>{s.display_name}</span>
                <span>{s.has_grid_meter ? 'metered' : 'no meter'}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      {sites.length === 0 ? (
        <p className={styles.sub}>No VRM-API-connected sites yet.</p>
      ) : (
        <>
          <FlowDiagram
            solarW={solarSites.length > 0 ? totalSolar : null}
            solarNote={`${solarSites.length} of ${sites.length} sites`}
            loadW={loadSites.length > 0 ? totalLoad : null}
            loadLabel="All homes"
            batteryW={batterySites.length > 0 ? totalBattery : null}
            batteryNote="net"
            gridW={totalGrid}
            hasGridMeter={meteredSites.length > 0}
            gridNote={`${meteredSites.length} of ${sites.length} sites`}
          />

          <ShapeChart
            siteIds={sites.map((s) => s.site_id)}
            title="Fleet shape"
            cardSub="Aggregate of every connected site's real 15-min VRM data, fetched on demand and summed — nothing here is stored."
          />

          <Table>
            <thead>
              <tr>
                <th>Site</th>
                <th>Connection</th>
                <th>Health</th>
                <th>Alarms</th>
                <th>Critical alerts</th>
                <th>Live</th>
                <th>Yield</th>
                <th>Type</th>
                <th></th>
              </tr>
            </thead>
            <tbody>{sites.map(row)}</tbody>
          </Table>

          {lowestSoc && (
            <p className={styles.sub} style={{ marginTop: 10 }}>
              Lowest SOC right now: {lowestSoc.live_soc_pct}% ({lowestSoc.display_name})
            </p>
          )}
        </>
      )}
    </div>
  );
}
