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
import { Button, Field, Input, Select } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import { listTimezones } from '@/lib/timezones';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import { SUPPORTED_FLAT_CURRENCIES } from '@/lib/currencies';
import type { SiteRecord } from '@/lib/server/db';
import { reverseGeocodeAction, type SiteFormState } from './actions';
import styles from './sites.module.css';

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
  onCancel?: () => void;
  onSaved?: () => void;
};

const TIMEZONES = listTimezones();
const COUNTRY_CODES = Object.keys(COUNTRIES);

export function SiteForm({ mode, lang, action, initial, onCancel, onSaved }: SiteFormProps) {
  const [state, formAction, pending] = useActionState(action, {} as SiteFormState);

  const [nominal, setNominal] = useState<string>(initial?.battery_nominal_kwh?.toString() ?? '');
  const [dod, setDod] = useState<string>(initial?.battery_dod_pct?.toString() ?? '');
  const usableKwh = (() => {
    const n = Number(nominal);
    const d = Number(dod);
    if (!nominal || !dod || !Number.isFinite(n) || !Number.isFinite(d)) return null;
    return Math.round(((n * d) / 100) * 100) / 100;
  })();

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
        <Button type="submit" disabled={pending}>
          {pending ? t(lang, 'sites_saving') : t(lang, mode === 'add' ? 'sites_create_button' : 'sites_save_button')}
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
