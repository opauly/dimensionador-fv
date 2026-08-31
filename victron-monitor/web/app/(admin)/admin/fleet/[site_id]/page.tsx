import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { requireAdmin } from '@/lib/server/auth';
import { getFleetSiteDetail, type BatteryStress } from '@/lib/server/db/admin';
import { formatDateTimeInZone } from '@/lib/dates';
import { FlowDiagram } from '../FlowDiagram';
import { Gauge } from '../Gauge';
import { ShapeChart } from '../ShapeChart';
import styles from './site.module.css';

// `/admin/fleet/[site_id]` — the "Vista de proyecto" drill-down IE-0499's
// own requirements doc calls for (§9), reached from the "View live →" link
// on `/admin/fleet`'s table (Fleet Dashboard Phase 2.5). Same data source
// as the fleet table (`getFleetSiteDetail()`, itself built on
// `getFleetOverview()`) — this page never computes an indicator the fleet
// table doesn't already compute the same way, by construction.
export async function generateMetadata({ params }: { params: Promise<{ site_id: string }> }): Promise<Metadata> {
  const { site_id } = await params;
  const site = await getFleetSiteDetail(site_id);
  return { title: site ? `${site.display_name} — Fleet Health` : 'Site not found — Fleet Health' };
}

function formatWatts(w: number | null): string {
  if (w === null) return '—';
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
}

// "America/Costa_Rica" -> "Costa Rica" — the site's own configured
// timezone (its Cerbo's local time), shown so it's clear this timestamp is
// NOT the viewer's own clock, unlike the fleet-wide badge on `/admin/fleet`.
function tzLabel(tz: string | null): string {
  if (!tz) return 'CR';
  return tz.split('/').pop()?.replace(/_/g, ' ') ?? tz;
}

// Same 3-tier-plus-"no data" wording `weekly_report.py` uses on the PDF
// (English side — admin is English-only by product decision).
function stressLabel(stress: BatteryStress): string {
  if (stress === 'high_stress') return 'High stress';
  if (stress === 'working_hard') return 'Working hard';
  if (stress === 'no_data') return 'No data';
  return 'Normal';
}

export default async function AdminFleetSitePage({ params }: { params: Promise<{ site_id: string }> }) {
  await requireAdmin();
  const { site_id } = await params;
  const site = await getFleetSiteDetail(site_id);
  if (!site) notFound();

  return (
    <div>
      <div className={styles.crumb}>
        <Link href="/admin/fleet">Fleet Health</Link> / <span>{site.display_name}</span>
      </div>
      <div className={styles.pagehead}>
        <div>
          <h1>{site.display_name}</h1>
          <div className={styles.sub}>
            {site.customer_name} · {site.system_type} system
          </div>
        </div>
        {site.live_captured_at && (
          <div className={styles.live}>
            <span className={styles.pulse} />
            LIVE — as of {formatDateTimeInZone(site.live_captured_at, site.timezone, 'en-US')} ({tzLabel(site.timezone)})
          </div>
        )}
      </div>

      <div className={styles.kpis}>
        <div className={styles.kpi}>
          <div className={styles.kpiLabel}>
            <span className={styles.swatch} style={{ background: 'var(--signal)' }} />
            Solar (PV)
          </div>
          <div className={styles.kpiValue}>{formatWatts(site.live_pv_power_w)}</div>
        </div>
        <div className={styles.kpi}>
          <div className={styles.kpiLabel}>
            <span className={styles.swatch} style={{ background: 'var(--paper-dim)' }} />
            Load
          </div>
          <div className={styles.kpiValue}>{formatWatts(site.live_load_power_w)}</div>
        </div>
        <div className={styles.kpi}>
          <div className={styles.kpiLabel}>
            <span className={styles.swatch} style={{ background: 'var(--good)' }} />
            Battery
          </div>
          <div className={styles.kpiValue}>
            {site.live_battery_power_w === null
              ? '—'
              : `${site.live_battery_power_w >= 0 ? '+' : ''}${formatWatts(site.live_battery_power_w)}`}
          </div>
          {site.live_battery_power_w !== null && (
            <div className={styles.kpiDelta}>{site.live_battery_power_w >= 0 ? 'charging' : 'discharging'}</div>
          )}
        </div>
        <div className={styles.kpi}>
          <div className={styles.kpiLabel}>
            <span className={styles.swatch} style={{ background: 'var(--mute)' }} />
            Grid
          </div>
          <div className={styles.kpiValue}>{site.has_grid_meter ? formatWatts(site.live_grid_power_w) : '—'}</div>
          {!site.has_grid_meter && <div className={styles.kpiDelta}>No physical grid meter</div>}
        </div>
        <div className={styles.kpi}>
          <div className={styles.kpiLabel}>
            <span className={styles.swatch} style={{ background: 'var(--victron-glow)' }} />
            State of charge
          </div>
          <div className={styles.kpiValue}>{site.live_soc_pct === null ? '—' : `${site.live_soc_pct}%`}</div>
        </div>
      </div>

      <div className={styles.split}>
        <div className={styles.flowCard}>
          <h2>Energy flow — right now</h2>
          <div className={styles.cardSub}>From this site&apos;s most recent snapshot, refreshed every ~15 minutes.</div>
          <FlowDiagram
            solarW={site.live_pv_power_w}
            loadW={site.live_load_power_w}
            batteryW={site.live_battery_power_w}
            batteryNote={site.live_soc_pct === null ? undefined : `${site.live_soc_pct}%`}
            gridW={site.live_grid_power_w}
            hasGridMeter={site.has_grid_meter}
          />
        </div>

        <div className={styles.gaugeCard}>
          <h2>{site.health_metrics_date ? `As of ${site.health_metrics_date}` : 'Today, at a glance'}</h2>
          <div className={styles.cardSub}>
            From <code>vrm.energy_daily</code> / <code>vrm.daily_health</code> — already computed, no new capture
            needed.
          </div>
          <Gauge
            pct={site.self_sufficiency_pct}
            color="var(--good)"
            label="Self-sufficiency"
            desc={site.self_sufficiency_pct === null ? 'Not enough data yet' : `${site.self_sufficiency_pct}% of load came from solar + battery`}
          />
          <Gauge
            pct={site.self_consumption_pct}
            color="var(--victron-glow)"
            label="Self-consumption"
            desc={site.self_consumption_pct === null ? 'Not enough data yet' : `${site.self_consumption_pct}% of solar generated was used on-site`}
          />
          <Gauge
            pct={site.dod_pct}
            color="var(--signal)"
            label="Depth of discharge"
            desc={site.dod_pct === null ? 'Not enough data yet' : `Battery cycled ${site.dod_pct}% overnight`}
          />
        </div>
      </div>

      <div className={styles.weekCard}>
        <h2>This week</h2>
        <div className={styles.cardSub}>
          From the last 7 days of <code>vrm.energy_daily</code> — the same figures and formulas the PDF report
          already computes, not a second definition.
        </div>
        <div className={styles.weekStats}>
          <div className={styles.weekStat}>
            <span className={styles.weekStatLabel}>Battery cycles</span>
            <span className={styles.weekStatValue}>{site.seven_day.batteryCycles ?? '—'}</span>
            <span className={`${styles.stressBadge} ${styles[`stress_${site.seven_day.batteryStress}`]}`}>
              {stressLabel(site.seven_day.batteryStress)}
            </span>
          </div>
          <div className={styles.weekStat}>
            <span className={styles.weekStatLabel}>Grid outages</span>
            <span className={styles.weekStatValue}>
              {site.seven_day.outageCount > 0 ? `${site.seven_day.outageCount} (${site.seven_day.outageMinutes} min)` : '0'}
            </span>
          </div>
          <div className={styles.weekStat}>
            <span className={styles.weekStatLabel}>SOC range</span>
            <span className={styles.weekStatValue}>
              {site.seven_day.minSoc !== null && site.seven_day.maxSoc !== null
                ? `${site.seven_day.minSoc}–${site.seven_day.maxSoc}%`
                : '—'}
            </span>
            {site.seven_day.avgSoc !== null && <span className={styles.weekStatSub}>avg {site.seven_day.avgSoc}%</span>}
          </div>
          <div className={styles.weekStat}>
            <span className={styles.weekStatLabel}>Days self-sufficient</span>
            <span className={styles.weekStatValue}>
              {site.seven_day.daysWithData > 0 ? `${site.seven_day.daysSelfSufficient} / ${site.seven_day.daysWithData}` : '—'}
            </span>
          </div>
          {site.grid_dependency_pct !== null && (
            <div className={styles.weekStat}>
              <span className={styles.weekStatLabel}>Grid dependency</span>
              <span className={styles.weekStatValue}>{site.grid_dependency_pct}%</span>
            </div>
          )}
          {site.specific_yield_kwh_per_kwp !== null && (
            <div className={styles.weekStat}>
              <span className={styles.weekStatLabel}>Specific yield</span>
              <span className={styles.weekStatValue}>{site.specific_yield_kwh_per_kwp}</span>
              <span className={styles.weekStatSub}>kWh/kWp</span>
            </div>
          )}
        </div>
      </div>

      <ShapeChart
        siteIds={[site.site_id]}
        title="Site shape"
        cardSub="This site's real 15-min VRM data, fetched on demand — nothing here is stored."
      />

      <div className={styles.metaRow}>
        {site.pv_kwp !== null && <span>Installed: {site.pv_kwp} kWp</span>}
        {site.battery_usable_kwh !== null && <span>Usable battery: {site.battery_usable_kwh} kWh</span>}
      </div>
    </div>
  );
}
