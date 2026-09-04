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
  title: 'VRM Fleet — Admin',
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

// Every rollup card's breakdown list, sorted by whatever value that card
// itself displays (2026-09-03, Oscar's own request) — highest first, `null`
// (nothing to rank) always last, and alphabetical by display_name as the
// tiebreaker for equal or absent values. Never mutates the input array.
function sortedByValue(sites: FleetOverviewRow[], valueFn: (s: FleetOverviewRow) => number | null): FleetOverviewRow[] {
  return [...sites].sort((a, b) => {
    const va = valueFn(a);
    const vb = valueFn(b);
    if (va === null && vb === null) return a.display_name.localeCompare(b.display_name);
    if (va === null) return 1;
    if (vb === null) return -1;
    if (va !== vb) return vb - va;
    return a.display_name.localeCompare(b.display_name);
  });
}

// Worst-first rank for the two cards that only have a categorical (not
// numeric) value to show — surfaces the sites actually worth looking at
// instead of an arbitrary DB-fetch order, without pretending "Online" vs
// "Stale" is a continuous quantity.
const _CONNECTION_RANK: Record<FleetConnectionStatus, number> = { never_synced: 2, stale: 1, online: 0 };

function sortedAlphabetically(sites: FleetOverviewRow[]): FleetOverviewRow[] {
  return [...sites].sort((a, b) => a.display_name.localeCompare(b.display_name));
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
        <div className={styles.sub}>
          Report data: {site.vrm_last_synced_at ? formatDateTime(site.vrm_last_synced_at, 'en-US') : 'never'}
        </div>
      </td>
      <td>
        <span
          className={`${styles.healthBadge} ${healthClass(site.health_score)}`}
          title={site.health_notes ? site.health_notes.split(';').map((n) => n.trim()).filter(Boolean).join('\n') : undefined}
        >
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
  // A stale site's last snapshot still has real (once-live) readings sitting
  // in its row — e.g. a site last seen at 10:42am with sun out still shows
  // "370W PV" 44 days later at 11pm with none. Gating on `connection_status
  // === 'online'` (the same ~45-minute freshness `_connectionStatus()`
  // already computes) keeps these fleet-wide "live" totals actually live,
  // instead of quietly summing months-old readings as if they were current.
  const onlineSites = sites.filter((s) => s.connection_status === 'online');
  const solarSites = onlineSites.filter((s) => s.live_pv_power_w !== null);
  const loadSites = onlineSites.filter((s) => s.live_load_power_w !== null);
  const batterySites = onlineSites.filter((s) => s.live_battery_power_w !== null);
  const meteredSites = onlineSites.filter((s) => s.has_grid_meter);
  const socSites = onlineSites.filter((s) => s.live_soc_pct !== null);

  const totalSolar = solarSites.reduce((a, s) => a + (s.live_pv_power_w ?? 0), 0);
  const totalLoad = loadSites.reduce((a, s) => a + (s.live_load_power_w ?? 0), 0);
  const totalBattery = batterySites.reduce((a, s) => a + (s.live_battery_power_w ?? 0), 0);
  const totalGrid = meteredSites.reduce((a, s) => a + (s.live_grid_power_w ?? 0), 0);
  const avgSoc = socSites.length > 0 ? Math.round((socSites.reduce((a, s) => a + (s.live_soc_pct ?? 0), 0) / socSites.length) * 10) / 10 : null;
  const lowestSoc = socSites.length > 0 ? socSites.reduce((min, s) => ((s.live_soc_pct ?? 0) < (min.live_soc_pct ?? 0) ? s : min)) : null;

  // "History Sync" — the DAILY report-data pipeline's own freshness
  // (vrm_last_synced_at), deliberately separate from "Online" above (the
  // LIVE ~15-min snapshot's own freshness) — see the Help tab for why the
  // two are independent pipelines that can genuinely disagree. 24h, not
  // the per-site "Online" badge's 45-minute window: this is a daily-grade
  // signal, checking "did today's sync actually run," not "is it live."
  const now = Date.now();
  const historySyncedSites = sites.filter((s) => {
    if (!s.vrm_last_synced_at) return false;
    return now - new Date(s.vrm_last_synced_at).getTime() <= 24 * 60 * 60 * 1000;
  });

  // Outages this week — from the same real energy_daily-derived figures
  // the per-site "This week" panel already shows, not a live signal (an
  // outage is inherently a past event by the time it's counted).
  const outageSites = sites.filter((s) => s.week.outageCount > 0);

  // Per-type anomaly counts (Fleet Dashboard Phase 3a/3b/3c) — computed here
  // from each site's own `active_anomalies` rather than adding three more
  // rollup fields to getFleetOverview(): the full per-anomaly detail
  // (including `anomaly_type`) already travels with every site, so slicing
  // it three ways client-side is enough, no new server-side aggregation
  // needed.
  const allActiveAnomalies = sites.flatMap((s) => s.active_anomalies);
  const silenceCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'unexpected_silence').length;
  const driftCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'quiet_drift').length;
  const underperformanceCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'underperformance').length;

  // Fleet averages for the three IE-0499 §4 daily-indicator formulas —
  // same per-site numbers `_dailyIndicators()` already computes, averaged
  // only over sites that actually have a value today (never treating a
  // missing denominator as a 0%).
  const avgOf = (values: (number | null)[]) => {
    const real = values.filter((v): v is number => v !== null);
    return real.length > 0 ? Math.round((real.reduce((a, b) => a + b, 0) / real.length) * 10) / 10 : null;
  };
  const avgSelfSufficiency = avgOf(sites.map((s) => s.self_sufficiency_pct));
  const avgSelfConsumption = avgOf(sites.map((s) => s.self_consumption_pct));
  const avgGridDependency = avgOf(sites.map((s) => s.grid_dependency_pct));

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
        <h1>VRM Fleet</h1>
        {mostRecentCapturedAt && (
          <div className={styles.liveBadge}>
            <span className={styles.pulse} />
            <FleetFreshness mostRecentCapturedAt={mostRecentCapturedAt} />
          </div>
        )}
      </div>
      <Link href="/admin/vrm-fleet" className={styles.manageLink}>
        + Link a new installation →
      </Link>
      <p className="mono" style={{ color: 'var(--paper-dim)', marginBottom: 20 }}>
        Every <code>source=&apos;vrm_api&apos;</code> site&apos;s current status — the most recent{' '}
        <code>vrm.daily_health</code>/<code>vrm.energy_daily</code> figures, any alarm/critical-alert episode still
        open, and a live PV/load/battery/SOC reading refreshed every ~15 minutes by{' '}
        <code>vrm-fleet/refresh-snapshots</code>. Grid power comes from a dedicated meter where one exists, and
        falls back to the inverter&apos;s own reading otherwise — checked per site from real data, not assumed.
      </p>

      <p className={styles.rollupHint}>Click any card to see the per-site numbers behind it.</p>

      <h2 className={styles.rollupGroupLabel}>Fleet &amp; connectivity</h2>
      <div className={styles.rollupRow}>
        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Sites monitored</span>
            <span className={styles.rollupValue}>{overview.rollup.site_count}</span>
            <span className={styles.rollupDesc}>Total sites currently linked via the VRM API</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedAlphabetically(sites).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
            <span className={styles.rollupDesc}>Live snapshot received in the last 45 minutes</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => _CONNECTION_RANK[s.connection_status]).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{connectionLabel(s.connection_status)}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Grid reading</span>
            <span className={styles.rollupValue}>
              {meteredSites.length}/{sites.length}
            </span>
            <span className={styles.rollupDesc}>Sites reporting grid power, via meter or inverter</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedAlphabetically(sites).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>
                  {s.live_grid_source === 'meter' ? 'dedicated meter'
                    : s.live_grid_source === 'inverter' ? 'via inverter'
                    : 'none'}
                </span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>History sync</span>
            <span className={styles.rollupValue}>
              {historySyncedSites.length}/{sites.length}
            </span>
            <span className={styles.rollupDesc}>Daily report data synced in the last 24 hours</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {/* Oldest/never-synced first — a negated epoch so "never"
               (null) sorts as the largest, most-concerning value via the
               same descending numeric sort every other card uses. */}
            {sortedByValue(sites, (s) => (s.vrm_last_synced_at ? -new Date(s.vrm_last_synced_at).getTime() : Infinity)).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.vrm_last_synced_at ? formatDateTime(s.vrm_last_synced_at, 'en-US') : 'never'}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      <h2 className={styles.rollupGroupLabel}>Health &amp; alerts</h2>
      <div className={styles.rollupRow}>
        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Avg health score</span>
            <span className={styles.rollupValue}>{overview.rollup.avg_health_score === null ? '—' : `${overview.rollup.avg_health_score}/100`}</span>
            <span className={styles.rollupDesc}>Average of each site&apos;s latest daily health score</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.health_score).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.health_score === null ? '—' : `${s.health_score}/100`}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Active alarms</span>
            <span className={styles.rollupValue}>{overview.rollup.total_active_alarms}</span>
            <span className={styles.rollupDesc}>Low battery / overload, present in the latest live fetch</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_alarms).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_alarms}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Active critical alerts</span>
            <span className={styles.rollupValue}>{overview.rollup.total_active_critical_alerts}</span>
            <span className={styles.rollupDesc}>DC ripple, cell imbalance, temp fault — live, right now</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_critical_alerts).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_critical_alerts}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Outages (7d)</span>
            <span className={styles.rollupValue}>
              {outageSites.length}/{sites.length}
            </span>
            <span className={styles.rollupDesc}>Sites with a grid outage in the last 7 days</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => (s.week.daysWithData === 0 ? null : s.week.outageMinutes)).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.week.daysWithData === 0 ? '—' : s.week.outageCount > 0 ? `${s.week.outageCount} (${s.week.outageMinutes} min)` : '0'}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      <h2 className={styles.rollupGroupLabel}>Energy performance (today)</h2>
      <div className={styles.rollupRow}>
        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Avg SOC</span>
            <span className={styles.rollupValue}>{avgSoc === null ? '—' : `${avgSoc}%`}</span>
            <span className={styles.rollupDesc}>Average state of charge across the fleet, right now</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.live_soc_pct).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.live_soc_pct === null ? '—' : `${s.live_soc_pct}%`}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Self-sufficiency</span>
            <span className={styles.rollupValue}>{avgSelfSufficiency === null ? '—' : `${avgSelfSufficiency}%`}</span>
            <span className={styles.rollupDesc}>Share of today&apos;s load covered by solar + battery</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.self_sufficiency_pct).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.self_sufficiency_pct === null ? '—' : `${s.self_sufficiency_pct}%`}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Self-consumption</span>
            <span className={styles.rollupValue}>{avgSelfConsumption === null ? '—' : `${avgSelfConsumption}%`}</span>
            <span className={styles.rollupDesc}>Share of solar generated that was used on-site</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.self_consumption_pct).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.self_consumption_pct === null ? '—' : `${s.self_consumption_pct}%`}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Grid dependency</span>
            <span className={styles.rollupValue}>{avgGridDependency === null ? '—' : `${avgGridDependency}%`}</span>
            <span className={styles.rollupDesc}>Share of today&apos;s load pulled from the grid</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.grid_dependency_pct).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.grid_dependency_pct === null ? '—' : `${s.grid_dependency_pct}%`}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      <h2 className={styles.rollupGroupLabel}>AI Insights</h2>
      <p className={styles.sub}>
        Deterministic checks against each site&apos;s own history — not a model. Split by type below so a spike in
        one kind of anomaly doesn&apos;t hide in a single combined count.
      </p>
      <div className={styles.rollupRow}>
        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Unexpected silence</span>
            <span className={styles.rollupValue}>{silenceCount}</span>
            <span className={styles.rollupDesc}>A real zero during hours this site has historically produced</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'unexpected_silence').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'unexpected_silence').length}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Quiet drift</span>
            <span className={styles.rollupValue}>{driftCount}</span>
            <span className={styles.rollupDesc}>Trending down vs. this site&apos;s own recent baseline</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'quiet_drift').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'quiet_drift').length}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>Underperformance</span>
            <span className={styles.rollupValue}>{underperformanceCount}</span>
            <span className={styles.rollupDesc}>Below what this site&apos;s installed size should deliver</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'underperformance').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/admin/fleet/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'underperformance').length}</span>
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
