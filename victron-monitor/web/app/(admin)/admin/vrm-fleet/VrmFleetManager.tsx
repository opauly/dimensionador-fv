'use client';

// Admin VRM fleet flow (PLAN_PHASE15.md §3.3 / §8 Step 4b) — Oscar's own
// VRM install base, browsed live and linked/synced onto any customer's
// site, the API-era equivalent of `/admin/upload`'s "upload a CSV on their
// behalf." Copy is English, inline (admin views went English-only
// 2026-08-19 — `admin/layout.tsx`'s own comment). Same "pick from a live
// list, then the same preview/import job shape `/admin/upload` already
// has" interaction as that page, adapted for "pick from a live list"
// instead of "upload a file."
//
// Bug-fix pass 2026-08-18 (Bug 1): this form used to collect ONLY a
// customer + a site name — no `system_type`/coordinates/`pv_kwp`/battery
// fields at all, which is what let a real link (installation 156868,
// "Proyecto KM Ukiyo") get created with `system_type` silently defaulting
// to 'hybrid' and every location/battery field NULL, producing a live bad
// report. The `SiteFieldsState`/`emptyFields()`/`buildSiteFields()` trio
// below is the same `SiteFieldsIn`-shaped form `AdminUploadManager.tsx`
// already has — restated here (not shared as a component) because the two
// forms sit in genuinely different flows (upload-a-file vs. pick-from-a-
// live-list) with only the site-fields portion in common; see that file for
// the form this one is deliberately kept in parity with.
import { Fragment, startTransition, useEffect, useState } from 'react';
import { Button, Field, Input, Select, Table } from '@/components/ui';
import { JobProgress, type JobProgressJob } from '@/components/app';
import { COUNTRIES, DEFAULT_COUNTRY } from '@/lib/countries';
import { SUPPORTED_FLAT_CURRENCIES } from '@/lib/currencies';
import { listTimezones, DEFAULT_TIMEZONE } from '@/lib/timezones';
import { formatDateTime } from '@/lib/dates';
import type { SiteRecord } from '@/lib/server/db';
import type { AdminCustomerRow } from '@/lib/server/db/admin';
import type { VrmFleetInstallation } from '@/lib/server/pipeline';
import { listCustomerSitesAction, listVrmFleetInstallationsAction } from './actions';
import styles from './vrm-fleet.module.css';

const NEW_SITE_VALUE = '__new__';

type CustomerMode = 'existing' | 'new';

// Same shape as `AdminUploadManager.tsx`'s `SiteFieldsState`, minus
// `displayName` — this form already has a name field (`newSiteName` /
// the existing-site picker below), so there is no second "name" input to
// duplicate.
type SiteFieldsState = {
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

type LinkFormState = {
  customerMode: CustomerMode;
  customerId: string;
  newCustomerName: string;
  siteSelection: string; // an existing site_id, or NEW_SITE_VALUE
  newSiteName: string;
  siteFields: SiteFieldsState;
};

type SyncWindow = { start: string; end: string };

function emptySiteFields(): SiteFieldsState {
  return {
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

/** PLAN_PHASE15.md bug-fix pass, Bug 1's "genuinely useful pre-fill" —
 * `installation.suggested_fields`, sourced from a matching `monitoring.sites`
 * row (`vrm_api/routers/vrm_fleet.py:_monitoring_suggestions_by_installation()`),
 * copied into the form's initial state. `null`/missing fields fall back to
 * `emptySiteFields()`'s own defaults — this is ALWAYS just a starting point;
 * every field stays fully editable, and nothing here is sent anywhere until
 * the admin clicks Link. */
function fieldsFromSuggestion(suggested: VrmFleetInstallation['suggested_fields']): SiteFieldsState {
  const base = emptySiteFields();
  if (!suggested) return base;
  return {
    ...base,
    pvKwp: suggested.pv_kwp != null ? String(suggested.pv_kwp) : base.pvKwp,
    battNominal: suggested.battery_nominal_kwh != null ? String(suggested.battery_nominal_kwh) : base.battNominal,
    battDod: suggested.battery_dod_pct != null ? String(suggested.battery_dod_pct) : base.battDod,
    systemType: suggested.system_type ?? base.systemType,
    reportLanguage: suggested.report_language ?? base.reportLanguage,
    latitude: suggested.latitude != null ? String(suggested.latitude) : base.latitude,
    longitude: suggested.longitude != null ? String(suggested.longitude) : base.longitude,
    location: suggested.location ?? base.location,
    timezone: suggested.timezone ?? base.timezone,
  };
}

function toNumberOrNull(s: string): number | null {
  if (s.trim() === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Wire shape sent to `POST /api/admin/pipeline/vrm-fleet/link`'s
 * `siteFields` — same field set `AdminUploadManager.tsx:buildSiteFields()`
 * sends, minus `display_name` (see `SiteFieldsState`'s own comment). */
function buildSiteFields(fields: SiteFieldsState) {
  return {
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

// PLAN_PHASE15.md §6.2's own default range ("from MAX(date) already present
// ... or now - backfill_window on first sync ... through yesterday") and
// §0.5 Q4's 31-day backfill ceiling — this manual admin tool has no
// per-site MAX(date) to read client-side, so it always offers the same
// "yesterday back 31 days" starting point; the operator can widen or narrow
// it before clicking Sync.
function defaultSyncWindow(): SyncWindow {
  const end = new Date();
  end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 30);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

type SyncResult = { rows_written: number; alarm_events_written: number; days_replacing_csv: number };

const TIMEZONES = listTimezones();
const COUNTRY_CODES = Object.keys(COUNTRIES);

export function VrmFleetManager({ customers }: { customers: AdminCustomerRow[] }) {
  const [installations, setInstallations] = useState<VrmFleetInstallation[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [linkFormFor, setLinkFormFor] = useState<number | null>(null);
  const [linkForms, setLinkForms] = useState<Record<number, LinkFormState>>({});
  const [customerSites, setCustomerSites] = useState<Record<string, SiteRecord[]>>({});
  const [linkBusy, setLinkBusy] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);

  const [syncFormFor, setSyncFormFor] = useState<string | null>(null);
  const [syncWindows, setSyncWindows] = useState<Record<string, SyncWindow>>({});
  const [syncJobBySite, setSyncJobBySite] = useState<Record<string, string>>({});
  const [syncBusy, setSyncBusy] = useState<Record<string, boolean>>({});
  const [syncError, setSyncError] = useState<Record<string, string>>({});
  const [syncResult, setSyncResult] = useState<Record<string, SyncResult>>({});

  // No synchronous `setLoading(true)`/`setLoadError(null)` before
  // `startTransition` here — `refresh()` is called from BOTH the mount
  // effect below and several event handlers, and `react-hooks/set-state-in-effect`
  // flags any setState reachable synchronously from an effect's call graph
  // (`JobProgress.tsx`'s own comment on this same rule applies here too:
  // "a setState call unconditionally at the top of an effect body"). `loading`
  // starts `true` via `useState(true)` below, so the first render already
  // shows the loading state without needing to set it again here; every
  // setState in this function happens inside the async callback, after the
  // effect's own synchronous body has already finished running.
  function refresh() {
    startTransition(async () => {
      try {
        const data = await listVrmFleetInstallationsAction();
        setInstallations(data);
        setLoadError(null);
      } catch {
        // The env var's literal NAME is deliberately never spelled out in
        // this client-rendered string, even though it isn't the secret
        // itself — this component ships to the browser (`'use client'`),
        // and there is no reason a browser-visible string needs to name a
        // server-only credential's env var at all.
        setLoadError('Could not load the VRM fleet. Check the VRM token configuration on the server and try again.');
      }
      setLoading(false);
    });
  }

  useEffect(() => {
    refresh();
    // Runs once on mount — refresh() itself is stable enough for this
    // page's purposes (same "load once, re-call explicitly after a
    // mutation" shape `AdminUploadManager.tsx`'s own effects use).
  }, []);

  function toggleLinkForm(idSite: number, suggestedName: string, suggestedFields: VrmFleetInstallation['suggested_fields']) {
    setLinkError(null);
    if (linkFormFor === idSite) {
      setLinkFormFor(null);
      return;
    }
    setLinkFormFor(idSite);
    if (!linkForms[idSite]) {
      setLinkForms((f) => ({
        ...f,
        [idSite]: {
          customerMode: 'existing',
          customerId: customers[0]?.id ?? '',
          newCustomerName: '',
          siteSelection: NEW_SITE_VALUE,
          newSiteName: suggestedName,
          siteFields: fieldsFromSuggestion(suggestedFields),
        },
      }));
      if (customers[0]?.id) handleCustomerSelect(customers[0].id);
    }
  }

  function updateLinkForm(idSite: number, patch: Partial<LinkFormState>) {
    setLinkForms((f) => ({ ...f, [idSite]: { ...f[idSite], ...patch } }));
  }

  function updateSiteFields(idSite: number, patch: Partial<SiteFieldsState>) {
    setLinkForms((f) => ({ ...f, [idSite]: { ...f[idSite], siteFields: { ...f[idSite].siteFields, ...patch } } }));
  }

  function handleCustomerSelect(customerId: string) {
    if (!customerId || customerSites[customerId]) return;
    startTransition(async () => {
      const sites = await listCustomerSitesAction(customerId);
      setCustomerSites((s) => ({ ...s, [customerId]: sites }));
    });
  }

  async function handleLinkSubmit(idSite: number) {
    const form = linkForms[idSite];
    if (!form) return;

    const siteNameOrId =
      form.customerMode === 'existing' && form.siteSelection !== NEW_SITE_VALUE ? form.siteSelection : form.newSiteName.trim();

    if (form.customerMode === 'new' && !form.newCustomerName.trim()) {
      setLinkError('Enter the new customer name.');
      return;
    }
    if (!siteNameOrId) {
      setLinkError('Enter the site name.');
      return;
    }

    setLinkBusy(true);
    setLinkError(null);
    try {
      const res = await fetch('/api/admin/pipeline/vrm-fleet/link', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...(form.customerMode === 'existing'
            ? { vrmInstallationId: idSite, customerId: form.customerId, siteNameOrId }
            : { vrmInstallationId: idSite, newCustomerName: form.newCustomerName.trim(), siteNameOrId }),
          siteFields: buildSiteFields(form.siteFields),
        }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        setLinkError(
          body?.error === 'installation_already_linked_to_customer'
            ? 'That installation is already linked to that customer.'
            : body?.error === 'exactly_one_customer_field_required'
              ? 'Choose an existing customer or type the name of a new one, not both.'
              : 'Could not link. Please try again.',
        );
        return;
      }
      setLinkFormFor(null);
      refresh();
    } catch {
      setLinkError('Could not reach the linking service.');
    } finally {
      setLinkBusy(false);
    }
  }

  function toggleSyncForm(siteId: string) {
    setSyncError((e) => ({ ...e, [siteId]: '' }));
    if (syncFormFor === siteId) {
      setSyncFormFor(null);
      return;
    }
    setSyncFormFor(siteId);
    if (!syncWindows[siteId]) setSyncWindows((w) => ({ ...w, [siteId]: defaultSyncWindow() }));
  }

  async function handleSync(siteId: string) {
    const win = syncWindows[siteId] ?? defaultSyncWindow();
    setSyncBusy((b) => ({ ...b, [siteId]: true }));
    setSyncError((e) => ({ ...e, [siteId]: '' }));
    setSyncResult((r) => {
      const next = { ...r };
      delete next[siteId];
      return next;
    });
    try {
      const res = await fetch('/api/admin/pipeline/vrm-fleet/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ siteId, start: win.start, end: win.end }),
      });
      if (!res.ok) {
        setSyncError((e) => ({ ...e, [siteId]: 'Could not start the sync.' }));
        setSyncBusy((b) => ({ ...b, [siteId]: false }));
        return;
      }
      const { job_id } = (await res.json()) as { job_id: string };
      setSyncJobBySite((j) => ({ ...j, [siteId]: job_id }));
    } catch {
      setSyncError((e) => ({ ...e, [siteId]: 'Could not reach the sync service.' }));
      setSyncBusy((b) => ({ ...b, [siteId]: false }));
    }
  }

  function clearSyncJob(siteId: string) {
    setSyncJobBySite((j) => {
      const next = { ...j };
      delete next[siteId];
      return next;
    });
    setSyncBusy((b) => ({ ...b, [siteId]: false }));
  }

  function handleSyncJobDone(siteId: string, job: JobProgressJob) {
    const result = job.result as Partial<SyncResult> | null;
    setSyncResult((r) => ({
      ...r,
      [siteId]: {
        rows_written: result?.rows_written ?? 0,
        alarm_events_written: result?.alarm_events_written ?? 0,
        days_replacing_csv: result?.days_replacing_csv ?? 0,
      },
    }));
    clearSyncJob(siteId);
    refresh();
  }

  function handleSyncJobFailed(siteId: string, message: string) {
    setSyncError((e) => ({ ...e, [siteId]: message }));
    clearSyncJob(siteId);
  }

  if (loading && !installations) return <p className={styles.status}>Loading fleet…</p>;
  if (loadError) return <p className={styles.error}>{loadError}</p>;
  if (!installations) return null;

  return (
    <div>
      <Table>
        <thead>
          <tr>
            <th>Installation</th>
            <th>idSite</th>
            <th>Linked to</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {installations.map((inst) => {
            const form = linkForms[inst.id_site];
            return (
              <Fragment key={inst.id_site}>
                <tr>
                  <td>
                    {inst.name ?? '—'}
                    {inst.identifier && <div className={styles.linkMeta}>{inst.identifier}</div>}
                  </td>
                  <td className="mono">{inst.id_site}</td>
                  <td>
                    {inst.links.length === 0 ? (
                      <span className={styles.statusUnlinked}>Not linked</span>
                    ) : (
                      <div className={styles.linksList}>
                        {inst.links.map((link) => (
                          <div key={link.site_id} className={styles.linkChip}>
                            <span className={styles.statusLinked}>{link.customer_name ?? link.customer_id}</span>
                            <span>→ {link.site_display_name}</span>
                            <Button type="button" variant="ghost" onClick={() => toggleSyncForm(link.site_id)}>
                              Sync
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => toggleLinkForm(inst.id_site, inst.name ?? `Installation ${inst.id_site}`, inst.suggested_fields)}
                    >
                      {inst.links.length === 0 ? 'Link' : 'Link to another customer'}
                    </Button>
                  </td>
                </tr>

                {linkFormFor === inst.id_site && form && (
                  <tr>
                    <td colSpan={4} className={styles.editRow}>
                      <div className={styles.radioRow}>
                        <label className={styles.radioLabel}>
                          <input
                            type="radio"
                            checked={form.customerMode === 'existing'}
                            onChange={() => updateLinkForm(inst.id_site, { customerMode: 'existing' })}
                          />
                          Existing customer
                        </label>
                        <label className={styles.radioLabel}>
                          <input
                            type="radio"
                            checked={form.customerMode === 'new'}
                            onChange={() => updateLinkForm(inst.id_site, { customerMode: 'new' })}
                          />
                          New customer
                        </label>
                      </div>

                      {form.customerMode === 'existing' ? (
                        <div className={styles.fieldRow}>
                          <Field label="Customer" htmlFor={`vrm-fleet-cust-${inst.id_site}`}>
                            <Select
                              id={`vrm-fleet-cust-${inst.id_site}`}
                              value={form.customerId}
                              onChange={(e) => {
                                updateLinkForm(inst.id_site, { customerId: e.target.value, siteSelection: NEW_SITE_VALUE });
                                handleCustomerSelect(e.target.value);
                              }}
                            >
                              {customers.map((c) => (
                                <option key={c.id} value={c.id}>
                                  {c.name}
                                </option>
                              ))}
                            </Select>
                          </Field>
                          <Field label="Site" htmlFor={`vrm-fleet-site-${inst.id_site}`}>
                            <Select
                              id={`vrm-fleet-site-${inst.id_site}`}
                              value={form.siteSelection}
                              onChange={(e) => updateLinkForm(inst.id_site, { siteSelection: e.target.value })}
                            >
                              {(customerSites[form.customerId] ?? []).map((s) => (
                                <option key={s.site_id} value={s.site_id}>
                                  {s.display_name}
                                </option>
                              ))}
                              <option value={NEW_SITE_VALUE}>New site…</option>
                            </Select>
                          </Field>
                          {form.siteSelection === NEW_SITE_VALUE && (
                            <Field label="New site name" htmlFor={`vrm-fleet-newsite-${inst.id_site}`} required>
                              <Input
                                id={`vrm-fleet-newsite-${inst.id_site}`}
                                value={form.newSiteName}
                                onChange={(e) => updateLinkForm(inst.id_site, { newSiteName: e.target.value })}
                              />
                            </Field>
                          )}
                        </div>
                      ) : (
                        <div className={styles.fieldRow}>
                          <Field label="New customer name" htmlFor={`vrm-fleet-newcust-${inst.id_site}`} required>
                            <Input
                              id={`vrm-fleet-newcust-${inst.id_site}`}
                              value={form.newCustomerName}
                              onChange={(e) => updateLinkForm(inst.id_site, { newCustomerName: e.target.value })}
                            />
                          </Field>
                          <Field label="Site name" htmlFor={`vrm-fleet-newcustsite-${inst.id_site}`} required>
                            <Input
                              id={`vrm-fleet-newcustsite-${inst.id_site}`}
                              value={form.newSiteName}
                              onChange={(e) => updateLinkForm(inst.id_site, { newSiteName: e.target.value })}
                            />
                          </Field>
                        </div>
                      )}

                      <h4 className={styles.sectionTitle}>Site data</h4>
                      {inst.suggested_fields ? (
                        <p className={styles.caption}>
                          Some fields were pre-filled from an already-monitored site (<code>monitoring</code> schema) for this
                          same physical installation — review and correct them if needed; nothing is saved until you click
                          Link.
                        </p>
                      ) : (
                        <p className={styles.caption}>
                          No automatic suggestions for this installation — fill in the site data by hand (system type,
                          location, power, battery) so the report comes out correct.
                        </p>
                      )}

                      <div className={styles.fieldRow}>
                        <Field label="PV power (kWp)" htmlFor={`vrm-fleet-kwp-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-kwp-${inst.id_site}`}
                            type="number"
                            step="0.1"
                            min="0"
                            value={form.siteFields.pvKwp}
                            onChange={(e) => updateSiteFields(inst.id_site, { pvKwp: e.target.value })}
                          />
                        </Field>
                        <Field label="System type" htmlFor={`vrm-fleet-type-${inst.id_site}`}>
                          <Select
                            id={`vrm-fleet-type-${inst.id_site}`}
                            value={form.siteFields.systemType}
                            onChange={(e) => updateSiteFields(inst.id_site, { systemType: e.target.value as SiteFieldsState['systemType'] })}
                          >
                            <option value="hybrid">Hybrid</option>
                            <option value="off_grid">Off-grid</option>
                            <option value="grid_zero">Grid-tied, no battery</option>
                          </Select>
                        </Field>
                        <Field label="Report language" htmlFor={`vrm-fleet-lang-${inst.id_site}`}>
                          <Select
                            id={`vrm-fleet-lang-${inst.id_site}`}
                            value={form.siteFields.reportLanguage}
                            onChange={(e) => updateSiteFields(inst.id_site, { reportLanguage: e.target.value as 'en' | 'es' })}
                          >
                            <option value="en">English</option>
                            <option value="es">Español</option>
                          </Select>
                        </Field>
                      </div>

                      <div className={styles.fieldRow}>
                        <Field label="Nominal battery (kWh)" htmlFor={`vrm-fleet-battnom-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-battnom-${inst.id_site}`}
                            type="number"
                            step="0.1"
                            min="0"
                            value={form.siteFields.battNominal}
                            onChange={(e) => updateSiteFields(inst.id_site, { battNominal: e.target.value })}
                          />
                        </Field>
                        <Field label="DoD (%)" htmlFor={`vrm-fleet-battdod-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-battdod-${inst.id_site}`}
                            type="number"
                            step="1"
                            min="0"
                            max="100"
                            value={form.siteFields.battDod}
                            onChange={(e) => updateSiteFields(inst.id_site, { battDod: e.target.value })}
                          />
                        </Field>
                      </div>

                      <div className={styles.fieldRow}>
                        <Field label="Latitude" htmlFor={`vrm-fleet-lat-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-lat-${inst.id_site}`}
                            type="number"
                            step="0.000001"
                            value={form.siteFields.latitude}
                            onChange={(e) => updateSiteFields(inst.id_site, { latitude: e.target.value })}
                          />
                        </Field>
                        <Field label="Longitude" htmlFor={`vrm-fleet-lng-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-lng-${inst.id_site}`}
                            type="number"
                            step="0.000001"
                            value={form.siteFields.longitude}
                            onChange={(e) => updateSiteFields(inst.id_site, { longitude: e.target.value })}
                          />
                        </Field>
                        <Field label="Location" htmlFor={`vrm-fleet-loc-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-loc-${inst.id_site}`}
                            value={form.siteFields.location}
                            onChange={(e) => updateSiteFields(inst.id_site, { location: e.target.value })}
                          />
                        </Field>
                      </div>

                      <div className={styles.fieldRow}>
                        <Field label="Timezone" htmlFor={`vrm-fleet-tz-${inst.id_site}`}>
                          <Select
                            id={`vrm-fleet-tz-${inst.id_site}`}
                            value={form.siteFields.timezone}
                            onChange={(e) => updateSiteFields(inst.id_site, { timezone: e.target.value })}
                          >
                            {TIMEZONES.map((tz) => (
                              <option key={tz} value={tz}>
                                {tz}
                              </option>
                            ))}
                          </Select>
                        </Field>
                        <Field label="Country" htmlFor={`vrm-fleet-country-${inst.id_site}`}>
                          <Select
                            id={`vrm-fleet-country-${inst.id_site}`}
                            value={form.siteFields.country}
                            onChange={(e) => updateSiteFields(inst.id_site, { country: e.target.value })}
                          >
                            {COUNTRY_CODES.map((code) => (
                              <option key={code} value={code}>
                                {COUNTRIES[code]}
                              </option>
                            ))}
                          </Select>
                        </Field>
                      </div>

                      <div className={styles.fieldRow}>
                        <Field label="Rate (per kWh)" htmlFor={`vrm-fleet-rate-${inst.id_site}`}>
                          <Input
                            id={`vrm-fleet-rate-${inst.id_site}`}
                            type="number"
                            step="0.0001"
                            min="0"
                            value={form.siteFields.savingsRate}
                            onChange={(e) => updateSiteFields(inst.id_site, { savingsRate: e.target.value })}
                          />
                        </Field>
                        <Field label="Currency" htmlFor={`vrm-fleet-currency-${inst.id_site}`}>
                          <Select
                            id={`vrm-fleet-currency-${inst.id_site}`}
                            value={form.siteFields.savingsCurrency}
                            onChange={(e) => updateSiteFields(inst.id_site, { savingsCurrency: e.target.value })}
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
                          checked={form.siteFields.exportsToGrid}
                          onChange={(e) => updateSiteFields(inst.id_site, { exportsToGrid: e.target.checked })}
                        />
                        This system exports energy to the grid
                      </label>

                      <p className={styles.caption}>
                        Days already imported by CSV for the chosen site will be replaced by data pulled from VRM the first
                        time it syncs.
                      </p>

                      {linkError && <p className={styles.error}>{linkError}</p>}

                      <div className={styles.formActions}>
                        <Button type="button" onClick={() => handleLinkSubmit(inst.id_site)} disabled={linkBusy}>
                          {linkBusy ? 'Linking…' : 'Link'}
                        </Button>
                      </div>
                    </td>
                  </tr>
                )}

                {inst.links
                  .filter((link) => syncFormFor === link.site_id)
                  .map((link) => (
                    <tr key={`sync-${link.site_id}`}>
                      <td colSpan={4} className={styles.editRow}>
                        <div className={styles.fieldRow}>
                          <Field label="From" htmlFor={`vrm-fleet-start-${link.site_id}`}>
                            <Input
                              id={`vrm-fleet-start-${link.site_id}`}
                              type="date"
                              value={syncWindows[link.site_id]?.start ?? ''}
                              onChange={(e) =>
                                setSyncWindows((w) => ({ ...w, [link.site_id]: { ...w[link.site_id], start: e.target.value } }))
                              }
                              disabled={!!syncBusy[link.site_id]}
                            />
                          </Field>
                          <Field label="To" htmlFor={`vrm-fleet-end-${link.site_id}`}>
                            <Input
                              id={`vrm-fleet-end-${link.site_id}`}
                              type="date"
                              value={syncWindows[link.site_id]?.end ?? ''}
                              onChange={(e) =>
                                setSyncWindows((w) => ({ ...w, [link.site_id]: { ...w[link.site_id], end: e.target.value } }))
                              }
                              disabled={!!syncBusy[link.site_id]}
                            />
                          </Field>
                        </div>
                        <p className={styles.caption}>
                          {link.vrm_last_synced_at
                            ? `Last sync: ${formatDateTime(link.vrm_last_synced_at)}.`
                            : 'This site has not been synced from the API yet.'}
                        </p>

                        {syncError[link.site_id] && <p className={styles.error}>{syncError[link.site_id]}</p>}
                        {syncResult[link.site_id] && (
                          <p className={styles.success}>
                            Imported {syncResult[link.site_id].rows_written} day(s) and {syncResult[link.site_id].alarm_events_written}{' '}
                            alarm event(s)
                            {syncResult[link.site_id].days_replacing_csv > 0
                              ? ` (${syncResult[link.site_id].days_replacing_csv} day(s) replaced CSV data)`
                              : ''}
                            .
                          </p>
                        )}

                        {!syncJobBySite[link.site_id] && (
                          <div className={styles.formActions}>
                            <Button type="button" onClick={() => handleSync(link.site_id)} disabled={!!syncBusy[link.site_id]}>
                              {syncBusy[link.site_id] ? 'Starting…' : 'Sync'}
                            </Button>
                          </div>
                        )}
                        {syncJobBySite[link.site_id] && (
                          <JobProgress
                            jobId={syncJobBySite[link.site_id]}
                            endpoint="/api/admin/pipeline/jobs"
                            runningLabel="Syncing with VRM…"
                            genericFailedLabel="Something went wrong. Please try again."
                            unreachableLabel="Could not reach the sync service."
                            onDone={(job) => handleSyncJobDone(link.site_id, job)}
                            onFailed={(message) => handleSyncJobFailed(link.site_id, message)}
                          />
                        )}
                      </td>
                    </tr>
                  ))}
              </Fragment>
            );
          })}
        </tbody>
      </Table>
    </div>
  );
}
