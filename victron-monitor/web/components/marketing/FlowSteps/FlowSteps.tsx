import { SectionHead } from '@/components/ui';
import styles from './FlowSteps.module.css';

const STEPS = [
  {
    num: '01',
    title: 'Upload',
    body: "Export a CSV straight from VRM, or connect the VRM API for automatic pulls. No changes to Node-RED, no re-flashing a Cerbo GX — this reads data your equipment is already generating.",
  },
  {
    num: '02',
    title: 'Process',
    body: 'We parse daily energy, battery cycling, alarms, and outages; score system health 0–100; and let Claude write the week in plain language — not just a wall of numbers.',
  },
  {
    num: '03',
    title: 'Deliver',
    body: "A branded PDF lands in your inbox automatically — or your customer's, if you're managing more than one site. Pick a range past a month and it becomes a monthly Overview instead — same report, right granularity.",
  },
] as const;

export function FlowSteps() {
  return (
    <section id="how" className="band">
      <div className="wrap">
        <SectionHead
          eyebrow="How it works"
          lede="The same pipeline that has been sending Pauly & Co.'s own customers a report every Monday for months — now available whether you're watching one home or a whole fleet of installs."
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
