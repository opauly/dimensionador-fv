import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { requireAdmin } from '@/lib/server/auth';
import { getFleetSiteDetail } from '@/lib/server/db/admin';
import { formatDateTimeInZone } from '@/lib/dates';
import { FlowDiagram } from '../FlowDiagram';
import { Gauge } from '../Gauge';
import { PeriodStatsPanel } from '../PeriodStatsPanel';
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
  return { title: site ? `${site.display_name} — VRM Fleet` : 'Site not found — VRM Fleet' };
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

export default async function AdminFleetSitePage({ params }: { params: Promise<{ site_id: string }> }) {
  await requireAdmin();
  const { site_id } = await params;
  const site = await getFleetSiteDetail(site_id);
  if (!site) notFound();

  return (
    <div>
      <div className={styles.crumb}>
        <Link href="/admin/fleet">VRM Fleet</Link> / <span>{site.display_name}</span>
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
          {site.live_pv_chargers && site.live_pv_chargers.length > 1 && (
            <details className={styles.chargerBreakdown}>
              <summary>{site.live_pv_chargers.length} chargers</summary>
              <ul>
                {site.live_pv_chargers.map((c) => (
                  <li key={c.instance}>
                    Charger {c.instance + 1}: {formatWatts(c.power_w)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <div className={styles.kpi}>
          <div className={styles.kpiLabel}>
            <span className={styles.swatch} style={{ background: 'var(--paper-dim)' }} />
            Load
          </div>
          <div className={styles.kpiValue}>{formatWatts(site.live_load_power_w)}</div>
          {site.live_load_phases && site.live_load_phases.length > 1 && (
            <details className={styles.chargerBreakdown}>
              <summary>{site.live_load_phases.length} phases</summary>
              <ul>
                {site.live_load_phases.map((p) => (
                  <li key={p.phase}>
                    {p.phase}: {formatWatts(p.power_w)}
                  </li>
                ))}
              </ul>
            </details>
          )}
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
          {site.live_grid_source === 'inverter' && (
            <div className={styles.kpiDelta}>Via inverter (no dedicated meter)</div>
          )}
          {site.live_grid_source === null && <div className={styles.kpiDelta}>No grid reading available</div>}
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

      <PeriodStatsPanel week={site.week} month={site.month} />

      <ShapeChart
        siteIds={[site.site_id]}
        title="Site shape"
        cardSub="This site's real 15-min VRM data, fetched on demand — nothing here is stored."
      />

      <div className={styles.metaRow}>
        {site.specific_yield_kwh_per_kwp !== null && <span>Specific yield: {site.specific_yield_kwh_per_kwp} kWh/kWp</span>}
        {site.grid_dependency_pct !== null && <span>Grid dependency: {site.grid_dependency_pct}%</span>}
        {site.pv_kwp !== null && <span>Installed: {site.pv_kwp} kWp</span>}
        {site.battery_usable_kwh !== null && <span>Usable battery: {site.battery_usable_kwh} kWh</span>}
      </div>
    </div>
  );
}
