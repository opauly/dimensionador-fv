import type { Metadata } from 'next';
import { requireAdmin } from '@/lib/server/auth';
import { Panel } from '@/components/ui';
import styles from './help.module.css';

export const metadata: Metadata = {
  title: 'Help — Admin',
};

// `/admin/help` — admin-side reference, plain English literals throughout
// (no `lib/i18n/strings.ts` keys), matching every other `/admin/**` page's
// convention (`layout.tsx`'s own comment on why admin stayed English-only).
// Static content, no client interactivity, so this stays a pure Server
// Component like `/admin/fleet` itself.
export default async function AdminHelpPage() {
  await requireAdmin();

  return (
    <div>
      <h1>Help</h1>
      <p className={styles.intro}>Reference for admin-only workflows — Fleet Health, VRM linking, and site upkeep.</p>

      <Panel className={styles.section}>
        <h2>Monitor a site live</h2>
        <p>
          <strong>Fleet Health</strong> (the <code>/admin/fleet</code> tab) only shows sites connected through the{' '}
          <strong>VRM API</strong> — a site that only ever receives CSV uploads has no live connection to poll, so it
          never appears there, no matter how many reports it has. To get a site onto Fleet Health, connect it to VRM
          first, one of two ways:
        </p>
        <ol className={styles.stepList}>
          <li>
            <strong>Customer connects their own installation.</strong> The customer goes to their <em>Sites</em> page
            and uses the VRM Link panel to enter their own VRM installation and personal access token. Once
            connected, the site&apos;s <code>source</code> flips to <code>vrm_api</code> automatically — no separate
            step needed to make it show up on Fleet Health.
          </li>
          <li>
            <strong>You link it directly, as admin.</strong> Go to <em>VRM Fleet</em> in the nav (the personal,
            highlighted tab — this is your own VRM account, not a customer&apos;s). Pick the installation from the
            list, and either attach it to an existing customer or create a new one, then give it a site name. This
            is the right path for your own field installations, or any site where walking a customer through
            self-service linking doesn&apos;t make sense.
          </li>
        </ol>
        <p>Once linked, two things start happening automatically — nothing else to configure:</p>
        <ul className={styles.bulletList}>
          <li>
            A GitHub Actions cron (<code>fleet-snapshots.yml</code>) refreshes every connected site&apos;s live
            PV/load/battery/grid/SOC reading roughly every 15 minutes.
          </li>
          <li>
            The site&apos;s existing daily report pipeline keeps computing health score, self-sufficiency,
            self-consumption, depth of discharge, and yield the same way it always has — Fleet Health just surfaces
            those same numbers instead of only mailing them in a weekly PDF.
          </li>
        </ul>
      </Panel>

      <Panel className={styles.section}>
        <h2>Reading the fleet table</h2>
        <ul className={styles.bulletList}>
          <li>
            <strong>Connection</strong> is based on <code>vrm_last_synced_at</code> — <em>Online</em> within 48
            hours, <em>Stale</em> beyond that, <em>Never synced</em> if it hasn&apos;t completed a report sync yet.
            A brand-new VRM link can show live power immediately while still saying &quot;Never synced&quot; here —
            the live snapshot and the daily report sync are two independent things.
          </li>
          <li>
            <strong>Grid</strong> only shows a number for a site that actually has a physical grid meter — checked
            per site from real data, not assumed from the system type. Most installations don&apos;t have one, and
            that column reads &quot;no meter&quot; there instead of a guessed value.
          </li>
          <li>
            Click any of the summary cards at the top (Sites monitored, Online, Avg health score, etc.) to expand
            the per-site numbers behind that aggregate.
          </li>
          <li>
            <strong>View live →</strong> on each row opens that site&apos;s own drill-down page — a bigger flow
            diagram, the same gauges, and an hour-by-hour shape chart with a Today / 7-day avg / 30-day avg toggle.
          </li>
        </ul>
      </Panel>

      <Panel className={styles.section}>
        <h2>Removing a site from monitoring</h2>
        <p>
          There&apos;s no one-click &quot;unmonitor&quot; today. Fleet Health shows every site with{' '}
          <code>source = &apos;vrm_api&apos;</code>, regardless of whether that customer&apos;s subscription is
          active — deliberately, since this page is about hardware you&apos;re responsible for, not billing status.
          Genuinely disconnecting a site from VRM isn&apos;t a supported self-service action yet; ask engineering if
          you need one removed.
        </p>
      </Panel>
    </div>
  );
}
