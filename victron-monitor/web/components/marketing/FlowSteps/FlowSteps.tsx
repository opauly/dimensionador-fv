import { SectionHead } from '@/components/ui';
import styles from './FlowSteps.module.css';

// Reframed 2026-09-05 (Oscar's own feedback: with the Live Dashboard now
// also on this page, the old 3-step Upload/Process/Deliver flow read as
// report-only, with the dashboard bolted on elsewhere). Same 3 steps, but
// step 3 now forks into the two outputs the pipeline actually has, instead
// of ending at "a PDF lands in your inbox" — one pipeline, watched live or
// read weekly, not two separate stories.
const STEPS = [
  {
    num: '01',
    title: 'Connect',
    body: "Export a CSV straight from VRM, or connect the VRM API for automatic, continuous sync. No changes to Node-RED, no re-flashing a Cerbo GX — this reads data your equipment is already generating.",
  },
  {
    num: '02',
    title: 'Process',
    body: "We parse daily energy, battery cycling, alarms, and outages; score system health 0–100; and check each site against its own history for anomalies — the same numbers the live dashboard and the weekly report are both built from.",
  },
  {
    num: '03',
    title: 'Watch or read',
    body: "Check the live dashboard anytime, updated every ~15 minutes — or let a branded, AI-narrated report land in your inbox automatically every week (or your customer's, if you're managing a fleet). Same pipeline, however you want to see it. Growth and Fleet installers can also choose which report sections show up, per site.",
  },
] as const;

export function FlowSteps() {
  return (
    <section id="how" className="band">
      <div className="wrap">
        <SectionHead
          eyebrow="How it works"
          lede="The same pipeline that has been running Pauly & Co.'s own systems for months — as a live dashboard, a weekly report, or both, whether you're watching one home or a whole fleet of installs."
        >
          Three steps. Zero new hardware.
        </SectionHead>

        <div className={styles.flow}>
          {STEPS.map((step, i) => (
            <div key={step.num} className={styles.step}>
              {i > 0 && <div className={styles.trace} aria-hidden="true" />}
              <span className={styles.num}>{step.num}</span>
              <h3>{step.title}</h3>
              <p className={styles.body}>{step.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
