import 'server-only';

// ══════════════════════════════════════════════════════════════════════
// SHARED core for the Fleet Dashboard's row/indicator computation — safe
// for BOTH `lib/server/db/admin.ts` (the unscoped, cross-customer
// `/admin/fleet` version) and a tenant-scoped caller (`fleetDashboard.ts`,
// the customer-facing `/app/dashboard` version, 2026-09-03) to import.
//
// Unlike `admin.ts` itself (see that file's own "ADMIN-ONLY" header — no
// function there takes a `customerId`, and it must never be imported by
// `app/(portal)/**`), everything in THIS file only ever touches the site
// rows a caller already fetched and filtered. `buildFleetOverview()` below
// takes that already-scoped `siteRows` array as its input and derives every
// other query from the `site_id`s in it (`.in('site_id', siteIds)`) — it
// never queries `vrm.sites` itself, so it can never accidentally widen
// scope back out to the whole fleet. The tenant boundary is enforced by
// each CALLER's own `sites` query (admin.ts: no filter; fleetDashboard.ts:
// `.eq('customer_id', customerId)`), not by anything in here — this file
// is where the two callers share the (identical, carefully-tuned) row
// shape and indicator math, so a health score or battery-cycle estimate
// can never mean something subtly different on the two dashboards.
// ══════════════════════════════════════════════════════════════════════
import { getSupabaseAdmin } from '@/lib/server/supabase';
import type { SiteRecord } from './types';

export type FleetConnectionStatus = 'online' | 'stale' | 'never_synced';

// `vrm.site_anomalies` (migration 038) — see FleetOverviewRow.active_anomalies'
// own comment. `detail`'s shape varies by `anomaly_type` (the table's own
// COMMENT ON COLUMN says so) — kept as a loose record here rather than a
// narrower type per known anomaly_type, since all four (`unexpected_silence`,
// `quiet_drift`, `underperformance`, `incomplete_charging` — migration 040)
// are real, live-written shapes whose own thresholds/keys may still change
// during tuning (PLAN_PHASE19_FLEET_P3.md §7 item 1: thresholds are
// "starting points, not locked").
export type SiteAnomalyRow = {
  id: string;
  site_id: string;
  anomaly_type: string;
  detected_at: string;
  detail: Record<string, unknown> | null;
};

export type BatteryStress = 'normal' | 'working_hard' | 'high_stress' | 'no_data';

export type PeriodIndicators = {
  // Equivalent full cycles over the window. Two possible bases, same split
  // `vrm.compute_daily_health()` (migration 039) now uses per-day:
  //   - Exact: sum real discharge over the window, divide by usable
  //     capacity — computed exactly the way
  //     `victron/weekly_report.py:build_report_data()` does for the PDF
  //     report. `null` only when EVERY day in the window has both charge
  //     and discharge NULL (every VRM-API site, by design) — a CSV-sourced
  //     site can have a real zero-discharge day, which must stay a real 0.
  //   - Estimated (VRM-API sites, migration 039): sum each day's own SOC
  //     swing `(max_soc - min_soc) / 100` across the window — an
  //     approximation (assumes ~one discharge/recharge swing per day), but
  //     real, not a fabricated 0. `batteryCyclesEstimated` distinguishes
  //     which basis produced `batteryCycles`, so the UI can label it.
  batteryCycles: number | null;
  batteryCyclesEstimated: boolean;
  // Same 3-tier-plus-"no data" label `weekly_report.py` shows on the PDF,
  // thresholds scaled by the window's own length the same way that
  // module's own comment describes ("a 30-day custom range naturally
  // accumulates ~4x the cycles a 7-day one does for the exact same daily
  // usage pattern... these thresholds... scale with the window's length")
  // — a month window must not read as "High stress" purely for being
  // longer than a week. `'no_data'` is a genuine fourth state, not lumped
  // in with `'normal'` — the report's own comment on why: "'Normal' would
  // actively assert everything's fine for data that is actually just
  // absent." The estimated basis uses its own, much smaller-scale
  // thresholds (see `_EST_CYCLES_*_PER_DAY`) — SOC swing is bounded to
  // [0,1] per day, so reusing the exact metric's 7.0/10.0-per-week
  // thresholds would make it structurally incapable of ever firing.
  batteryStress: BatteryStress;
  outageMinutes: number;
  outageCount: number;
  minSoc: number | null;
  maxSoc: number | null;
  avgSoc: number | null;
  daysSelfSufficient: number;
  daysWithData: number;
};

export type FleetOverviewRow = {
  site_id: string;
  display_name: string;
  customer_id: string;
  customer_name: string;
  system_type: SiteRecord['system_type'];
  pv_kwp: number | null;
  battery_usable_kwh: number | null;
  // The site's own configured timezone (its Cerbo's local time), same
  // field `victron/vrm_live.py`/`vrm_shape.py` already pass to VRM — a
  // live reading is timestamped in THIS, not the app-wide
  // America/Costa_Rica default `lib/dates.ts:formatDateTime()` otherwise
  // assumes. `null` falls back to that default (a site with no configured
  // timezone, effectively "unknown" rather than "definitely UTC").
  timezone: string | null;
  vrm_last_synced_at: string | null;
  connection_status: FleetConnectionStatus;
  health_score: number | null;
  health_status: string | null;
  health_date: string | null;
  // The reasons behind health_score, straight from vrm.compute_daily_health()
  // (migration 012) — semicolon-joined (e.g. "High grid dependency; Low
  // battery voltage (45.2V)"), or "Normal operation" when nothing was
  // penalized. `null` only when there's no daily_health row at all yet.
  health_notes: string | null;
  // Live-only (2026-09-01): counts categories present in the MOST RECENT
  // live snapshot's raw.alarms/raw.critical_alerts, nothing else — not an
  // episode/history count. A category active yesterday but cleared by the
  // latest ~15-minute fetch does not count; one that just started does,
  // even if it started five minutes ago. 0 whenever there's no live
  // snapshot yet, same as every other live-only field here.
  active_alarms: number;
  active_critical_alerts: number;
  // Fleet Dashboard Phase 3 (2026-09-03) — every OPEN (`cleared_at IS
  // NULL`) `vrm.site_anomalies` row for this site (migration 038), any
  // `anomaly_type`. `unexpected_silence` (3b) is written by
  // `victron/anomaly_silence.py` via the ~15-minute `refresh-snapshots`
  // sweep; `quiet_drift`/`underperformance` (3a/3c) and `incomplete_charging`
  // (3d) are written by the daily `POST /v1/vrm-fleet/detect-anomalies-daily`
  // sweep. This query itself (below) already reads every `anomaly_type`
  // generically — no change needed here when a new type starts being
  // written. `[]`, never omitted, when this site has no open anomaly.
  active_anomalies: SiteAnomalyRow[];
  // Fleet Dashboard Phase 2 (2026-08-30) — from `vrm.site_snapshots`
  // (migration 031), upserted by the ~15-minute `refresh-snapshots` sweep
  // (`vrm_api/routers/vrm_fleet.py`). `null` for every field, including
  // `live_captured_at`, means no snapshot has landed for this site yet —
  // never a fabricated 0, same "no data is better than fabricated data"
  // rule the whole pipeline already follows.
  live_captured_at: string | null;
  live_pv_power_w: number | null;
  live_load_power_w: number | null;
  live_battery_power_w: number | null;
  live_grid_power_w: number | null;
  live_soc_pct: number | null;
  // Per-solar-charger breakdown (victron/vrm_live.py:_pv_power_from_diagnostics(),
  // 2026-09-01) — `null` on a single-charger site (nothing to break down) or
  // one with no PV at all; on a multi-charger site, entries sum to exactly
  // `live_pv_power_w`.
  live_pv_chargers: { instance: number; power_w: number }[] | null;
  // A live snapshot value that has ever landed non-null means there's SOME
  // grid reading to show — originally assumed that always meant a physical
  // grid meter, corrected 2026-09-01: most sites have no dedicated meter
  // and this is instead the inverter/charger's own AC input measurement
  // (`live_grid_source: 'inverter'`) — see victron/vrm_live.py's
  // GRID_POWER_CODES/INVERTER_INPUT_CODES comment for why the two read
  // meaningfully different values on the one site checked with both, and
  // are never conflated. `live_grid_source` is `null` only when this site
  // publishes no grid signal of either kind.
  has_grid_meter: boolean;
  live_grid_source: 'meter' | 'inverter' | null;
  // Per-phase live load breakdown (a1/a2, i.e. L1/L2) — same shape/intent
  // as live_pv_chargers, entries sum to exactly live_load_power_w.
  live_load_phases: { phase: string; power_w: number }[] | null;
  // Fleet Dashboard Phase 2.5 (2026-08-30) — every one of these is derived
  // from the most recent `vrm.energy_daily`/`vrm.daily_health` row using
  // exactly the formulas IE-0499's own requirements doc §4 specifies
  // (`self_sufficiency = 1 - grid_kwh/load_kwh`, etc.) — no new ingestion,
  // this data has been sitting on those two tables all along. `null` when
  // that day's denominator is zero/missing rather than a divide-by-zero or
  // a fabricated 0%.
  health_metrics_date: string | null;
  specific_yield_kwh_per_kwp: number | null;
  self_sufficiency_pct: number | null;
  self_consumption_pct: number | null;
  dod_pct: number | null;
  grid_dependency_pct: number | null;
  // Everything computed the same way `victron/weekly_report.py` computes
  // it for the PDF report (see `_periodIndicators()`) — battery cycles,
  // stress label, outage minutes/count, min/max/avg SOC, days
  // self-sufficient — over the last 7 and last 30 days of
  // `vrm.energy_daily` rows respectively, so the per-site page's
  // week/month toggle needs no extra fetch, just a client-side switch
  // between two already-computed objects. NOT read from
  // `vrm.daily_health.battery_cycles`, which still fabricates a 0.0 for
  // every VRM-API site (migration 012, unfixed).
  week: PeriodIndicators;
  month: PeriodIndicators;
};

export type FleetOverview = {
  sites: FleetOverviewRow[];
  rollup: {
    site_count: number;
    online_count: number;
    avg_health_score: number | null;
    total_active_alarms: number;
    total_active_critical_alerts: number;
    // Fleet Dashboard Phase 3 — count of OPEN vrm.site_anomalies rows
    // across every site, any anomaly_type (unexpected_silence, quiet_drift,
    // underperformance, incomplete_charging).
    total_active_anomalies: number;
  };
};

/** The exact `vrm.sites` column list both callers' own scoped query must
 * select — kept here so a field added to one caller's query is never
 * silently missing from the other's. */
export const FLEET_SITE_SELECT_FIELDS =
  'site_id, display_name, customer_id, system_type, pv_kwp, battery_usable_kwh, timezone, vrm_last_synced_at';

export type FleetSiteInput = {
  site_id: string;
  display_name: string;
  customer_id: string;
  system_type: SiteRecord['system_type'];
  pv_kwp: number | null;
  battery_usable_kwh: number | null;
  timezone: string | null;
  vrm_last_synced_at: string | null;
};

// Based on `site_snapshots.captured_at` (the ~15-minute `refresh-snapshots`
// sweep), NOT `vrm_last_synced_at` (the daily energy_daily/report sync) —
// found live 2026-08-31 that those two can disagree for days at a time
// (the daily sync can stall on a bad date range or a standing VRM error
// while the live snapshot sweep keeps succeeding every 15 minutes
// regardless, since it's a completely separate code path). An admin reading
// "online" reasonably means "is this site talking to VRM right now," which
// is exactly what the snapshot sweep answers and the daily sync does not.
// 45 minutes = 3x the sweep's own interval, tolerating one missed run
// without flagging a genuinely live site as stale.
const _ONLINE_WITHIN_MS = 45 * 60 * 1000;

function _connectionStatus(liveCapturedAt: string | null, now: number): FleetConnectionStatus {
  if (!liveCapturedAt) return 'never_synced';
  const age = now - new Date(liveCapturedAt).getTime();
  return age <= _ONLINE_WITHIN_MS ? 'online' : 'stale';
}

// `site_snapshots.raw` is a loosely-typed jsonb blob (see migration 031's
// own comment on that column) — pulled apart here rather than trusted
// as-is, same defensive parsing every other jsonb-sourced field in this
// file already does.
function _pvChargersFromRaw(raw: unknown): { instance: number; power_w: number }[] | null {
  if (!raw || typeof raw !== 'object') return null;
  const list = (raw as Record<string, unknown>).pv_chargers;
  if (!Array.isArray(list) || list.length === 0) return null;
  const parsed = list
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({ instance: Number(e.instance), power_w: Number(e.power_w) }))
    .filter((e) => Number.isFinite(e.instance) && Number.isFinite(e.power_w));
  return parsed.length > 0 ? parsed : null;
}

function _loadPhasesFromRaw(raw: unknown): { phase: string; power_w: number }[] | null {
  if (!raw || typeof raw !== 'object') return null;
  const list = (raw as Record<string, unknown>).load_phases;
  if (!Array.isArray(list) || list.length === 0) return null;
  const parsed = list
    .filter((e): e is Record<string, unknown> => !!e && typeof e === 'object')
    .map((e) => ({ phase: String(e.phase), power_w: Number(e.power_w) }))
    .filter((e) => e.phase.length > 0 && Number.isFinite(e.power_w));
  return parsed.length > 0 ? parsed : null;
}

function _gridSourceFromRaw(raw: unknown): 'meter' | 'inverter' | null {
  if (!raw || typeof raw !== 'object') return null;
  const source = (raw as Record<string, unknown>).grid_source;
  return source === 'meter' || source === 'inverter' ? source : null;
}

/** IE-0499's own §4 formulas, applied to the most recent `energy_daily`
 * row: specific yield = pv_kwh / pv_kwp; self-sufficiency = 1 -
 * grid_kwh/load_kwh (approximated here as `pv_kwh - grid_export_kwh` for
 * "load" — this table has no direct `load_kwh` column read into this
 * query, and PV-minus-exports is the same quantity the doc's own
 * self-consumption formula already uses); DoD = 100% - min_soc. `null`
 * whenever the row itself is missing or a denominator is zero, never a
 * fabricated 0%/divide-by-zero.
 *
 * `pv_kwp_snapshot` (meant to freeze the capacity a given day's yield was
 * computed against, surviving a later capacity change) is `null` on every
 * real row as of 2026-08-30 — checked live, not assumed, and it's a real
 * gap in the ingestion pipeline this function doesn't own. `fallbackKwp`
 * (the site's CURRENT `pv_kwp`) is what actually makes yield computable
 * today; swap back to `pv_kwp_snapshot`-only once that column is actually
 * populated at ingestion time. */
function _dailyIndicators(
  energy: { pv_kwh: number | null; grid_kwh: number | null; grid_export_kwh: number | null; pv_kwp_snapshot: number | null; min_soc: number | null } | undefined,
  fallbackKwp: number | null
): {
  specificYield: number | null; selfSufficiency: number | null; selfConsumption: number | null; dod: number | null;
} {
  if (!energy) return { specificYield: null, selfSufficiency: null, selfConsumption: null, dod: null };
  const pv = energy.pv_kwh ?? null;
  const grid = energy.grid_kwh ?? null;
  const exported = energy.grid_export_kwh ?? 0;
  const kwp = energy.pv_kwp_snapshot ?? fallbackKwp ?? null;
  const minSoc = energy.min_soc ?? null;

  const specificYield = pv !== null && kwp !== null && kwp > 0 ? Math.round((pv / kwp) * 100) / 100 : null;
  const selfConsumption = pv !== null && pv > 0 ? Math.round(((pv - exported) / pv) * 1000) / 10 : null;

  const consumedLocally = pv !== null ? Math.max(pv - exported, 0) : null;
  const totalLoad = consumedLocally !== null && grid !== null ? consumedLocally + grid : null;
  const selfSufficiency = totalLoad !== null && totalLoad > 0 && grid !== null
    ? Math.round((1 - grid / totalLoad) * 1000) / 10
    : null;

  const dod = minSoc !== null ? Math.round((100 - minSoc) * 10) / 10 : null;

  return { specificYield, selfSufficiency, selfConsumption, dod };
}

const _BATTERY_CYCLES_HIGH = 10.0;
const _BATTERY_CYCLES_MID = 7.0;
// Per-day, matching vrm.compute_daily_health()'s estCyclesHigh/Mid defaults
// (migration 039) — calibrated against the real distribution of daily SOC
// swings across the current VRM-API fleet (523 days: median 0.45, p90 0.74,
// max ever seen 0.82). Summed across the window below, same "per-day rate
// scaled by how many real days you have" shape the exact metric already
// uses via `weekScale`.
const _EST_CYCLES_HIGH_PER_DAY = 0.85;
const _EST_CYCLES_MID_PER_DAY = 0.65;

function _periodIndicators(
  rows: {
    grid_kwh: number | null;
    min_soc: number | null;
    max_soc: number | null;
    avg_soc: number | null;
    outage_count: number | null;
    outage_minutes: number | null;
    battery_charge_kwh: number | null;
    battery_discharge_kwh: number | null;
  }[],
  batteryUsableKwh: number | null
): PeriodIndicators {
  const batteryKwhAvailable = !(
    rows.every((r) => r.battery_charge_kwh === null) && rows.every((r) => r.battery_discharge_kwh === null)
  );
  const exactCycles = rows.length > 0 && batteryKwhAvailable
    ? Math.round((rows.reduce((sum, r) => sum + (r.battery_discharge_kwh ?? 0), 0) / (batteryUsableKwh || 1)) * 100) / 100
    : null;
  // Estimated fallback — only when the exact metric has nothing to work
  // with. A day missing either end of its SOC swing contributes 0, same
  // "treat missing as 0 within a sum, not null" convention the exact
  // metric already uses for `battery_discharge_kwh ?? 0`.
  const estCycles = rows.length > 0 && !batteryKwhAvailable
    ? Math.round(
        rows.reduce((sum, r) => sum + (r.min_soc !== null && r.max_soc !== null ? (r.max_soc - r.min_soc) / 100 : 0), 0) * 100
      ) / 100
    : null;
  const batteryCyclesEstimated = exactCycles === null && estCycles !== null;
  const batteryCycles = batteryCyclesEstimated ? estCycles : exactCycles;

  // `weekScale` from the actual row COUNT, same as `weekly_report.py`'s own
  // `len(days) / 7` — a site with gaps in its history gets thresholds
  // scaled to how much real data it actually has, not the window's nominal
  // length.
  const weekScale = rows.length > 0 ? rows.length / 7 : 1;
  const batteryStress: BatteryStress =
    batteryCycles === null ? 'no_data'
    : batteryCyclesEstimated
      ? (batteryCycles > _EST_CYCLES_HIGH_PER_DAY * rows.length ? 'high_stress'
         : batteryCycles > _EST_CYCLES_MID_PER_DAY * rows.length ? 'working_hard'
         : 'normal')
    : batteryCycles > _BATTERY_CYCLES_HIGH * weekScale ? 'high_stress'
    : batteryCycles > _BATTERY_CYCLES_MID * weekScale ? 'working_hard'
    : 'normal';

  const minSocValues = rows.map((r) => r.min_soc).filter((v): v is number => v !== null);
  const maxSocValues = rows.map((r) => r.max_soc).filter((v): v is number => v !== null);
  const avgSocValues = rows.map((r) => r.avg_soc).filter((v): v is number => v !== null);

  return {
    batteryCycles,
    batteryCyclesEstimated,
    batteryStress,
    outageMinutes: Math.round(rows.reduce((sum, r) => sum + (r.outage_minutes ?? 0), 0) * 10) / 10,
    outageCount: rows.reduce((sum, r) => sum + (r.outage_count ?? 0), 0),
    minSoc: minSocValues.length > 0 ? Math.min(...minSocValues) : null,
    maxSoc: maxSocValues.length > 0 ? Math.max(...maxSocValues) : null,
    avgSoc: avgSocValues.length > 0 ? Math.round((avgSocValues.reduce((a, b) => a + b, 0) / avgSocValues.length) * 10) / 10 : null,
    daysSelfSufficient: rows.filter((r) => (r.grid_kwh ?? 0) <= 0).length,
    daysWithData: rows.length,
  };
}

/** Live-only "Active Alarms"/"Active Critical Alerts" count (2026-09-01) —
 * counts `true` entries in a `site_snapshots.raw.alarms`/`raw.critical_alerts`
 * blob (see `victron/vrm_live.py:check_live_alarms()`). Deliberately NOT
 * episode/history-based any more: a category present in the latest live
 * fetch counts, one absent from it (including "no live snapshot at all")
 * does not — this is a live dashboard, not a historical alarm log. */
function _activeCountFromRaw(raw: unknown, key: 'alarms' | 'critical_alerts'): number {
  if (!raw || typeof raw !== 'object') return 0;
  const states = (raw as Record<string, unknown>)[key];
  if (!states || typeof states !== 'object') return 0;
  return Object.values(states as Record<string, unknown>).filter((v) => v === true).length;
}

/** Builds a `FleetOverview` for exactly the sites in `siteRows` — connection
 * freshness, latest health score, open alarm/critical-alert counts, and
 * open `vrm.site_anomalies` rows for each one. Every other query here is
 * derived from `siteRows`' own `site_id`s (`.in('site_id', siteIds)`), so
 * the caller's own `siteRows` query is the ONLY place tenant scope is
 * decided — see this file's own header comment. */
export async function buildFleetOverview(siteRows: FleetSiteInput[]): Promise<FleetOverview> {
  const admin = getSupabaseAdmin();
  const now = Date.now();
  // Generous enough to always contain the real most-recent health row (a
  // site can go a few days without a fresh sync) and any genuinely open
  // alarm/critical-alert episode (an episode that's been open longer than
  // this would be a real, separate "stuck" bug worth its own investigation,
  // not something this dashboard needs to keep scanning further back for).
  const lookbackIso = new Date(now - 14 * 24 * 60 * 60 * 1000).toISOString();
  const lookbackDate = lookbackIso.slice(0, 10);
  // `energy_daily` alone needs a deeper window than the other tables above —
  // the "This month" toggle on the per-site page needs 30 real days to sum
  // over, not just 14.
  const lookback30Date = new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

  const siteIds = siteRows.map((s) => s.site_id);

  if (siteIds.length === 0) {
    return {
      sites: [],
      rollup: {
        site_count: 0, online_count: 0, avg_health_score: null,
        total_active_alarms: 0, total_active_critical_alerts: 0, total_active_anomalies: 0,
      },
    };
  }

  const [
    { data: customers, error: customersError },
    { data: health, error: healthError },
    { data: snapshots, error: snapshotsError },
    { data: energyDaily, error: energyDailyError },
    { data: anomalies, error: anomaliesError },
  ] = await Promise.all([
    admin.schema('vrm').from('customers').select('id, name'),
    // `battery_cycles` deliberately NOT selected here — `vrm.compute_daily_health()`
    // (migration 012) still does `COALESCE(battery_discharge_kwh, 0) / capacity`,
    // fabricating a confident 0.0 for every VRM-API site (that field is
    // NULL there by design — see `energyDaily`'s own comment below). Cycles
    // are computed independently a few lines down, mirroring
    // `weekly_report.py`'s own already-correct guard instead of trusting
    // that column.
    // `notes` — the same human-readable reasons `vrm.compute_daily_health()`
    // (migration 012) already builds while scoring (e.g. "High grid
    // dependency; Low battery voltage (45.2V)") and stores right alongside
    // the score, previously computed and thrown away by never being
    // selected here. Surfaced on the per-site page so a low score isn't
    // just a bare number with no way to tell what actually needs attention.
    admin.schema('vrm').from('daily_health').select('site_id, date, health_score, health_status, grid_dependency_pct, notes').in('site_id', siteIds).gte('date', lookbackDate),
    // `alarm_events`/`critical_alerts` deliberately NOT fetched here any
    // more (2026-09-01) — this is a live monitoring dashboard, and those
    // tables are the HISTORICAL sync's own record (through yesterday only,
    // for report/health-score purposes). "Active Alarms"/"Active Critical
    // Alerts" below now read straight from the live snapshot's own
    // raw.alarms/raw.critical_alerts instead — present in the latest live
    // fetch means shown, not present means not shown, no episode/history
    // reasoning involved. For real alarm HISTORY, the official VRM portal
    // is the source of truth, not this dashboard.
    // Fleet Dashboard Phase 2 — one row per site already (migration 031's
    // PRIMARY KEY on site_id), so no "latest per site" grouping needed
    // here the way daily_health above needs one.
    admin.schema('vrm').from('site_snapshots').select('site_id, captured_at, pv_power_w, load_power_w, battery_power_w, grid_power_w, soc_pct, raw').in('site_id', siteIds),
    // Fleet Dashboard Phase 2.5 — the raw kWh/SOC/yield fields IE-0499 §4's
    // formulas are built from (self-sufficiency, self-consumption, DoD,
    // specific yield, battery cycles). Same lookback window as daily_health
    // above. `battery_charge_kwh`/`battery_discharge_kwh` are NULL on every
    // row for a VRM-API site by design (`victron/vrm_series.py`'s own
    // docstring point 2b — VRM's derived flow-diagram totals disagreed with
    // a real battery monitor by up to 97%/58%) — fetched anyway so cycles
    // can apply the same all-null guard `weekly_report.py` already does,
    // rather than trusting `vrm.daily_health.battery_cycles`, which still
    // fabricates a 0.0 for exactly this case (migration 012, unfixed).
    admin.schema('vrm').from('energy_daily')
      .select('site_id, date, pv_kwh, grid_kwh, grid_export_kwh, pv_kwp_snapshot, min_soc, max_soc, avg_soc, outage_count, outage_minutes, battery_charge_kwh, battery_discharge_kwh')
      .in('site_id', siteIds).gte('date', lookback30Date),
    // Fleet Dashboard Phase 3b (migration 038) — every OPEN anomaly across
    // every site in one query, same "no bulk vrm_api endpoint exists for
    // this and none is needed, direct Postgres read" precedent every other
    // query in this function already follows.
    admin.schema('vrm').from('site_anomalies')
      .select('id, site_id, anomaly_type, detected_at, detail')
      .in('site_id', siteIds).is('cleared_at', null).order('detected_at', { ascending: false }),
  ]);
  if (customersError) throw customersError;
  if (healthError) throw healthError;
  if (snapshotsError) throw snapshotsError;
  if (energyDailyError) throw energyDailyError;
  if (anomaliesError) throw anomaliesError;

  const customerNameById = new Map((customers ?? []).map((c) => [c.id as string, c.name as string]));
  const snapshotBySite = new Map((snapshots ?? []).map((s) => [s.site_id as string, s]));
  const anomaliesBySite = new Map<string, SiteAnomalyRow[]>();
  for (const row of (anomalies ?? []) as SiteAnomalyRow[]) {
    const list = anomaliesBySite.get(row.site_id) ?? [];
    list.push(row);
    anomaliesBySite.set(row.site_id, list);
  }

  // Latest daily_health row per site — but "latest" means the most recent
  // COMPLETE day, not just the highest date. A row whose own notes say
  // "Partial day" was scored from an incomplete sync window (confirmed live
  // 2026-09-03: a backfill bounded by "now" at sync time rather than that
  // date's own midnight-to-midnight span — every site's rows for two
  // different, fully-elapsed past dates all showed the identical ~21h
  // coverage, which is a sync-timing artifact, not real per-site outages)
  // — not the concrete, trustworthy signal a customer/admin should see as
  // "the" site's health. Highest-date-among-complete-days wins; a tie (two
  // dump_types for the same date) keeps the higher health_score, same
  // dedup rule `database/vrm_report_db.py:bucket_health_days()` already
  // uses for exactly this "which row represents this date" question. Only
  // falls back to a partial row when literally nothing complete exists yet
  // in the lookback window (a brand-new site with no full day scored yet) —
  // better to show something, clearly labeled as partial, than nothing.
  const healthRowsBySite = new Map<string, { date: string; health_score: number | null; health_status: string | null; grid_dependency_pct: number | null; notes: string | null }[]>();
  for (const row of health ?? []) {
    const list = healthRowsBySite.get(row.site_id) ?? [];
    list.push({ date: row.date, health_score: row.health_score, health_status: row.health_status, grid_dependency_pct: row.grid_dependency_pct, notes: row.notes });
    healthRowsBySite.set(row.site_id, list);
  }
  const isPartialDay = (notes: string | null) => !!notes && notes.includes('Partial day');
  const latestHealthBySite = new Map<string, { date: string; health_score: number | null; health_status: string | null; grid_dependency_pct: number | null; notes: string | null }>();
  for (const [siteId, rows] of healthRowsBySite) {
    rows.sort((a, b) => (a.date === b.date ? (b.health_score ?? -1) - (a.health_score ?? -1) : b.date.localeCompare(a.date)));
    latestHealthBySite.set(siteId, rows.find((r) => !isPartialDay(r.notes)) ?? rows[0]);
  }

  // Latest energy_daily row per site — same "highest date wins" rule.
  const latestEnergyBySite = new Map<string, { date: string; pv_kwh: number | null; grid_kwh: number | null; grid_export_kwh: number | null; pv_kwp_snapshot: number | null; min_soc: number | null }>();
  for (const row of energyDaily ?? []) {
    const existing = latestEnergyBySite.get(row.site_id);
    if (!existing || row.date > existing.date) {
      latestEnergyBySite.set(row.site_id, row);
    }
  }

  // Every row from the last 7/30 days per site (not just the latest) — what
  // `_periodIndicators()` below sums/aggregates over, mirroring
  // `weekly_report.py`'s own framing exactly for whichever window a caller
  // asks for. A single day's discharge/outage figure is too noisy to mean
  // much alone; a week's or month's total/spread is the same grain the PDF
  // report already shows.
  type EnergyRowPeriod = {
    grid_kwh: number | null;
    min_soc: number | null;
    max_soc: number | null;
    avg_soc: number | null;
    outage_count: number | null;
    outage_minutes: number | null;
    battery_charge_kwh: number | null;
    battery_discharge_kwh: number | null;
  };
  const sevenDaysAgo = new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const last7dEnergyBySite = new Map<string, EnergyRowPeriod[]>();
  const last30dEnergyBySite = new Map<string, EnergyRowPeriod[]>();
  for (const row of energyDaily ?? []) {
    const entry: EnergyRowPeriod = {
      grid_kwh: row.grid_kwh,
      min_soc: row.min_soc,
      max_soc: row.max_soc,
      avg_soc: row.avg_soc,
      outage_count: row.outage_count,
      outage_minutes: row.outage_minutes,
      battery_charge_kwh: row.battery_charge_kwh,
      battery_discharge_kwh: row.battery_discharge_kwh,
    };
    // `lookback30Date` already bounds `energyDaily` to 30 days, so every
    // row here belongs in the month map; only the more recent ones also
    // belong in the week map.
    const monthList = last30dEnergyBySite.get(row.site_id) ?? [];
    monthList.push(entry);
    last30dEnergyBySite.set(row.site_id, monthList);
    if (row.date >= sevenDaysAgo) {
      const weekList = last7dEnergyBySite.get(row.site_id) ?? [];
      weekList.push(entry);
      last7dEnergyBySite.set(row.site_id, weekList);
    }
  }

  const rows: FleetOverviewRow[] = siteRows.map((s) => {
    const latestHealth = latestHealthBySite.get(s.site_id);
    const snapshot = snapshotBySite.get(s.site_id);
    const energy = latestEnergyBySite.get(s.site_id);
    const indicators = _dailyIndicators(energy, s.pv_kwp);
    return {
      site_id: s.site_id,
      display_name: s.display_name,
      customer_id: s.customer_id,
      customer_name: customerNameById.get(s.customer_id) ?? '—',
      system_type: s.system_type,
      pv_kwp: s.pv_kwp,
      battery_usable_kwh: s.battery_usable_kwh,
      timezone: s.timezone,
      vrm_last_synced_at: s.vrm_last_synced_at,
      connection_status: _connectionStatus(snapshot?.captured_at ?? null, now),
      health_score: latestHealth?.health_score ?? null,
      health_status: latestHealth?.health_status ?? null,
      health_date: latestHealth?.date ?? null,
      health_notes: latestHealth?.notes ?? null,
      active_alarms: _activeCountFromRaw(snapshot?.raw, 'alarms'),
      active_critical_alerts: _activeCountFromRaw(snapshot?.raw, 'critical_alerts'),
      active_anomalies: anomaliesBySite.get(s.site_id) ?? [],
      live_captured_at: snapshot?.captured_at ?? null,
      live_pv_power_w: snapshot?.pv_power_w ?? null,
      live_load_power_w: snapshot?.load_power_w ?? null,
      live_battery_power_w: snapshot?.battery_power_w ?? null,
      live_grid_power_w: snapshot?.grid_power_w ?? null,
      live_soc_pct: snapshot?.soc_pct ?? null,
      live_pv_chargers: _pvChargersFromRaw(snapshot?.raw),
      has_grid_meter: (snapshot?.grid_power_w ?? null) !== null,
      live_grid_source: _gridSourceFromRaw(snapshot?.raw),
      live_load_phases: _loadPhasesFromRaw(snapshot?.raw),
      health_metrics_date: energy?.date ?? null,
      specific_yield_kwh_per_kwp: indicators.specificYield,
      self_sufficiency_pct: indicators.selfSufficiency,
      self_consumption_pct: indicators.selfConsumption,
      dod_pct: indicators.dod,
      grid_dependency_pct: latestHealth?.grid_dependency_pct ?? null,
      week: _periodIndicators(last7dEnergyBySite.get(s.site_id) ?? [], s.battery_usable_kwh),
      month: _periodIndicators(last30dEnergyBySite.get(s.site_id) ?? [], s.battery_usable_kwh),
    };
  });

  const scores = rows.map((r) => r.health_score).filter((v): v is number => v !== null);
  const rollup = {
    site_count: rows.length,
    online_count: rows.filter((r) => r.connection_status === 'online').length,
    avg_health_score: scores.length > 0 ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null,
    total_active_alarms: rows.reduce((a, r) => a + r.active_alarms, 0),
    total_active_critical_alerts: rows.reduce((a, r) => a + r.active_critical_alerts, 0),
    total_active_anomalies: rows.reduce((a, r) => a + r.active_anomalies.length, 0),
  };

  return { sites: rows, rollup };
}
