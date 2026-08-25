'use client';

// "Apply this schedule to all my sites" (PLAN_PHASE17.md §3.7, §2.2 "moment
// 1") — a sibling of `SiteForm.tsx`, not a reuse of it: this writes ONE
// schedule across every active `source='vrm_api'` site at once
// (`applyScheduleToAllSites()`), and — the one thing that makes this a
// separate component rather than a `SiteForm` mode — it shows the Cap B
// projection and REFUSES to let the customer confirm past it, which a
// per-site edit never needs to (§3.7's own design: the bulk action is where
// "moment 1" lives, not the individual site form).
import { startTransition, useEffect, useState } from 'react';
import { Button, Field, Input, Select } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import type { ReportSchedule } from '@/lib/server/db';
import { applyScheduleToAllSitesAction, getBulkScheduleProjectionAction } from './actions';
import styles from './sites.module.css';

export type BulkScheduleFormProps = {
  lang: Lang;
  onCancel: () => void;
  onApplied: (count: number) => void;
};

const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7];
const HOURS = Array.from({ length: 24 }, (_, h) => h);
// Same lookup as `SiteForm.tsx` — see that file's own comment.
const WEEKDAY_STRING_KEYS = [
  'sites_weekday_1', 'sites_weekday_2', 'sites_weekday_3', 'sites_weekday_4',
  'sites_weekday_5', 'sites_weekday_6', 'sites_weekday_7',
] as const;

export function BulkScheduleForm({ lang, onCancel, onApplied }: BulkScheduleFormProps) {
  const [schedule, setSchedule] = useState<ReportSchedule>('daily');
  const [weekday, setWeekday] = useState(1);
  const [dayOfMonth, setDayOfMonth] = useState(1);
  const [hour, setHour] = useState(6);

  const [projection, setProjection] = useState<{ siteCount: number; projectedPerPeriod: number; cap: number; overCap: boolean } | null>(null);
  const [loadingProjection, setLoadingProjection] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  // "Adjusting state when a prop/state change happens" during render, not
  // in the effect body itself — same pattern (and reasoning)
  // `ReportManager.tsx`'s own `trackedSiteId` uses: a synchronous
  // `setState` at the top of an effect body is what `react-hooks/set-state-in-effect`
  // correctly flags, and React's own docs recommend deriving "the old
  // projection is now stale" from a render-time comparison instead.
  const [trackedSchedule, setTrackedSchedule] = useState(schedule);
  if (schedule !== trackedSchedule) {
    setTrackedSchedule(schedule);
    setLoadingProjection(true);
    setProjection(null);
  }

  // Re-fetched every time the chosen cadence changes — the projection
  // depends only on `schedule` (`estimatedReportsPerPeriod()`'s own
  // per-cadence constant) and the customer's own site count/plan, neither
  // of which the weekday/day-of-month/hour choice affects.
  useEffect(() => {
    let cancelled = false;
    getBulkScheduleProjectionAction(schedule).then((result) => {
      if (cancelled) return;
      setLoadingProjection(false);
      if ('error' in result) {
        setError(result.error);
        setProjection(null);
        return;
      }
      setError(null);
      setProjection(result);
    });
    return () => {
      cancelled = true;
    };
  }, [schedule]);

  function handleConfirm() {
    setError(null);
    setApplying(true);
    startTransition(async () => {
      const result = await applyScheduleToAllSitesAction({
        report_schedule: schedule,
        report_schedule_weekday: weekday,
        report_schedule_day_of_month: dayOfMonth,
        report_schedule_hour: hour,
      });
      setApplying(false);
      if ('error' in result) {
        setError(result.error);
        return;
      }
      onApplied(result.count);
    });
  }

  const confirmDisabled = applying || loadingProjection || !projection || projection.siteCount === 0 || projection.overCap;

  return (
    <div className={styles.panel}>
      <h3>{t(lang, 'sites_bulk_apply_title')}</h3>
      <p className={styles.sectionCaption}>{t(lang, 'sites_bulk_apply_intro')}</p>

      <div className={styles.fieldRow}>
        <Field label={t(lang, 'sites_field_report_schedule')} htmlFor="bulk-schedule">
          <Select id="bulk-schedule" value={schedule} onChange={(e) => setSchedule(e.target.value as ReportSchedule)} disabled={applying}>
            <option value="off">{t(lang, 'sites_schedule_off')}</option>
            <option value="daily">{t(lang, 'sites_schedule_daily')}</option>
            <option value="weekly">{t(lang, 'sites_schedule_weekly')}</option>
            <option value="monthly">{t(lang, 'sites_schedule_monthly')}</option>
          </Select>
        </Field>
        {schedule === 'weekly' && (
          <Field label={t(lang, 'sites_field_schedule_weekday')} htmlFor="bulk-weekday">
            <Select id="bulk-weekday" value={weekday} onChange={(e) => setWeekday(Number(e.target.value))} disabled={applying}>
              {WEEKDAYS.map((d) => (
                <option key={d} value={d}>
                  {t(lang, WEEKDAY_STRING_KEYS[d - 1])}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {schedule === 'monthly' && (
          <Field label={t(lang, 'sites_field_schedule_day_of_month')} htmlFor="bulk-day-of-month">
            <Input
              id="bulk-day-of-month"
              type="number"
              min="1"
              max="28"
              value={dayOfMonth}
              onChange={(e) => setDayOfMonth(Number(e.target.value))}
              disabled={applying}
            />
          </Field>
        )}
        {schedule !== 'off' && (
          <Field label={t(lang, 'sites_field_schedule_hour')} htmlFor="bulk-hour">
            <Select id="bulk-hour" value={hour} onChange={(e) => setHour(Number(e.target.value))} disabled={applying}>
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, '0')}:00
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>

      {!loadingProjection && projection && projection.siteCount === 0 && (
        <p className={styles.sectionCaption}>{t(lang, 'sites_bulk_apply_no_sites')}</p>
      )}

      {!loadingProjection && projection && projection.siteCount > 0 && schedule !== 'off' && (
        <p className={projection.overCap ? styles.error : styles.sectionCaption}>
          {t(lang, projection.overCap ? 'sites_bulk_apply_over_cap' : 'sites_bulk_apply_projection')
            .replace('{count}', String(projection.projectedPerPeriod))
            .replace('{sites}', String(projection.siteCount))
            .replace('{cap}', String(projection.cap))}
        </p>
      )}

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.formActions}>
        <Button type="button" onClick={handleConfirm} disabled={confirmDisabled}>
          {applying
            ? t(lang, 'sites_bulk_apply_applying')
            : t(lang, 'sites_bulk_apply_confirm_button').replace('{count}', String(projection?.siteCount ?? 0))}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={applying}>
          {t(lang, 'sites_cancel_button')}
        </Button>
      </div>
    </div>
  );
}
