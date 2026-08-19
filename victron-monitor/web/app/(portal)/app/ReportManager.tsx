'use client';

// Reports (PLAN_PHASE14.md §2 Step 6) — this is the dashboard's landing
// page, replacing Step 3's placeholder. No report math happens here: every
// number comes back inside a `report` job's `result.summary`, computed by
// `victron/weekly_report.py:build_report_data()` inside `vrm_api` (§1.11 —
// "the Next.js layer does not reimplement `build_report_data` in
// TypeScript"). This component's job is the range picker, the mode caption
// (driven by `GET /api/pipeline/limits`, never a hardcoded constant — same
// §1.11 reasoning, one level down), and rendering the summary vrm_api hands
// back.
import { useEffect, useState } from 'react';
import { Select, Stat } from '@/components/ui';
import { JobProgress, type JobProgressJob } from '@/components/app';
import { t, type Lang } from '@/lib/i18n/strings';
import type { SiteRecord } from '@/lib/server/db';
import styles from './reports.module.css';

export type ReportManagerProps = {
  sites: SiteRecord[];
  lang: Lang;
};

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
    // for every day in range (VRM-API-ingested sites, PLAN_PHASE15.md §4.6)
    // — `discharge`/`charge` above are then a fabrication-safe 0.0, not a
    // real reading, and must not be presented as a confirmed zero.
    batteryKwhAvailable: boolean;
  };
  gridIndependencePct: number;
  avgHealth: number | string;
  healthStatus: string;
  // `null` when battery_charge_kwh/battery_discharge_kwh are unavailable
  // (e.g. VRM-API-ingested sites, PLAN_PHASE15.md §4.6) — `weekly_report.py`
  // distinguishes "no data" from "genuinely zero" rather than fabricating 0.
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
  exportsToGrid: boolean;
};

type Limits = { max_custom_range_days: number; max_overview_range_days: number };

function isoDaysAgo(dates: string[], fromEnd: number): string {
  return dates[Math.max(0, dates.length - fromEnd)];
}

function daysBetween(start: string, end: string): number {
  const a = new Date(`${start}T00:00:00Z`).getTime();
  const b = new Date(`${end}T00:00:00Z`).getTime();
  return Math.round((b - a) / 86_400_000) + 1;
}

export function ReportManager({ sites, lang }: ReportManagerProps) {
  const [siteId, setSiteId] = useState<string>(sites[0]?.site_id ?? '');
  const [limits, setLimits] = useState<Limits | null>(null);
  const [dates, setDates] = useState<string[] | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [jobId, setJobId] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [summary, setSummary] = useState<ReportSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  // "Adjusting state when a prop/state change happens" during render, not
  // in an effect (react-hooks/set-state-in-effect flags an unconditional
  // setState right at the top of an effect body — the fix React's own docs
  // recommend is to derive the reset from render inputs instead). Tracking
  // the *previous* siteId in state and comparing during render is what lets
  // "the site changed, so the old range/summary/error are stale" be a
  // render-time fact rather than a side effect.
  const [trackedSiteId, setTrackedSiteId] = useState(siteId);
  if (siteId !== trackedSiteId) {
    setTrackedSiteId(siteId);
    setDates(null);
    setSummary(null);
    setError(null);
    setStart('');
    setEnd('');
  }

  useEffect(() => {
    let cancelled = false;
    fetch('/api/pipeline/limits')
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Limits | null) => {
        if (!cancelled) setLimits(data);
      })
      .catch(() => {
        if (!cancelled) setLimits(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!siteId) return;
    let cancelled = false;
    fetch(`/api/pipeline/sites/${encodeURIComponent(siteId)}/available-dates`)
      .then((res) => (res.ok ? res.json() : { dates: [] }))
      .then((data: { dates: string[] }) => {
        if (cancelled) return;
        setDates(data.dates);
        if (data.dates.length > 0) {
          setStart(isoDaysAgo(data.dates, 7));
          setEnd(data.dates[data.dates.length - 1]);
        }
      })
      .catch(() => {
        if (!cancelled) setDates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [siteId]);

  if (sites.length === 0) {
    return (
      <div className={styles.emptyPanel}>
        <p>{t(lang, 'reports_no_sites')}</p>
        <a href="/app/upload">{t(lang, 'reports_no_sites_cta')}</a>
      </div>
    );
  }

  const numDays = start && end ? daysBetween(start, end) : 0;
  const isOverviewRange = !!limits && numDays > limits.max_custom_range_days;
  const tooLong = !!limits && numDays > limits.max_overview_range_days;
  const covered = dates && start && end ? dates.filter((d) => d >= start && d <= end).length : 0;

  async function handleGenerate() {
    setError(null);
    setSummary(null);
    setGenerating(true);
    try {
      const res = await fetch('/api/pipeline/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ siteId, start, end }),
      });
      if (!res.ok) {
        // `range_too_long` is the server-side twin of this component's own
        // `tooLong` check (both read from the same `GET /api/pipeline/limits`)
        // — reachable in practice only via a tampered request, since the
        // Generate button is already disabled past this boundary, but it
        // still deserves the specific message rather than the generic one.
        const body = (await res.json().catch(() => null)) as { error?: string; maxDays?: number } | null;
        if (body?.error === 'range_too_long') {
          setError(t(lang, 'reports_range_too_long').replace('{days}', String(numDays)).replace('{max}', String(body.maxDays ?? '')));
        } else {
          setError(t(lang, 'reports_error_generic'));
        }
        setGenerating(false);
        return;
      }
      const { job_id } = (await res.json()) as { job_id: string };
      setJobId(job_id);
    } catch {
      setError(t(lang, 'reports_error_unreachable'));
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
      const res = await fetch(`/api/pipeline/reports/${encodeURIComponent(jobId)}/download`);
      if (!res.ok) {
        setError(t(lang, 'reports_download_error'));
        return;
      }
      const { url } = (await res.json()) as { url: string; filename: string };
      // A short-TTL Supabase Storage signed URL, not a public one (see
      // lib/server/storage.ts) — opened directly rather than fetched again
      // client-side, since the whole point of a signed URL is that the
      // browser can use it once, on its own, without this app's server
      // sitting in the middle of the actual PDF bytes.
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch {
      setError(t(lang, 'reports_download_error'));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div>
      <div className={styles.controls}>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>{t(lang, 'reports_site_label')}</span>
          <Select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            {sites.map((s) => (
              <option key={s.site_id} value={s.site_id}>
                {s.display_name}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {dates && dates.length === 0 && (
        <div className={styles.emptyPanel}>
          <p>{t(lang, 'reports_no_data')}</p>
          <a href="/app/upload">{t(lang, 'reports_no_data_cta')}</a>
        </div>
      )}

      {dates && dates.length > 0 && (
        <div className={styles.panel}>
          <p className={styles.caption}>
            {t(lang, 'reports_range_available')
              .replace('{start}', dates[0])
              .replace('{end}', dates[dates.length - 1])
              .replace('{days}', String(dates.length))}
          </p>
          <div className={styles.controls}>
            <label className={styles.controlField}>
              <span className={styles.controlLabel}>{t(lang, 'reports_range_start')}</span>
              <input
                type="date"
                className={styles.dateInput}
                value={start}
                min={dates[0]}
                max={end || dates[dates.length - 1]}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label className={styles.controlField}>
              <span className={styles.controlLabel}>{t(lang, 'reports_range_end')}</span>
              <input
                type="date"
                className={styles.dateInput}
                value={end}
                min={start || dates[0]}
                max={dates[dates.length - 1]}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
          </div>

          {limits && numDays > 0 && !tooLong && (
            <p className={styles.caption}>
              {isOverviewRange
                ? t(lang, 'reports_mode_overview').replace('{days}', String(numDays)).replace('{max}', String(limits.max_custom_range_days))
                : t(lang, 'reports_mode_detailed').replace('{days}', String(numDays))}
            </p>
          )}
          {tooLong && limits && (
            <p className={styles.error}>{t(lang, 'reports_range_too_long').replace('{days}', String(numDays)).replace('{max}', String(limits.max_overview_range_days))}</p>
          )}
          {!tooLong && numDays > 0 && covered < numDays && (
            <p className={styles.warning}>
              {t(lang, 'reports_coverage_warning')
                .replace('{start}', start)
                .replace('{end}', end)
                .replace('{covered}', String(covered))
                .replace('{days}', String(numDays))}
            </p>
          )}

          {error && <p className={styles.error}>{error}</p>}

          {!generating && (
            <button type="button" className={styles.generateButton} onClick={handleGenerate} disabled={!start || !end || tooLong}>
              {t(lang, 'reports_generate_button')}
            </button>
          )}
          {generating && jobId && (
            <JobProgress
              jobId={jobId}
              runningLabel={t(lang, 'reports_generating')}
              genericFailedLabel={t(lang, 'job_generic_failed')}
              unreachableLabel={t(lang, 'reports_error_unreachable')}
              onDone={handleJobDone}
              onFailed={handleJobFailed}
            />
          )}
        </div>
      )}

      {summary && (
        <div className={styles.panel}>
          <div className={styles.statGrid}>
            <Stat label={t(lang, 'reports_stat_pv')} value={summary.totals.pv.toFixed(1)} unit="kWh" />
            <Stat label={t(lang, 'reports_stat_load')} value={summary.totals.load.toFixed(1)} unit="kWh" />
            <Stat label={t(lang, 'reports_stat_independence')} value={summary.gridIndependencePct} unit="%" />
            <Stat label={t(lang, 'reports_stat_health')} value={summary.avgHealth} unit={`/100 · ${summary.healthStatus}`} good />
          </div>

          {/* Reorganized 2026-08-19 at Oscar's request, mirroring the same
             change in pages/06_vrm_monitor.py's tab_report(): this panel is
             a quick "did this run correctly" glance before downloading, not
             a second copy of the report — grid quality, outages,
             battery-stress cycle count, and the energy-mix chart are all
             already their own dedicated PDF sections (report_svg.py's Grid
             Quality block, Events block, SALUD DE LA BATERÍA block, and the
             DE DÓNDE VINO SU ENERGÍA donut). Kept: the four Stat cards
             above, system type/data coverage (genuine "is this the right
             site/window" context, not a restated PDF stat), and the
             weather-fetch-failure warning (not a duplicated number — a
             heads-up that a PDF section came out silently empty because an
             external call failed). */}
          <div className={styles.chipRow}>
            <span className={styles.chip}>{summary.systemType}</span>
            <span className={styles.chip}>
              {t(lang, 'reports_chip_days').replace('{covered}', String(summary.daysWithData)).replace('{total}', String(summary.daysWithData + summary.missingDays))}
            </span>
          </div>

          <p className={styles.caption}>
            {t(lang, 'reports_period_caption')
              .replace('{start}', summary.startStr)
              .replace('{end}', summary.endStr)
              .replace('{days}', String(summary.daysWithData))}
          </p>

          {summary.weatherErrors.length > 0 && <p className={styles.warning}>{t(lang, 'reports_weather_error_warning')}</p>}

          <button type="button" className={styles.generateButton} onClick={handleDownload} disabled={downloading}>
            {downloading ? t(lang, 'reports_downloading') : t(lang, 'reports_download_button')}
          </button>
        </div>
      )}
    </div>
  );
}

