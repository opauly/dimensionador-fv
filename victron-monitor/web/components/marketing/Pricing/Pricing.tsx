'use client';

import { useState } from 'react';
import { Button, ModeToggle, Panel, SectionHead } from '@/components/ui';
import styles from './Pricing.module.css';

type Mode = 'subscription' | 'single';

// Client component for the same reason ModuleGrid is: which whole block
// renders (the three-tier grid vs. the one-time single-report card) depends
// on `mode`, not just the toggle widget. This is also the toggle whose
// template equivalent (landing_template.html L887-896) went inert because
// of document-order-dependent querySelectorAll — see ModeToggle's own
// comment for why a useState component can't reproduce that bug class.
export function Pricing() {
  const [mode, setMode] = useState<Mode>('subscription');

  return (
    <section id="pricing">
      <div className="wrap">
        <SectionHead
          eyebrow="Pricing"
          lede="No seats, no per-user math — you pay for what's actually being monitored, whether that's your own home or fifty customers. Or skip the commitment and try one report first."
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
                $14<span className={styles.per}>/ site / mo</span>
              </div>
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
              <Button href="#cta" variant="ghost" style={{ justifyContent: 'center' }}>
                Get started
              </Button>
            </Panel>

            <Panel variant="price" featured hairline featuredTag="Most installers">
              <div className={styles.head}>
                <h3>Growth</h3>
                <span className={styles.range}>Up to 50 sites</span>
              </div>
              <div className={styles.num}>
                $9<span className={styles.per}>/ site / mo</span>
              </div>
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
              <Button href="#cta" style={{ justifyContent: 'center' }}>
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
                $29<span className={styles.per}>/ report</span>
              </div>
              <Button href="#cta" style={{ justifyContent: 'center', width: '100%' }}>
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
