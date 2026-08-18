'use client';

// Admin report generation (PLAN_PHASE14.md §2 Step 7) — the admin-side
// counterpart of `app/(portal)/app/ReportManager.tsx`, extended with a
// schema toggle (`vrm` / `monitoring`) and a customer picker. Copy is
// Spanish, inline (§1.10). No report math happens here — same §1.11
// reasoning as the customer version: every number comes back inside a
// `report` job's `result.summary`, computed once, in `vrm_api`.
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
  };
  gridIndependencePct: number;
  avgHealth: number | string;
  healthStatus: string;
  batteryCycles: number;
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

  const sites: SiteSummary[] =
    schema === 'vrm'
      ? vrmSites.filter((s) => s.customer_id === customerId).map((s) => ({ site_id: s.site_id, display_name: s.display_name }))
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
          setError(`El rango elegido es de ${numDays} días; el máximo es ${body.maxDays ?? '—'}.`);
        } else if (body?.error === 'not_authorized') {
          setError('Este sitio no pertenece al cliente elegido.');
        } else {
          setError('No se pudo generar el reporte. Intentá de nuevo.');
        }
        setGenerating(false);
        return;
      }
      const { job_id } = (await res.json()) as { job_id: string };
      setJobId(job_id);
    } catch {
      setError('No se pudo contactar al servicio de reportes.');
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
        setError('No se pudo preparar la descarga.');
        return;
      }
      const { url } = (await res.json()) as { url: string; filename: string };
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch {
      setError('No se pudo preparar la descarga.');
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div>
      <div className={styles.controls}>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>Origen</span>
          <Select value={schema} onChange={(e) => setSchema(e.target.value as Schema)}>
            <option value="vrm">vrm — clientes externos</option>
            <option value="monitoring">monitoring — sitios propios</option>
          </Select>
        </label>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>Cliente {schema === 'monitoring' ? '(solo referencia del job)' : ''}</span>
          <Select value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </label>
        <label className={styles.controlField}>
          <span className={styles.controlLabel}>Sitio</span>
          <Select value={siteId} onChange={(e) => setSiteId(e.target.value)}>
            <option value="">— elegí un sitio —</option>
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
          Los sitios <code>monitoring</code> no pertenecen a ningún cliente — el cliente elegido arriba solo se usa como
          referencia interna del job (requerida por <code>vrm.jobs.customer_id</code>), no para filtrar sitios.
        </p>
      )}

      {sites.length === 0 && <p className={styles.emptyPanel}>No hay sitios en el esquema {schema}.</p>}

      {dates && dates.length === 0 && siteId && <p className={styles.emptyPanel}>Ese sitio todavía no tiene datos diarios.</p>}

      {dates && dates.length > 0 && (
        <div className={styles.panel}>
          <p className={styles.caption}>
            Datos disponibles: {dates[0]} → {dates[dates.length - 1]} ({dates.length} días)
          </p>
          <div className={styles.controls}>
            <label className={styles.controlField}>
              <span className={styles.controlLabel}>Fecha de inicio</span>
              <input type="date" className={styles.dateInput} value={start} min={dates[0]} max={end || dates[dates.length - 1]} onChange={(e) => setStart(e.target.value)} />
            </label>
            <label className={styles.controlField}>
              <span className={styles.controlLabel}>Fecha de fin</span>
              <input type="date" className={styles.dateInput} value={end} min={start || dates[0]} max={dates[dates.length - 1]} onChange={(e) => setEnd(e.target.value)} />
            </label>
          </div>

          {limits && numDays > 0 && !tooLong && (
            <p className={styles.caption}>
              {isOverviewRange
                ? `Resumen (Overview) — ${numDays} días, agrupado por mes.`
                : `Detallado — ${numDays} días, día por día.`}
            </p>
          )}
          {tooLong && limits && <p className={styles.error}>El rango es de {numDays} días; el máximo es {limits.max_overview_range_days}.</p>}
          {!tooLong && numDays > 0 && covered < numDays && (
            <p className={styles.warning}>
              El rango {start} → {end} tiene {covered} de {numDays} días con datos.
            </p>
          )}

          {error && <p className={styles.error}>{error}</p>}

          {!generating && (
            <button type="button" className={styles.generateButton} onClick={handleGenerate} disabled={!start || !end || tooLong}>
              Generar reporte
            </button>
          )}
          {generating && jobId && (
            <JobProgress
              jobId={jobId}
              endpoint="/api/admin/pipeline/jobs"
              runningLabel="Generando…"
              genericFailedLabel="Algo salió mal. Intentá de nuevo."
              unreachableLabel="No se pudo contactar al servicio de reportes."
              onDone={handleJobDone}
              onFailed={handleJobFailed}
            />
          )}
        </div>
      )}

      {summary && (
        <div className={styles.panel}>
          <div className={styles.statGrid}>
            <Stat label="Generación solar" value={summary.totals.pv.toFixed(1)} unit="kWh" />
            <Stat label="Consumo" value={summary.totals.load.toFixed(1)} unit="kWh" />
            <Stat label="Independencia" value={summary.gridIndependencePct} unit="%" />
            <Stat label="Salud" value={summary.avgHealth} unit={`/100 · ${summary.healthStatus}`} good />
          </div>

          <div className={styles.chipRow}>
            <span className={styles.chip}>{summary.systemType}</span>
            <span className={styles.chip}>
              {summary.daysWithData}/{summary.daysWithData + summary.missingDays} días con datos
            </span>
            <span className={styles.chip} style={{ color: summary.battStressColor }}>
              {summary.battStressLabel} ({summary.batteryCycles} cyc)
            </span>
            <span className={styles.chip} style={{ color: summary.gridQualityColor }}>
              {summary.gridQualityStatus} ({summary.gridQualityScore}/100)
            </span>
            <span className={styles.chip}>
              {summary.totals.outageCount > 0 ? `${summary.totals.outageCount} corte(s) (${summary.totals.outageMinutes} min)` : 'Sin cortes'}
            </span>
          </div>

          <p className={styles.caption}>
            Periodo {summary.startStr} → {summary.endStr} · {summary.daysWithData} días
          </p>

          {summary.weatherErrors.length > 0 && <p className={styles.warning}>No se pudo obtener el clima de Open-Meteo.</p>}
          {(summary.battStressLabel === 'Alto estrés' || summary.battStressLabel === 'High stress') && (
            <p className={styles.warning}>
              Estrés de batería alto: {summary.batteryCycles} ciclos en {summary.daysWithData} días.
            </p>
          )}
          {summary.gridQualityScore < 70 && (
            <p className={styles.warning}>
              Calidad de red baja: {summary.gridQualityScore}/100 ({summary.gridQualityStatus}).
            </p>
          )}

          <button type="button" className={styles.generateButton} onClick={handleDownload} disabled={downloading}>
            {downloading ? 'Preparando…' : 'Descargar PDF'}
          </button>
        </div>
      )}
    </div>
  );
}
