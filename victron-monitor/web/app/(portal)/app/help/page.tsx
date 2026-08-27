import type { Metadata } from 'next';
import { requireCustomerAllowPending } from '@/lib/server/auth';
import { t, type StringKey } from '@/lib/i18n/strings';
import { Panel } from '@/components/ui';
import { HelpManager } from './HelpManager';
import styles from './help.module.css';

export const metadata: Metadata = {
  title: 'Help',
};

const SUPPORT_EMAIL = 'proyectos@paulyco.com';

// One (question key, answer key) pair per FAQ entry — kept as plain data
// so the list below is just a `.map()`, not 10 repeated <details> blocks.
// Deliberately its OWN card, not folded into a topic above (Oscar's own
// call, 2026-08-26): some of these questions span more than one topic
// (e.g. the cadence-vs-CSV question touches both Getting started and
// Scheduling), so picking a single topic to attach each one to would be
// arbitrary either way — a separate, always-visible FAQ avoids that.
const FAQ_KEYS: Array<{ q: StringKey; a: StringKey }> = [
  { q: 'help_faq_q1', a: 'help_faq_a1' },
  { q: 'help_faq_q2', a: 'help_faq_a2' },
  { q: 'help_faq_q3', a: 'help_faq_a3' },
  { q: 'help_faq_q4', a: 'help_faq_a4' },
  { q: 'help_faq_q5', a: 'help_faq_a5' },
  { q: 'help_faq_q6', a: 'help_faq_a6' },
  { q: 'help_faq_q7', a: 'help_faq_a7' },
  { q: 'help_faq_q8', a: 'help_faq_a8' },
  { q: 'help_faq_q9', a: 'help_faq_a9' },
  { q: 'help_faq_q10', a: 'help_faq_a10' },
];

// `app/(portal)/app/help` — the topic switcher (`HelpManager`) is the only
// client-side piece; the FAQ and contact cards below it are static content,
// so they stay server-rendered here rather than joining that client
// bundle for no reason (same split `/app` itself uses for
// `VrmConnectionBanner`/`BillingBanners` vs. `ReportManager`).
// `requireCustomerAllowPending()`, same as `/app/profile` and
// `/app/billing`: a pending_subscription customer stuck setting up billing
// should still be able to read how the product works, not get bounced
// back to /app/billing by the normal gate.
export default async function HelpPage() {
  const session = await requireCustomerAllowPending();
  const lang = session.uiLanguage;

  return (
    <div>
      <h1>{t(lang, 'help_title')}</h1>
      <p className={styles.intro}>{t(lang, 'help_intro')}</p>

      <HelpManager lang={lang} />

      <Panel className={styles.section}>
        <h2>{t(lang, 'help_faq_title')}</h2>
        <div className={styles.faqList}>
          {FAQ_KEYS.map(({ q, a }) => (
            <details key={q} className={styles.faqItem}>
              <summary>{t(lang, q)}</summary>
              <p>{t(lang, a)}</p>
            </details>
          ))}
        </div>
      </Panel>

      <Panel className={styles.contact}>
        <h2>{t(lang, 'help_contact_title')}</h2>
        <p>{t(lang, 'help_contact_body')}</p>
        <a href={`mailto:${SUPPORT_EMAIL}`} className={styles.contactLink}>
          {SUPPORT_EMAIL}
        </a>
      </Panel>
    </div>
  );
}
