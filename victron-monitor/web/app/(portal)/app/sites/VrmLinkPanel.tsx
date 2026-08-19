'use client';

// The "Victron VRM account" panel (PLAN_PHASE15.md §3.1 / §8 Step 5) — a
// sibling of `SitesManager.tsx` on the same page, not a replacement for it:
// the token is account-level but every meaningful action is a per-site
// mapping, and `source` is a per-site column, so the panel and the site
// table belong on one page (§3.1's own reasoning).
//
// Three deliberate steps, none of which stores anything until the last
// (§3.1):
//   1. Disconnected — paste a token, `POST /api/vrm/validate`. Nothing is
//      written; the response is only ever held in this component's state.
//   2. Mapping — the real installation list `validate` returned. Every
//      installation defaults to "ignore" (simply omitted from the
//      `mappings` array sent to `/api/vrm/connect`) — nothing is ever
//      pre-selected, not even when there's exactly one installation and one
//      site (§3.1 step 2, verbatim).
//   3. Connected — `POST /api/vrm/connect` wrote the token + mappings.
//      `status` (this component's main prop) is a Server Component read
//      (`getVrmLinkStatus()` in `page.tsx`), refreshed via `router.refresh()`
//      after every mutation — there is no client-side cache of connection
//      state to keep in sync by hand, same convention `SitesManager.tsx`'s
//      own `sites` prop already uses.
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button, Field, Input, Select } from '@/components/ui';
import { JobProgress, type JobProgressJob } from '@/components/app';
import { t, type Lang } from '@/lib/i18n/strings';
import { formatDate, formatDateTime, type DateLocale } from '@/lib/dates';
import type { CanAddSiteResult, SiteRecord, VrmLinkStatusOut } from '@/lib/server/db';
import type { VrmLinkValidateOut } from '@/lib/server/pipeline';
import styles from './sites.module.css';

export type VrmLinkPanelProps = {
  status: VrmLinkStatusOut;
  sites: SiteRecord[];
  lang: Lang;
  canAdd: CanAddSiteResult;
  siteLimit: number | null;
};

type Mode = 'idle' | 'validating' | 'mapping' | 'connecting' | 'disconnecting';

type MappingChoice = 'ignore' | 'existing' | 'new';

type MappingRow = {
  choice: MappingChoice;
  siteId: string;
  newSiteName: string;
};

type SyncResult = { rows_written: number; alarm_events_written: number; days_replacing_csv: number };

const DATE_LOCALE: Record<Lang, DateLocale> = { en: 'en-US', es: 'es-CR' };

/** §6.2/§0.5 Q4's own 31-day backfill default, mirrored client-side since
 * there is no per-site date picker in this panel (unlike `/admin/vrm-fleet`'s
 * manual window) — a click on "Sync now" always asks for everything since
 * the last successful sync, or the last 31 days on a site's first-ever
 * sync, through yesterday. */
function defaultSyncWindow(lastSyncedAt: string | null): { start: string; end: string } {
  const end = new Date();
  end.setUTCDate(end.getUTCDate() - 1);
  const start = lastSyncedAt ? new Date(lastSyncedAt) : new Date(end);
  if (!lastSyncedAt) start.setUTCDate(start.getUTCDate() - 31);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

function buildInitialMappingRows(installations: VrmLinkValidateOut['installations'], sites: SiteRecord[]): Record<number, MappingRow> {
  const rows: Record<number, MappingRow> = {};
  for (const inst of installations) {
    rows[inst.id_site] = {
      choice: 'ignore',
      siteId: sites[0]?.site_id ?? '',
      newSiteName: inst.name ?? `VRM ${inst.id_site}`,
    };
  }
  return rows;
}

export function VrmLinkPanel({ status, sites, lang, canAdd, siteLimit }: VrmLinkPanelProps) {
  const router = useRouter();

  const [mode, setMode] = useState<Mode>('idle');

  // "Adjusting state when a prop changes" during render (same idiom
  // `JobProgress.tsx` itself uses, not a workaround) — the instant the
  // Server Component's own `status.connected` flips (after a
  // `router.refresh()` this component triggered), any local 'connecting'/
  // 'disconnecting' transition state resets to 'idle' so the prop takes
  // over as the single source of truth, rather than this component
  // guessing when the refresh landed.
  const [trackedConnected, setTrackedConnected] = useState(status.connected);
  if (status.connected !== trackedConnected) {
    setTrackedConnected(status.connected);
    setMode('idle');
  }

  const [token, setToken] = useState('');
  const [validateError, setValidateError] = useState<string | null>(null);
  const [validation, setValidation] = useState<VrmLinkValidateOut | null>(null);
  const [mappingRows, setMappingRows] = useState<Record<number, MappingRow>>({});
  const [connectError, setConnectError] = useState<string | null>(null);
  const [limitBlocked, setLimitBlocked] = useState(false);
  const [disconnectError, setDisconnectError] = useState<string | null>(null);

  const [syncJobBySite, setSyncJobBySite] = useState<Record<string, string>>({});
  const [syncBusy, setSyncBusy] = useState<Record<string, boolean>>({});
  const [syncError, setSyncError] = useState<Record<string, string>>({});
  const [syncResult, setSyncResult] = useState<Record<string, SyncResult>>({});

  function updateMappingRow(idSite: number, patch: Partial<MappingRow>) {
    setMappingRows((rows) => ({ ...rows, [idSite]: { ...rows[idSite], ...patch } }));
  }

  async function handleValidate() {
    setValidateError(null);
    setMode('validating');
    try {
      const res = await fetch('/api/vrm/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        setValidateError(
          body?.error === 'invalid_vrm_token'
            ? t(lang, 'vrm_link_validate_error_invalid_token')
            : t(lang, 'vrm_link_validate_error_generic'),
        );
        setMode('idle');
        return;
      }
      const data = (await res.json()) as VrmLinkValidateOut;
      setValidation(data);
      setMappingRows(buildInitialMappingRows(data.installations, sites));
      setLimitBlocked(false);
      setConnectError(null);
      setMode('mapping');
    } catch {
      setValidateError(t(lang, 'vrm_link_validate_error_unreachable'));
      setMode('idle');
    }
  }

  function handleCancelMapping() {
    setMode('idle');
    setValidation(null);
    setMappingRows({});
    setToken('');
    setConnectError(null);
    setLimitBlocked(false);
  }

  async function handleConnect() {
    if (!validation) return;

    type MappingBody = {
      siteSelection: 'existing' | 'new';
      vrmInstallationId: number;
      siteId?: string;
      newSiteName?: string;
      siteFields?: { display_name?: string };
    };
    const mappings: MappingBody[] = [];
    for (const inst of validation.installations) {
      const row = mappingRows[inst.id_site];
      if (!row || row.choice === 'ignore') continue;
      if (row.choice === 'existing') {
        if (!row.siteId) continue;
        // The existing site's OWN display name travels along as
        // `siteFields.display_name` — `vrm_api/routers/vrm_link.py`'s
        // connect handler falls back to the raw `site_name_or_id` (the
        // site's id, not its friendly name) whenever `site_fields` doesn't
        // carry one, which would otherwise clobber the real display name
        // with the site_id slug. `UploadManager.tsx`'s own existing-site
        // branch avoids the exact same trap the same way.
        const site = sites.find((s) => s.site_id === row.siteId);
        mappings.push({
          siteSelection: 'existing',
          vrmInstallationId: inst.id_site,
          siteId: row.siteId,
          siteFields: site ? { display_name: site.display_name } : undefined,
        });
      } else {
        const name = row.newSiteName.trim();
        if (!name) continue;
        mappings.push({ siteSelection: 'new', vrmInstallationId: inst.id_site, newSiteName: name });
      }
    }

    setConnectError(null);
    setLimitBlocked(false);
    setMode('connecting');
    try {
      const res = await fetch('/api/vrm/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, mappings }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { error?: string } | null;
        if (body?.error === 'site_limit_reached') {
          setLimitBlocked(true);
        } else {
          setConnectError(
            body?.error === 'vrm_account_already_linked'
              ? t(lang, 'vrm_link_mapping_error_account_already_linked')
              : t(lang, 'vrm_link_mapping_error_generic'),
          );
        }
        setMode('mapping');
        return;
      }
      setToken('');
      setValidation(null);
      setMappingRows({});
      // Stays 'connecting' — the render-time watcher above clears it once
      // `status.connected` (the refreshed Server Component prop) actually
      // flips true, so there's no flash back to the disconnected form while
      // the refresh is in flight.
      router.refresh();
    } catch {
      setConnectError(t(lang, 'vrm_link_mapping_error_unreachable'));
      setMode('mapping');
    }
  }

  async function handleDisconnect() {
    // A native confirm — this repo has no custom confirm-dialog component
    // yet, and the text itself is the load-bearing part here (§3.1: "the UI
    // says so" — existing telemetry is kept, not deleted).
    if (!window.confirm(t(lang, 'vrm_link_disconnect_confirm'))) return;
    setDisconnectError(null);
    setMode('disconnecting');
    try {
      const res = await fetch('/api/vrm/disconnect', { method: 'POST' });
      if (!res.ok) {
        setDisconnectError(t(lang, 'vrm_link_disconnect_error_generic'));
        setMode('idle');
        return;
      }
      router.refresh(); // watcher above clears 'disconnecting' once status.connected flips false
    } catch {
      setDisconnectError(t(lang, 'vrm_link_disconnect_error_generic'));
      setMode('idle');
    }
  }

  async function handleSync(siteId: string, lastSyncedAt: string | null) {
    const win = defaultSyncWindow(lastSyncedAt);
    setSyncBusy((b) => ({ ...b, [siteId]: true }));
    setSyncError((e) => ({ ...e, [siteId]: '' }));
    setSyncResult((r) => {
      const next = { ...r };
      delete next[siteId];
      return next;
    });
    try {
      const res = await fetch('/api/vrm/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ siteId, start: win.start, end: win.end }),
      });
      if (!res.ok) {
        setSyncError((e) => ({ ...e, [siteId]: t(lang, 'vrm_link_connected_sync_error_unreachable') }));
        setSyncBusy((b) => ({ ...b, [siteId]: false }));
        return;
      }
      const { job_id } = (await res.json()) as { job_id: string };
      setSyncJobBySite((j) => ({ ...j, [siteId]: job_id }));
    } catch {
      setSyncError((e) => ({ ...e, [siteId]: t(lang, 'vrm_link_connected_sync_error_unreachable') }));
      setSyncBusy((b) => ({ ...b, [siteId]: false }));
    }
  }

  function handleSyncAll() {
    for (const site of status.sites) {
      if (!syncBusy[site.site_id] && !syncJobBySite[site.site_id]) {
        handleSync(site.site_id, site.vrm_last_synced_at);
      }
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
    router.refresh(); // picks up the fresh vrm_last_synced_at on status.sites
  }

  function handleSyncJobFailed(siteId: string, message: string) {
    setSyncError((e) => ({ ...e, [siteId]: message }));
    clearSyncJob(siteId);
    router.refresh(); // picks up vrm_last_sync_error / vrm_sync_enabled changes on failure (§9)
  }

  // ── Transitioning: a connect/disconnect just landed, waiting for the
  // refreshed `status` prop to actually reflect it ─────────────────────
  if (mode === 'connecting' || mode === 'disconnecting') {
    return (
      <div className={styles.vrmPanel}>
        <h2>{t(lang, 'vrm_link_title')}</h2>
        <p className={styles.status}>{t(lang, mode === 'connecting' ? 'vrm_link_mapping_connecting' : 'vrm_link_disconnecting')}</p>
      </div>
    );
  }

  // ── Connected ──────────────────────────────────────────────────────
  if (status.connected) {
    return (
      <div className={styles.vrmPanel}>
        <h2>{t(lang, 'vrm_link_title')}</h2>
        <p className={styles.linkedSiteMeta}>
          {t(lang, 'vrm_link_connected_account_label')}: {status.vrm_account_email ?? '—'}
          {' · '}
          {t(lang, 'vrm_link_connected_since_label')}:{' '}
          {status.connected_since ? formatDate(status.connected_since, DATE_LOCALE[lang]) : '—'}
        </p>

        <h3 className={styles.installationName}>{t(lang, 'vrm_link_connected_sites_title')}</h3>
        {status.sites.length === 0 ? (
          <p className={styles.status}>—</p>
        ) : (
          <div>
            {status.sites.map((site) => (
              <div key={site.site_id} className={styles.linkedSiteRow}>
                <div>
                  <div>{site.display_name}</div>
                  <div className={styles.linkedSiteMeta}>
                    {t(lang, 'vrm_link_connected_last_synced_label')}:{' '}
                    {site.vrm_last_synced_at
                      ? formatDateTime(site.vrm_last_synced_at, DATE_LOCALE[lang])
                      : t(lang, 'vrm_link_connected_never_synced')}
                  </div>
                  {site.vrm_last_sync_error && <div className={styles.syncErrorText}>{site.vrm_last_sync_error}</div>}
                  {syncError[site.site_id] && <div className={styles.syncErrorText}>{syncError[site.site_id]}</div>}
                  {syncResult[site.site_id] && (
                    <div className={styles.success}>
                      {t(lang, 'vrm_link_connected_sync_success')
                        .replace('{rows}', String(syncResult[site.site_id].rows_written))
                        .replace('{alarms}', String(syncResult[site.site_id].alarm_events_written))}
                    </div>
                  )}
                </div>
                <div>
                  {syncJobBySite[site.site_id] ? (
                    <JobProgress
                      jobId={syncJobBySite[site.site_id]}
                      runningLabel={t(lang, 'vrm_link_connected_syncing')}
                      genericFailedLabel={t(lang, 'job_generic_failed')}
                      unreachableLabel={t(lang, 'vrm_link_connected_sync_error_unreachable')}
                      onDone={(job) => handleSyncJobDone(site.site_id, job)}
                      onFailed={(message) => handleSyncJobFailed(site.site_id, message)}
                    />
                  ) : (
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => handleSync(site.site_id, site.vrm_last_synced_at)}
                      disabled={!!syncBusy[site.site_id]}
                    >
                      {t(lang, 'vrm_link_connected_sync_now_button')}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className={styles.formActions}>
          {status.sites.length > 0 && (
            <Button type="button" variant="ghost" onClick={handleSyncAll}>
              {t(lang, 'vrm_link_connected_sync_all_button')}
            </Button>
          )}
          <Button type="button" variant="ghost" onClick={handleDisconnect}>
            {t(lang, 'vrm_link_disconnect_button')}
          </Button>
        </div>
        {disconnectError && <p className={styles.error}>{disconnectError}</p>}
      </div>
    );
  }

  // ── Mapping ────────────────────────────────────────────────────────
  if (mode === 'mapping' && validation) {
    return (
      <div className={styles.vrmPanel}>
        <h2>{t(lang, 'vrm_link_mapping_title')}</h2>
        <p className={styles.status}>{t(lang, 'vrm_link_mapping_intro')}</p>
        <p className={styles.portalPath}>{t(lang, 'vrm_link_mapping_replace_notice')}</p>

        {validation.installations.map((inst) => {
          const row = mappingRows[inst.id_site];
          if (!row) return null;
          return (
            <div key={inst.id_site} className={styles.installationRow}>
              <div className={styles.installationName}>{inst.name ?? `VRM ${inst.id_site}`}</div>
              <div className={styles.installationMeta}>
                {t(lang, 'vrm_link_mapping_installation_id_label').replace('{id}', String(inst.id_site))}
                {inst.identifier ? ` · ${inst.identifier}` : ''}
              </div>

              <div className={styles.radioRow}>
                <label className={styles.radioLabel}>
                  <input
                    type="radio"
                    checked={row.choice === 'ignore'}
                    onChange={() => updateMappingRow(inst.id_site, { choice: 'ignore' })}
                  />
                  {t(lang, 'vrm_link_mapping_choice_ignore')}
                </label>
                {sites.length > 0 && (
                  <label className={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={row.choice === 'existing'}
                      onChange={() => updateMappingRow(inst.id_site, { choice: 'existing' })}
                    />
                    {t(lang, 'vrm_link_mapping_choice_existing')}
                  </label>
                )}
                {canAdd.ok && (
                  <label className={styles.radioLabel}>
                    <input
                      type="radio"
                      checked={row.choice === 'new'}
                      onChange={() => updateMappingRow(inst.id_site, { choice: 'new' })}
                    />
                    {t(lang, 'vrm_link_mapping_choice_new')}
                  </label>
                )}
              </div>

              {row.choice === 'existing' && (
                <Field label={t(lang, 'vrm_link_mapping_existing_site_label')} htmlFor={`vrm-map-site-${inst.id_site}`}>
                  <Select
                    id={`vrm-map-site-${inst.id_site}`}
                    value={row.siteId}
                    onChange={(e) => updateMappingRow(inst.id_site, { siteId: e.target.value })}
                  >
                    {sites.map((s) => (
                      <option key={s.site_id} value={s.site_id}>
                        {s.display_name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}

              {row.choice === 'new' && (
                <Field label={t(lang, 'vrm_link_mapping_new_site_name_label')} htmlFor={`vrm-map-newname-${inst.id_site}`} required>
                  <Input
                    id={`vrm-map-newname-${inst.id_site}`}
                    value={row.newSiteName}
                    onChange={(e) => updateMappingRow(inst.id_site, { newSiteName: e.target.value })}
                  />
                </Field>
              )}
            </div>
          );
        })}

        {(limitBlocked || !canAdd.ok) && (
          <div className={styles.limitCallout}>
            <p>
              <strong>{t(lang, 'sites_limit_title')}</strong>
            </p>
            <p>{t(lang, 'sites_limit_body').replace('{limit}', siteLimit === null ? '—' : String(siteLimit))}</p>
            <Button href="mailto:proyectos@paulyco.com" variant="ghost">
              {t(lang, 'sites_limit_cta')}
            </Button>
          </div>
        )}
        {connectError && <p className={styles.error}>{connectError}</p>}

        <div className={styles.formActions}>
          <Button type="button" onClick={handleConnect}>
            {t(lang, 'vrm_link_mapping_connect_button')}
          </Button>
          <Button type="button" variant="ghost" onClick={handleCancelMapping}>
            {t(lang, 'vrm_link_mapping_cancel_button')}
          </Button>
        </div>
      </div>
    );
  }

  // ── Disconnected (default) ────────────────────────────────────────
  // PLAN_PHASE15.md §8 Step 6: "not connected yet" (never connected) and
  // "was connected, then broke" are NOT the same message — `broken` below
  // is the same §9 condition `VrmConnectionBanner` uses at the top of this
  // page, checked again here because that global banner doesn't know this
  // panel is about to show the exact same neutral "paste a token" copy a
  // customer who never connected at all would also see.
  const busy = mode === 'validating';
  const broken = Boolean(status.token_revoked_at) || Boolean(status.token_last_error);
  // Sites still on record from before the break (§3.1's disconnect flow
  // only reverts `source` on a DELIBERATE disconnect — an auth failure
  // leaves these as `source='vrm_api'`, so `status.sites` still lists them;
  // see `vrm_link.py:get_status()`) — surfaced with their own per-site
  // error text where present, human sentences only (PLAN_PHASE14.md §1.12
  // rule 6), same as the connected view above already does.
  const brokenSites = broken ? status.sites.filter((s) => s.vrm_last_sync_error) : [];
  return (
    <div className={styles.vrmPanel}>
      <h2>{t(lang, 'vrm_link_title')}</h2>
      {broken ? (
        <>
          <p className={styles.syncErrorText}>{t(lang, 'vrm_link_broken_banner')}</p>
          {brokenSites.length > 0 && (
            <div>
              {brokenSites.map((site) => (
                <div key={site.site_id} className={styles.linkedSiteRow}>
                  <div className={styles.linkedSiteMeta}>
                    {site.display_name}: {site.vrm_last_sync_error}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      ) : (
        <p className={styles.status}>{t(lang, 'vrm_link_disconnected_intro')}</p>
      )}
      <p className={styles.portalPath}>{t(lang, 'vrm_link_portal_path')}</p>

      <Field label={t(lang, 'vrm_link_token_label')} htmlFor="vrm-link-token" required>
        <Input
          id="vrm-link-token"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          disabled={busy}
        />
      </Field>

      {validateError && <p className={styles.error}>{validateError}</p>}

      <div className={styles.formActions}>
        <Button type="button" onClick={handleValidate} disabled={busy || !token.trim()}>
          {busy ? t(lang, 'vrm_link_validating') : t(lang, 'vrm_link_validate_button')}
        </Button>
      </div>
    </div>
  );
}
