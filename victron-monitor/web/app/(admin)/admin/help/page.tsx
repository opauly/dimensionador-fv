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
      <p className={styles.intro}>Reference for admin-only workflows — VRM Fleet, linking installations, and site upkeep.</p>

      <Panel className={styles.section}>
        <h2>Monitor a site live</h2>
        <p>
          <strong>VRM Fleet</strong> (the <code>/admin/fleet</code> tab) only shows sites connected through the{' '}
          <strong>VRM API</strong> — a site that only ever receives CSV uploads has no live connection to poll, so it
          never appears there, no matter how many reports it has. To get a site onto VRM Fleet, connect it to VRM
          first, one of two ways:
        </p>
        <ol className={styles.stepList}>
          <li>
            <strong>Customer connects their own installation.</strong> The customer goes to their <em>Sites</em> page
            and uses the VRM Link panel to enter their own VRM installation and personal access token. Once
            connected, the site&apos;s <code>source</code> flips to <code>vrm_api</code> automatically — no separate
            step needed to make it show up on VRM Fleet.
          </li>
          <li>
            <strong>You link it directly, as admin.</strong> From the VRM Fleet dashboard, click{' '}
            <em>+ Link a new installation</em> (this is your own VRM account, not a customer&apos;s — the dashboard
            itself is highlighted in the nav for the same reason). Pick the installation from the list,
            and either attach it to an existing customer or create a new one, then give it a site name. This is the
            right path for your own field installations, or any site where walking a customer through self-service
            linking doesn&apos;t make sense.
          </li>
        </ol>
        <p>Once linked and active, two things start happening automatically — nothing else to configure or enable:</p>
        <ul className={styles.bulletList}>
          <li>
            A GitHub Actions cron (<code>fleet-snapshots.yml</code>) refreshes every connected site&apos;s live
            PV/load/battery/grid/SOC reading every ~15 minutes — this is the ONLY requirement (
            <code>source = &apos;vrm_api&apos;</code> and <code>active = true</code>), there is no separate
            enrollment step or allowlist to add a site to.
          </li>
          <li>
            The site&apos;s existing daily report pipeline keeps computing health score, self-sufficiency,
            self-consumption, depth of discharge, and yield the same way it always has — VRM Fleet just surfaces
            those same numbers instead of only mailing them in a weekly PDF.
          </li>
        </ul>
      </Panel>

      <Panel className={styles.section}>
        <h2>Reading the fleet table</h2>
        <ul className={styles.bulletList}>
          <li>
            <strong>Connection</strong> is based on <code>site_snapshots.captured_at</code> — the same ~15-minute
            live sweep above — so <em>Online</em> means &quot;this site answered VRM within the last 45 minutes,&quot;
            not anything about the daily report sync. The &quot;Report data: …&quot; line underneath is that separate
            daily sync&apos;s own last-completed date; the two can genuinely disagree for days (a site can be{' '}
            <em>Online</em> with live power showing while its report data is a week old, or vice versa) — that&apos;s
            expected, not a bug, since they&apos;re two independent pipelines.
          </li>
          <li>
            <strong>Grid</strong> prefers a dedicated grid meter when one exists, and falls back to the
            inverter/charger&apos;s own AC input reading when it doesn&apos;t — most installations have no separate
            meter, but the inverter itself still measures what it draws from grid. The two are NOT the same number
            (cross-checked live on the one site with both: they read meaningfully differently, since a separate
            meter and the inverter&apos;s own sensor sit at different points in the electrical system) — the fleet
            table&apos;s per-site breakdown says which source a given reading came from. Only a site with neither
            signal at all shows &quot;no reading.&quot;
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
          VRM Fleet shows every site with <code>source = &apos;vrm_api&apos;</code> AND{' '}
          <code>active = true</code>, regardless of whether that customer&apos;s subscription is active —
          deliberately, since this page is about hardware you&apos;re responsible for, not billing status. There&apos;s
          no one-click &quot;unmonitor&quot; button in the UI yet, but setting a site&apos;s own <code>active</code>{' '}
          column to <code>false</code> (in Supabase directly today) removes it from VRM Fleet immediately, without
          deleting its history — the same flag the live snapshot sweep and the daily sync already respect, so a
          deactivated site also stops being polled going forward. Genuinely deleting a site is still not a
          supported self-service action; ask engineering if you need one truly gone.
        </p>
      </Panel>
    </div>
  );
}
