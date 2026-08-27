'use client';

// Topic-card switcher for `/app/help` — the only client state on this page
// is "which topic is active," same shape as `SitesManager.tsx`'s own
// "which row is being edited" (a plain useState, data itself is static
// content baked into this file, not fetched). Split out of `page.tsx`
// (a Server Component) for the same reason `ReportManager`/`ReportHistory`
// are split out of `app/(portal)/app/page.tsx` — everything that doesn't
// need interactivity (the FAQ list, the contact card) stays server-rendered
// there instead of being dragged into this client bundle for no reason.
import { useState } from 'react';
import { t, type Lang, type StringKey } from '@/lib/i18n/strings';
import { Panel } from '@/components/ui';
import styles from './help.module.css';

type Topic = {
  id: string;
  navKey: StringKey;
  titleKey: StringKey;
  leadKey: StringKey;
  steps?: StringKey[];
  bullets?: StringKey[];
};

// Order here is the order topic cards render in — roughly the order a new
// customer actually touches these screens (connect a site, schedule it,
// then the less-frequently-visited billing/branding/account settings).
const TOPICS: Topic[] = [
  {
    id: 'sites',
    navKey: 'help_nav_sites',
    titleKey: 'help_section_sites_title',
    leadKey: 'help_section_sites_lead',
    steps: ['help_sites_step_1', 'help_sites_step_2'],
    bullets: ['help_sites_bullet_reconnect'],
  },
  {
    id: 'schedule',
    navKey: 'help_nav_schedule',
    titleKey: 'help_section_schedule_title',
    leadKey: 'help_section_schedule_lead',
    steps: ['help_schedule_step_1', 'help_schedule_step_2', 'help_schedule_step_3', 'help_schedule_step_4', 'help_schedule_step_5'],
    bullets: ['help_schedule_bullet_recipients', 'help_schedule_bullet_cap', 'help_schedule_bullet_bulk'],
  },
  {
    id: 'branding',
    navKey: 'help_nav_branding',
    titleKey: 'help_section_branding_title',
    leadKey: 'help_section_branding_lead',
    bullets: ['help_branding_bullet_who', 'help_branding_bullet_what', 'help_branding_bullet_where'],
  },
  {
    id: 'billing',
    navKey: 'help_nav_billing',
    titleKey: 'help_section_billing_title',
    leadKey: 'help_section_billing_lead',
    bullets: ['help_billing_bullet_plan', 'help_billing_bullet_limit', 'help_billing_bullet_upgrade'],
  },
  {
    id: 'account',
    navKey: 'help_nav_account',
    titleKey: 'help_section_account_title',
    leadKey: 'help_section_account_lead',
    bullets: ['help_account_bullet_password', 'help_account_bullet_language'],
  },
];

export function HelpManager({ lang }: { lang: Lang }) {
  const [activeId, setActiveId] = useState(TOPICS[0].id);
  const active = TOPICS.find((topic) => topic.id === activeId) ?? TOPICS[0];

  return (
    <div>
      <div className={styles.topicGrid} role="tablist">
        {TOPICS.map((topic) => (
          <button
            key={topic.id}
            type="button"
            role="tab"
            aria-selected={topic.id === activeId}
            className={topic.id === activeId ? styles.topicCardActive : styles.topicCard}
            onClick={() => setActiveId(topic.id)}
          >
            {t(lang, topic.navKey)}
          </button>
        ))}
      </div>

      <Panel className={styles.section}>
        <h2>{t(lang, active.titleKey)}</h2>
        <p>{t(lang, active.leadKey)}</p>
        {active.steps && (
          <ol className={styles.stepList}>
            {active.steps.map((key) => (
              <li key={key}>{t(lang, key)}</li>
            ))}
          </ol>
        )}
        {active.bullets && (
          <ul className={styles.bulletList}>
            {active.bullets.map((key) => (
              <li key={key}>{t(lang, key)}</li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
