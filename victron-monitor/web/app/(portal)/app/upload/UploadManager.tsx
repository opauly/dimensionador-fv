'use client';

// Upload flow (PLAN_PHASE14.md §2 Step 6) — the two-step parse -> preview ->
// confirm shape `pages/06_vrm_monitor.py:tab_upload()` uses, re-implemented
// against `vrm_api` through this app's own proxy routes instead of calling
// `victron.*` directly (that only happens in `vrm_api`, never in Next.js —
// PLAN_PHASE14.md §1.11). "Never write on the first click" here means: the
// CSV is uploaded to Storage and parsed by `ingest/preview` before anything
// touches `vrm.sites` / `vrm.energy_daily`; only clicking "Import to your
// account" calls `ingest/commit`.
import { startTransition, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Field, Input, Select, Table } from '@/components/ui';
import { JobProgress, type JobProgressJob } from '@/components/app';
import { t, type Lang } from '@/lib/i18n/strings';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import { SUPPORTED_FLAT_CURRENCIES } from '@/lib/currencies';
import { listTimezones, DEFAULT_TIMEZONE } from '@/lib/timezones';
import { MAX_UPLOAD_BYTES, formatBytes } from '@/lib/uploadLimits';
import { formatDateTime } from '@/lib/dates';
import { reverseGeocodeAction } from '../sites/actions';
import type { CanAddSiteResult, IngestionLogRecord, SiteRecord } from '@/lib/server/db';
import { uploadFileToSignedUrl } from '@/lib/uploadClient';
import styles from './upload.module.css';

export type UploadManagerProps = {
  sites: SiteRecord[];
  lang: Lang;
  canAdd: CanAddSiteResult;
  ingestions: IngestionLogRecord[];
};

type ParsedRow = {
  date: string;
  pv_kwh: number;
  load_kwh: number;
  grid_kwh: number;
  battery_charge_kwh: number;
  battery_discharge_kwh: number;
  min_soc: number | null;
  max_soc: number | null;
  outage_count: number;
  outage_minutes: number;
  hours_covered: number;
  complete_day: boolean;
};

type ParsedExport = {
  installation_id: string | number | null;
  timezone_label: string;
  sample_count: number;
  period_start: string;
  period_end: string;
  rows: ParsedRow[];
  alarm_events: unknown[];
  outages: unknown[];
  warnings: string[];
};

type PreviewResult = {
  site_id: string;
  site_is_existing: boolean;
  site_name: string;
  storage_path: string;
  site_fields: Record<string, unknown>;
  parsed: ParsedExport;
};

type CommitResult = {
  site_id: string;
  rows_written: number;
  alarm_events_written: number;
};

type SiteFieldsState = {
  displayName: string;
  pvKwp: string;
  battNominal: string;
  battDod: string;
  systemType: 'hybrid' | 'off_grid' | 'grid_zero';
  reportLanguage: 'en' | 'es';
  latitude: string;
  longitude: string;
  location: string;
  timezone: string;
  country: string;
  savingsRate: string;
  savingsCurrency: string;
  exportsToGrid: boolean;
};

const NEW_SITE_VALUE = '__new__';

function emptyFields(): SiteFieldsState {
  return {
    displayName: '',
    pvKwp: '',
    battNominal: '',
    battDod: '',
    systemType: 'hybrid',
    reportLanguage: 'en',
    latitude: '',
    longitude: '',
    location: '',
    timezone: DEFAULT_TIMEZONE,
    country: DEFAULT_COUNTRY,
    savingsRate: '',
    savingsCurrency: 'USD',
    exportsToGrid: false,
  };
}

function fieldsFromSite(site: SiteRecord): SiteFieldsState {
  return {
    displayName: site.display_name,
    pvKwp: site.pv_kwp?.toString() ?? '',
    battNominal: site.battery_nominal_kwh?.toString() ?? '',
    battDod: site.battery_dod_pct?.toString() ?? '',
    systemType: site.system_type,
    reportLanguage: site.report_language,
    latitude: site.latitude?.toString() ?? '',
    longitude: site.longitude?.toString() ?? '',
    location: site.location ?? '',
    timezone: site.timezone,
    country: site.country ?? DEFAULT_COUNTRY,
    savingsRate: site.savings_rate?.toString() ?? '',
    savingsCurrency: site.savings_currency ?? 'USD',
    exportsToGrid: site.exports_to_grid,
  };
}

function toNumberOrNull(s: string): number | null {
  if (s.trim() === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

type Phase = 'form' | 'signing' | 'uploading' | 'previewing' | 'preview_ready' | 'committing' | 'done' | 'error';

const TIMEZONES = listTimezones();
const COUNTRY_CODES = Object.keys(COUNTRIES);

export function UploadManager({ sites, lang, canAdd, ingestions }: UploadManagerProps) {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [siteSelection, setSiteSelection] = useState<string>(sites[0]?.site_id ?? (canAdd.ok ? NEW_SITE_VALUE : ''));
  const [fields, setFields] = useState<SiteFieldsState>(() => {
    const initial = sites.find((s) => s.site_id === siteSelection);
    return initial ? fieldsFromSite(initial) : emptyFields();
  });
  const [file, setFile] = useState<File | null>(null);
  const [phase, setPhase] = useState<Phase>('form');
  const [uploadPct, setUploadPct] = useState(0);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [commitJobId, setCommitJobId] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [geocodeError, setGeocodeError] = useState<string | null>(null);
  const [geocoding, setGeocoding] = useState(false);

  const usableKwh = useMemo(() => {
    const n = Number(fields.battNominal);
    const d = Number(fields.battDod);
    if (!fields.battNominal || !fields.battDod || !Number.isFinite(n) || !Number.isFinite(d)) return null;
    return Math.round(((n * d) / 100) * 100) / 100;
  }, [fields.battNominal, fields.battDod]);

  function handleSiteSelectionChange(value: string) {
    setSiteSelection(value);
    if (value === NEW_SITE_VALUE) {
      setFields(emptyFields());
    } else {
      const site = sites.find((s) => s.site_id === value);
      if (site) setFields(fieldsFromSite(site));
    }
  }

  function handleGeocodeClick() {
    if (!fields.latitude && !fields.longitude) {
      setGeocodeError(t(lang, 'sites_geocode_missing_coords'));
      return;
    }
    const lat = Number(fields.latitude);
    const lng = Number(fields.longitude);
    setGeocodeError(null);
    startTransition(async () => {
      setGeocoding(true);
      const result = await reverseGeocodeAction(lat, lng);
      setGeocoding(false);
      if ('error' in result) {
        setGeocodeError(result.error);
        return;
      }
      setFields((f) => ({
        ...f,
        location: result.location ?? f.location,
        country: result.countryCode && COUNTRIES[result.countryCode] ? result.countryCode : f.country,
      }));
    });
  }

  function buildSiteFields(): Record<string, unknown> {
    return {
      display_name: fields.displayName.trim(),
      pv_kwp: toNumberOrNull(fields.pvKwp),
      battery_nominal_kwh: toNumberOrNull(fields.battNominal),
      battery_dod_pct: toNumberOrNull(fields.battDod),
      system_type: fields.systemType,
      report_language: fields.reportLanguage,
      location: fields.location.trim() || null,
      timezone: fields.timezone,
      latitude: toNumberOrNull(fields.latitude),
      longitude: toNumberOrNull(fields.longitude),
      country: fields.country,
      savings_rate: toNumberOrNull(fields.savingsRate),
      savings_currency: fields.savingsRate ? fields.savingsCurrency : null,
      exports_to_grid: fields.exportsToGrid,
    };
  }

  async function handleProcessClick() {
    setErrorMessage(null);
    if (!file || !fields.displayName.trim()) {
      setErrorMessage(t(lang, 'upload_error_missing_site'));
      return;
    }

    try {
      setPhase('signing');
      const signRes = await fetch('/api/uploads/sign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, sizeBytes: file.size }),
      });
      if (signRes.status === 413) {
        setErrorMessage(t(lang, 'upload_file_too_large').replace('{limit}', formatBytes(MAX_UPLOAD_BYTES)));
        setPhase('form');
        return;
      }
      if (!signRes.ok) {
        setErrorMessage(t(lang, 'upload_error_generic'));
        setPhase('form');
        return;
      }
      const { uploadUrl, path } = (await signRes.json()) as { uploadUrl: string; path: string };

      setPhase('uploading');
      setUploadPct(0);
      await uploadFileToSignedUrl(uploadUrl, file, setUploadPct);

      setPhase('previewing');
      const previewRes = await fetch('/api/pipeline/ingest/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          siteSelection === NEW_SITE_VALUE
            ? { siteSelection: 'new', newSiteName: fields.displayName.trim(), storagePath: path, filename: file.name, siteFields: buildSiteFields() }
            : { siteSelection: 'existing', siteId: siteSelection, storagePath: path, filename: file.name, siteFields: buildSiteFields() },
        ),
      });
      if (!previewRes.ok) {
        setErrorMessage(t(lang, 'upload_error_generic'));
        setPhase('error');
        return;
      }
      const { job_id } = (await previewRes.json()) as { job_id: string };
      setPreviewJobId(job_id);
    } catch {
      setErrorMessage(t(lang, 'upload_error_unreachable'));
      setPhase('error');
    }
  }

  function handlePreviewJobDone(job: JobProgressJob) {
    setPreview(job.result as unknown as PreviewResult);
    setPhase('preview_ready');
  }

  function handlePreviewJobFailed(message: string) {
    setErrorMessage(message);
    setPhase('error');
  }

  async function handleConfirmClick() {
    if (!previewJobId) return;
    setErrorMessage(null);
    try {
      setPhase('committing');
      const res = await fetch('/api/pipeline/ingest/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId: previewJobId }),
      });
      if (!res.ok) {
        setErrorMessage(t(lang, 'upload_error_generic'));
        setPhase('error');
        return;
      }
      const { job_id } = (await res.json()) as { job_id: string };
      setCommitJobId(job_id);
    } catch {
      setErrorMessage(t(lang, 'upload_error_unreachable'));
      setPhase('error');
    }
  }

  function handleCommitJobDone(job: JobProgressJob) {
    setCommitResult(job.result as unknown as CommitResult);
    setPhase('done');
    // Refreshes the Server Component tree (this page's own `listSites` /
    // `listIngestions`, and the site dropdown/history table below) so a
    // newly-created site and the just-written history row show up without
    // a manual reload — there is no client-side cache of either to patch
    // by hand.
    router.refresh();
  }

  function handleCommitJobFailed(message: string) {
    setErrorMessage(message);
    setPhase('error');
  }

  function handleStartOver() {
    setPhase('form');
    setFile(null);
    setPreview(null);
    setCommitResult(null);
    setPreviewJobId(null);
    setCommitJobId(null);
    setErrorMessage(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  const formDisabled = phase !== 'form' && phase !== 'error';
  const savingsNote = fields.systemType === 'off_grid' ? t(lang, 'upload_savings_offgrid_note') : '';

  return (
    <div>
      {phase !== 'done' && (
        <div className={styles.panel}>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'upload_site_label')} htmlFor="upload-site">
              <Select
                id="upload-site"
                value={siteSelection}
                onChange={(e) => handleSiteSelectionChange(e.target.value)}
                disabled={formDisabled}
              >
                {sites.map((s) => (
                  <option key={s.site_id} value={s.site_id}>
                    {s.display_name}
                  </option>
                ))}
                {canAdd.ok && <option value={NEW_SITE_VALUE}>{t(lang, 'upload_site_new_option')}</option>}
              </Select>
            </Field>
            <Field
              label={siteSelection === NEW_SITE_VALUE ? t(lang, 'upload_new_site_name_label') : t(lang, 'sites_field_name')}
              htmlFor="upload-site-name"
              required
            >
              <Input
                id="upload-site-name"
                value={fields.displayName}
                onChange={(e) => setFields((f) => ({ ...f, displayName: e.target.value }))}
                disabled={formDisabled}
                required
              />
            </Field>
          </div>

          {!canAdd.ok && sites.length === 0 && <p className={styles.error}>{t(lang, 'sites_limit_title')}</p>}

          <div className={styles.fieldRow}>
            <Field label={t(lang, 'sites_field_pv_kwp')} htmlFor="upload-pv-kwp">
              <Input
                id="upload-pv-kwp"
                type="number"
                step="0.1"
                min="0"
                value={fields.pvKwp}
                onChange={(e) => setFields((f) => ({ ...f, pvKwp: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
            <Field label={t(lang, 'sites_field_system_type')} htmlFor="upload-system-type">
              <Select
                id="upload-system-type"
                value={fields.systemType}
                onChange={(e) => setFields((f) => ({ ...f, systemType: e.target.value as SiteFieldsState['systemType'] }))}
                disabled={formDisabled}
              >
                <option value="hybrid">{t(lang, 'system_type_hybrid')}</option>
                <option value="off_grid">{t(lang, 'system_type_off_grid')}</option>
                <option value="grid_zero">{t(lang, 'system_type_grid_zero')}</option>
              </Select>
            </Field>
            <Field label={t(lang, 'sites_field_report_language')} htmlFor="upload-report-language">
              <Select
                id="upload-report-language"
                value={fields.reportLanguage}
                onChange={(e) => setFields((f) => ({ ...f, reportLanguage: e.target.value as 'en' | 'es' }))}
                disabled={formDisabled}
              >
                <option value="en">{t(lang, 'lang_en')}</option>
                <option value="es">{t(lang, 'lang_es')}</option>
              </Select>
            </Field>
          </div>

          <div className={styles.fieldRow}>
            <Field label={t(lang, 'sites_field_battery_nominal')} htmlFor="upload-batt-nominal">
              <Input
                id="upload-batt-nominal"
                type="number"
                step="0.1"
                min="0"
                value={fields.battNominal}
                onChange={(e) => setFields((f) => ({ ...f, battNominal: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
            <Field label={t(lang, 'sites_field_battery_dod')} htmlFor="upload-batt-dod">
              <Input
                id="upload-batt-dod"
                type="number"
                step="1"
                min="0"
                max="100"
                value={fields.battDod}
                onChange={(e) => setFields((f) => ({ ...f, battDod: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
          </div>
          {usableKwh !== null && (
            <p className={styles.caption}>{t(lang, 'sites_field_battery_usable_caption').replace('{value}', usableKwh.toFixed(2))}</p>
          )}

          <p className={styles.sectionCaption}>{t(lang, 'sites_geocode_help')}</p>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'sites_field_latitude')} htmlFor="upload-lat">
              <Input
                id="upload-lat"
                type="number"
                step="0.000001"
                value={fields.latitude}
                onChange={(e) => setFields((f) => ({ ...f, latitude: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
            <Field label={t(lang, 'sites_field_longitude')} htmlFor="upload-lng">
              <Input
                id="upload-lng"
                type="number"
                step="0.000001"
                value={fields.longitude}
                onChange={(e) => setFields((f) => ({ ...f, longitude: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
            <div className={styles.geocodeButtonWrap}>
              <Button type="button" variant="ghost" onClick={handleGeocodeClick} disabled={formDisabled || geocoding}>
                {geocoding ? '…' : t(lang, 'sites_geocode_button')}
              </Button>
            </div>
          </div>
          {geocodeError && <p className={styles.error}>{geocodeError}</p>}

          <div className={styles.fieldRow}>
            <Field label={t(lang, 'sites_field_location')} htmlFor="upload-location">
              <Input
                id="upload-location"
                value={fields.location}
                onChange={(e) => setFields((f) => ({ ...f, location: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
            <Field label={t(lang, 'sites_field_timezone')} htmlFor="upload-timezone">
              <Select
                id="upload-timezone"
                value={fields.timezone}
                onChange={(e) => setFields((f) => ({ ...f, timezone: e.target.value }))}
                disabled={formDisabled}
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t(lang, 'sites_field_country')} htmlFor="upload-country">
              <Select
                id="upload-country"
                value={fields.country}
                onChange={(e) => setFields((f) => ({ ...f, country: e.target.value }))}
                disabled={formDisabled}
              >
                {COUNTRY_CODES.map((code) => (
                  <option key={code} value={code}>
                    {COUNTRIES[code]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <p className={styles.sectionCaption}>{t(lang, 'sites_field_savings_rate_help')}</p>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'sites_field_savings_rate')} htmlFor="upload-savings-rate">
              <Input
                id="upload-savings-rate"
                type="number"
                step="0.0001"
                min="0"
                value={fields.savingsRate}
                onChange={(e) => setFields((f) => ({ ...f, savingsRate: e.target.value }))}
                disabled={formDisabled}
              />
            </Field>
            <Field label={t(lang, 'sites_field_savings_currency')} htmlFor="upload-savings-currency">
              <Select
                id="upload-savings-currency"
                value={fields.savingsCurrency}
                onChange={(e) => setFields((f) => ({ ...f, savingsCurrency: e.target.value }))}
                disabled={formDisabled}
              >
                {SUPPORTED_FLAT_CURRENCIES.map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={fields.exportsToGrid}
              onChange={(e) => setFields((f) => ({ ...f, exportsToGrid: e.target.checked }))}
              disabled={formDisabled}
            />
            {t(lang, 'sites_field_exports_to_grid')}
          </label>

          <div className={styles.fileRow}>
            <Field label={t(lang, 'upload_file_label')} htmlFor="upload-file">
              <input
                ref={fileInputRef}
                id="upload-file"
                type="file"
                accept=".csv"
                className={styles.fileInput}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                disabled={formDisabled}
              />
            </Field>
          </div>
          <p className={styles.caption}>{t(lang, 'upload_file_caption').replace('{limit}', formatBytes(MAX_UPLOAD_BYTES))}</p>

          {errorMessage && phase !== 'preview_ready' && <p className={styles.error}>{errorMessage}</p>}

          {phase === 'form' || phase === 'error' ? (
            <Button type="button" onClick={handleProcessClick} disabled={!file || !siteSelection}>
              {t(lang, 'upload_process_button')}
            </Button>
          ) : null}

          {phase === 'signing' && <p className={styles.status}>{t(lang, 'upload_signing')}</p>}
          {phase === 'uploading' && <p className={styles.status}>{t(lang, 'upload_uploading').replace('{pct}', String(uploadPct))}</p>}
          {phase === 'previewing' && previewJobId && (
            <JobProgress
              jobId={previewJobId}
              runningLabel={t(lang, 'upload_processing')}
              genericFailedLabel={t(lang, 'job_generic_failed')}
              unreachableLabel={t(lang, 'upload_error_unreachable')}
              onDone={handlePreviewJobDone}
              onFailed={handlePreviewJobFailed}
            />
          )}
        </div>
      )}

      {preview && (phase === 'preview_ready' || phase === 'committing') && (
        <div className={styles.panel}>
          <h3>{t(lang, 'upload_summary_title')}</h3>
          <div className={styles.summaryGrid}>
            <div className={styles.summaryStat}>
              <div className={styles.summaryLbl}>{t(lang, 'upload_summary_days')}</div>
              <div className={styles.summaryVal}>{preview.parsed.rows.length}</div>
            </div>
            <div className={styles.summaryStat}>
              <div className={styles.summaryLbl}>{t(lang, 'upload_summary_samples')}</div>
              <div className={styles.summaryVal}>{preview.parsed.sample_count.toLocaleString()}</div>
            </div>
            <div className={styles.summaryStat}>
              <div className={styles.summaryLbl}>{t(lang, 'upload_summary_alarms')}</div>
              <div className={styles.summaryVal}>{preview.parsed.alarm_events.length}</div>
            </div>
            <div className={styles.summaryStat}>
              <div className={styles.summaryLbl}>{t(lang, 'upload_summary_outages')}</div>
              <div className={styles.summaryVal}>{preview.parsed.outages.length}</div>
            </div>
          </div>
          <p className={styles.caption}>
            {t(lang, 'upload_summary_caption')
              .replace('{installationId}', String(preview.parsed.installation_id ?? '—'))
              .replace('{start}', preview.parsed.period_start.slice(0, 10))
              .replace('{end}', preview.parsed.period_end.slice(0, 10))
              .replace('{tz}', preview.parsed.timezone_label)
              .replace('{lang}', t(lang, fields.reportLanguage === 'es' ? 'lang_es' : 'lang_en'))}
          </p>
          <p className={styles.caption}>{savingsCaption(lang, fields, savingsNote)}</p>

          {preview.parsed.warnings.length > 0 && (
            <div className={styles.warnings}>
              <strong>{t(lang, 'upload_warnings_title')}</strong>
              <ul>
                {preview.parsed.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {(() => {
            const partial = preview.parsed.rows.filter((r) => !r.complete_day).length;
            return partial > 0 ? <p className={styles.info}>{t(lang, 'upload_partial_days').replace('{count}', String(partial))}</p> : null;
          })()}

          <div className={styles.tableScroll}>
            <Table>
              <thead>
                <tr>
                  <th>{t(lang, 'upload_table_date')}</th>
                  <th>{t(lang, 'upload_table_pv')}</th>
                  <th>{t(lang, 'upload_table_load')}</th>
                  <th>{t(lang, 'upload_table_grid')}</th>
                  <th>{t(lang, 'upload_table_charge')}</th>
                  <th>{t(lang, 'upload_table_discharge')}</th>
                  <th>{t(lang, 'upload_table_min_soc')}</th>
                  <th>{t(lang, 'upload_table_max_soc')}</th>
                  <th>{t(lang, 'upload_table_outages')}</th>
                  <th>{t(lang, 'upload_table_outage_min')}</th>
                  <th>{t(lang, 'upload_table_complete')}</th>
                </tr>
              </thead>
              <tbody>
                {preview.parsed.rows.map((r) => (
                  <tr key={r.date}>
                    <td>{r.date}</td>
                    <td>{r.pv_kwh}</td>
                    <td>{r.load_kwh}</td>
                    <td>{r.grid_kwh}</td>
                    <td>{r.battery_charge_kwh}</td>
                    <td>{r.battery_discharge_kwh}</td>
                    <td>{r.min_soc ?? '—'}</td>
                    <td>{r.max_soc ?? '—'}</td>
                    <td>{r.outage_count}</td>
                    <td>{r.outage_minutes}</td>
                    <td>{r.complete_day ? '✓' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>

          {errorMessage && <p className={styles.error}>{errorMessage}</p>}

          {phase === 'preview_ready' && (
            <Button type="button" onClick={handleConfirmClick}>
              {t(lang, 'upload_confirm_button')}
            </Button>
          )}
          {phase === 'committing' && commitJobId && (
            <JobProgress
              jobId={commitJobId}
              runningLabel={t(lang, 'upload_importing')}
              genericFailedLabel={t(lang, 'job_generic_failed')}
              unreachableLabel={t(lang, 'upload_error_unreachable')}
              onDone={handleCommitJobDone}
              onFailed={handleCommitJobFailed}
            />
          )}
        </div>
      )}

      {phase === 'done' && commitResult && (
        <div className={styles.panel}>
          <p className={styles.success}>
            {t(lang, 'upload_confirm_success')
              .replace('{rows}', String(commitResult.rows_written))
              .replace('{alarms}', String(commitResult.alarm_events_written))
              .replace('{siteId}', commitResult.site_id)}
          </p>
          <div className={styles.formActions}>
            <Button href="/app">{t(lang, 'upload_confirm_success_cta')}</Button>
            <Button type="button" variant="ghost" onClick={handleStartOver}>
              {t(lang, 'upload_start_over')}
            </Button>
          </div>
        </div>
      )}

      <h2 className={styles.historyTitle}>{t(lang, 'upload_history_title')}</h2>
      {ingestions.length === 0 ? (
        <p className={styles.intro}>{t(lang, 'upload_history_empty')}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>{t(lang, 'upload_history_col_site')}</th>
              <th>{t(lang, 'upload_history_col_file')}</th>
              <th>{t(lang, 'upload_history_col_period')}</th>
              <th>{t(lang, 'upload_history_col_rows')}</th>
              <th>{t(lang, 'upload_history_col_alarms')}</th>
              <th>{t(lang, 'upload_history_col_warnings')}</th>
              <th>{t(lang, 'upload_history_col_date')}</th>
            </tr>
          </thead>
          <tbody>
            {ingestions.map((log) => {
              const site = sites.find((s) => s.site_id === log.site_id);
              const warnings = (log.warnings as { messages?: string[] } | null)?.messages ?? [];
              return (
                <tr key={log.id}>
                  <td>{site?.display_name ?? log.site_id}</td>
                  <td>{log.filename ?? '—'}</td>
                  <td>
                    {log.period_start?.slice(0, 10) ?? '—'} → {log.period_end?.slice(0, 10) ?? '—'}
                  </td>
                  <td>{log.rows_written ?? '—'}</td>
                  <td>{log.alarm_events_written ?? '—'}</td>
                  <td>{warnings.length}</td>
                  <td>{formatDateTime(log.uploaded_at, lang === 'es' ? 'es-CR' : 'en-US')}</td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      )}
    </div>
  );
}

function savingsCaption(lang: Lang, fields: SiteFieldsState, note: string): string {
  if (fields.country === 'CR') {
    return t(lang, 'upload_savings_auto').replace('{note}', note);
  }
  if (fields.savingsRate) {
    return t(lang, 'upload_savings_flat').replace('{rate}', `${fields.savingsCurrency} ${fields.savingsRate}`).replace('{note}', note);
  }
  return t(lang, 'upload_savings_none');
}
