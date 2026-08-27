'use client';

// Shared edit/add form for `app/(portal)/app/sites` (PLAN_PHASE14.md §2
// Step 4). One component for both modes — `updateSiteAction` and
// `addSiteAction` share the exact same field set (`sites.ts`'s
// `SITE_WHITELIST`), so a second near-duplicate component would just be two
// places for the field list to drift apart.
//
// Client-side only for form interactivity (live battery caption, the
// reverse-geocode button, pending/error display) — every actual write goes
// through the Server Actions in `./actions.ts`, never a client-side
// Supabase call (there is no Supabase import anywhere in this file).
import { startTransition, useActionState, useEffect, useState } from 'react';
import { Button, Field, Input, Select, Textarea } from '@/components/ui';
import { t, type Lang, type StringKey } from '@/lib/i18n/strings';
import { listTimezones } from '@/lib/timezones';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import { SUPPORTED_FLAT_CURRENCIES } from '@/lib/currencies';
import type { SiteRecord } from '@/lib/server/db';
import { reverseGeocodeAction, type SiteFormState } from './actions';
import styles from './sites.module.css';

// A local copy of `sites.ts:REPORT_MODULES` — NOT imported from
// `@/lib/server/db`, same reasoning `MAX_REPORT_RECIPIENTS` below already
// gives (this is a Client Component; that barrel pulls in `server-only`
// modules). Real enforcement is server-side either way
// (`sanitizeReportModules()`), so drifting here would be a display nit.
const REPORT_MODULES = [
  'energy_mix', 'battery_health', 'grid_quality', 'events',
  'soc_chart', 'solar_performance', 'weather', 'trend', 'savings',
] as const;
const MODULE_LABEL_KEYS: Record<(typeof REPORT_MODULES)[number], StringKey> = {
  energy_mix: 'sites_module_energy_mix',
  battery_health: 'sites_module_battery_health',
  grid_quality: 'sites_module_grid_quality',
  events: 'sites_module_events',
  soc_chart: 'sites_module_soc_chart',
  solar_performance: 'sites_module_solar_performance',
  weather: 'sites_module_weather',
  trend: 'sites_module_trend',
  savings: 'sites_module_savings',
};

// React 19's `useActionState` return type — imported this way (rather than
// destructuring the hook itself here) so `page.tsx`'s server-rendered
// wrapper doesn't need to know React's exact action-state shape, just that
// the bound action it hands down matches this signature.
type BoundAction = (prevState: SiteFormState, formData: FormData) => Promise<SiteFormState>;

export type SiteFormProps = {
  mode: 'edit' | 'add';
  lang: Lang;
  action: BoundAction;
  initial?: SiteRecord;
  /** PLAN_PHASE18.md §5 — resolved server-side (`getReportModulesAccess()`)
   * by the Server Component that renders this form; `false` for any
   * customer not Growth/Fleet-installer-entitled hides the section
   * entirely, same "hide the editor is UX, the write path is the control"
   * split `sites.ts:sanitizeReportModules()` enforces independently.
   * Defaults to `false` so the 'add' mode call site (which never shows
   * this section regardless) doesn't need to pass it. */
  moduleSelectionAllowed?: boolean;
  onCancel?: () => void;
  onSaved?: () => void;
};

const TIMEZONES = listTimezones();
const COUNTRY_CODES = Object.keys(COUNTRIES);
// Indexed by (isoWeekday - 1) — a plain template-literal key
// (`sites_weekday_${d}`) doesn't narrow to a `StringKey` union member for
// `t()`, so this is the lookup that keeps the mapping type-safe.
const WEEKDAY_STRING_KEYS = [
  'sites_weekday_1', 'sites_weekday_2', 'sites_weekday_3', 'sites_weekday_4',
  'sites_weekday_5', 'sites_weekday_6', 'sites_weekday_7',
] as const;
// A local copy of `sites.ts:MAX_REPORT_RECIPIENTS` — NOT imported from
// `@/lib/server/db`: this is a Client Component, and importing even a
// plain constant (not just a type) from that barrel pulls its `server-only`
// modules into the client bundle graph, which Next.js correctly refuses to
// build. Same "each file keeps its own copy rather than sharing one" shape
// `sites.ts`'s own whitelist comment already states for a different
// reason; the real enforcement is server-side either way
// (`sanitizeRecipients()`), so this is UX-only and drifting by one digit
// would be a display nit, not a security gap.
const MAX_REPORT_RECIPIENTS = 5;

export function SiteForm({ mode, lang, action, initial, moduleSelectionAllowed = false, onCancel, onSaved }: SiteFormProps) {
  const [state, formAction, pending] = useActionState(action, {} as SiteFormState);

  const [nominal, setNominal] = useState<string>(initial?.battery_nominal_kwh?.toString() ?? '');
  const [dod, setDod] = useState<string>(initial?.battery_dod_pct?.toString() ?? '');
  const usableKwh = (() => {
    const n = Number(nominal);
    const d = Number(dod);
    if (!nominal || !dod || !Number.isFinite(n) || !Number.isFinite(d)) return null;
    return Math.round(((n * d) / 100) * 100) / 100;
  })();

  // PLAN_PHASE17.md §3.7 — only ever rendered as a real editor when editing
  // an EXISTING `source='vrm_api'` site (see the JSX below); `mode='add'`
  // never shows it at all, because `createSite()` only ever creates a
  // `source='csv_upload'` site (§3.1) and would reject a schedule anyway.
  const [reportSchedule, setReportSchedule] = useState<string>(initial?.report_schedule ?? 'off');
  const [scheduleWeekday, setScheduleWeekday] = useState<string>(String(initial?.report_schedule_weekday ?? 1));
  const [scheduleDayOfMonth, setScheduleDayOfMonth] = useState<string>(String(initial?.report_schedule_day_of_month ?? 1));
  const [scheduleHour, setScheduleHour] = useState<string>(String(initial?.report_schedule_hour ?? 6));

  // A real change to the schedule itself (cadence/day/hour) — not
  // recipients, not any other field — requires reviewing the plain-language
  // summary below before Save is allowed to apply it (Oscar's own request:
  // "all with a prior confirmation message"). Any further schedule edit
  // after confirming re-arms this, so a changed mind never saves on a stale
  // confirmation. Never true for `mode === 'add'` — there's no `initial` to
  // have changed away from, and this section never renders there anyway.
  const scheduleChanged =
    mode === 'edit' &&
    Boolean(initial) &&
    (reportSchedule !== (initial?.report_schedule ?? 'off') ||
      (reportSchedule === 'weekly' && Number(scheduleWeekday) !== (initial?.report_schedule_weekday ?? 1)) ||
      (reportSchedule === 'monthly' && Number(scheduleDayOfMonth) !== (initial?.report_schedule_day_of_month ?? 1)) ||
      (reportSchedule !== 'off' && Number(scheduleHour) !== (initial?.report_schedule_hour ?? 6)));
  const [scheduleConfirmed, setScheduleConfirmed] = useState(false);
  const [trackedSchedule, setTrackedSchedule] = useState({ reportSchedule, scheduleWeekday, scheduleDayOfMonth, scheduleHour });
  if (
    reportSchedule !== trackedSchedule.reportSchedule ||
    scheduleWeekday !== trackedSchedule.scheduleWeekday ||
    scheduleDayOfMonth !== trackedSchedule.scheduleDayOfMonth ||
    scheduleHour !== trackedSchedule.scheduleHour
  ) {
    setTrackedSchedule({ reportSchedule, scheduleWeekday, scheduleDayOfMonth, scheduleHour });
    setScheduleConfirmed(false);
  }

  function describeSchedule(): string {
    if (reportSchedule === 'off') return t(lang, 'sites_schedule_off');
    const hourLabel = `${String(scheduleHour).padStart(2, '0')}:00`;
    if (reportSchedule === 'daily') return `${t(lang, 'sites_schedule_daily')} · ${hourLabel}`;
    if (reportSchedule === 'weekly') {
      return `${t(lang, 'sites_schedule_weekly')} · ${t(lang, WEEKDAY_STRING_KEYS[Number(scheduleWeekday) - 1])} · ${hourLabel}`;
    }
    return `${t(lang, 'sites_schedule_monthly')} · ${t(lang, 'sites_field_schedule_day_of_month')} ${scheduleDayOfMonth} · ${hourLabel}`;
  }

  // PLAN_PHASE18.md §5. `NULL` in the database means "every module on" —
  // the initial checkbox state mirrors that exactly rather than starting
  // from an empty set, so an entitled customer opening this form for the
  // first time on an already-existing site sees today's real behavior
  // (everything included), not a blank slate that reads as "nothing sends."
  const initialModules = new Set<string>(initial?.report_modules && initial.report_modules.length > 0 ? initial.report_modules : REPORT_MODULES);
  const [selectedModules, setSelectedModules] = useState<Set<string>>(initialModules);
  function toggleModule(id: string) {
    setSelectedModules((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const modulesChanged =
    mode === 'edit' &&
    Boolean(initial) &&
    (selectedModules.size !== initialModules.size || [...selectedModules].some((m) => !initialModules.has(m)));
  const [modulesConfirmed, setModulesConfirmed] = useState(false);
  const [trackedModules, setTrackedModules] = useState(selectedModules);
  if (selectedModules !== trackedModules && (selectedModules.size !== trackedModules.size || [...selectedModules].some((m) => !trackedModules.has(m)))) {
    setTrackedModules(selectedModules);
    setModulesConfirmed(false);
  }
  function describeModules(): string {
    if (selectedModules.size === REPORT_MODULES.length) return t(lang, 'sites_modules_summary_all');
    if (selectedModules.size === 0) return t(lang, 'sites_modules_summary_none');
    return t(lang, 'sites_modules_summary_count').replace('{count}', String(selectedModules.size));
  }

  // PLAN_PHASE17.md §0.6 Q5 — one recipient per line; `actions.ts`'s
  // `reportRecipientsField` also accepts commas, but a textarea's own
  // Enter-per-line affordance is the more discoverable one to show back.
  const [recipients, setRecipients] = useState<string>((initial?.report_recipients ?? []).join('\n'));
  const recipientCount = recipients.split('\n').map((s) => s.trim()).filter(Boolean).length;

  const [latitude, setLatitude] = useState<string>(initial?.latitude?.toString() ?? '');
  const [longitude, setLongitude] = useState<string>(initial?.longitude?.toString() ?? '');
  const [location, setLocation] = useState<string>(initial?.location ?? '');
  const [country, setCountry] = useState<string>(initial?.country ?? DEFAULT_COUNTRY);
  const [geocodeError, setGeocodeError] = useState<string | null>(null);
  const [geocoding, setGeocoding] = useState(false);

  // Closes the edit panel / clears the add form once the Server Action
  // reports success — the single response that carries both the action's
  // result and the re-rendered `/app/sites` list (Next.js's "a single
  // response carries data and UI") means `state.success` and the refreshed
  // table land in the same round trip, so this fires right after the table
  // itself has already updated.
  useEffect(() => {
    if (state.success) onSaved?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onSaved intentionally excluded: re-running this on every parent re-render would re-fire the callback
  }, [state.success]);

  // `type="button"` already keeps this from submitting the enclosing
  // <form>, so there's no event/preventDefault plumbing needed here — just
  // the same "0,0 means unset, not Null Island" guard
  // `pages/06_vrm_monitor.py`'s own reverse-geocode button uses before
  // calling out to Nominatim.
  function handleGeocodeClick() {
    if (!latitude && !longitude) {
      setGeocodeError(t(lang, 'sites_geocode_missing_coords'));
      return;
    }
    const lat = Number(latitude);
    const lng = Number(longitude);
    setGeocodeError(null);
    startTransition(async () => {
      setGeocoding(true);
      const result = await reverseGeocodeAction(lat, lng);
      setGeocoding(false);
      if ('error' in result) {
        setGeocodeError(result.error);
        return;
      }
      if (result.location) setLocation(result.location);
      if (result.countryCode && COUNTRIES[result.countryCode]) setCountry(result.countryCode);
    });
  }

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label={t(lang, 'sites_field_name')} htmlFor="site-name" required>
          <Input id="site-name" name="display_name" defaultValue={initial?.display_name} required disabled={pending} />
        </Field>
        <Field label={t(lang, 'sites_field_system_type')} htmlFor="site-system-type">
          <Select id="site-system-type" name="system_type" defaultValue={initial?.system_type ?? 'hybrid'} disabled={pending}>
            <option value="hybrid">{t(lang, 'system_type_hybrid')}</option>
            <option value="off_grid">{t(lang, 'system_type_off_grid')}</option>
            <option value="grid_zero">{t(lang, 'system_type_grid_zero')}</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label={t(lang, 'sites_field_pv_kwp')} htmlFor="site-pv-kwp">
          <Input
            id="site-pv-kwp"
            name="pv_kwp"
            type="number"
            step="0.1"
            min="0"
            defaultValue={initial?.pv_kwp ?? ''}
            disabled={pending}
          />
        </Field>
        <Field label={t(lang, 'sites_field_report_language')} htmlFor="site-report-language">
          <Select id="site-report-language" name="report_language" defaultValue={initial?.report_language ?? 'en'} disabled={pending}>
            <option value="en">{t(lang, 'lang_en')}</option>
            <option value="es">{t(lang, 'lang_es')}</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label={t(lang, 'sites_field_battery_nominal')} htmlFor="site-batt-nominal">
          <Input
            id="site-batt-nominal"
            name="battery_nominal_kwh"
            type="number"
            step="0.1"
            min="0"
            value={nominal}
            onChange={(e) => setNominal(e.target.value)}
            disabled={pending}
          />
        </Field>
        <Field label={t(lang, 'sites_field_battery_dod')} htmlFor="site-batt-dod">
          <Input
            id="site-batt-dod"
            name="battery_dod_pct"
            type="number"
            step="1"
            min="0"
            max="100"
            value={dod}
            onChange={(e) => setDod(e.target.value)}
            disabled={pending}
          />
        </Field>
      </div>
      {usableKwh !== null && (
        <p className={styles.caption}>{t(lang, 'sites_field_battery_usable_caption').replace('{value}', usableKwh.toFixed(2))}</p>
      )}

      <p className={styles.sectionCaption}>{t(lang, 'sites_geocode_help')}</p>
      <div className={styles.fieldRow}>
        <Field label={t(lang, 'sites_field_latitude')} htmlFor="site-lat">
          <Input
            id="site-lat"
            name="latitude"
            type="number"
            step="0.000001"
            value={latitude}
            onChange={(e) => setLatitude(e.target.value)}
            disabled={pending}
          />
        </Field>
        <Field label={t(lang, 'sites_field_longitude')} htmlFor="site-lng">
          <Input
            id="site-lng"
            name="longitude"
            type="number"
            step="0.000001"
            value={longitude}
            onChange={(e) => setLongitude(e.target.value)}
            disabled={pending}
          />
        </Field>
        <div className={styles.geocodeButtonWrap}>
          <Button type="button" variant="ghost" onClick={handleGeocodeClick} disabled={pending || geocoding}>
            {geocoding ? '…' : t(lang, 'sites_geocode_button')}
          </Button>
        </div>
      </div>
      {geocodeError && <p className={styles.error}>{geocodeError}</p>}

      <div className={styles.fieldRow}>
        <Field label={t(lang, 'sites_field_location')} htmlFor="site-location">
          <Input id="site-location" name="location" value={location} onChange={(e) => setLocation(e.target.value)} disabled={pending} />
        </Field>
        <Field label={t(lang, 'sites_field_timezone')} htmlFor="site-timezone">
          <Select id="site-timezone" name="timezone" defaultValue={initial?.timezone ?? 'America/Costa_Rica'} disabled={pending}>
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t(lang, 'sites_field_country')} htmlFor="site-country">
          <Select id="site-country" name="country" value={country} onChange={(e) => setCountry(e.target.value)} disabled={pending}>
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
        <Field label={t(lang, 'sites_field_savings_rate')} htmlFor="site-savings-rate">
          <Input
            id="site-savings-rate"
            name="savings_rate"
            type="number"
            step="0.0001"
            min="0"
            defaultValue={initial?.savings_rate ?? ''}
            disabled={pending}
          />
        </Field>
        <Field label={t(lang, 'sites_field_savings_currency')} htmlFor="site-savings-currency">
          <Select id="site-savings-currency" name="savings_currency" defaultValue={initial?.savings_currency ?? 'USD'} disabled={pending}>
            {SUPPORTED_FLAT_CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {/* PLAN_PHASE17.md §3.7 — only for an EXISTING site (mode='edit');
         `mode='add'` never shows this, since `createSite()` only ever
         creates `source='csv_upload'` sites (§3.1) and would reject a
         schedule write regardless. For a csv_upload site, one sentence
         instead of a disabled control — "hiding an editor is UX, never a
         control," but a disabled control that explains nothing invites a
         support email a plain sentence naming the actual next action
         doesn't (§3.7's own reasoning). */}
      {mode === 'edit' && initial && initial.source !== 'vrm_api' && (
        <p className={styles.sectionCaption}>{t(lang, 'sites_schedule_csv_notice')}</p>
      )}
      {mode === 'edit' && initial && initial.source === 'vrm_api' && (
        <>
          <div className={styles.fieldRow}>
            <Field label={t(lang, 'sites_field_report_schedule')} htmlFor="site-report-schedule">
              <Select
                id="site-report-schedule"
                name="report_schedule"
                value={reportSchedule}
                onChange={(e) => setReportSchedule(e.target.value)}
                disabled={pending}
              >
                <option value="off">{t(lang, 'sites_schedule_off')}</option>
                <option value="daily">{t(lang, 'sites_schedule_daily')}</option>
                <option value="weekly">{t(lang, 'sites_schedule_weekly')}</option>
                <option value="monthly">{t(lang, 'sites_schedule_monthly')}</option>
              </Select>
            </Field>
            {reportSchedule === 'weekly' && (
              <Field label={t(lang, 'sites_field_schedule_weekday')} htmlFor="site-schedule-weekday">
                <Select
                  id="site-schedule-weekday"
                  name="report_schedule_weekday"
                  value={scheduleWeekday}
                  onChange={(e) => setScheduleWeekday(e.target.value)}
                  disabled={pending}
                >
                  {[1, 2, 3, 4, 5, 6, 7].map((d) => (
                    <option key={d} value={d}>
                      {t(lang, WEEKDAY_STRING_KEYS[d - 1])}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            {reportSchedule === 'monthly' && (
              <Field label={t(lang, 'sites_field_schedule_day_of_month')} htmlFor="site-schedule-day-of-month">
                <Input
                  id="site-schedule-day-of-month"
                  name="report_schedule_day_of_month"
                  type="number"
                  min="1"
                  max="28"
                  value={scheduleDayOfMonth}
                  onChange={(e) => setScheduleDayOfMonth(e.target.value)}
                  disabled={pending}
                />
              </Field>
            )}
            {reportSchedule !== 'off' && (
              <Field label={t(lang, 'sites_field_schedule_hour')} htmlFor="site-schedule-hour">
                <Select
                  id="site-schedule-hour"
                  name="report_schedule_hour"
                  value={scheduleHour}
                  onChange={(e) => setScheduleHour(e.target.value)}
                  disabled={pending}
                >
                  {Array.from({ length: 24 }, (_, h) => (
                    <option key={h} value={h}>
                      {String(h).padStart(2, '0')}:00
                    </option>
                  ))}
                </Select>
              </Field>
            )}
          </div>
          {reportSchedule !== 'off' && <p className={styles.sectionCaption}>{t(lang, 'sites_schedule_help')}</p>}

          {scheduleChanged && (
            <p className={scheduleConfirmed ? styles.sectionCaption : styles.error}>
              {t(lang, scheduleConfirmed ? 'sites_schedule_confirmed_notice' : 'sites_schedule_review_notice')} {describeSchedule()}
              {!scheduleConfirmed && (
                <>
                  {' '}
                  <button type="button" className={styles.linkButton} onClick={() => setScheduleConfirmed(true)}>
                    {t(lang, 'sites_schedule_confirm_link')}
                  </button>
                </>
              )}
            </p>
          )}

          <Field label={t(lang, 'sites_field_report_recipients')} htmlFor="site-report-recipients">
            <Textarea
              id="site-report-recipients"
              name="report_recipients"
              rows={3}
              placeholder={t(lang, 'sites_field_report_recipients_placeholder')}
              value={recipients}
              onChange={(e) => setRecipients(e.target.value)}
              disabled={pending}
            />
          </Field>
          <p className={recipientCount > MAX_REPORT_RECIPIENTS ? styles.error : styles.sectionCaption}>
            {t(lang, 'sites_field_report_recipients_help').replace('{max}', String(MAX_REPORT_RECIPIENTS)).replace('{count}', String(recipientCount))}
          </p>
        </>
      )}

      {/* PLAN_PHASE18.md §5 — only for an EXISTING source='vrm_api' site (same
         gate the schedule section above uses), AND only when the server
         already resolved this customer as entitled. A non-entitled customer
         never sees this section at all — the write path independently
         ignores a tampered submission regardless (`sanitizeReportModules()`). */}
      {mode === 'edit' && initial && initial.source === 'vrm_api' && moduleSelectionAllowed && (
        <>
          <h3 className={styles.subheading}>{t(lang, 'sites_modules_title')}</h3>
          <p className={styles.sectionCaption}>{t(lang, 'sites_modules_intro')}</p>
          {/* Distinguishes "this section rendered and the customer
             unchecked every box" (a real, valid choice — zero optional
             modules) from "this section never rendered at all" (report_modules
             absent from FormData either way) — `actions.ts`'s parseSiteForm()
             checks for this key's presence before including report_modules
             in the parsed object at all, so a submission from a form that
             never showed this section can never overwrite an existing
             selection with an empty one. */}
          <input type="hidden" name="report_modules_present" value="true" />
          <div className={styles.moduleGrid}>
            {REPORT_MODULES.map((id) => (
              <label key={id} className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  name="report_modules"
                  value={id}
                  checked={selectedModules.has(id)}
                  onChange={() => toggleModule(id)}
                  disabled={pending}
                />
                {t(lang, MODULE_LABEL_KEYS[id])}
              </label>
            ))}
          </div>

          {modulesChanged && (
            <p className={modulesConfirmed ? styles.sectionCaption : styles.error}>
              {t(lang, modulesConfirmed ? 'sites_modules_confirmed_notice' : 'sites_modules_review_notice')} {describeModules()}
              {!modulesConfirmed && (
                <>
                  {' '}
                  <button type="button" className={styles.linkButton} onClick={() => setModulesConfirmed(true)}>
                    {t(lang, 'sites_modules_confirm_link')}
                  </button>
                </>
              )}
            </p>
          )}
        </>
      )}

      <div className={styles.checkboxRow}>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="exports_to_grid" value="true" defaultChecked={initial?.exports_to_grid ?? false} disabled={pending} />
          {t(lang, 'sites_field_exports_to_grid')}
        </label>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="active" value="true" defaultChecked={initial?.active ?? true} disabled={pending} />
          {t(lang, 'sites_field_active')}
        </label>
      </div>

      {state.error && <p className={styles.error}>{state.error}</p>}

      <div className={styles.formActions}>
        <Button
          type="submit"
          disabled={pending || (scheduleChanged && !scheduleConfirmed) || (modulesChanged && !modulesConfirmed)}
        >
          {pending
            ? t(lang, 'sites_saving')
            : t(
                lang,
                scheduleChanged
                  ? 'sites_schedule_confirm_save_button'
                  : modulesChanged
                    ? 'sites_modules_confirm_save_button'
                    : mode === 'add'
                      ? 'sites_create_button'
                      : 'sites_save_button',
              )}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
            {t(lang, 'sites_cancel_button')}
          </Button>
        )}
      </div>
    </form>
  );
}
