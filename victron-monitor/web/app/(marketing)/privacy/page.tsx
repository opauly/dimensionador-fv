import type { Metadata } from 'next';
import Link from 'next/link';
import { Footer, Nav } from '@/components/marketing';
import styles from '../legal.module.css';

export const metadata: Metadata = {
  title: 'Privacy Policy',
  description: 'What VRM Monitor collects, why, and who it shares data with.',
};

const LAST_UPDATED = 'August 20, 2026';

// `app/(marketing)/privacy` — sibling to `app/(marketing)/terms`, same
// Nav/Footer shape, same shared legal.module.css. See terms/page.tsx's own
// header comment for the route-group reasoning; not repeated here.
export default function PrivacyPage() {
  return (
    <>
      <Nav />
      <div className="wrap">
        <div className={styles.page}>
          <header className={styles.header}>
            <h1>Privacy Policy</h1>
            <p className={styles.updated}>Last updated: {LAST_UPDATED}</p>
          </header>

          <div className={styles.draftNotice}>
            <p>
              <strong>Draft.</strong> This is a first draft written to reflect how VRM Monitor actually handles data today. It has
              not yet been reviewed by a lawyer and should not be treated as final. If you have questions, contact us at{' '}
              <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a> before relying on it.
            </p>
          </div>

          <div className={styles.body}>
            <h2>1. Scope</h2>
            <p>
              This policy covers VRM Monitor, a product of Pauly &amp; Co. (Atenas, Costa Rica). It explains what data we collect
              when you use the service, why we collect it, and who else sees it.
            </p>

            <h2>2. Data we collect</h2>
            <p>
              <strong>Account data</strong> — your name, email address, and password (stored hashed, never in plain text) when you
              create an account.
            </p>
            <p>
              <strong>Site and telemetry data</strong> — the Victron VRM installations you connect, and the telemetry (battery
              state, solar production, consumption, alarms, and similar readings) that your Victron system already reports to VRM.
              We read this using an API token you provide; we don&apos;t access anything in your VRM account beyond what that token
              scopes us to.
            </p>
            <p>
              <strong>Billing data</strong> — your subscription plan, billing status, and invoice history. Your card details are
              collected and stored directly by our payment processor, ONVO Pay — we never see or store your full card number.
            </p>
            <p>
              <strong>Usage data</strong> — basic operational logs (sign-ins, report deliveries, API errors) used to keep the
              service running and to troubleshoot problems.
            </p>

            <h2>3. How we use it</h2>
            <ul>
              <li>To generate and deliver your scheduled reports;</li>
              <li>To operate your account — authentication, billing, and support;</li>
              <li>To send account-related email (verification, billing receipts, service notices);</li>
              <li>To monitor and improve the reliability of the service.</li>
            </ul>
            <p>We don&apos;t sell your data, and we don&apos;t use your telemetry data to train AI models.</p>

            <h2>4. Who we share data with</h2>
            <p>
              We use a small number of service providers (&ldquo;sub-processors&rdquo;) to run VRM Monitor. Each only receives the
              data it needs to do its job:
            </p>
            <ul>
              <li>
                <strong>ONVO Pay</strong> — processes subscription payments and stores payment method details. See{' '}
                <a href="https://onvopay.com/policies" target="_blank" rel="noopener noreferrer">
                  ONVO Pay&apos;s privacy policy and terms
                </a>
                .
              </li>
              <li>
                <strong>Resend</strong> — delivers transactional email (verification links, receipts, service notices).
              </li>
              <li>
                <strong>Supabase</strong> — hosts our database and handles authentication; this is where your account, site, and
                telemetry data is stored.
              </li>
              <li>
                <strong>Anthropic (Claude)</strong> — generates the narrative text in your reports from your system&apos;s
                telemetry. Telemetry sent for this purpose is used only to generate your report, not to train Anthropic&apos;s
                models.
              </li>
              <li>
                <strong>Victron Energy (VRM)</strong> — the source of your telemetry data, connected at your choice via an API
                token you control and can revoke at any time.
              </li>
            </ul>
            <p>We don&apos;t share your data with anyone else, other than as required by law.</p>

            <h2>5. Data retention</h2>
            <p>
              We keep your account and telemetry data for as long as your account is active. If you close your account, we delete
              your personal account data within a reasonable period, except where we&apos;re required to retain billing records for
              longer (for example, for tax or accounting purposes).
            </p>

            <h2>6. Your rights</h2>
            <p>
              You can access, correct, export, or delete your account data by contacting us at{' '}
              <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a>. You can also disconnect any VRM installation, or
              revoke its API token directly in your Victron VRM account, at any time.
            </p>

            <h2>7. Security</h2>
            <p>
              We use industry-standard measures to protect your data, including encrypted connections (HTTPS/TLS) and hashed
              password storage. No system is perfectly secure, and we can&apos;t guarantee absolute security — but we treat your
              data, and your Victron API token in particular, as sensitive and limit who and what can access it.
            </p>

            <h2>8. Cookies</h2>
            <p>
              We use only the minimal cookies needed to keep you signed in (session cookies). We don&apos;t use advertising or
              cross-site tracking cookies.
            </p>

            <h2>9. Children&apos;s privacy</h2>
            <p>VRM Monitor is not directed at children, and we don&apos;t knowingly collect data from anyone under 18.</p>

            <h2>10. Changes to this policy</h2>
            <p>
              If we make a material change to how we handle your data, we&apos;ll post the updated policy here with a new
              &ldquo;last updated&rdquo; date, and where practical, notify you by email.
            </p>

            <h2>11. Contact</h2>
            <p>
              Questions about this policy or your data? Reach us at <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a>
              .
            </p>
          </div>

          <Link href="/" className={styles.backLink}>
            ← Back to VRM Monitor
          </Link>
        </div>
      </div>
      <Footer />
    </>
  );
}
