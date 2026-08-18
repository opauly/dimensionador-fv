'use client';

// Cross-customer site edit form for `/admin/sites` (PLAN_PHASE14.md §2
// Step 7) — same field set as `app/(portal)/app/sites/SiteForm.tsx`, minus
// the customer-facing reverse-geocode helper (an admin editing another
// customer's site by hand is an infrequent correction, not the primary
// data-entry path `pages/06_vrm_monitor.py:tab_upload()`'s own geocode
// button optimizes for) — kept intentionally simpler rather than
// duplicating that client-side geocoding flow for a rarely-used surface.
import { useActionState, useEffect, useState } from 'react';
import { Button, Field, Input, Select } from '@/components/ui';
import { listTimezones } from '@/lib/timezones';
import { COUNTRIES } from '@/lib/countries';
import { SUPPORTED_FLAT_CURRENCIES } from '@/lib/currencies';
import type { SiteRecord } from '@/lib/server/db';
import { updateAnySiteAction, type AdminSiteFormState } from './actions';
import styles from './sites.module.css';

const TIMEZONES = listTimezones();
const COUNTRY_CODES = Object.keys(COUNTRIES);

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

  useEffect(() => {
    if (state.success) onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onDone intentionally excluded, see SiteForm.tsx's own precedent
  }, [state.success]);

  return (
    <form action={formAction} className={styles.form}>
      <div className={styles.fieldRow}>
        <Field label="Nombre del sitio" htmlFor={`as-name-${site.site_id}`} required>
          <Input id={`as-name-${site.site_id}`} name="display_name" defaultValue={site.display_name} required disabled={pending} />
        </Field>
        <Field label="Tipo de sistema" htmlFor={`as-type-${site.site_id}`}>
          <Select id={`as-type-${site.site_id}`} name="system_type" defaultValue={site.system_type} disabled={pending}>
            <option value="hybrid">Híbrido</option>
            <option value="off_grid">Off-grid</option>
            <option value="grid_zero">Conectado a red, sin batería</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Potencia FV (kWp)" htmlFor={`as-kwp-${site.site_id}`}>
          <Input id={`as-kwp-${site.site_id}`} name="pv_kwp" type="number" step="0.1" min="0" defaultValue={site.pv_kwp ?? ''} disabled={pending} />
        </Field>
        <Field label="Idioma del reporte" htmlFor={`as-lang-${site.site_id}`}>
          <Select id={`as-lang-${site.site_id}`} name="report_language" defaultValue={site.report_language} disabled={pending}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
      </div>

      <div className={styles.fieldRow}>
        <Field label="Batería nominal (kWh)" htmlFor={`as-batt-nom-${site.site_id}`}>
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
      {usableKwh !== null && <p className={styles.caption}>Batería utilizable = nominal × DoD/100 = {usableKwh.toFixed(2)} kWh</p>}

      <div className={styles.fieldRow}>
        <Field label="Ubicación" htmlFor={`as-loc-${site.site_id}`}>
          <Input id={`as-loc-${site.site_id}`} name="location" defaultValue={site.location ?? ''} disabled={pending} />
        </Field>
        <Field label="Zona horaria" htmlFor={`as-tz-${site.site_id}`}>
          <Select id={`as-tz-${site.site_id}`} name="timezone" defaultValue={site.timezone} disabled={pending}>
            {TIMEZONES.map((tz) => (
              <option key={tz} value={tz}>
                {tz}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="País" htmlFor={`as-country-${site.site_id}`}>
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
        <Field label="Latitud" htmlFor={`as-lat-${site.site_id}`}>
          <Input id={`as-lat-${site.site_id}`} name="latitude" type="number" step="0.000001" defaultValue={site.latitude ?? ''} disabled={pending} />
        </Field>
        <Field label="Longitud" htmlFor={`as-lng-${site.site_id}`}>
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
        <Field label="Tarifa de ahorro (por kWh)" htmlFor={`as-rate-${site.site_id}`}>
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
        <Field label="Moneda" htmlFor={`as-currency-${site.site_id}`}>
          <Select id={`as-currency-${site.site_id}`} name="savings_currency" defaultValue={site.savings_currency ?? 'USD'} disabled={pending}>
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
          <input type="checkbox" name="exports_to_grid" value="true" defaultChecked={site.exports_to_grid} disabled={pending} />
          Este sistema exporta energía a la red
        </label>
        <label className={styles.checkboxLabel}>
          <input type="checkbox" name="active" value="true" defaultChecked={site.active} disabled={pending} />
          Activo
        </label>
      </div>

      {state.error && <p className={styles.error}>{state.error}</p>}

      <div className={styles.formActions}>
        <Button type="submit" disabled={pending}>
          {pending ? 'Guardando…' : 'Guardar'}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone} disabled={pending}>
          Cancelar
        </Button>
      </div>
    </form>
  );
}
