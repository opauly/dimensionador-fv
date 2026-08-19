'use client';

// Admin report generation (PLAN_PHASE14.md §2 Step 7) — the admin-side
// counterpart of `app/(portal)/app/ReportManager.tsx`, extended with a
// schema toggle (`vrm` / `monitoring`) and a customer picker. Copy is
// English, inline (admin views went English-only 2026-08-19). No report
// math happens here — same §1.11 reasoning as the customer version: every
// number comes back inside a `report` job's `result.summary`, computed
// once, in `vrm_api`.
import { startTransition, useEffect, useState } from 'react';
import { Select, Stat } from '@/components/ui';
import { JobProgress, type JobProgressJob } from '@/components/app';
import type { SiteRecord } from '@/lib/server/db';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import type { Schema, SiteSummary } from '@/lib/server/pipeline';
import { getAvailableDatesForAdminAction, getReportLimitsAction, listMonitoringSitesAction } from './actions';
import styles from './reports.module.css';

type ReportSummary = {
  siteName: string;
  startStr: string;
  endStr: string;
  systemType: string;
  totals: {
    pv: number;
    load: number;
    grid: number;
    discharge: number;
    charge: number;
    outageCount: number;
    outageMinutes: number;
    // `false` when battery_charge_kwh/battery_discharge_kwh are unavailable
    // (VRM-API-ingested sites, PLAN_PHASE15.md §4.6) — `discharge`/`charge`
    // above are then a fabrication-safe 0.0, not a real reading. Typed here
    // for shape-accuracy even though this admin view has no energy-mix bar
    // of its own to gate on it (see `ReportManager.tsx`'s `EnergyMixBar`
    // for the customer-facing fix that actually needed this field).
    batteryKwhAvailable: boolean;
  };
  gridIndependencePct: number;
  avgHealth: number | string;
  healthStatus: string;
  // `null` for a site whose battery_charge_kwh/battery_discharge_kwh are
  // unavailable (e.g. VRM-API-ingested sites, PLAN_PHASE15.md §4.6) —
  // `weekly_report.py` distinguishes "no data" from "genuinely zero" rather
  // than fabricating 0.
  batteryCycles: number | null;
  battStressLabel: string;
  battStressColor: string;
  gridQualityScore: number;
  gridQualityStatus: string;
  gridQualityColor: string;
  weatherErrors: string[];
  missingDays: number;
  daysWithData: number;
  isOverview: boolean;
};

function daysBetween(start: string, end: string): number {
  const a = new Date(`${start}T00:00:00Z`).getTime();
  const b = new Date(`${end}T00:00:00Z`).getTime();
  return Math.round((b - a) / 86_400_000) + 1;
}

export function AdminReportsManager({ vrmSites, customers }: { vrmSites: SiteRecord[]; customers: AdminCustomerRow[] }) {
  const [schema, setSchema] = useState<Schema>('vrm');
  const [customerId, setCustomerId] = useState<string>(customers[0]?.id ?? '');
  const [monitoringSites, setMonitoringSites] = useState<SiteSummary[] | null>(null);

  // Bug-fix pass 2026-08-18 (Bug 3): `monitoring.sites` has no `customer_id`
  // FK (this schema predates `vrm.customers` — it's Oscar's own
  // Node-RED-monitored fleet, a different, older product), but its `owner`
  // text column holds the real person's name, populated on every current
  // row and confirmed to match `vrm.customers.name` exactly for at least
  // one real customer (Karen Montealegre, 3 sites). Exact match,
  // case-insensitive/trimmed — the data checked is consistently formatted,
  // so a looser substring match would only risk a false-positive match
  // between two differently-named people, not save anyone from a typo.
  const selectedCustomerName = customers.find((c) => c.id === customerId)?.name ?? null;
  const normalizedCustomerName = selectedCustomerName?.trim().toLowerCase() ?? null;

  const sites: SiteSummary[] =
    schema === 'vrm'
      ? vrmSites
          .filter((s) => s.customer_id === customerId)
          .map((s) => ({ site_id: s.site_id, display_name: s.display_name, owner: null }))
      : normalizedCustomerName
        ? (monitoringSites ?? []).filter((s) => (s.owner ?? '').trim().toLowerCase() === normalizedCustomerName)
        : (monitoringSites ?? []);

  const [siteId, setSiteId] = useState<string>('');
  const [limits, setLimits] = useState<{ max_custom_range_days: number; max_overview_range_days: number } | null>(null);
  const [dates, setDates] = useState<string[] | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  // Same "adjust state during render, not in an effect" shape
  // `ReportManager.tsx`'s own `trackedSiteId` comment documents — resets
  // everything downstream the instant `schema`/`customerId` change.
  const [trackedKey, setTrackedKey] = useState(`${schema}:${customerId}`);
  const currentKey = `${schema}:${customerId}`;
  if (currentKey !== trackedKey) {
    setTrackedKey(currentKey);
    setSiteId('');
    setDates(null);
    setSummary(null);
    setError(null);
    setStart('');
    setEnd('');
  }

  useEffect(() => {
    startTransition(async () => {
      const l = await getReportLimitsAction();
      setLimits(l);
    });
  }, []);

  useEffect(() => {
    if (schema !== 'monitoring') return;
    startTransition(async () => {
      const s = await listMonitoringSitesAction();
      setMonitoringSites(s);
    });
  }, [schema]);

  useEffect(() => {
    if (!siteId || !customerId) return;
    let cancelled = false;
    startTransition(async () => {
      const d = await getAvailableDatesForAdminAction(siteId, customerId, schema);
      if (cancelled) return;
      setDates(d);
      if (d.length > 0) {
        setStart(d[Math.max(0, d.length - 7)]);
        setEnd(d[d.length - 1]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [siteId, customerId, schema]);

  const numDays = start && end ? daysBetween(start, end) : 0;
  const isOverviewRange = !!limits && numDays > limits.max_custom_range_days;
  const tooLong = !!limits && numDays > limits.max_overview_range_days;
  const covered = dates && start && end ? dates.filter((d) => d >= start && d <= end).length : 0;

  async function handleGenerate() {
    setError(null);
    setSummary(null);
    setGenerating(true);
    try {
      const res = await fetch('/api/admin/pipeline/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customerId, siteId, start, end, schema }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string; maxDays?: number } | null;
        if (body?.error === 'range_too_long') {
          setError(`The chosen range is ${numDays} days; the maximum is ${body.maxDays ?? '—'}.`);
        } else if (body?.error === 'not_authorized') {
          setError('This site does not belong to the selected customer.');
        } else {
          setError('Could not generate the report. Please try again.');
        }
        setGenerating(false);
        return;
      }
      const { job_id } = (await res.json()) as { job_id: string };
      setJobId(job_id);
    } catch {
      setError('Could not reach the reporting service.');
      setGenerating(false);
    }
  }

  function handleJobDone(job: JobProgressJob) {
    const result = job.result as { summary?: ReportSummary } | null;
    setSummary(result?.summary ?? null);
    setGenerating(false);
  }

  function handleJobFailed(message: string) {
    setError(message);
    setGenerating(false);
  }

  async function handleDownload() {
    if (!jobId) return;
    setDownloading(true);
    try {
      const res = await fetch(`/api/admin/pipeline/reports/${encodeURIComponent(jobId)}/download`);
      if (!res.ok) {
        setError('Could not prepare the download.');
        return;
      }
      const { url } = (await res.json()) as { url: string; filename: string };
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch {
      setError('Could not prepare the download.');
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div>
      <div className={styles.controls}>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>Source</span>
          <Select value={schema} onChange={(e) => setSchema(e.target.value as Schema)}>
            <option value="vrm">vrm — external customers</option>
            <option value="monitoring">monitoring — own sites</option>
          </Select>
        </label>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>Customer {schema === 'monitoring' ? '(job reference only)' : ''}</span>
          <Select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </label>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>Site</span>
          <Select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">— choose a site —</option>
            {sites.map((s) => (
              <option key={s.site_id} value={s.site_id}>
                {s.display_name}
              </option>
            ))}
          </Select>
        </label>
      </div>
      {schema === 'monitoring' && (
        <p className={styles.caption}>
          <code>monitoring</code> sites have no customer FK — they are filtered by the <code>owner</code> field (person&apos;s
          name) compared against the customer name chosen above; that customer also remains the job&apos;s internal reference
          (required by <code>vrm.jobs.customer_id</code>).
        </p>
      )}

      {sites.length === 0 && <p className={styles.emptyPanel}>No sites in the {schema} schema.</p>}

      {dates && dates.length === 0 && siteId && <p className={styles.emptyPanel}>This site has no daily data yet.</p>}

      {dates && dates.length > 0 && (
        <div className={styles.panel}>
          <p className={styles.caption}>
            Available data: {dates[0]} → {dates[dates.length - 1]} ({dates.length} days)
          </p>
          <div className={styles.controls}>
            <label className={styles.controlField}>
              <span className={styles.controlLabel}>Start date</span>
              <input type="date" className={styles.dateInput} value={start} min={dates[0]} max={end || dates[dates.length - 1]} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className={styles.controlField}>
              <span className={styles.controlLabel}>End date</span>
              <input type="date" className={styles.dateInput} value={end} min={start || dates[0]} max={dates[dates.length - 1]} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>

          {limits && numDays > 0 && !tooLong && (
            <p className={styles.caption}>
              {isOverviewRange
                ? `Overview — ${numDays} days, grouped by month.`
                : `Detailed — ${numDays} days, day by day.`}
            </p>
          )}
          {tooLong && limits && <p className={styles.error}>The range is {numDays} days; the maximum is {limits.max_overview_range_days}.</p>}
          {!tooLong && numDays > 0 && covered < numDays && (
            <p className={styles.warning}>
              The range {start} → {end} has {covered} of {numDays} days with data.
            </p>
          )}

          {error && <p className={styles.error}>{error}</p>}

          {!generating && (
            <button type="button" className={styles.generateButton} onClick={handleGenerate} disabled={!start || !end || tooLong}>
              Generate report
            </button>
          )}
          {generating && jobId && (
            <JobProgress
              jobId={jobId}
              endpoint="/api/admin/pipeline/jobs"
              runningLabel="Generating…"
              genericFailedLabel="Something went wrong. Please try again."
              unreachableLabel="Could not reach the reporting service."
              onDone={handleJobDone}
              onFailed={handleJobFailed}
            />
          )}
        </div>
      )}

      {summary && (
        <div className={styles.panel}>
          <div className={styles.statGrid}>
            <Stat label="Solar generation" value={summary.totals.pv.toFixed(1)} unit="kWh" />
            <Stat label="Consumption" value={summary.totals.load.toFixed(1)} unit="kWh" />
            <Stat label="Independence" value={summary.gridIndependencePct} unit="%" />
            <Stat label="Health" value={summary.avgHealth} unit={`/100 · ${summary.healthStatus}`} good />
          </div>

          {/* Reorganized 2026-08-19 at Oscar's request, mirroring the same
             change in pages/06_vrm_monitor.py's tab_report() and
             ReportManager.tsx: this panel is a quick "did this run
             correctly" glance before downloading, not a second copy of the
             report — grid quality, outages, and battery-stress cycle count
             are all already their own dedicated PDF sections
             (report_svg.py's Grid Quality block, Events block, and SALUD DE
             LA BATERÍA block). Kept: the four Stat cards above, system
             type/data coverage (genuine "is this the right site/window"
             context, not a restated PDF stat), and the
             weather-fetch-failure warning (not a duplicated number — a
             heads-up that a PDF section came out silently empty because an
             external call failed). */}
          <div className={styles.chipRow}>
            <span className={styles.chip}>{summary.systemType}</span>
            <span className={styles.chip}>
              {summary.daysWithData}/{summary.daysWithData + summary.missingDays} days with data
            </span>
          </div>

          <p className={styles.caption}>
            Period {summary.startStr} → {summary.endStr} · {summary.daysWithData} days
          </p>

          {summary.weatherErrors.length > 0 && <p className={styles.warning}>Could not fetch weather data from Open-Meteo.</p>}

          <button type="button" className={styles.generateButton} onClick={handleDownload} disabled={downloading}>
            {downloading ? 'Preparing…' : 'Download PDF'}
          </button>
        </div>
      )}
    </div>
  );
}
