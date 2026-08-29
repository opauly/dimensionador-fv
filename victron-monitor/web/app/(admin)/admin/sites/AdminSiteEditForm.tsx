'use client';

// Cross-customer site edit form for `/admin/sites` (PLAN_PHASE14.md §2
// Step 7) — same field set as `app/(portal)/app/sites/SiteForm.tsx`, minus
// the customer-facing reverse-geocode helper (an admin editing another
// customer's site by hand is an infrequent correction, not the primary
// data-entry path `pages/06_vrm_monitor.py:tab_upload()`'s own geocode
// button optimizes for) — kept intentionally simpler rather than
// duplicating that client-side geocoding flow for a rarely-used surface.
import { useActionState, useEffect, useState } from 'react';
import { Button, Field, Input, Select, Textarea } from '@/components/ui';
import { listTimezones } from '@/lib/timezones';
import { COUNTRIES } from '@/lib/countries';
import { SUPPORTED_FLAT_CURRENCIES } from '@/lib/currencies';
import type { SiteRecord } from '@/lib/server/db';
import { REPORT_MODULE_ICONS } from '@/lib/reportModuleThumbnails';
import { updateAnySiteAction, type AdminSiteFormState } from './actions';
import styles from './sites.module.css';

const TIMEZONES = listTimezones();
const COUNTRY_CODES = Object.keys(COUNTRIES);
// ISO weekday order (1 = Monday), same as `app/(portal)/app/sites/SiteForm.tsx`'s
// own `WEEKDAY_STRING_KEYS` — plain English here since this whole panel is
// (admin views are English-only, see `lib/i18n/strings.ts`'s own header).
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
const MAX_REPORT_RECIPIENTS = 5;
// Same 13 ids `sites.ts:REPORT_MODULES` / `victron/weekly_report.py:
// ALL_MODULES` / migration 029's widened CHECK constraint use, with plain
// English labels — same "restated, not imported" reasoning this file's
// other constants already give. `desc` (2026-08-29, Oscar's own
// instruction) pairs with a static thumbnail icon
// (lib/reportModuleThumbnails.tsx) for the same "preview + description per
// checkbox" this file's customer-facing counterpart (SiteForm.tsx) shows.
const REPORT_MODULES: Array<{ id: string; label: string; desc: string }> = [
  { id: 'energy_mix', label: 'Where your energy came from',
    desc: 'A donut chart showing the split between solar, battery, and grid energy.' },
  { id: 'battery_health', label: 'Battery health',
    desc: 'Full-charge days, lowest charge level, temperature, and voltage range.' },
  { id: 'grid_quality', label: 'Grid quality',
    desc: 'Voltage and frequency stability from the utility grid.' },
  { id: 'events', label: 'Events',
    desc: 'Grid outages and alarm episodes recorded during the period.' },
  { id: 'soc_chart', label: 'Battery charge over time',
    desc: 'Daily high and low battery charge level over the period.' },
  { id: 'solar_performance', label: 'Solar performance',
    desc: 'Actual solar output compared to the theoretical maximum.' },
  { id: 'weather', label: 'Weather',
    desc: 'Local sunshine, rain, and cloud cover for the period.' },
  { id: 'trend', label: '4-week trend',
    desc: 'Health score and solar production trend across the last 4 weeks.' },
  { id: 'savings', label: 'Tariff savings',
    desc: 'Estimated cost avoided by using solar instead of grid power.' },
  { id: 'critical_alerts', label: 'Critical alerts',
    desc: 'DC ripple, cell imbalance, and temperature faults on the battery system.' },
  { id: 'grid_meter_detail', label: 'Grid meter detail',
    desc: 'Per-phase voltage, current, and power factor from a real physical grid meter, where installed.' },
  { id: 'generator_runtime', label: 'Generator runtime',
    desc: 'Hours the backup generator ran during the period.' },
  { id: 'tank_level', label: 'Tank level',
    desc: 'Fuel or water tank capacity, fluid type, and last known status.' },
];
// Same set `victron/weekly_report.py:DEFAULT_MODULES` treats as "no
// customization yet" — the original 9 plus critical_alerts, NOT the 3
// hardware-conditional modules most sites have no hardware for. See
// SiteForm.tsx's own DEFAULT_REPORT_MODULES for the full reasoning.
const DEFAULT_REPORT_MODULES = [
  'energy_mix', 'battery_health', 'grid_quality', 'events',
  'soc_chart', 'solar_performance', 'weather', 'trend', 'savings',
  'critical_alerts',
];
// The report's fixed spine (PLAN_PHASE18.md's Decisions section) — never
// selectable, shown alongside REPORT_MODULES as always-checked/disabled.
const FIXED_MODULE_LABELS = [
  'Summary cards (always included)',
  'AI narrative (always included)',
  'Solar vs. consumption chart (always included)',
];

/** Plain-language summary of a schedule choice, shown before it's saved —
 * same purpose as `SiteForm.tsx`'s own confirmation copy, restated in
 * English here rather than imported since nothing else in this admin panel
 * goes through `t()`. */
function describeSchedule(schedule: string, weekday: number, dayOfMonth: number, hour: number): string {
  if (schedule === 'off') return 'No scheduled reports (paused).';
  const hourLabel = `${String(hour).padStart(2, '0')}:00`;
  if (schedule === 'daily') return `Daily, at ${hourLabel}.`;
  if (schedule === 'weekly') return `Weekly on ${WEEKDAYS[weekday - 1]}, at ${hourLabel}.`;
  return `Monthly on day ${dayOfMonth}, at ${hourLabel}.`;
}

function describeModules(mode: 'default' | 'custom', selected: Set<string>): string {
  if (mode === 'default') return 'Default modules (core sections + critical alerts).';
  if (selected.size === REPORT_MODULES.length) return 'All modules included.';
  if (selected.size === 0) return 'No optional modules — only the core summary.';
  return `${selected.size} of ${REPORT_MODULES.length} modules included.`;
}

export function AdminSiteEditForm({ site, onDone }: { site: SiteRecord; onDone: () => void }) {
  const boundAction = updateAnySiteAction.bind(null, site.site_id);
  const [state, formAction, pending] = useActionState<AdminSiteFormState, FormData>(boundAction, {});

  const [nominal, setNominal] = useState(site.battery_nominal_kwh?.toString() ?? '');
  const [dod, setDod] = useState(site.battery_dod_pct?.toString() ?? '');
  const usableKwh = (() => {
    const n = Number(nominal);
    const d = Number(dod);
    if (!nominal || !dod || !Number.isFinite(n) || !Number.isFinite(d)) return null;
    return Math.round(((n * d) / 100) * 100) / 100;
  })();

  // Only ever a real editor for a `source='vrm_api'` site — same rule
  // `SiteForm.tsx` enforces (client-side UX; `updateAnySite()`'s
  // `AdminScheduleRequiresVrmApi` is the actual control, see that file).
  const [reportSchedule, setReportSchedule] = useState<string>(site.report_schedule);
  const [scheduleWeekday, setScheduleWeekday] = useState(String(site.report_schedule_weekday));
  const [scheduleDayOfMonth, setScheduleDayOfMonth] = useState(String(site.report_schedule_day_of_month));
  const [scheduleHour, setScheduleHour] = useState(String(site.report_schedule_hour));
  const [recipients, setRecipients] = useState((site.report_recipients ?? []).join('\n'));
  const recipientCount = recipients.split('\n').map((s) => s.trim()).filter(Boolean).length;

  // PLAN_PHASE18.md §5/§7. `NULL` in the database means DEFAULT_REPORT_MODULES
  // (the original 9 plus critical_alerts, NOT the 3 hardware-conditional
  // modules) — same initial-state rule `SiteForm.tsx` uses.
  const initialModules = new Set<string>(
    site.report_modules && site.report_modules.length > 0 ? site.report_modules : DEFAULT_REPORT_MODULES,
  );
  const [selectedModules, setSelectedModules] = useState<Set<string>>(initialModules);
  // Default/Custom mode — see SiteForm.tsx's own comment for the full
  // reasoning. Switching to "Default" and saving submits the sentinel with
  // no report_modules values, which sanitizeReportModules() (admin.ts)
  // already turns into `null`.
  const initialModuleMode: 'default' | 'custom' = site.report_modules && site.report_modules.length > 0 ? 'custom' : 'default';
  const [moduleMode, setModuleMode] = useState<'default' | 'custom'>(initialModuleMode);
  function toggleModule(id: string) {
    setSelectedModules((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const modulesChanged =
    moduleMode !== initialModuleMode ||
    (moduleMode === 'custom' &&
      (selectedModules.size !== initialModules.size || [...selectedModules].some((m) => !initialModules.has(m))));

  // A real change to the SCHEDULE itself (cadence/day/hour) — not
  // recipients, not any other field — shows a plain-language summary of
  // what's about to be applied (Oscar's own request: "a prior confirmation
  // message"). Originally gated Save behind a separate "confirm this"
  // click before the button would even work — found confusing in a real
  // live test (2026-08-28) and simplified: the summary is shown, the
  // button is relabeled to say what it's about to do, and clicking it
  // both confirms and saves in one action.
  const scheduleChanged =
    reportSchedule !== site.report_schedule ||
    (reportSchedule === 'weekly' && Number(scheduleWeekday) !== site.report_schedule_weekday) ||
    (reportSchedule === 'monthly' && Number(scheduleDayOfMonth) !== site.report_schedule_day_of_month) ||
    (reportSchedule !== 'off' && Number(scheduleHour) !== site.report_schedule_hour);

  useEffect(() => {
    if (state.success) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onDone intentionally excluded, see SiteForm.tsx's own precedent
  }, [state.success]);

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label="Site name" htmlFor={`as-name-${site.site_id}`} required>
          <Input id={`as-name-${site.site_id}`} name="display_name" defaultValue={site.display_name} required disabled={pending} />
        </Field>
        <Field label="System type" htmlFor={`as-type-${site.site_id}`}>
          <Select id={`as-type-${site.site_id}`} name="system_type" defaultValue={site.system_type} disabled={pending}>
            <option value="hybrid">Hybrid</option>
            <option value="off_grid">Off-grid</option>
            <option value="grid_zero">Grid-tied, no battery</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="PV power (kWp)" htmlFor={`as-kwp-${site.site_id}`}>
          <Input id={`as-kwp-${site.site_id}`} name="pv_kwp" type="number" step="0.1" min="0" defaultValue={site.pv_kwp ?? ''} disabled={pending} />
        </Field>
        <Field label="Report language" htmlFor={`as-lang-${site.site_id}`}>
          <Select id={`as-lang-${site.site_id}`} name="report_language" defaultValue={site.report_language} disabled={pending}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Nominal battery (kWh)" htmlFor={`as-batt-nom-${site.site_id}`}>
          <Input
            id={`as-batt-nom-${site.site_id}`}
            name="battery_nominal_kwh"
            type="number"
            step="0.1"
            min="0"
            value={nominal}
            onChange={(e) => setNominal(e.target.value)}
            disabled={pending}
          />
        </Field>
        <Field label="DoD (%)" htmlFor={`as-batt-dod-${site.site_id}`}>
          <Input
            id={`as-batt-dod-${site.site_id}`}
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
      {usableKwh !== null && <p className={styles.caption}>Usable battery = nominal × DoD/100 = {usableKwh.toFixed(2)} kWh</p>}

      <div className={styles.fieldRow}>
        <Field label="Location" htmlFor={`as-loc-${site.site_id}`}>
          <Input id={`as-loc-${site.site_id}`} name="location" defaultValue={site.location ?? ''} disabled={pending} />
        </Field>
        <Field label="Timezone" htmlFor={`as-tz-${site.site_id}`}>
          <Select id={`as-tz-${site.site_id}`} name="timezone" defaultValue={site.timezone} disabled={pending}>
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Country" htmlFor={`as-country-${site.site_id}`}>
          <Select id={`as-country-${site.site_id}`} name="country" defaultValue={site.country ?? 'CR'} disabled={pending}>
            {COUNTRY_CODES.map((code) => (
              <option key={code} value={code}>
                {COUNTRIES[code]}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Latitude" htmlFor={`as-lat-${site.site_id}`}>
          <Input id={`as-lat-${site.site_id}`} name="latitude" type="number" step="0.000001" defaultValue={site.latitude ?? ''} disabled={pending} />
        </Field>
        <Field label="Longitude" htmlFor={`as-lng-${site.site_id}`}>
          <Input
            id={`as-lng-${site.site_id}`}
            name="longitude"
            type="number"
            step="0.000001"
            defaultValue={site.longitude ?? ''}
            disabled={pending}
          />
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Savings rate (per kWh)" htmlFor={`as-rate-${site.site_id}`}>
          <Input
            id={`as-rate-${site.site_id}`}
            name="savings_rate"
            type="number"
            step="0.0001"
            min="0"
            defaultValue={site.savings_rate ?? ''}
            disabled={pending}
          />
        </Field>
        <Field label="Currency" htmlFor={`as-currency-${site.site_id}`}>
          <Select id={`as-currency-${site.site_id}`} name="savings_currency" defaultValue={site.savings_currency ?? 'USD'} disabled={pending}>
            {SUPPORTED_FLAT_CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {site.source !== 'vrm_api' && (
        <p className={styles.caption}>This site was added by CSV upload, so it has no live connection for a schedule to run against.</p>
      )}
      {site.source === 'vrm_api' && (
        <>
          <div className={styles.fieldRow}>
            <Field label="Report schedule" htmlFor={`as-schedule-${site.site_id}`}>
              <Select
                id={`as-schedule-${site.site_id}`}
                name="report_schedule"
                value={reportSchedule}
                onChange={(e) => setReportSchedule(e.target.value)}
                disabled={pending}
              >
                <option value="off">No schedule (paused)</option>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </Select>
            </Field>
            {reportSchedule === 'weekly' && (
              <Field label="Weekday" htmlFor={`as-weekday-${site.site_id}`}>
                <Select
                  id={`as-weekday-${site.site_id}`}
                  name="report_schedule_weekday"
                  value={scheduleWeekday}
                  onChange={(e) => setScheduleWeekday(e.target.value)}
                  disabled={pending}
                >
                  {WEEKDAYS.map((label, i) => (
                    <option key={label} value={i + 1}>
                      {label}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            {reportSchedule === 'monthly' && (
              <Field label="Day of month" htmlFor={`as-dom-${site.site_id}`}>
                <Input
                  id={`as-dom-${site.site_id}`}
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
              <Field label="Hour" htmlFor={`as-hour-${site.site_id}`}>
                <Select
                  id={`as-hour-${site.site_id}`}
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

          {scheduleChanged && (
            <p className={styles.caption}>
              Review before saving: {describeSchedule(reportSchedule, Number(scheduleWeekday), Number(scheduleDayOfMonth), Number(scheduleHour))}
            </p>
          )}

          <Field label="Report recipients" htmlFor={`as-recipients-${site.site_id}`}>
            <Textarea
              id={`as-recipients-${site.site_id}`}
              name="report_recipients"
              rows={3}
              placeholder="One email per line"
              value={recipients}
              onChange={(e) => setRecipients(e.target.value)}
              disabled={pending}
            />
          </Field>
          <p className={recipientCount > MAX_REPORT_RECIPIENTS ? styles.error : styles.caption}>
            {recipientCount} / {MAX_REPORT_RECIPIENTS} recipients
          </p>

          {/* PLAN_PHASE18.md §5 — untiered on the admin side, unlike the
             customer-facing form (`updateAnySite()`'s `sanitizeReportModules()`
             has no entitlement check, same "admin write path is separate
             and untiered" precedent branding.ts states). Sentinel input is
             still needed here, for the same reason it is on the customer
             side: distinguishing "unchecked everything" from "this section
             never rendered" (a non-vrm_api site). */}
          <input type="hidden" name="report_modules_present" value="true" />
          <p className={styles.moduleCaption}>Report modules — {describeModules(moduleMode, selectedModules)}</p>
          <div className={styles.moduleModeRow}>
            <label className={styles.checkboxLabel}>
              <input type="radio" name="_module_mode" checked={moduleMode === 'default'} onChange={() => setModuleMode('default')} disabled={pending} />
              Default
            </label>
            <label className={styles.checkboxLabel}>
              <input type="radio" name="_module_mode" checked={moduleMode === 'custom'} onChange={() => setModuleMode('custom')} disabled={pending} />
              Custom
            </label>
          </div>
          {moduleMode === 'custom' && (
            <div className={styles.moduleGrid}>
              {/* Always included, never selectable — shown alongside the real
                 checkboxes (checked + greyed out) so it's visually obvious
                 what's fixed vs. optional. No `name`: display only, never
                 submitted. */}
              {FIXED_MODULE_LABELS.map((label) => (
                <label key={label} className={styles.checkboxLabelDisabled}>
                  <input type="checkbox" checked disabled />
                  {label}
                </label>
              ))}
              {REPORT_MODULES.map((m) => (
                <label key={m.id} className={styles.moduleCard}>
                  <div className={styles.moduleCardHeader}>
                    <input
                      type="checkbox"
                      name="report_modules"
                      value={m.id}
                      checked={selectedModules.has(m.id)}
                      onChange={() => toggleModule(m.id)}
                      disabled={pending}
                    />
                    <span className={styles.moduleThumb} aria-hidden="true">{REPORT_MODULE_ICONS[m.id]}</span>
                    <span>{m.label}</span>
                  </div>
                  <p className={styles.moduleDesc}>{m.desc}</p>
                </label>
              ))}
            </div>
          )}
          {modulesChanged && <p className={styles.caption}>Review before saving — {describeModules(moduleMode, selectedModules)}</p>}
        </>
      )}

      <div className={styles.checkboxRow}>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="exports_to_grid" value="true" defaultChecked={site.exports_to_grid} disabled={pending} />
          This system exports energy to the grid
        </label>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="active" value="true" defaultChecked={site.active} disabled={pending} />
          Active
        </label>
      </div>

      {state.error && <p className={styles.error}>{state.error}</p>}

      <div className={styles.formActions}>
        <Button type="submit" disabled={pending}>
          {pending ? 'Saving…' : scheduleChanged || modulesChanged ? 'Confirm & save' : 'Save'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={pending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
