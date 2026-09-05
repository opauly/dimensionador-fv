'use client';

import { useState } from 'react';
import { ModeToggle, Panel, SectionHead } from '@/components/ui';
import { FIXED_MODULE_ICONS, REPORT_MODULE_ICONS } from '@/lib/reportModuleThumbnails';
import styles from './ModuleGrid.module.css';

type Mode = 'detallado' | 'overview';

// Client component: the whole grid's text depends on `mode`, not just the
// toggle itself, so the interactive boundary is the section, matching how
// the template's [data-only] CSS hid/showed content inside the whole
// .cards-wrap rather than inside an isolated widget. React state replaces
// the template's data-mode attribute + [data-only] CSS pair directly — no
// DOM nodes for the inactive mode exist at all, rather than existing and
// being display:none'd, which is a strictly smaller DOM than the original
// for no behavioral difference a visitor or a screen reader would notice.
//
// Grouped into 5 native <details> sections (2026-09-05, Oscar's own
// feedback — 16 flat cards was too much to scan at once), same collapsible
// pattern the admin Fleet Dashboard's rollup cards already use: no client
// state needed for the grouping itself, keyboard-operable and accessible
// for free. All five start collapsed — no single group is privileged over
// the others — and every card's `mode`-dependent text still updates live
// even while its group is collapsed, since <details> only hides content
// visually, it doesn't unmount it.
export function ModuleGrid() {
  const [mode, setMode] = useState<Mode>('detallado');

  return (
    <section id="modules">
      <div className="wrap">
        <SectionHead
          eyebrow="What's inside"
          lede="Sixteen sections, computed once. Every plan gets a solid default report automatically, safety alerts included — Growth and Fleet installers can choose exactly which sections appear on each site's report, including a few that only apply if you've got a generator, tank, or physical grid meter wired in. Two sections also read differently depending on the range you pick — try the toggle."
        >
          Every section a report
          <br />
          can contain.
        </SectionHead>

        <div className={styles.toggleRow}>
          <ModeToggle
            aria-label="Report mode"
            value={mode}
            onChange={(next) => setMode(next as Mode)}
            options={[
              { value: 'detallado', label: 'Detailed · ≤31 days' },
              { value: 'overview', label: 'Overview · 32 days–6 months' },
            ]}
          />
          <span className={styles.hint}>Past 31 days, the report switches itself — no setting to remember.</span>
        </div>

        <p className={styles.groupHint}>Click any group to see what it contains.</p>

        <div className={styles.groups}>
          <details className={styles.group}>
            <summary className={styles.groupSummary}>
              <h3>Scoring &amp; story</h3>
              <span className={styles.groupCount}>3 sections</span>
            </summary>
            <div className={styles.groupGrid}>
              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{FIXED_MODULE_ICONS.kpi}</span>
                <span className={styles.tag}>Scoring</span>
                <h3>Health score</h3>
                <p className={styles.body}>
                  0–100, alongside solar generation, grid independence, and events for the period — one number a
                  homeowner can actually track over time.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{FIXED_MODULE_ICONS.narrative}</span>
                <span className={styles.tag}>Narrative</span>
                <h3>AI narrative</h3>
                <p className={styles.body}>
                  {mode === 'detallado'
                    ? 'A short paragraph explaining what happened this period — plain language, not a wall of numbers.'
                    : 'A paragraph that describes how the system trended across segments — improving, worsening, or steady — not one lump total.'}
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.savings}</span>
                <span className={styles.tag}>Savings</span>
                <h3>Estimated savings</h3>
                <p className={styles.body}>
                  Estimated electricity cost avoided this period by using solar instead of buying from the grid — a
                  real number, never a placeholder.
                </p>
              </Panel>
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupSummary}>
              <h3>Solar &amp; energy</h3>
              <span className={styles.groupCount}>5 sections</span>
            </summary>
            <div className={styles.groupGrid}>
              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{FIXED_MODULE_ICONS.bar_chart}</span>
                <span className={styles.adapts}>Adapts to range</span>
                <h3>{mode === 'detallado' ? 'Daily solar vs. consumption' : 'Solar vs. consumption'}</h3>
                <p className={styles.body}>
                  {mode === 'detallado'
                    ? 'Compares daily solar production against household consumption for each day in this period.'
                    : 'Compares solar production against household consumption for each segment of this period.'}
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.energy_mix}</span>
                <span className={styles.tag}>Energy mix</span>
                <h3>Where your energy came from</h3>
                <p className={styles.body}>
                  Shows how much of your energy came from solar panels, batteries, and the utility grid — one donut,
                  always up to date.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.solar_performance}</span>
                <span className={styles.tag}>Performance</span>
                <h3>Solar performance</h3>
                <p className={styles.body}>
                  Compares real solar production to the theoretical maximum, based on your panel capacity and the
                  sunlight actually available.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.trend}</span>
                <span className={styles.fixedBadge}>Always weekly</span>
                <h3>4-week solar trend</h3>
                <p className={styles.body}>
                  Compares production across the past 4 weeks to spot seasonal patterns — fixed at this cadence on
                  purpose, whatever range you picked.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.weather}</span>
                <span className={styles.tag}>Weather</span>
                <h3>Weather context</h3>
                <p className={styles.body}>
                  Local conditions for this period — cloud cover and rain directly reduce solar output, so the
                  report accounts for them.
                </p>
              </Panel>
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupSummary}>
              <h3>Battery</h3>
              <span className={styles.groupCount}>2 sections</span>
            </summary>
            <div className={styles.groupGrid}>
              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.battery_health}</span>
                <span className={styles.tag}>Battery</span>
                <h3>Battery health</h3>
                <p className={styles.body}>
                  Tracks how well your batteries charged and discharged throughout this period — cycling stress,
                  float days, voltage range.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.soc_chart}</span>
                <span className={styles.adapts}>Adapts to range</span>
                <h3>Battery SOC timeline</h3>
                <p className={styles.body}>
                  {mode === 'detallado'
                    ? 'Shows the daily high and low battery charge level — a dip below 20% signals heavy use.'
                    : "Shows each segment's high and low battery charge level — a dip below 20% signals heavy use."}
                </p>
              </Panel>
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupSummary}>
              <h3>Grid &amp; safety</h3>
              <span className={styles.groupCount}>3 sections</span>
            </summary>
            <div className={styles.groupGrid}>
              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.grid_quality}</span>
                <span className={styles.tag}>Grid</span>
                <h3>Grid quality</h3>
                <p className={styles.body}>
                  Measures the quality and stability of the utility grid supply at your site — frequency and
                  voltage extremes, not just outages.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.events}</span>
                <span className={styles.tag}>Events</span>
                <h3>Outages &amp; alarms</h3>
                <p className={styles.body}>
                  Logs grid outages and alarm episodes recorded by the system during this period — the same
                  definition your live monitoring uses. Scored toward the health score above.
                </p>
              </Panel>

              {/* PLAN_PHASE18.md §7 (2026-08-29) — critical_alerts is the one
                 module below in the default report for everyone; the other
                 three (in "Optional add-ons" below) are opt-in and depend on
                 hardware most systems don't have, so both get said outright
                 rather than implied. */}
              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.critical_alerts}</span>
                <span className={styles.tag}>Safety</span>
                <h3>Critical alerts</h3>
                <p className={styles.body}>
                  DC ripple, cell imbalance, and temperature faults on the battery system — tracked separately from
                  the health score, included by default on every plan.
                </p>
              </Panel>
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupSummary}>
              <h3>Optional add-ons</h3>
              <span className={styles.groupCount}>3 sections</span>
            </summary>
            <div className={styles.groupGrid}>
              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.grid_meter_detail}</span>
                <span className={styles.conditional}>If a meter is installed</span>
                <h3>Grid meter detail</h3>
                <p className={styles.body}>
                  Per-phase voltage, current, and power factor from a real physical grid meter, where one is wired
                  into the system.
                </p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.generator_runtime}</span>
                <span className={styles.conditional}>If a generator is installed</span>
                <h3>Generator runtime</h3>
                <p className={styles.body}>Hours the backup generator ran during the period.</p>
              </Panel>

              <Panel variant="card" interactive led>
                <span className={styles.icon} aria-hidden="true">{REPORT_MODULE_ICONS.tank_level}</span>
                <span className={styles.conditional}>If a tank sensor is installed</span>
                <h3>Tank level</h3>
                <p className={styles.body}>Fuel or water tank capacity, fluid type, and last known status.</p>
              </Panel>
            </div>
          </details>
        </div>
      </div>
    </section>
  );
}
