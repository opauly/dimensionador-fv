'use client';

// Client wrapper around the sites table + edit/add forms
// (PLAN_PHASE14.md §2 Step 4). Only client-side state here is "which row
// (if any) has its edit form open" and "is the add-site form open" — the
// data itself (`sites`) is passed down from the Server Component page,
// which re-fetches it on every request; there is no client-side cache to
// keep in sync by hand.
import { useState } from 'react';
import { Button, Table } from '@/components/ui';
import { t, type Lang } from '@/lib/i18n/strings';
import { countryLabel } from '@/lib/countries';
import type { CanAddSiteResult, SiteRecord } from '@/lib/server/db';
import { addSiteAction, updateSiteAction } from './actions';
import { SiteForm } from './SiteForm';
import styles from './sites.module.css';

export type SitesManagerProps = {
  sites: SiteRecord[];
  lang: Lang;
  canAdd: CanAddSiteResult;
  siteLimit: number | null;
};

const SYSTEM_TYPE_KEY = {
  hybrid: 'system_type_hybrid',
  off_grid: 'system_type_off_grid',
  grid_zero: 'system_type_grid_zero',
} as const;

export function SitesManager({ sites, lang, canAdd, siteLimit }: SitesManagerProps) {
  const [editingSiteId, setEditingSiteId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  return (
    <div>
      {sites.length === 0 ? (
        <p className={styles.intro}>{t(lang, 'sites_none_yet')}</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <th>{t(lang, 'sites_table_site')}</th>
              <th>{t(lang, 'sites_table_type')}</th>
              <th>{t(lang, 'sites_table_pv')}</th>
              <th>{t(lang, 'sites_table_battery')}</th>
              <th>{t(lang, 'sites_table_language')}</th>
              <th>{t(lang, 'sites_table_country')}</th>
              <th>{t(lang, 'sites_table_status')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sites.map((site) => (
              <tr key={site.site_id}>
                <td>{site.display_name}</td>
                <td>{t(lang, SYSTEM_TYPE_KEY[site.system_type])}</td>
                <td>{site.pv_kwp ?? '—'}</td>
                <td>{site.battery_usable_kwh ?? '—'}</td>
                <td>{t(lang, site.report_language === 'es' ? 'lang_es' : 'lang_en')}</td>
                <td>{countryLabel(site.country)}</td>
                <td>
                  <span className={site.active ? styles.statusActive : styles.statusInactive}>
                    {t(lang, site.active ? 'sites_status_active' : 'sites_status_inactive')}
                  </span>
                </td>
                <td>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setEditingSiteId(editingSiteId === site.site_id ? null : site.site_id)}
                  >
                    {t(lang, 'sites_edit_button')}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {editingSiteId &&
        (() => {
          const site = sites.find((s) => s.site_id === editingSiteId);
          if (!site) return null;
          return (
            <div className={styles.panel}>
              <h3>{t(lang, 'sites_edit_title')}</h3>
              <SiteForm
                mode="edit"
                lang={lang}
                initial={site}
                action={updateSiteAction.bind(null, site.site_id)}
                onCancel={() => setEditingSiteId(null)}
                onSaved={() => setEditingSiteId(null)}
              />
            </div>
          );
        })()}

      <div className={styles.actionsRow}>
        {canAdd.ok ? (
          !adding && (
            <Button type="button" onClick={() => setAdding(true)}>
              {t(lang, 'sites_add_button')}
            </Button>
          )
        ) : (
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
      </div>

      {adding && canAdd.ok && (
        <div className={styles.panel}>
          <h3>{t(lang, 'sites_add_title')}</h3>
          <SiteForm mode="add" lang={lang} action={addSiteAction} onCancel={() => setAdding(false)} onSaved={() => setAdding(false)} />
        </div>
      )}
    </div>
  );
}
