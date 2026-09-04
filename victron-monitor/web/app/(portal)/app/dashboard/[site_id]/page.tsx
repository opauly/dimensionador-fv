import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { requireCustomer } from '@/lib/server/auth';
import { getCustomer, getDashboardAccess, getCustomerFleetSiteDetail, type SiteAnomalyRow } from '@/lib/server/db';
import { formatDateTimeInZone } from '@/lib/dates';
import { t } from '@/lib/i18n/strings';
import { Panel, Button } from '@/components/ui';
import { FlowDiagram } from '../../../../(admin)/admin/fleet/FlowDiagram';
import { Gauge } from '../../../../(admin)/admin/fleet/Gauge';
import { PeriodStatsPanel } from '../../../../(admin)/admin/fleet/PeriodStatsPanel';
import { ShapeChart } from '../../../../(admin)/admin/fleet/ShapeChart';
import dashboardStyles from '../dashboard.module.css';
import styles from './site.module.css';

// `/app/dashboard/[site_id]` — the customer-facing counterpart of
// `/admin/fleet/[site_id]` (2026-09-03). Same data source
// (`getCustomerFleetSiteDetail()`, itself built on `getCustomerFleetOverview()`
// -> `fleetOverviewCore.ts`) so this page never computes an indicator the
// list page doesn't already compute the same way, by construction — and
// never diverges from what `/admin/fleet/[site_id]` shows for the same
// site, since both ultimately read the same shared core.
export async function generateMetadata({ params }: { params: Promise<{ site_id: string }> }): Promise<Metadata> {
  const { site_id } = await params;
  return { title: `Dashboard — ${site_id}` };
}

function formatWatts(w: number | null): string {
  if (w === null) return '—';
  return Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)}kW` : `${Math.round(w)}W`;
}

function healthClass(score: number | null): string {
  if (score === null) return styles.healthNone;
  if (score >= 90) return styles.healthExcellent;
  if (score >= 80) return styles.healthGood;
  if (score >= 70) return styles.healthFair;
  return styles.healthPoor;
}

function healthNotesList(notes: string | null): string[] {
  if (!notes) return [];
  return notes.split(';').map((n) => n.trim()).filter(Boolean);
}

function tzLabel(tz: string | null): string {
  if (!tz) return 'CR';
  return tz.split('/').pop()?.replace(/_/g, ' ') ?? tz;
}

// Fleet Dashboard Phase 3's full vocabulary (migration 038/040) — all four
// checks now write real rows. `incomplete_charging` (3d) was missing from
// the admin version's own copy of this function until this same change
// (2026-09-03 drive-by fix, see admin/fleet/[site_id]/page.tsx) — fixed in
// both places at once so they can't drift again.
function anomalyTypeLabel(lang: Parameters<typeof t>[0], type: string): string {
  if (type === 'unexpected_silence') return t(lang, 'dashboard_anomaly_unexpected_silence');
  if (type === 'quiet_drift') return t(lang, 'dashboard_anomaly_quiet_drift');
  if (type === 'underperformance') return t(lang, 'dashboard_anomaly_underperformance');
  if (type === 'incomplete_charging') return t(lang, 'dashboard_anomaly_incomplete_charging');
  return type;
}

// `detail`'s shape is anomaly_type-specific — see
// `admin/fleet/[site_id]/page.tsx`'s own copy of this function for the full
// per-field reasoning (kept in English here even on this bilingual page;
// see this file's own header comment on that scope line). Plain calendar
// dates (e.g. "2026-08-30") are UTC-pinned deliberately — see the admin
// version's own comment on why a real-timestamp formatter would shift the
// displayed day.
function formatPlainDate(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return isoDate;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

function anomalyDetailSummary(a: SiteAnomalyRow): string {
  const detail = a.detail ?? {};
  if (a.anomaly_type === 'unexpected_silence') {
    const minutes = typeof detail.minutes_silent === 'number' ? Math.round(detail.minutes_silent) : null;
    const window = typeof detail.expected_window_local === 'string' ? detail.expected_window_local : null;
    const validDays = typeof detail.window_basis_valid_days === 'number' ? detail.window_basis_valid_days : null;
    const productiveDays = typeof detail.window_basis_productive_days === 'number' ? detail.window_basis_productive_days : null;
    const parts: string[] = [];
    if (minutes !== null) parts.push(`Reporting zero solar output for ${minutes} min`);
    if (window) parts.push(`during its normal ${window} local productive hours`);
    if (validDays !== null && productiveDays !== null) {
      parts.push(`(based on ${productiveDays} productive of the last ${validDays} days with data)`);
    }
    return parts.length > 0 ? parts.join(' ') : 'No detail recorded';
  }
  if (a.anomaly_type === 'quiet_drift') {
    const recent = typeof detail.recent_mean_kwh_adj === 'number' ? detail.recent_mean_kwh_adj : null;
    const baseline = typeof detail.baseline_mean_kwh_adj === 'number' ? detail.baseline_mean_kwh_adj : null;
    const ratio = typeof detail.ratio_recent_to_baseline === 'number' ? detail.ratio_recent_to_baseline : null;
    const days = typeof detail.days_flagged === 'number' ? detail.days_flagged : null;
    const window = typeof detail.recent_window_days === 'number' ? detail.recent_window_days : null;
    const parts: string[] = [];
    if (recent !== null && baseline !== null) {
      parts.push(`Generating ~${recent.toFixed(1)} kWh/day recently vs. ~${baseline.toFixed(1)} kWh/day normally`);
    }
    if (ratio !== null) parts.push(`(${Math.round(ratio * 100)}% of its own recent baseline)`);
    if (days !== null && window !== null) parts.push(`— ${days} of the last ${window} days below threshold`);
    return parts.length > 0 ? parts.join(' ') : 'No detail recorded';
  }
  if (a.anomaly_type === 'underperformance') {
    const pvKwh = typeof detail.best_recent_pv_kwh === 'number' ? detail.best_recent_pv_kwh : null;
    const expectedKwh = typeof detail.best_recent_expected_kwh === 'number' ? detail.best_recent_expected_kwh : null;
    const pr = typeof detail.best_recent_pr === 'number' ? detail.best_recent_pr : null;
    const pvKwp = typeof detail.pv_kwp === 'number' ? detail.pv_kwp : null;
    const date = typeof detail.best_recent_date === 'string' ? formatPlainDate(detail.best_recent_date) : null;
    const parts: string[] = [];
    if (pvKwh !== null && expectedKwh !== null) {
      parts.push(`Best day recently produced ${pvKwh.toFixed(1)} kWh vs. an expected ${expectedKwh.toFixed(1)} kWh`);
    }
    if (pvKwp !== null) parts.push(`for this ${pvKwp} kWp system`);
    if (pr !== null) parts.push(`(${Math.round(pr * 100)}% of design)`);
    if (date) parts.push(`— best day was ${date}`);
    return parts.length > 0 ? parts.join(' ') : 'No detail recorded';
  }
  if (a.anomaly_type === 'incomplete_charging') {
    const incompleteDays = typeof detail.incomplete_days === 'number' ? detail.incomplete_days : null;
    const validDays = typeof detail.valid_days_checked === 'number' ? detail.valid_days_checked : null;
    const windowDays = typeof detail.window_days === 'number' ? detail.window_days : null;
    const parts: string[] = [];
    if (incompleteDays !== null && validDays !== null) {
      parts.push(`Battery didn't reach full charge on ${incompleteDays} of the last ${validDays} days checked`);
    }
    if (windowDays !== null) parts.push(`(${windowDays}-day window)`);
    return parts.length > 0 ? parts.join(' ') : 'No detail recorded';
  }
  return JSON.stringify(detail);
}

export default async function CustomerDashboardSitePage({ params }: { params: Promise<{ site_id: string }> }) {
  const session = await requireCustomer();
  const lang = session.uiLanguage;
  const { site_id } = await params;

  const customer = await getCustomer(session.customerId);
  const allowed = await getDashboardAccess(customer);
  if (!allowed) {
    return (
      <div>
        <h1>{t(lang, 'dashboard_title')}</h1>
        <Panel className={dashboardStyles.upsell}>
          <h2>{t(lang, 'dashboard_upsell_title')}</h2>
          <p>{t(lang, 'dashboard_upsell_body')}</p>
          <Button href="/app/billing">{t(lang, 'dashboard_upsell_cta')}</Button>
        </Panel>
      </div>
    );
  }

  const site = await getCustomerFleetSiteDetail(session.customerId, site_id);
  if (!site) notFound();

  return (
    <div>
      <div className={styles.crumb}>
        <Link href="/app/dashboard">{t(lang, 'dashboard_title')}</Link> / <span>{site.display_name}</span>
      </div>
      <div className={styles.pagehead}>
        <div>
          <h1>{site.display_name}</h1>
          <div className={styles.sub}>{site.system_type} system</div>
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
          <div className={styles.cardSub}>Health score, self-sufficiency, self-consumption, and depth of discharge.</div>

          <div className={styles.healthRow}>
            <span className={`${styles.healthBadge} ${healthClass(site.health_score)}`}>
              {site.health_score === null ? '—' : `${site.health_score}/100`}
            </span>
            {site.health_status && <span className={styles.healthStatus}>{site.health_status}</span>}
          </div>
          {site.health_score !== null && (
            <ul className={styles.healthNotes}>
              {healthNotesList(site.health_notes).map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          )}

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

      <div className={styles.gaugeCard} style={{ marginBottom: 24 }}>
        <h2>
          {t(lang, 'dashboard_ai_insights_title')} <span className={styles.betaBadge}>{t(lang, 'dashboard_beta_badge')}</span>
        </h2>
        <div className={styles.cardSub}>{t(lang, 'dashboard_ai_insights_intro')}</div>
        {site.active_anomalies.length === 0 ? (
          <p className={styles.sub}>{t(lang, 'dashboard_no_active_anomalies')}</p>
        ) : (
          <ul className={styles.healthNotes}>
            {site.active_anomalies.map((a) => (
              <li key={a.id}>
                <strong>{anomalyTypeLabel(lang, a.anomaly_type)}</strong> — {anomalyDetailSummary(a)} (since{' '}
                {formatDateTimeInZone(a.detected_at, site.timezone, 'en-US')})
              </li>
            ))}
          </ul>
        )}
      </div>

      <PeriodStatsPanel week={site.week} month={site.month} />

      <ShapeChart
        siteIds={[site.site_id]}
        title="Site shape"
        cardSub="This site's real 15-min VRM data, fetched on demand — nothing here is stored."
        apiBasePath="/api/pipeline/vrm-fleet"
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
