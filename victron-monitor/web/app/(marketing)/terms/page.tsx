import type { Metadata } from 'next';
import Link from 'next/link';
import { Footer, Nav } from '@/components/marketing';
import styles from '../legal.module.css';

export const metadata: Metadata = {
  title: 'Terms of Service',
  description: 'The terms that govern use of VRM Monitor, including subscriptions, billing and cancellation.',
};

const LAST_UPDATED = 'August 20, 2026';

// `app/(marketing)/terms` — same route-group shape as the marketing home
// page (Nav + page content + Footer, no shared layout.tsx — see the home
// page's own comment on why (marketing) doesn't have one). Content is a
// first draft written from the product's real mechanics (PLAN_PHASE16.md),
// not boilerplate — but still explicitly flagged as pending real legal
// review per Oscar's own instruction, not a substitute for a lawyer.
export default function TermsPage() {
  return (
    <>
      <Nav />
      <div className="wrap">
        <div className={styles.page}>
          <header className={styles.header}>
            <h1>Terms of Service</h1>
            <p className={styles.updated}>Last updated: {LAST_UPDATED}</p>
          </header>

          <div className={styles.draftNotice}>
            <p>
              <strong>Draft.</strong> This is a first draft written to reflect how VRM Monitor actually works today. It has not yet
              been reviewed by a lawyer and should not be treated as final. If you have questions about these terms, contact us at{' '}
              <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a> before relying on them.
            </p>
          </div>

          <div className={styles.body}>
            <h2>1. Who we are</h2>
            <p>
              VRM Monitor is a product of Pauly &amp; Co., based in Atenas, Costa Rica. Throughout these terms, &ldquo;we,&rdquo;
              &ldquo;us&rdquo; and &ldquo;VRM Monitor&rdquo; refer to Pauly &amp; Co., and &ldquo;you&rdquo; refers to the person or
              organization that creates an account.
            </p>

            <h2>2. What the service does</h2>
            <p>
              VRM Monitor connects to your Victron VRM account, reads the telemetry your Victron system already exports, and turns
              it into a branded, AI-narrated report delivered on a schedule. You control which VRM installations are connected and
              can disconnect them at any time.
            </p>

            <h2>3. Accounts</h2>
            <p>
              You need an account to use VRM Monitor. You&apos;re responsible for keeping your login credentials and your Victron
              VRM API token confidential, and for all activity that happens under your account. Tell us right away at{' '}
              <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a> if you think your account has been compromised.
            </p>
            <p>You must be able to form a binding contract to create an account, and the information you give us must be accurate.</p>

            <h2>4. Subscriptions, trials and billing</h2>
            <p>
              VRM Monitor is offered on paid subscription plans (currently Starter, Growth and Fleet), each with a monthly or
              annual billing interval you choose at signup. New subscriptions include a 7-day free trial; a valid payment method is
              required upfront, but you are not charged until the trial ends unless you cancel first.
            </p>
            <p>
              Payments are processed by our payment processor, <strong>ONVO Pay</strong>, not by us directly — we never see or store
              your full card number. See{' '}
              <a href="https://onvopay.com/policies" target="_blank" rel="noopener noreferrer">
                ONVO Pay&apos;s own terms and privacy policy
              </a>{' '}
              for how they handle payment data.
            </p>
            <p>
              Subscriptions renew automatically at the end of each billing period unless canceled. If you change plans, the new
              plan takes effect immediately at its own price — we don&apos;t currently prorate or credit the unused portion of your
              previous plan.
            </p>

            <h2>5. Cancellation and refunds</h2>
            <p>
              You can cancel at any time from your account&apos;s billing page. Canceling stops future renewals but does not refund
              the current billing period — your access continues until the end of the period you&apos;ve already paid for, then
              ends. We don&apos;t offer partial refunds for unused time within a period.
            </p>

            <h2>6. Acceptable use</h2>
            <p>You agree not to:</p>
            <ul>
              <li>Use VRM Monitor to access VRM installations or data you don&apos;t have the right to access;</li>
              <li>Attempt to disrupt, overload, or gain unauthorized access to the service or its underlying infrastructure;</li>
              <li>Resell or sublicense the service without our written agreement;</li>
              <li>Use the service for any unlawful purpose.</li>
            </ul>
            <p>We may suspend or terminate accounts that violate these terms.</p>

            <h2>7. Data and third-party services</h2>
            <p>
              Delivering VRM Monitor means sharing some data with a small number of service providers — for example, our email
              provider for account and report emails, our database provider for storing your account and site data, ONVO Pay for
              billing, and Anthropic&apos;s Claude for generating the narrative text in your reports. Full detail on what&apos;s
              collected and why is in our <Link href="/privacy">Privacy Policy</Link>.
            </p>

            <h2>8. AI-generated content</h2>
            <p>
              Report narratives are generated with AI based on your system&apos;s telemetry. We work to keep this accurate, but AI
              output can occasionally be wrong or misleading. Don&apos;t rely on report narratives alone for decisions with safety
              or financial consequences — treat them as a summary, and check the underlying data in VRM for anything that matters.
            </p>

            <h2>9. Availability</h2>
            <p>
              We aim to keep VRM Monitor reliable, but we don&apos;t guarantee uninterrupted availability. The service also depends
              on Victron&apos;s own VRM platform being reachable — outages on their end are outside our control.
            </p>

            <h2>10. Limitation of liability</h2>
            <p>
              To the extent permitted by law, VRM Monitor and Pauly &amp; Co. are not liable for indirect, incidental, or
              consequential damages arising from your use of the service. Our total liability for any claim is limited to the
              amount you paid us in the 12 months before the claim arose.
            </p>

            <h2>11. Changes to these terms</h2>
            <p>
              We may update these terms as the product evolves. If we make a material change, we&apos;ll post the updated version
              here with a new &ldquo;last updated&rdquo; date, and where practical, notify you by email.
            </p>

            <h2>12. Governing law</h2>
            <p>These terms are governed by the laws of Costa Rica.</p>

            <h2>13. Contact</h2>
            <p>
              Questions about these terms? Reach us at <a href="mailto:proyectos@paulyco.com">proyectos@paulyco.com</a>.
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
