import type { Metadata } from 'next';
import Link from 'next/link';
import { requireCustomer } from '@/lib/server/auth';
import { getCustomer, getDashboardAccess, getCustomerFleetOverview, type FleetConnectionStatus, type FleetOverviewRow } from '@/lib/server/db';
import { Table, Panel, Button } from '@/components/ui';
import { formatDateTime, formatDateTimeInZone } from '@/lib/dates';
import { t } from '@/lib/i18n/strings';
import { FleetFreshness } from '../../../(admin)/admin/fleet/FleetFreshness';
import { FlowDiagram } from '../../../(admin)/admin/fleet/FlowDiagram';
import { ShapeChart } from '../../../(admin)/admin/fleet/ShapeChart';
import styles from './dashboard.module.css';

export const metadata: Metadata = {
  title: 'Dashboard',
};

// `/app/dashboard` — the customer-facing counterpart of the admin-only
// `/admin/fleet` (2026-09-03, Oscar's decision to offer the same live
// health/AI-Insights view to real Growth/Fleet subscribers). Reuses
// `admin/fleet`'s own presentational components (FlowDiagram/ShapeChart/
// FleetFreshness — pure, no admin coupling) and its exact indicator math
// (`fleetOverviewCore.ts`, via `getCustomerFleetOverview()`), but never
// imports `lib/server/db/admin.ts` itself — this file's data comes from
// `lib/server/db`'s tenant-scoped barrel only, same rule every other
// `/app/**` page follows.
//
// Card labels/descriptions below are intentionally left in English for
// this first version (matching a lot of the underlying technical
// vocabulary — SOC, kWh/kWp — that reads the same in both languages
// anyway); the page chrome that actually needs it (title, intro, the
// upsell panel, AI Insights heading, and anomaly type names) DOES respect
// `session.uiLanguage` via `t()`, unlike the English-only admin version.
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

function healthClass(score: number | null): string {
  if (score === null) return styles.healthNone;
  if (score >= 90) return styles.healthExcellent;
  if (score >= 80) return styles.healthGood;
  if (score >= 70) return styles.healthFair;
  return styles.healthPoor;
}

function formatWatts(w: number | null): string {
  if (w === null) return '—';
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
}

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

const _CONNECTION_RANK: Record<FleetConnectionStatus, number> = { never_synced: 2, stale: 1, online: 0 };

function sortedAlphabetically(sites: FleetOverviewRow[]): FleetOverviewRow[] {
  return [...sites].sort((a, b) => a.display_name.localeCompare(b.display_name));
}

export default async function CustomerDashboardPage() {
  const session = await requireCustomer();
  const lang = session.uiLanguage;
  const customer = await getCustomer(session.customerId);
  const allowed = await getDashboardAccess(customer);

  if (!allowed) {
    return (
      <div>
        <h1>{t(lang, 'dashboard_title')}</h1>
        <Panel className={styles.upsell}>
          <h2>{t(lang, 'dashboard_upsell_title')}</h2>
          <p>{t(lang, 'dashboard_upsell_body')}</p>
          <Button href="/app/billing">{t(lang, 'dashboard_upsell_cta')}</Button>
        </Panel>
      </div>
    );
  }

  const overview = await getCustomerFleetOverview(session.customerId);
  const sites = overview.sites;

  const row = (site: FleetOverviewRow) => (
    <tr key={site.site_id}>
      <td>
        <div>{site.display_name}</div>
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
        <Link href={`/app/dashboard/${encodeURIComponent(site.site_id)}`} className={styles.viewLive}>
          {t(lang, 'dashboard_view_site')}
        </Link>
      </td>
    </tr>
  );

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

  const now = Date.now();
  const historySyncedSites = sites.filter((s) => {
    if (!s.vrm_last_synced_at) return false;
    return now - new Date(s.vrm_last_synced_at).getTime() <= 24 * 60 * 60 * 1000;
  });

  const outageSites = sites.filter((s) => s.week.outageCount > 0);

  const allActiveAnomalies = sites.flatMap((s) => s.active_anomalies);
  const silenceCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'unexpected_silence').length;
  const driftCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'quiet_drift').length;
  const underperformanceCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'underperformance').length;
  const incompleteChargingCount = allActiveAnomalies.filter((a) => a.anomaly_type === 'incomplete_charging').length;

  const avgOf = (values: (number | null)[]) => {
    const real = values.filter((v): v is number => v !== null);
    return real.length > 0 ? Math.round((real.reduce((a, b) => a + b, 0) / real.length) * 10) / 10 : null;
  };
  const avgSelfSufficiency = avgOf(sites.map((s) => s.self_sufficiency_pct));
  const avgSelfConsumption = avgOf(sites.map((s) => s.self_consumption_pct));
  const avgGridDependency = avgOf(sites.map((s) => s.grid_dependency_pct));

  const capturedTimestamps = sites.map((s) => s.live_captured_at).filter((v): v is string => v !== null);
  const mostRecentCapturedAt = capturedTimestamps.length > 0
    ? capturedTimestamps.reduce((latest, ts) => (ts > latest ? ts : latest))
    : null;

  return (
    <div>
      <div className={styles.pageHead}>
        <div className={styles.titleRow}>
          <h1>{t(lang, 'dashboard_title')}</h1>
        </div>
        {mostRecentCapturedAt && (
          <div className={styles.liveBadge}>
            <span className={styles.pulse} />
            <FleetFreshness mostRecentCapturedAt={mostRecentCapturedAt} />
          </div>
        )}
      </div>
      <p className={`mono ${styles.pageDesc}`}>{t(lang, 'dashboard_intro')}</p>

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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
            {sortedByValue(sites, (s) => (s.vrm_last_synced_at ? -new Date(s.vrm_last_synced_at).getTime() : Infinity)).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
            <span className={styles.rollupDesc}>Average state of charge across your sites, right now</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.live_soc_pct).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
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
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.grid_dependency_pct === null ? '—' : `${s.grid_dependency_pct}%`}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      <h2 className={styles.rollupGroupLabel}>
        {t(lang, 'dashboard_ai_insights_title')} <span className={styles.betaBadge}>{t(lang, 'dashboard_beta_badge')}</span>
      </h2>
      <p className={styles.sub}>{t(lang, 'dashboard_ai_insights_intro')}</p>
      <div className={styles.rollupRow}>
        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>{t(lang, 'dashboard_anomaly_unexpected_silence')}</span>
            <span className={styles.rollupValue}>{silenceCount}</span>
            <span className={styles.rollupDesc}>A real zero during hours this site has historically produced</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'unexpected_silence').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'unexpected_silence').length}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>{t(lang, 'dashboard_anomaly_quiet_drift')}</span>
            <span className={styles.rollupValue}>{driftCount}</span>
            <span className={styles.rollupDesc}>Trending down vs. this site&apos;s own recent baseline</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'quiet_drift').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'quiet_drift').length}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>{t(lang, 'dashboard_anomaly_underperformance')}</span>
            <span className={styles.rollupValue}>{underperformanceCount}</span>
            <span className={styles.rollupDesc}>Below what this site&apos;s installed size should deliver</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'underperformance').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'underperformance').length}</span>
              </div>
            ))}
          </div>
        </details>

        <details className={styles.rollupCard}>
          <summary>
            <span className={styles.rollupLabel}>{t(lang, 'dashboard_anomaly_incomplete_charging')}</span>
            <span className={styles.rollupValue}>{incompleteChargingCount}</span>
            <span className={styles.rollupDesc}>Battery hasn&apos;t reached full charge in 5+ of the last 7 days</span>
          </summary>
          <div className={styles.rollupBreakdown}>
            {sortedByValue(sites, (s) => s.active_anomalies.filter((a) => a.anomaly_type === 'incomplete_charging').length).map((s) => (
              <div key={s.site_id} className={styles.rollupBreakdownRow}>
                <Link href={`/app/dashboard/${encodeURIComponent(s.site_id)}`} className={styles.rollupBreakdownLink}>{s.display_name}</Link>
                <span>{s.active_anomalies.filter((a) => a.anomaly_type === 'incomplete_charging').length}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      {sites.length === 0 ? (
        <p className={styles.sub}>{t(lang, 'dashboard_no_sites')}</p>
      ) : (
        <>
          <FlowDiagram
            solarW={solarSites.length > 0 ? totalSolar : null}
            solarNote={`${solarSites.length} of ${sites.length} sites`}
            loadW={loadSites.length > 0 ? totalLoad : null}
            loadLabel="All sites"
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
            apiBasePath="/api/pipeline/vrm-fleet"
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
