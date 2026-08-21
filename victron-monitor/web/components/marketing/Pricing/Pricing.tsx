'use client';

import { useState } from 'react';
import { Button, ModeToggle, Panel, SectionHead } from '@/components/ui';
import styles from './Pricing.module.css';

type Mode = 'subscription' | 'single';

export type PricingProps = {
  /** Real `vrm.plans.id` rows for the MONTHLY Starter/Growth tiers, in the
   * current `ONVO_MODE` (PLAN_PHASE16.md §8 Step 5.5 build item 7,
   * `lib/server/db/signup.ts:getFeaturedSelfServePlanIds()`) — fetched by
   * `app/(marketing)/page.tsx` (a Server Component; this one is a client
   * component and has no session-free way to reach the database itself).
   * `null` for a tier that isn't currently seeded/self-serve/active, in
   * which case that card's button falls back to a bare `/signup` link
   * rather than a dead id. */
  starterPlanId: string | null;
  growthPlanId: string | null;
};

function signupHref(planId: string | null): string {
  return planId ? `/signup?plan=${planId}` : '/signup';
}

// Client component for the same reason ModuleGrid is: which whole block
// renders (the three-tier grid vs. the one-time single-report card) depends
// on `mode`, not just the toggle widget. This is also the toggle whose
// template equivalent (landing_template.html L887-896) went inert because
// of document-order-dependent querySelectorAll — see ModeToggle's own
// comment for why a useState component can't reproduce that bug class.
export function Pricing({ starterPlanId, growthPlanId }: PricingProps) {
  const [mode, setMode] = useState<Mode>('subscription');

  return (
    <section id="pricing">
      <div className="wrap">
        <SectionHead
          eyebrow="Pricing"
          lede="One flat rate per tier — no per-site math, no surprise bill as you add sites. Or skip the commitment and try one report first."
        >
          Subscribe one system,
          <br />
          or a whole fleet.
        </SectionHead>

        <div className={styles.toggleRow}>
          <ModeToggle
            aria-label="Pricing model"
            value={mode}
            onChange={(next) => setMode(next as Mode)}
            options={[
              { value: 'subscription', label: 'Subscription' },
              { value: 'single', label: 'Single report' },
            ]}
          />
          <span className={styles.hint}>
            Start with a single report, upgrade to a subscription whenever — nothing to migrate.
          </span>
        </div>

        {mode === 'subscription' ? (
          <div className={styles.grid}>
            <Panel variant="price">
              <div className={styles.head}>
                <h3>Starter</h3>
                <span className={styles.range}>Up to 10 sites</span>
              </div>
              <div className={styles.num}>
                $29.99<span className={styles.per}>/ mo</span>
              </div>
              <p className={styles.singleNote} style={{ marginTop: -8, marginBottom: 12 }}>
                or $299.99 / yr
              </p>
              <ul className={styles.features}>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Automatic weekly &amp; Overview reports
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Health score + AI narrative
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  CSV upload · Spanish / English
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Automatic email delivery
                </li>
              </ul>
              <Button href={signupHref(starterPlanId)} variant="ghost" style={{ justifyContent: 'center' }}>
                Get started
              </Button>
            </Panel>

            <Panel variant="price" featured hairline featuredTag="Most installers">
              <div className={styles.head}>
                <h3>Growth</h3>
                <span className={styles.range}>Up to 50 sites</span>
              </div>
              <div className={styles.num}>
                $99.99<span className={styles.per}>/ mo</span>
              </div>
              <p className={styles.singleNote} style={{ marginTop: -8, marginBottom: 12 }}>
                or $999.99 / yr
              </p>
              <ul className={styles.features}>
                <li className={styles.carry}>Everything in Starter, plus</li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Full white-label branding
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Priority support
                </li>
              </ul>
              <Button href={signupHref(growthPlanId)} style={{ justifyContent: 'center' }}>
                Get started
              </Button>
            </Panel>

            <Panel variant="price">
              <div className={styles.head}>
                <h3>Fleet</h3>
                <span className={styles.range}>50+ sites</span>
              </div>
              <div className={styles.num} style={{ fontSize: 32 }}>
                Custom
              </div>
              <ul className={styles.features}>
                <li className={styles.carry}>Everything in Growth, plus</li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  VRM API auto-ingestion
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Dedicated onboarding
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Delivery SLA
                </li>
              </ul>
              <Button
                href="mailto:proyectos@paulyco.com?subject=VRM%20Monitor%20-%20Fleet%20pricing"
                variant="ghost"
                style={{ justifyContent: 'center' }}
              >
                Talk to us
              </Button>
            </Panel>
          </div>
        ) : (
          <div className={styles.single}>
            <div>
              <span className={styles.singleTag}>One-time · no subscription</span>
              <h3 className={styles.singleH3}>Single Report</h3>
              <p className={styles.singleP}>
                Already have a CSV export, or just want to see one system&apos;s story before committing to a
                subscription? Upload it once — get back the exact same report a subscriber gets every week, nothing
                held back.
              </p>
              <ul className={styles.features} style={{ marginTop: 20 }}>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  One site, any range up to 6 months of history
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  All 12 report sections, full health scoring + AI narrative
                </li>
                <li>
                  <span className={styles.dot} aria-hidden="true" />
                  Delivered within minutes of upload
                </li>
              </ul>
            </div>
            <div className={styles.singleRight}>
              <div className={styles.num}>
                $9.99<span className={styles.per}>/ report</span>
              </div>
              {/* Single Report deliberately has no `vrm.plans` row and is
                  not purchasable from /signup in v1 — PLAN_PHASE16.md §9 /
                  §0.6 Q1: "not a vrm.plans/subscription row — a one-off
                  purchase ... unchanged flow." The plan's original text
                  routed this CTA to the now-deleted `AccessForm`; with that
                  gone (Oscar's explicit decision, §8 Step 5.5), a direct
                  mailto — the same pattern Fleet's own "Talk to us" button
                  already uses — replaces the dangling `#cta` anchor rather
                  than leaving a dead in-page link. */}
              <Button
                href="mailto:proyectos@paulyco.com?subject=VRM%20Monitor%20-%20Single%20report"
                style={{ justifyContent: 'center', width: '100%' }}
              >
                Get a report
              </Button>
              <span className={styles.singleNote}>
                One PDF, delivered once — no automatic re-delivery. Want it weekly instead? Switch to a subscription
                above, anytime.
              </span>
            </div>
          </div>
        )}

        <p className={styles.note}>
          Early-access pricing — subscription rates locked in for 12 months for owners and installers who join
          during onboarding.
        </p>
      </div>
    </section>
  );
}
